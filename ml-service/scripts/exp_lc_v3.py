"""Learning Curve V3 — nested subset + dev/final attack แยก + episode-aware sequence.

ออกแบบตามสเปค:
  - train pool 5,000/คน · validation 1,000/คน · final normal test 1,000/คน (ตรึงทุกขนาด)
  - nested subset: Train-50 ⊂ 100 ⊂ 500 ⊂ 1000 ⊂ 5000 (ห้ามแบ่ง 80/20 ใหม่ต่อขนาด)
  - dev attack ใช้เลือก config · final attack วัดครั้งเดียว (parameter/รูปแบบต่างกัน)
  - sequence window **ห้ามข้าม episode** · threshold p99 จาก validation เท่านั้น
  - L3 = Config F (6 residual features × [mean, slope, ptp] = 18 inputs) per-user IForest

รายงานต่อขนาด: recall รวม/แยกกลุ่ม · L3 unique · normal FPR · precision · F1 ·
latency · abstention rate

Run: cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/exp_lc_v3.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest

ML = Path(__file__).resolve().parent
sys.path.insert(0, str(ML))
import build_profiles_v2 as BP  # noqa: E402
import gen_v3 as G3  # noqa: E402
import lc_l3_ownership as O  # noqa: E402
import lc_l3_sequence as SEQ  # noqa: E402
import lc_run_4layer as LC  # noqa: E402

from app.security.behavior_profiling import evaluate_behavior  # noqa: E402
from app.security.iforest_scorer import IForestResult  # noqa: E402
from app.security.risk_aggregator import aggregate  # noqa: E402
from app.security.rule_engine import evaluate_rules  # noqa: E402

REPORTS = LC.REPORTS
RANK = LC.RANK
W = 5  # เทียบกับ W=10 ด้วยวิธีที่ถูกต้อง (family-grouped + real history tail)
P99 = 0.999  # จาก threshold sweep — จุดเดียวที่ FPR <=1% (ดู exp_thr_and_gaps)
MIN_TRAIN_FOR_L3 = 100  # ต่ำกว่านี้ abstain (ตาม tier)
NEUTRAL = IForestResult(0.0, 0.0, "neutral")
SUBTLE = set(BP.SUBTLE_SCENARIOS)
CAMPAIGNY = {"campaign"} | set(BP.UNSEEN_FAMILIES)


def _family(scn: str) -> str:
    if scn in CAMPAIGNY:
        return "campaign"
    if scn in SUBTLE:
        return "subtle"
    return "obvious"


def _ep_bounds_of(n: int) -> list[int]:
    """ขอบ episode สำหรับ slice ยาว n (gen_v3 แบ่ง episode ละ EPISODE_EVENTS)."""
    e = G3.EPISODE_EVENTS
    b = list(range(0, n, e))
    return (b + [n]) if b and b[-1] != n else (b or [0, n])


def _windows_per_episode(res: list, bounds: list[int]) -> list:
    """window ภายใน episode เดียวกัน (ห้ามข้าม) — รวม index ต้น episode ที่ยัง pad อยู่.

    ต้องรวม padded window ด้วย เพราะตอน score จริงก็ pad เหมือนกัน ถ้า train/validation
    มีแต่ window เต็ม padded window จะกลายเป็น "ของแปลก" -> FPR พุ่ง (เคยเห็น 5.8%)
    """
    out = []
    for a, b in zip(bounds, bounds[1:]):
        seg = res[a:b]
        for i in range(len(seg)):
            w = seg[max(0, i - W + 1) : i + 1]
            while len(w) < W:
                w = [w[0]] + w
            out.append(SEQ._winfeat(w))
    return out


def _fit(X):
    X = np.asarray(X, dtype=float)
    if len(X) < 20:
        return None
    keep = X.std(axis=0) > 1e-9
    if not keep.any():
        return None
    m = IsolationForest(n_estimators=100, contamination=0.02, random_state=42).fit(
        X[:, keep]
    )
    return m, keep


def _anom(model, X):
    m, keep = model
    return -m.score_samples(np.asarray(X, dtype=float)[:, keep])


def run_size(users, size):
    rows, abstained, t_fit, t_score = [], 0, [], []
    for alias, u in users.items():
        tr_raw, tr_ft = G3.nested_subset(u, size)
        prof = LC.build_profile(tr_raw)
        model = thr = base = None
        if prof is None or size < MIN_TRAIN_FOR_L3:
            abstained += 1
        else:
            t0 = time.perf_counter()
            base = O._baseline(tr_ft)
            tres = [SEQ._resid(v, r, prof, base) for v, r in zip(tr_ft, tr_raw)]
            Xtr = _windows_per_episode(tres, G3.episode_bounds(u, size))
            model = _fit(Xtr)
            t_fit.append(time.perf_counter() - t0)
            if model is None:
                abstained += 1
            else:
                # threshold p99 จาก validation เท่านั้น (ไม่แตะ train/test)
                val_raw = [x for x, _ in u["test"]][: len(u["val_ft"])]
                vres = [
                    SEQ._resid(v, r, prof, base) for v, r in zip(u["val_ft"], val_raw)
                ]
                # ต้องไม่ข้าม episode เหมือนตอน train ไม่งั้น threshold เพี้ยน
                Xva = _windows_per_episode(vres, _ep_bounds_of(len(vres)))
                thr = float(np.quantile(_anom(model, Xva), P99)) if Xva else None

        # history จริงท้าย train — นำหน้า window ของ attack แทนการ pad ด้วยตัวเอง
        # สำคัญกับ W ยาว: campaign 5 phase ต้องเห็น baseline จริงก่อนหน้าถึงวัด drift ได้
        tail = tres[-(W - 1) :] if model is not None else []

        def evaluate(pairs, label, tag, use_tail=False):
            if not pairs:
                return
            fired = [False] * len(pairs)
            if model is not None and thr is not None:
                res = [SEQ._resid(v, r, prof, base) for r, v in pairs]
                wins, run = [], (list(tail) if use_tail else [])
                for r in res:
                    w = (run + [r])[-W:]
                    while len(w) < W:
                        w = [w[0]] + w
                    wins.append(SEQ._winfeat(w))
                    run.append(r)
                t0 = time.perf_counter()
                a = _anom(model, wins)
                t_score.append((time.perf_counter() - t0) / len(wins))
                fired = list(a >= thr)
            for (raw, vec), f in zip(pairs, fired):
                rule = evaluate_rules(
                    vec, db=None, user_id=alias, ip=None, geo_country=None
                )
                beh = evaluate_behavior(
                    vec,
                    prof,
                    subsystem_id=raw.get("subsystem"),
                    user_agent=raw.get("user_agent"),
                )
                access = aggregate(rule, beh, NEUTRAL).decision
                rows.append(
                    dict(
                        label=label,
                        tag=tag,
                        family=_family(raw.get("scenario", "normal")),
                        access=access,
                        fire=bool(f),
                    )
                )

        tb = _ep_bounds_of(len(u["test"]))
        for x, y in zip(tb, tb[1:]):  # normal test: window ไม่ข้าม episode
            evaluate(u["test"][x:y], 0, "normal")
        evaluate(u["camp_like"], 0, "camp_like", use_tail=True)
        for tag, key in (("dev", "dev_attacks"), ("final", "final_attacks")):
            by = {}
            for raw, vec in u[key]:
                by.setdefault(raw["scenario"], []).append((raw, vec))
            for scn, prs in by.items():  # window ไม่ปนข้าม family
                prs.sort(key=lambda x: x[0]["created_at"])
                evaluate(prs, 1, tag, use_tail=True)
    return (
        rows,
        abstained / len(users),
        float(np.mean(t_fit or [0])),
        float(np.mean(t_score or [0]) * 1000),
    )


def metrics(rows, track):
    """track = 'dev' หรือ 'final' — normal ใช้ชุดเดียวกันทั้งคู่."""
    atk = [r for r in rows if r["label"] == 1 and r["tag"] == track]
    nor = [r for r in rows if r["label"] == 0]
    wn = lambda d: RANK[d] >= RANK["warn"]  # noqa: E731
    ch = lambda d: RANK[d] >= RANK["challenge"]  # noqa: E731
    surf = lambda r: wn(r["access"]) or r["fire"]  # noqa: E731

    tp = sum(ch(r["access"]) for r in atk)
    fp = sum(ch(r["access"]) for r in nor)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / len(atk) if atk else 0.0
    cl = [r for r in nor if r["tag"] == "camp_like"]
    out = dict(
        recall=rec,
        precision=prec,
        f1=(2 * prec * rec / (prec + rec) if prec + rec else 0.0),
        surfaced=(sum(surf(r) for r in atk) / len(atk)) if atk else 0.0,
        l3_raw_unique=(
            sum(1 for r in atk if r["fire"] and not wn(r["access"])) / len(atk)
        )
        if atk
        else 0.0,
        cfpr=fp / len(nor),
        l3_fpr=sum(r["fire"] for r in nor) / len(nor),
        camp_like_fpr=(sum(r["fire"] for r in cl) / len(cl)) if cl else 0.0,
        n_atk=len(atk),
        n_nor=len(nor),
    )
    for fam in ("obvious", "subtle", "campaign"):
        g = [r for r in atk if r["family"] == fam]
        out[f"recall_{fam}"] = (sum(ch(r["access"]) for r in g) / len(g)) if g else 0.0
        out[f"surfaced_{fam}"] = (sum(surf(r) for r in g) / len(g)) if g else 0.0
    return out


KEYS = [
    "recall",
    "recall_obvious",
    "recall_subtle",
    "recall_campaign",
    "l3_raw_unique",
    "cfpr",
    "l3_fpr",
    "precision",
    "f1",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
    ap.add_argument("--sizes", type=int, nargs="+", default=G3.LC_SIZES)
    args = ap.parse_args()

    acc = {t: {s: [] for s in args.sizes} for t in ("dev", "final")}
    extra = {s: [] for s in args.sizes}
    for seed in args.seeds:
        t0 = time.time()
        users = G3.build_seed(args.users, seed)
        for s in args.sizes:
            rows, abst, tf, ts = run_size(users, s)
            acc["dev"][s].append(metrics(rows, "dev"))
            acc["final"][s].append(metrics(rows, "final"))
            extra[s].append((abst, tf, ts))
        print(f"seed {seed} done ({time.time() - t0:.0f}s)", flush=True)

    _print(acc, extra, args.sizes, args.seeds)
    _report(acc, extra, args.sizes, args.seeds)


def _ci(acc, track, size, key):
    return O.ci95([a[key] for a in acc[track][size]])


def _print(acc, extra, sizes, seeds):
    for track in ("dev", "final"):
        print("=" * 94)
        print(
            f"[{track.upper()} attack] mean±CI95 · {len(seeds)} seeds · "
            f"attack {acc[track][sizes[0]][0]['n_atk']} · normal {acc[track][sizes[0]][0]['n_nor']}"
        )
        hdr = (
            "size",
            "recall",
            "obvious",
            "subtle",
            "campaign",
            "L3uniq",
            "cFPR",
            "L3FPR",
            "prec",
            "F1",
        )
        print("  " + "".join(f"{h:>10}" for h in hdr))
        for s in sizes:
            v = [_ci(acc, track, s, k)[0] * 100 for k in KEYS]
            print(f"  {s:>10}" + "".join(f"{x:>10.1f}" for x in v))
    print("\n  ต้นทุน/ความพร้อม:")
    print(f"  {'size':>10}{'abstain%':>12}{'fit(s)':>10}{'score(ms)':>12}")
    for s in sizes:
        ab = np.mean([e[0] for e in extra[s]]) * 100
        tf = np.mean([e[1] for e in extra[s]])
        ts = np.mean([e[2] for e in extra[s]])
        print(f"  {s:>10}{ab:>12.1f}{tf:>10.2f}{ts:>12.3f}")


def _report(acc, extra, sizes, seeds):
    L = [
        "# Learning Curve V3 — nested subset · dev/final attack แยก · episode-aware\n",
        "**วันที่:** 26 ส.ค. 2026  ",
        f"**seeds:** {seeds} (mean ± 95% CI) · sizes {sizes}\n",
        "\n## การออกแบบชุดข้อมูล (ต่อคน ต่อ seed)\n",
        "| ชุด | จำนวน | หน้าที่ |",
        "|---|---|---|",
        f"| Normal train pool | {G3.TRAIN_POOL:,} | ฝึกโปรไฟล์ + IForest (nested subset) |",
        f"| Normal validation | {G3.VAL_N:,} | หา p99 · ตรวจ FPR |",
        f"| Final normal test | {G3.TEST_N:,} | วัด FPR จริง |",
        "| Development attack | ~38 | เลือก config/ฟีเจอร์ |",
        "| Final attack | ~53 | วัดครั้งเดียว (รูปแบบ/parameter ต่างจาก dev) |",
        "| campaign-like normal | 5 | ทดสอบ false positive |",
        f"\n**Episode:** {G3.EPISODE_EVENTS} event / {G3.EPISODE_DAYS} วัน · reset rolling state ทุก episode · "
        "sequence window ห้ามข้าม episode  ",
        "**Nested:** Train-50 ⊂ 100 ⊂ 500 ⊂ 1000 ⊂ 5000 · validation/test ชุดเดิมทุกขนาด  ",
        "**Final attack** ใช้ campaign 5 family ที่ไม่เคยใช้ตอนเลือกฟีเจอร์ (หลบแกนของ Config F)\n",
    ]
    for track, lab in [
        ("dev", "Development attack (ใช้เลือก config)"),
        ("final", "Final attack (holdout — วัดครั้งเดียว)"),
    ]:
        L += [
            f"\n## {lab}\n",
            "| size | recall | obvious | subtle | campaign | L3 unique | cFPR | L3 FPR | precision | F1 |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for s in sizes:
            c = [_ci(acc, track, s, k) for k in KEYS]
            L.append(
                f"| {s} | "
                + " | ".join(f"{m * 100:.1f}±{e * 100:.1f}" for m, e in c)
                + " |"
            )
    L += [
        "\n## ต้นทุน / ความพร้อม\n",
        "| size | abstention | fit (s/คน) | score (ms/event) |",
        "|---|---|---|---|",
    ]
    for s in sizes:
        ab = np.mean([e[0] for e in extra[s]]) * 100
        tf = np.mean([e[1] for e in extra[s]])
        ts = np.mean([e[2] for e in extra[s]])
        L.append(f"| {s} | {ab:.1f}% | {tf:.2f} | {ts:.3f} |")
    cl = _ci(acc, "final", sizes[-1], "camp_like_fpr")
    L += [
        "\n## False positive — normal ที่ดูคล้าย campaign\n",
        f"L3 FPR บน campaign-like normal ที่ size {sizes[-1]}: **{cl[0] * 100:.1f} ± {cl[1] * 100:.1f}%**\n",
    ]
    (REPORTS / "exp_lc_v3_2026-08-26.md").write_text("\n".join(L), encoding="utf-8")
    print("\nreport ->", REPORTS / "exp_lc_v3_2026-08-26.md")


if __name__ == "__main__":
    main()
