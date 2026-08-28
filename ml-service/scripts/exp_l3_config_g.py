"""Config G — All-eligible-feature Sequence-Residual IForest (per-user) เทียบ Config F.

สเปค: L3 ประเมิน **ทุกฟีเจอร์ที่มีข้อมูลจริง** โดยแปลงเป็น "พฤติกรรมเบี่ยงเบนรายคน + ลำดับ"
ก่อนเข้า IsolationForest แล้วส่งผลให้ L4 เป็น **Monitoring Alert** ไม่ใช่บวกคะแนน

  Config F : 6 ฟีเจอร์ (residual-owned)  × [mean, slope, ptp] = 18 inputs  (ของเดิม)
  Config G : ทุกฟีเจอร์ที่ eligible      × [mean, slope, ptp] = 3N inputs  (ของใหม่)

การแปลงตามประเภท (ตามสเปค):
  - ต่อเนื่อง / ค่านับ      : residual เทียบ median/IQR ของ "คนนั้น"
  - boolean / ค่าที่ IQR=0  : อัตราการเกิดเทียบประวัติ (x − mean)/std  ← rate deviation
  - variance เป็นศูนย์ต่อคน : ตัดทิ้ง (ไม่มีข้อมูลให้เทียบ)
  - geo ที่คงที่จาก campus NAT : ไม่ใช้

Threshold (calibrate จาก train-normal ของคนนั้น):
  p99 -> investigate · p99.9 -> extreme monitoring (ทั้งคู่ไม่สั่ง MFA/block)

Monitoring label ที่ส่งให้ L4:
  normal · l3_unique_investigate (L1/L2 ผ่านแต่ L3 ยิง) · l3_overlap (ยิงพร้อมกัน)

เกณฑ์ตัดสิน G > F: unique ไม่น้อยกว่า F · challenge FPR ไม่เพิ่ม · warn FPR ในงบ ·
latency รับได้ · CI ของส่วนต่างไม่คร่อมศูนย์

Run: cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/exp_l3_config_g.py
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
import lc_l3_ownership as O  # noqa: E402
import lc_l3_sequence as SEQ  # noqa: E402
import lc_run_4layer as LC  # noqa: E402

from app.security.behavior_profiling import evaluate_behavior  # noqa: E402
from app.security.iforest_scorer import IForestResult  # noqa: E402
from app.security.risk_aggregator import aggregate  # noqa: E402
from app.security.rule_engine import evaluate_rules  # noqa: E402

REPORTS = LC.REPORTS
RANK = LC.RANK
FEATURES = LC.FEATURES
SIZE = 5000
W = 5
P_INVESTIGATE = 0.99
P_EXTREME = 0.999
NEUTRAL = IForestResult(0.0, 0.0, "neutral")

# geo ที่ตายเพราะ campus NAT — ไม่ใช้ตามสเปค
GEO_DEAD = {
    "is_thailand",
    "is_new_country",
    "country_change_count_30d",
    "impossible_travel_score",
}
G_CANDIDATES = [f for f in FEATURES if f not in GEO_DEAD]
G_IDX = [FEATURES.index(f) for f in G_CANDIDATES]


def _scale_params(col):
    """เลือกวิธี normalize ตามประเภทข้อมูล — คืน (kind, center, scale) หรือ None ถ้าไม่มี variance."""
    iqr = float(np.quantile(col, 0.75) - np.quantile(col, 0.25))
    if iqr > 1e-6:  # ต่อเนื่อง/ค่านับ -> robust residual
        return ("robust", float(np.median(col)), iqr)
    sd = float(col.std())
    if sd > 1e-9:  # boolean/rare -> อัตราการเกิดเทียบประวัติ
        return ("rate", float(col.mean()), sd)
    return None  # คงที่ต่อคนนี้ -> ตัดทิ้ง


def fit_g_scaler(train_vecs):
    """หา params การแปลงต่อฟีเจอร์ จาก train-normal ของผู้ใช้คนนั้น."""
    X = np.asarray(train_vecs, dtype=float)[:, G_IDX]
    params, keep = [], []
    for j in range(X.shape[1]):
        p = _scale_params(X[:, j])
        if p is not None:
            params.append(p)
            keep.append(j)
    return (params, keep) if keep else None


def g_residual(vec, scaler):
    params, keep = scaler
    x = np.asarray(vec, dtype=float)[G_IDX][keep]
    return [(v - c) / s for v, (_, c, s) in zip(x, params)]


def _winfeat(res_window):
    a = np.asarray(res_window, dtype=float)
    return np.concatenate([a.mean(axis=0), a[-1] - a[0], a.max(axis=0) - a.min(axis=0)])


def _fit_if(X):
    X = np.asarray(X, dtype=float)
    if len(X) < 20:
        return None
    keep = X.std(axis=0) > 1e-9
    if not keep.any():
        return None
    m = IsolationForest(n_estimators=100, contamination=0.02, random_state=42).fit(
        X[:, keep]
    )
    a = -m.score_samples(X[:, keep])
    return (
        m,
        keep,
        float(np.quantile(a, P_INVESTIGATE)),
        float(np.quantile(a, P_EXTREME)),
    )


def _score(model, X):
    if model is None or len(X) == 0:
        z = np.zeros(len(X), bool)
        return np.zeros(len(X)), z, z
    m, keep, thr, ext = model
    a = -m.score_samples(np.asarray(X, dtype=float)[:, keep])
    return a, a >= thr, a >= ext


def run_seed(users):
    rows = []
    timing = {
        "fit_f": [],
        "fit_g": [],
        "score_f": [],
        "score_g": [],
        "dims_f": [],
        "dims_g": [],
    }
    for alias, u in users.items():
        prof = LC.build_profile(u["train_raw"][:SIZE])
        tv, tr_ = u["train_ft"][:SIZE], u["train_raw"][:SIZE]
        base = O._baseline(tv)

        # ── Config F: 6 residual-owned -> 18 ──
        t0 = time.perf_counter()
        tres_f = [SEQ._resid(v, r, prof, base) for v, r in zip(tv, tr_)]
        Xf = [_winfeat(tres_f[i - W + 1 : i + 1]) for i in range(W - 1, len(tres_f))]
        mf = _fit_if(Xf)
        timing["fit_f"].append(time.perf_counter() - t0)
        timing["dims_f"].append(len(Xf[0]) if Xf else 0)

        # ── Config G: ทุกฟีเจอร์ eligible -> 3N ──
        t0 = time.perf_counter()
        scaler = fit_g_scaler(tv)
        tres_g = [g_residual(v, scaler) for v in tv] if scaler else []
        Xg = [_winfeat(tres_g[i - W + 1 : i + 1]) for i in range(W - 1, len(tres_g))]
        mg = _fit_if(Xg) if Xg else None
        timing["fit_g"].append(time.perf_counter() - t0)
        timing["dims_g"].append(len(Xg[0]) if Xg else 0)

        tail_f = tres_f[-(W - 1) :]
        tail_g = tres_g[-(W - 1) :] if tres_g else []

        def evaluate(pairs, label, scen):
            if not pairs:
                return
            wf, run = [], list(tail_f)
            wg, rung = [], list(tail_g)
            for raw, vec in pairs:
                r = SEQ._resid(vec, raw, prof, base)
                w = (run + [r])[-W:]
                while len(w) < W:
                    w = [w[0]] + w
                wf.append(_winfeat(w))
                run.append(r)
                if scaler:
                    rg = g_residual(vec, scaler)
                    w2 = (rung + [rg])[-W:]
                    while len(w2) < W:
                        w2 = [w2[0]] + w2
                    wg.append(_winfeat(w2))
                    rung.append(rg)

            t0 = time.perf_counter()
            _, ff, fe = _score(mf, wf)
            timing["score_f"].append((time.perf_counter() - t0) / max(1, len(wf)))
            t0 = time.perf_counter()
            if wg:
                _, gf, ge = _score(mg, wg)
            else:
                gf = ge = np.zeros(len(pairs), bool)
            timing["score_g"].append((time.perf_counter() - t0) / max(1, len(pairs)))

            for i, (raw, vec) in enumerate(pairs):
                rule = evaluate_rules(
                    vec, db=None, user_id=alias, ip=None, geo_country=None
                )
                beh = evaluate_behavior(
                    vec,
                    prof,
                    subsystem_id=raw.get("subsystem"),
                    user_agent=raw.get("user_agent"),
                )
                access = aggregate(rule, beh, NEUTRAL).decision  # L1+L2 เท่านั้น (ตามสเปค)
                rows.append(
                    dict(
                        label=label,
                        scenario=scen(raw),
                        access=access,
                        f_fire=bool(ff[i]),
                        f_ext=bool(fe[i]),
                        g_fire=bool(gf[i]),
                        g_ext=bool(ge[i]),
                    )
                )

        evaluate(u["test"], 0, lambda r: "normal")
        byscn = {}
        for raw, vec in u["attacks"]:
            byscn.setdefault(raw["scenario"], []).append((raw, vec))
        for scn, pairs in byscn.items():
            pairs.sort(key=lambda p: p[0]["created_at"])
            evaluate(pairs, 1, lambda r: r["scenario"])
    return rows, timing


def monitoring_label(r, cfg):
    """ป้าย monitoring ที่ L4 จะได้รับ (ตามสเปค)."""
    if not r[f"{cfg}_fire"]:
        return "normal"
    return "l3_unique_investigate" if r["access"] == "allow" else "l3_overlap"


def metrics(rows, cfg):
    atk = [r for r in rows if r["label"] == 1]
    nor = [r for r in rows if r["label"] == 0]
    wn = lambda d: RANK[d] >= RANK["warn"]  # noqa: E731
    ch = lambda d: RANK[d] >= RANK["challenge"]  # noqa: E731
    camp = [r for r in atk if r["scenario"] == "campaign"]
    fire = f"{cfg}_fire"

    def uniq(g):
        return (
            (sum(1 for r in g if r[fire] and not wn(r["access"])) / len(g))
            if g
            else 0.0
        )

    return dict(
        unique=uniq(atk),
        unique_campaign=uniq(camp),
        overlap=sum(1 for r in atk if r[fire] and wn(r["access"])) / len(atk),
        standalone=sum(r[fire] for r in atk) / len(atk),
        extreme=sum(r[f"{cfg}_ext"] for r in atk) / len(atk),
        # access decision มาจาก L1+L2 เท่านั้น -> challenge FPR ไม่ขึ้นกับ L3 (ตามสเปค)
        cfpr=sum(ch(r["access"]) for r in nor) / len(nor),
        # warn FPR หลังรวม monitoring: normal ที่ถูกยก investigate
        wfpr=sum(1 for r in nor if wn(r["access"]) or r[fire]) / len(nor),
        l3_fpr=sum(r[fire] for r in nor) / len(nor),
        n_atk=len(atk),
        n_nor=len(nor),
        n_camp=len(camp),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
    args = ap.parse_args()

    accF, accG, tims = [], [], []
    for seed in args.seeds:
        BP.SEED = seed
        t0 = time.time()
        users = LC.gen_all(args.users)
        rows, tm = run_seed(users)
        accF.append(metrics(rows, "f"))
        accG.append(metrics(rows, "g"))
        tims.append(tm)
        print(f"seed {seed} done ({time.time() - t0:.0f}s)", flush=True)

    _print(accF, accG, tims, args.seeds)
    _report(accF, accG, tims, args.seeds)


def _fmt(acc, key):
    m, e = O.ci95([a[key] for a in acc])
    return f"{m * 100:.1f}±{e * 100:.1f}"


def _delta(accG, accF, key):
    return O.ci95([g[key] - f[key] for g, f in zip(accG, accF)])


def _timing(tims):
    def avg(k):
        return float(np.mean([np.mean(t[k]) for t in tims]))

    return dict(
        fit_f=avg("fit_f"),
        fit_g=avg("fit_g"),
        score_f=avg("score_f") * 1000,
        score_g=avg("score_g") * 1000,
        dims_f=int(np.mean([np.mean(t["dims_f"]) for t in tims])),
        dims_g=int(np.mean([np.mean(t["dims_g"]) for t in tims])),
    )


def _verdict(accF, accG):
    du = _delta(accG, accF, "unique")
    dc = _delta(accG, accF, "cfpr")
    dw = _delta(accG, accF, "wfpr")
    ok_unique = du[0] >= -1e-9 and abs(du[0]) > du[1]  # ไม่น้อยกว่า F + CI ไม่คร่อม 0
    ok_cfpr = dc[0] <= 1e-9
    ok_wfpr = dw[0] * 100 <= 2.0  # งบ warn FPR +2pp
    return du, dc, dw, (ok_unique and ok_cfpr and ok_wfpr)


ROWS = [
    ("unique", "L3 unique"),
    ("unique_campaign", "L3 unique (campaign)"),
    ("standalone", "standalone"),
    ("overlap", "overlap"),
    ("extreme", "extreme rate"),
    ("l3_fpr", "L3 FPR (normal)"),
    ("cfpr", "Challenge FPR"),
    ("wfpr", "Warn FPR (รวม monitor)"),
]


def _print(accF, accG, tims, seeds):
    t = _timing(tims)
    print("=" * 76)
    print(f"Config F (6 feat -> {t['dims_f']}) vs Config G (eligible -> {t['dims_g']})")
    print(
        f"  {len(seeds)} seeds · size {SIZE} · attack {accF[0]['n_atk']} · normal {accF[0]['n_nor']}\n"
    )
    print(f"  {'metric':26}{'Config F':>13}{'Config G':>13}{'delta (G-F)':>17}")
    for key, lab in ROWS:
        d = _delta(accG, accF, key)
        print(
            f"  {lab:26}{_fmt(accF, key):>13}{_fmt(accG, key):>13}"
            f"{d[0] * 100:>+11.1f}±{d[1] * 100:<5.1f}"
        )
    print(
        f"\n  latency: fit F {t['fit_f']:.2f}s / G {t['fit_g']:.2f}s ต่อคน · "
        f"score F {t['score_f']:.3f}ms / G {t['score_g']:.3f}ms ต่อ event"
    )
    du, dc, dw, ok = _verdict(accF, accG)
    print(
        f"\n  เกณฑ์: unique {du[0] * 100:+.1f}±{du[1] * 100:.1f} · "
        f"cFPR {dc[0] * 100:+.1f} · wFPR {dw[0] * 100:+.1f}"
    )
    print(f"  => {'ใช้ Config G' if ok else 'คง Config F ไว้'}")


def _report(accF, accG, tims, seeds):
    t = _timing(tims)
    du, dc, dw, ok = _verdict(accF, accG)
    L = [
        "# Config G — All-eligible-feature Sequence-Residual IForest เทียบ Config F\n",
        "**วันที่:** 26 ส.ค. 2026  ",
        f"**seeds:** {seeds} (mean ± 95% CI) · size {SIZE} events/user · ชุดทดสอบเดียวกันทุก config  ",
        f"**ขนาด:** attack {accF[0]['n_atk']} · normal {accF[0]['n_nor']} (campaign {accF[0]['n_camp']})\n",
        "\n## การออกแบบที่ทดสอบ\n",
        "| | Config F (ปัจจุบัน) | Config G (ที่เสนอ) |",
        "|---|---|---|",
        "| ฟีเจอร์ต้นทาง | 6 (residual-owned) | ทุกฟีเจอร์ที่ eligible |",
        f"| inputs หลัง window | **{t['dims_f']}** | **{t['dims_g']}** |",
        "| การแปลง | residual median/IQR | robust residual + rate-deviation ตามประเภท |",
        "| window | 5 · [mean, slope, ptp] | 5 · [mean, slope, ptp] |",
        "| threshold | p99 | p99 (investigate) + p99.9 (extreme) |",
        "| ส่งให้ L4 | monitoring channel | monitoring channel |",
        "\n## ผลเปรียบเทียบ\n",
        "| metric | Config F | Config G | Δ (G−F) |",
        "|---|---|---|---|",
    ]
    for key, lab in ROWS:
        d = _delta(accG, accF, key)
        star = "**" if key == "unique" else ""
        L.append(
            f"| {star}{lab}{star} | {_fmt(accF, key)} | {_fmt(accG, key)} "
            f"| {d[0] * 100:+.1f}±{d[1] * 100:.1f} |"
        )
    L += [
        "\n## Latency\n",
        "| | Config F | Config G |",
        "|---|---|---|",
        f"| fit ต่อคน | {t['fit_f']:.2f}s | {t['fit_g']:.2f}s |",
        f"| score ต่อ event | {t['score_f']:.3f}ms | {t['score_g']:.3f}ms |",
        "\n## เกณฑ์ตัดสิน\n",
        "| เกณฑ์ | ผล |",
        "|---|---|",
        f"| unique ไม่น้อยกว่า F (CI ไม่คร่อม 0) | Δ **{du[0] * 100:+.1f} ± {du[1] * 100:.1f}** pp |",
        f"| Challenge FPR ไม่เพิ่ม | Δ {dc[0] * 100:+.1f} pp |",
        f"| Warn FPR เพิ่มไม่เกินงบ (+2pp) | Δ {dw[0] * 100:+.1f} pp |",
        f"| latency รับได้ | fit {t['fit_g']:.2f}s · score {t['score_g']:.3f}ms |",
        f"\n> **ข้อสรุป: {'ใช้ Config G เป็น L3 ตัวจริง' if ok else 'คง Config F ไว้ — G ยังไม่ผ่านเกณฑ์'}**\n",
    ]
    (REPORTS / "exp_l3_config_g_2026-08-26.md").write_text(
        "\n".join(L), encoding="utf-8"
    )
    print("\nreport ->", REPORTS / "exp_l3_config_g_2026-08-26.md")


if __name__ == "__main__":
    main()
