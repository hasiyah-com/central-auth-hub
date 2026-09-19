import sys
from collections import Counter
from pathlib import Path

ML = Path("E:/hub/central-auth-starter/ml-service")
sys.path.insert(0, str(ML / "scripts"))
sys.path.insert(0, str(Path("E:/hub/central-auth-starter/hub/backend")))
import build_profiles_v2 as BP  # noqa: E402
import exp_hybrid_gate as X  # noqa: E402
import gen_v3 as G3  # noqa: E402
from hybrid_experiment import dataset as DS  # noqa: E402

seed, target = 46, "U01"
raw = G3.build_seed(BP.DEFAULT_USERS_XLSX, seed)
for size in (50, 500, 5000):
    splits = DS.build(BP.DEFAULT_USERS_XLSX, seed, size, raw=raw)
    u = splits[target]
    print(
        f"size {size:>5}: train subsystems = {dict(Counter(r.get('subsystem') for r in u.train_raw))}"
    )
    pm, sm, ecdf = X.fit_all(splits, size, raw)
    prof = sm[target][2]
    keys = [k for k in prof if "sub" in k.lower() or "hour" in k.lower()]
    print(f"          profile keys(subsystem/hour) = {keys}")
    for k in keys:
        v = prof[k]
        print(f"            {k} = {str(v)[:120]}")
te = Counter(r.get("subsystem") for r, _ in splits[target].holdout_normal)
print(f"holdout subsystems = {dict(te)}")
