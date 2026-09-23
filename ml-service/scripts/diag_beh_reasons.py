"""เหตุผลใดของ L2 ที่ทำให้ U01 ถูก challenge — และคะแนน behavior กระจายอย่างไร."""

import re
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
CH = {"challenge", "block"}
seed, size, target = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]

raw = G3.build_seed(BP.DEFAULT_USERS_XLSX, seed)
splits = DS.build(BP.DEFAULT_USERS_XLSX, seed, size, raw=raw)
pm, sm, ecdf = X.fit_all(splits, size, raw)
eps = sorted({int(r["episode"]) for u in splits.values() for r, _ in u.holdout_normal})
lo, hi = eps[0], eps[-1]
mid = lo + (hi - lo + 1) // 2
sub = {
    a: replace(
        u,
        holdout_normal=[(r, v) for r, v in u.holdout_normal if int(r["episode"]) < mid],
        holdout_attacks=[],
    )
    for a, u in splits.items()
    if a == target
}
ctxs = X.compute_layer_outputs(sub, pm, sm, "holdout")

scores = Counter()
ch_reasons = Counter()
all_reasons = Counter()
n_ch = 0
for c in ctxs:
    d = CFG.evaluate(
        CFG.CONFIGS["B"],
        c.policy,
        c.rule,
        c.behavior,
        c.l3,
        calibrate_fn=ecdf,
        gamma=1.0,
        thresholds=THR,
    )
    scores[round(c.behavior.score, 2)] += 1
    tags = [re.split(r"[ =]", r)[0] for r in c.behavior.reasons]
    for t in tags:
        all_reasons[t] += 1
    if d.decision.removeprefix("would_") in CH:
        n_ch += 1
        for t in tags:
            ch_reasons[t] += 1

print(f"{target} seed{seed} size{size} testA · {len(ctxs)} normal · challenged {n_ch}")
print("\nbehavior score distribution (ทุก normal):")
for s, n in sorted(scores.items()):
    print(
        f"  {s:>5}  {n:>4}  ({n/len(ctxs)*100:5.1f}%)  ecdf->{ecdf('behavior', s):.4f}"
    )
print("\nreason tags ใน normal ทั้งหมด:", dict(all_reasons.most_common(8)))
print("reason tags ใน normal ที่ถูก challenge:", dict(ch_reasons.most_common(8)))
