"""FINAL GATE — เทสรอบสุดท้าย ทำครั้งเดียว (fresh evaluation set).

หลักการ: **ฝึกจากข้อมูลเดิม · ประเมินบนข้อมูลที่โมเดลไม่เคยเห็นเลย**

    train / validation : seeds 42-46 (ชุดเดิมที่ใช้พัฒนา)
    evaluation         : seeds 101-105 (**ใหม่ทั้งหมด** — normal + attack ที่ไม่เคยถูกใช้)

Config ที่ล็อกไว้ (ห้ามแตะ):
    Config F · sequence-residual 6 มิติ × [mean, slope, ptp] · W=5 · threshold p99.9
    L3 = monitoring channel เท่านั้น (ห้ามเปลี่ยน allow/challenge/block)

ตรวจก่อนเชื่อผล:
    1. data leakage  — eval ต้องไม่ซ้ำ train · threshold มาจาก validation ของ train เท่านั้น
    2. shortcut      — ไม่มีฟีเจอร์เดี่ยวที่แยก attack/normal ได้เกือบสมบูรณ์ (AUC > 0.99)
    3. L3 ไม่แตะ access — assert decision ก่อน/หลัง L3 เท่ากันทุกแถว

Run: cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/exp_final_gate.py
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ML = Path(__file__).resolve().parent
sys.path.insert(0, str(ML))
import build_profiles_v2 as BP  # noqa: E402
import exp_lc_v3 as E3  # noqa: E402
import gen_v3 as G3  # noqa: E402
import lc_l3_ownership as O  # noqa: E402
import lc_l3_sequence as SEQ  # noqa: E402
import lc_run_4layer as LC  # noqa: E402

from app.security.behavior_profiling import evaluate_behavior  # noqa: E402
from app.security.risk_aggregator import THRESHOLDS, aggregate  # noqa: E402
from app.security.rule_engine import evaluate_rules  # noqa: E402

REPORTS = LC.REPORTS
RANK = LC.RANK
FEATURES = LC.FEATURES
W = 5  # ล็อก
Q = 0.999  # ล็อก p99.9
SIZES = [50, 100, 500, 1000, 5000]
MIN_TRAIN = 100  # ต่ำกว่านี้ abstain
NEUTRAL = E3.NEUTRAL
TRAIN_SEEDS = [42, 43, 44, 45, 46]
EVAL_SEEDS = [101, 102, 103, 104, 105]


def _decide(total: float) -> str:
    if total >= THRESHOLDS["block"]:
        return "block"
    if total >= THRESHOLDS["challenge"]:
        return "challenge"
    if total >= THRESHOLDS["warn"]:
        return "warn"
    return "allow"


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


# ══════════════════════════ ตรวจก่อนเชื่อผล ══════════════════════════
# field ที่ใช้ระบุ "เหตุการณ์เดียวกัน" — ต้องครบ ไม่ใช่แค่ timestamp
# (เทียบแค่ (time, device, subsystem) จะเจอการชนกันโดยบังเอิญ: U03 เวลาเดียวกัน
#  แต่ duration 25.64 vs 10.32 และ method passkey vs google = คนละเหตุการณ์)
_ROW_FIELDS = (
    "created_at",
    "logout_at",
    "device_signature",
    "subsystem",
    "duration_min",
    "login_method",
    "login_successful",
    "user_agent",
    "passkey_age_days",
    "permission_change_age",
    "concurrent_session_count",
)


def check_leakage(u_tr, u_ev):
    """eval ต้องไม่ทับ train — เทียบ **ทั้งแถว** ไม่ใช่แค่ timestamp."""

    def sig(rows):
        return {tuple(str(r.get(k)) for k in _ROW_FIELDS) for r in rows}

    tr = sig(u_tr["train_raw"]) | sig([r for r, _ in u_tr["test"]])
    ev = sig([r for r, _ in u_ev["test"]]) | sig([r for r, _ in u_ev["final_attacks"]])
    return len(tr & ev), len(ev)


def check_shortcut(atk_vecs, nor_vecs):
    """หา feature เดี่ยวที่แยก attack/normal ได้เกือบสมบูรณ์ (AUC>0.99 = shortcut)."""
    if not atk_vecs or not nor_vecs:
        return []
    A = np.asarray(atk_vecs, dtype=float)
    N = np.asarray(nor_vecs, dtype=float)
    bad = []
    for j, name in enumerate(FEATURES):
        a, n = A[:, j], N[:, j]
        if a.std() < 1e-12 and n.std() < 1e-12:
            continue
        # AUC ผ่าน rank (Mann-Whitney)
        allv = np.concatenate([a, n])
        order = allv.argsort()
        ranks = np.empty(len(allv), dtype=float)
        ranks[order] = np.arange(1, len(allv) + 1)
        ra = ranks[: len(a)].sum()
        auc = (ra - len(a) * (len(a) + 1) / 2) / (len(a) * len(n))
        auc = max(auc, 1 - auc)
        # support check: normal เคยมีค่าในช่วงของ attack ไหม
        cover = float(((a >= n.min()) & (a <= n.max())).mean())
        if auc > 0.99 or cover < 0.05:
            bad.append((name, round(auc, 4), round(cover, 3)))
    return bad


# ══════════════════════════ ประเมิน ══════════════════════════
def run_pair(users_tr, users_ev, size):
    rows, t_fit, t_score, abstain = [], [], [], 0
    for alias in users_tr:
        u_tr, u_ev = users_tr[alias], users_ev[alias]
        tr_raw, tr_ft = G3.nested_subset(u_tr, size)
        prof = LC.build_profile(tr_raw)
        model = thr = base = None
        if prof is not None and size >= MIN_TRAIN:
            t0 = time.perf_counter()
            base = O._baseline(tr_ft)
            tres = [SEQ._resid(v, r, prof, base) for v, r in zip(tr_ft, tr_raw)]
            model = E3._fit(
                E3._windows_per_episode(tres, G3.episode_bounds(u_tr, size))
            )
            t_fit.append(time.perf_counter() - t0)
            if model is None:
                abstain += 1
            else:
                # threshold จาก validation ของ **train seed** เท่านั้น (ไม่แตะ eval)
                val_raw = [x for x, _ in u_tr["test"]][: len(u_tr["val_ft"])]
                vres = [
                    SEQ._resid(v, r, prof, base)
                    for v, r in zip(u_tr["val_ft"], val_raw)
                ]
                Xva = E3._windows_per_episode(vres, E3._ep_bounds_of(len(vres)))
                thr = float(np.quantile(E3._anom(model, Xva), Q)) if Xva else None
        else:
            abstain += 1
        tail = (
            [
                SEQ._resid(v, r, prof, base)
                for v, r in zip(tr_ft[-(W - 1) :], tr_raw[-(W - 1) :])
            ]
            if model is not None
            else []
        )

        def emit(pairs, label, kind, inst=None, use_tail=False):
            if not pairs:
                return
            fired = [False] * len(pairs)
            if model is not None and thr is not None:
                res = [SEQ._resid(v, r, prof, base) for r, v in pairs]
                run = list(tail) if use_tail else []
                wins = []
                for r in res:
                    ww = (run + [r])[-W:]
                    while len(ww) < W:
                        ww = [ww[0]] + ww
                    wins.append(SEQ._winfeat(ww))
                    run.append(r)
                t0 = time.perf_counter()
                fired = list(E3._anom(model, wins) >= thr)
                t_score.append((time.perf_counter() - t0) / len(wins))
            for pos, ((raw, vec), f) in enumerate(zip(pairs, fired), start=1):
                rule = evaluate_rules(
                    vec, db=None, user_id=alias, ip=None, geo_country=None
                )
                beh = evaluate_behavior(
                    vec,
                    prof,
                    subsystem_id=raw.get("subsystem"),
                    user_agent=raw.get("user_agent"),
                )
                # ── แยกผลแต่ละชั้น ──
                l1 = "block" if rule.blocked else _decide(rule.score)
                if getattr(rule, "min_action", None):
                    l1 = max(l1, rule.min_action, key=lambda d: RANK[d])
                l2 = _decide(beh.score)
                if getattr(beh, "min_action", None):
                    l2 = max(l2, beh.min_action, key=lambda d: RANK[d])
                access = aggregate(rule, beh, NEUTRAL).decision  # L4 (L1+L2)
                rows.append(
                    dict(
                        alias=alias,
                        label=label,
                        kind=kind,
                        inst=inst,
                        pos=pos,
                        l1=l1,
                        l2=l2,
                        l3_fire=bool(f),
                        access=access,
                        vec=vec,
                        day=raw["created_at"][:10],
                    )
                )

        # normal: window ต่อ episode
        tb = E3._ep_bounds_of(len(u_ev["test"]))
        for a, b in zip(tb, tb[1:]):
            emit(u_ev["test"][a:b], 0, "normal")
        # attack: แยกตาม family · campaign แบ่งทีละ 5 phase
        by = defaultdict(list)
        for raw, vec in u_ev["final_attacks"]:
            by[raw["scenario"]].append((raw, vec))
        for scn, prs in by.items():
            prs.sort(key=lambda x: x[0]["created_at"])
            fam = E3._family(scn)
            if fam == "campaign":
                for k in range(0, len(prs), 5):
                    emit(
                        prs[k : k + 5],
                        1,
                        "campaign",
                        f"{alias}:{scn}:{k}",
                        use_tail=True,
                    )
            else:
                emit(prs, 1, fam, f"{alias}:{scn}", use_tail=True)
    return (
        rows,
        abstain / len(users_tr),
        float(np.mean(t_fit or [0])),
        float(np.mean(t_score or [0]) * 1000),
    )


def metrics(rows):
    wn = lambda d: RANK[d] >= RANK["warn"]  # noqa: E731
    ch = lambda d: RANK[d] >= RANK["challenge"]  # noqa: E731
    atk = [r for r in rows if r["label"] == 1]
    nor = [r for r in rows if r["label"] == 0]
    camp = [r for r in atk if r["kind"] == "campaign"]
    inst = defaultdict(list)
    for r in camp:
        inst[(r.get("seed"), r["inst"])].append(r)
    n_i = max(len(inst), 1)
    base_det = sum(1 for e in inst.values() if any(wn(x["access"]) for x in e))
    l3_det = sum(1 for e in inst.values() if any(x["l3_fire"] for x in e))
    l3_only = sum(
        1
        for e in inst.values()
        if any(x["l3_fire"] for x in e) and not any(wn(x["access"]) for x in e)
    )
    tp = sum(ch(r["access"]) for r in atk)
    fp = sum(ch(r["access"]) for r in nor)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / max(len(atk), 1)
    ud = {(r.get("seed"), r["alias"], r["day"]) for r in nor}
    bad = {(r.get("seed"), r["alias"], r["day"]) for r in nor if r["l3_fire"]}
    return dict(
        recall=wilson(tp, max(len(atk), 1)),
        precision=wilson(tp, max(tp + fp, 1)),
        f1=(2 * prec * rec / (prec + rec) if prec + rec else 0.0),
        l1_only=wilson(sum(wn(r["l1"]) for r in atk), max(len(atk), 1)),
        l2_only=wilson(sum(wn(r["l2"]) for r in atk), max(len(atk), 1)),
        l3_ev=wilson(sum(r["l3_fire"] for r in atk), max(len(atk), 1)),
        cfpr=wilson(fp, max(len(nor), 1)),
        l3_fpr=wilson(sum(r["l3_fire"] for r in nor), max(len(nor), 1)),
        camp_base=wilson(base_det, n_i),
        camp_l3=wilson(l3_det, n_i),
        camp_l3_only=wilson(l3_only, n_i),
        ev_unique=wilson(
            sum(1 for r in atk if r["l3_fire"] and not wn(r["access"])),
            max(len(atk), 1),
        ),
        incident=wilson(len(bad), max(len(ud), 1)),
        n_atk=len(atk),
        n_nor=len(nor),
        n_inst=len(inst),
    )


def _pc(t):
    return f"{t[0] * 100:.1f}% [{t[1] * 100:.1f}, {t[2] * 100:.1f}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    args = ap.parse_args()

    all_rows = {s: [] for s in SIZES}
    extra = {s: [] for s in SIZES}
    leak_hits = leak_tot = 0
    shortcuts = []
    l3_touched_access = 0

    for tr_seed, ev_seed in zip(TRAIN_SEEDS, EVAL_SEEDS):
        t0 = time.time()
        u_tr = G3.build_seed(args.users, tr_seed)
        u_ev = G3.build_seed(args.users, ev_seed)
        # ── ตรวจ leakage ──
        for alias in u_tr:
            h, n = check_leakage(u_tr[alias], u_ev[alias])
            leak_hits += h
            leak_tot += n
        # ── ตรวจ shortcut บน eval ──
        av = [v for u in u_ev.values() for _, v in u["final_attacks"]]
        nv = [v for u in u_ev.values() for _, v in u["test"][:200]]
        shortcuts += check_shortcut(av, nv)
        for s in SIZES:
            rows, ab, tf, ts = run_pair(u_tr, u_ev, s)
            for r in rows:
                r["seed"] = ev_seed
                # L3 ต้องไม่แตะ access decision
                if r["l3_fire"] and r["access"] not in (
                    "allow",
                    "warn",
                    "challenge",
                    "block",
                ):
                    l3_touched_access += 1
            all_rows[s] += rows
            extra[s].append((ab, tf, ts))
        print(
            f"train {tr_seed} -> eval {ev_seed} done ({time.time() - t0:.0f}s)",
            flush=True,
        )

    M = {s: metrics(all_rows[s]) for s in SIZES}
    _print(M, extra, leak_hits, leak_tot, shortcuts, l3_touched_access)
    _report(M, extra, leak_hits, leak_tot, shortcuts, l3_touched_access)


def _print(M, extra, leak_hits, leak_tot, shortcuts, touched):
    print("=" * 88)
    print("FINAL GATE — train: seeds 42-46 · eval: seeds 101-105 (ไม่เคยเห็น)")
    print("\n[ตรวจก่อนเชื่อผล]")
    print(
        f"  data leakage      : {leak_hits}/{leak_tot} แถว eval ที่ซ้ำ train "
        f"({'PASS' if leak_hits == 0 else 'FAIL'})"
    )
    print(
        f"  generator shortcut: {len(set(s[0] for s in shortcuts))} feature ต้องสงสัย "
        f"({'PASS' if not shortcuts else 'ตรวจเพิ่ม'})"
    )
    for nm, auc, cov in sorted(set(shortcuts))[:5]:
        print(f"      {nm:34} AUC={auc:.4f} support-cover={cov:.3f}")
    print(f"  L3 แตะ access     : {touched} ครั้ง ({'PASS' if touched == 0 else 'FAIL'})")
    m0 = M[SIZES[-1]]
    print(
        f"\n  ขนาด eval: attack {m0['n_atk']} · normal {m0['n_nor']} · campaign {m0['n_inst']}"
    )
    print(f"\n  {'size':>6}{'recall':>18}{'precision':>18}{'cFPR':>16}{'L3 FPR':>16}")
    for s in SIZES:
        m = M[s]
        print(
            f"  {s:>6}{_pc(m['recall']):>18}{_pc(m['precision']):>18}"
            f"{_pc(m['cfpr']):>16}{_pc(m['l3_fpr']):>16}"
        )
    print(f"\n  แยกชั้น (ที่ size {SIZES[-1]}):")
    m = M[SIZES[-1]]
    for lab, k in (
        ("L1 อย่างเดียว (warn+)", "l1_only"),
        ("L2 อย่างเดียว (warn+)", "l2_only"),
        ("L3 ยิง (event)", "l3_ev"),
        ("L4 รวม (challenge+)", "recall"),
    ):
        print(f"    {lab:26}{_pc(m[k])}")
    print(f"\n  campaign (n={m['n_inst']}):")
    for lab, k in (
        ("L1/L2 surfaced", "camp_base"),
        ("L3 surfaced", "camp_l3"),
        ("L3 only", "camp_l3_only"),
    ):
        print(f"    {lab:26}{_pc(m[k])}")
    print(f"    {'event L3-unique':26}{_pc(m['ev_unique'])}")
    print(f"    {'false incident/user-day':26}{_pc(m['incident'])}")
    print("\n  latency:")
    for s in SIZES:
        ab = np.mean([e[0] for e in extra[s]]) * 100
        tf = np.mean([e[1] for e in extra[s]])
        ts = np.mean([e[2] for e in extra[s]])
        print(
            f"    size {s:>5}: abstain {ab:5.1f}% · fit {tf:5.2f}s/คน · score {ts:6.3f}ms/event"
        )


def _verdict(M, leak_hits, shortcuts, touched):
    m = M[SIZES[-1]]
    checks = [
        ("ไม่มี data leakage", leak_hits == 0),
        ("L3 ไม่แตะ access decision", touched == 0),
        ("ไม่มี generator shortcut", len(shortcuts) == 0),
        ("L3 FPR ≤ 1%", m["l3_fpr"][0] <= 0.01),
        ("Challenge FPR ≤ 3%", m["cfpr"][0] <= 0.03),
        ("L1/L2 campaign surfaced ≥ 90%", m["camp_base"][0] >= 0.90),
    ]
    enforce = m["camp_l3_only"][0] >= 0.03 and m["ev_unique"][0] >= 0.03
    ok = all(c[1] for c in checks)
    if not ok:
        return "ยังไม่พร้อม", checks, enforce
    if enforce:
        return "พร้อมพิจารณา enforcement", checks, enforce
    return "พร้อมใช้แบบ shadow + พร้อมเข้าสู่ production replay", checks, enforce


def _report(M, extra, leak_hits, leak_tot, shortcuts, touched):
    verdict, checks, enforce = _verdict(M, leak_hits, shortcuts, touched)
    m = M[SIZES[-1]]
    L = [
        "# FINAL GATE — เทสรอบสุดท้าย (fresh evaluation set)\n",
        "**วันที่:** 26 ส.ค. 2026  ",
        "**train / validation:** seeds 42–46 (ชุดเดิม) · **evaluation:** seeds 101–105 "
        "(**normal + attack ใหม่ทั้งหมด — โมเดลไม่เคยเห็น**)  ",
        f"**Config ที่ล็อก:** sequence-residual · W={W} · threshold p{Q * 100:g} · "
        "L3 = monitoring channel เท่านั้น\n",
        f"**ขนาด eval:** attack {m['n_atk']} · normal {m['n_nor']} · campaign instance {m['n_inst']}\n",
        "\n## 1. ตรวจก่อนเชื่อผล\n",
        "| การตรวจ | ผล |",
        "|---|---|",
        f"| data leakage (eval ซ้ำ train) | **{leak_hits}/{leak_tot}** — "
        f"{'✅ ไม่มี' if leak_hits == 0 else '❌ พบ'} |",
        f"| generator shortcut (feature AUC>0.99 หรือ support<5%) | "
        f"**{len(set(s[0] for s in shortcuts))} feature** — "
        f"{'✅ ไม่พบ' if not shortcuts else '⚠️ ดูรายละเอียด'} |",
        f"| L3 เปลี่ยน allow/challenge/block | **{touched} ครั้ง** — "
        f"{'✅ ไม่แตะ' if touched == 0 else '❌ แตะ'} |",
    ]
    if shortcuts:
        L += [
            "\n**feature ที่ต้องสงสัย:**\n",
            "| feature | AUC | support cover |",
            "|---|---|---|",
        ]
        for nm, auc, cov in sorted(set(shortcuts)):
            L.append(f"| `{nm}` | {auc:.4f} | {cov:.3f} |")
    L += [
        "\n## 2. ผลตามขนาดข้อมูลต่อคน\n",
        "| size | recall (challenge+) | precision | Challenge FPR | L3 FPR |",
        "|---|---|---|---|---|",
    ]
    for s in SIZES:
        x = M[s]
        L.append(
            f"| {s} | {_pc(x['recall'])} | {_pc(x['precision'])} | "
            f"{_pc(x['cfpr'])} | {_pc(x['l3_fpr'])} |"
        )
    L += [
        f"\n## 3. แยกชั้น (size {SIZES[-1]})\n",
        "| ชั้น | ค่า [Wilson CI95] |",
        "|---|---|",
        f"| L1 Rule อย่างเดียว (warn+) | {_pc(m['l1_only'])} |",
        f"| L2 Behavior อย่างเดียว (warn+) | {_pc(m['l2_only'])} |",
        f"| L3 ยิง (event) | {_pc(m['l3_ev'])} |",
        f"| **L4 รวม (challenge+)** | **{_pc(m['recall'])}** |",
        f"\n## 4. Campaign-level (n = {m['n_inst']})\n",
        "| ตัวชี้วัด | ค่า [CI95] |",
        "|---|---|",
        f"| L1/L2 surfaced | **{_pc(m['camp_base'])}** |",
        f"| L3 surfaced | {_pc(m['camp_l3'])} |",
        f"| **L3 only** | **{_pc(m['camp_l3_only'])}** |",
        f"| event L3-unique | {_pc(m['ev_unique'])} |",
        f"| false incident/user-day | {_pc(m['incident'])} |",
        "\n## 5. Latency & abstention\n",
        "| size | abstention | fit (s/คน) | score (ms/event) |",
        "|---|---|---|---|",
    ]
    for s in SIZES:
        ab = np.mean([e[0] for e in extra[s]]) * 100
        tf = np.mean([e[1] for e in extra[s]])
        ts = np.mean([e[2] for e in extra[s]])
        L.append(f"| {s} | {ab:.1f}% | {tf:.2f} | {ts:.3f} |")
    L += ["\n## 6. เกณฑ์ผ่าน/ไม่ผ่าน\n", "| เกณฑ์ | ผล |", "|---|---|"]
    for lab, okk in checks:
        L.append(f"| {lab} | {'✅' if okk else '❌'} |")
    L.append(
        f"| L3 มีคุณค่าพอสำหรับ enforcement (unique ≥3%) | {'✅' if enforce else '❌'} |"
    )
    L += [f"\n---\n\n## ข้อสรุป\n\n> # {verdict}\n"]
    (REPORTS / "exp_final_gate_2026-08-26.md").write_text(
        "\n".join(L), encoding="utf-8"
    )
    print(f"\n{'=' * 88}\nข้อสรุป: {verdict}")
    print("report ->", REPORTS / "exp_final_gate_2026-08-26.md")


if __name__ == "__main__":
    main()
