"""U01 ระเบิดใน testA เพราะอะไร — policy floor หรือ score-driven?"""

import sys
from collections import Counter
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

THR = {"warn": 0.98, "challenge": 0.995, "block": 0.9999}
GAMMA = 1.0
CHALLENGED = {"challenge", "block"}


def main():
    seed = int(sys.argv[1])
    size = int(sys.argv[2])
    target = sys.argv[3]
    raw = G3.build_seed(BP.DEFAULT_USERS_XLSX, seed)
    splits = DS.build(BP.DEFAULT_USERS_XLSX, seed, size, raw=raw)
    pm, sm, ecdf = X.fit_all(splits, size, raw)
    eps = sorted(
        {int(r["episode"]) for u in splits.values() for r, _ in u.holdout_normal}
    )
    lo, hi = eps[0], eps[-1]
    mid = lo + (hi - lo + 1) // 2

    sub = {
        a: replace(
            u,
            holdout_normal=[
                (r, v) for r, v in u.holdout_normal if int(r["episode"]) < mid
            ],
            holdout_attacks=[],
        )
        for a, u in splits.items()
        if a == target
    }
    ctxs = X.compute_layer_outputs(sub, pm, sm, "holdout")
    print(f"{target} · seed {seed} · testA ep[{lo},{mid}) · {len(ctxs)} normal events")

    floors = Counter()
    prim = Counter()
    layers = Counter()
    byep = Counter()
    n_ch = 0
    for c in ctxs:
        d = CFG.evaluate(
            CFG.CONFIGS["B"],
            c.policy,
            c.rule,
            c.behavior,
            c.l3,
            calibrate_fn=ecdf,
            gamma=GAMMA,
            thresholds=THR,
        )
        if d.decision.removeprefix("would_") not in CHALLENGED:
            continue
        n_ch += 1
        res = d.breakdown.get("resolver") or {}
        pol = d.breakdown.get("policy") or {}
        floors[
            pol.get("min_action")
            if isinstance(pol, dict)
            else getattr(pol, "min_action", None)
        ] += 1
        for r in (pol.get("reasons") if isinstance(pol, dict) else []) or []:
            prim[r.split("=")[0]] += 1
        ev = d.breakdown.get("evidence", {})
        top = max(
            ev.items(),
            key=lambda kv: (kv[1] or {}).get("evidence_score", 0) or 0,
            default=(None, {}),
        )
        layers[top[0]] += 1
    print(f"  challenged = {n_ch} ({n_ch/len(ctxs)*100:.2f}%)")
    print(f"  policy min_action distribution: {dict(floors)}")
    print(f"  policy floor reasons: {dict(prim)}")
    print(f"  ชั้นที่ให้หลักฐานสูงสุด: {dict(layers)}")


if __name__ == "__main__":
    main()
