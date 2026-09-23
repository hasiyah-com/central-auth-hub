"""ตัวแปรจริงคือผู้ใช้หรือ block? — แยก challenge FPR ราย user ต่อ block."""

import sys
from dataclasses import replace
from pathlib import Path

ML = Path("E:/hub/central-auth-starter/ml-service")
sys.path.insert(0, str(ML / "scripts"))
sys.path.insert(0, str(Path("E:/hub/central-auth-starter/hub/backend")))

import build_profiles_v2 as BP  # noqa: E402
import exp_hybrid_gate as X  # noqa: E402
import gen_v3 as G3  # noqa: E402
from hybrid_experiment import configs as CFG  # noqa: E402
from hybrid_experiment import dataset as DS  # noqa: E402

USERS = BP.DEFAULT_USERS_XLSX
THR = {"warn": 0.98, "challenge": 0.995, "block": 0.9999}
GAMMA = 1.0
CHALLENGED = {"challenge", "block"}


def per_user(rows):
    agg = {}
    for r in rows:
        if r.is_attack:
            continue
        n, h = agg.get(r.user, (0, 0))
        agg[r.user] = (
            n + 1,
            h + (1 if r.decision.removeprefix("would_") in CHALLENGED else 0),
        )
    return {u: (h / n if n else 0.0) for u, (n, h) in agg.items()}


def run(seed, size):
    raw = G3.build_seed(USERS, seed)
    splits = DS.build(USERS, seed, size, raw=raw)
    pm, sm, ecdf = X.fit_all(splits, size, raw)
    eps = sorted(
        {int(r["episode"]) for u in splits.values() for r, _ in u.holdout_normal}
    )
    lo, hi = eps[0], eps[-1]
    mid = lo + (hi - lo + 1) // 2

    res = {}
    ctxs = X.compute_layer_outputs(splits, pm, sm, "tune")
    res["tune"] = per_user(X.apply_config(ctxs, CFG.CONFIGS["B"], ecdf, GAMMA, THR))
    for name, pred in (("testA", lambda e: e < mid), ("testB", lambda e: e >= mid)):
        sub = {
            a: replace(
                u,
                holdout_normal=[
                    (r, v) for r, v in u.holdout_normal if pred(int(r["episode"]))
                ],
                holdout_attacks=[],
            )
            for a, u in splits.items()
        }
        ctxs = X.compute_layer_outputs(sub, pm, sm, "holdout")
        res[name] = per_user(X.apply_config(ctxs, CFG.CONFIGS["B"], ecdf, GAMMA, THR))
    return res


if __name__ == "__main__":
    size = int(sys.argv[1])
    for seed in [int(x) for x in sys.argv[2].split(",")]:
        r = run(seed, size)
        users = sorted(r["tune"])
        print(f"\nseed {seed} · size {size} — challenge FPR ราย user (%)")
        print(f"{'user':<8}{'tune':>9}{'testA':>9}{'testB':>9}")
        for u in users:
            print(
                f"{u:<8}{r['tune'][u]*100:8.2f}%{r['testA'][u]*100:8.2f}%{r['testB'][u]*100:8.2f}%"
            )
        for b in ("tune", "testA", "testB"):
            v = sorted(r[b].values(), reverse=True)
            tot = sum(v)
            print(
                f"  {b:<6} top-1 user กินสัดส่วน {v[0]/tot*100:5.1f}% ของ FPR รวม · "
                f"top-3 = {sum(v[:3])/tot*100:5.1f}% · nonzero users = {sum(1 for x in v if x>0)}/{len(v)}"
            )
