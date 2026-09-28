# V7 L3-view pilot results

Date: 2026-09-28. Pre-registered in `REAL_SEEDED_V7_PREREG.md`.
Validation used 32 new synthetic aliases (16 holdout aliases unopened), three
seeds 761–763, history 2,000, and an anomaly fraction of 6.481% per seed.
All candidates share the V6 offline L2 correction, behavioral 10-feature
point model and production Config C/D/E/G fusion; thresholds were calibrated
only on normal calibration and frozen before mixed tuning. No production
behavior was changed and the offline personal model lacks service parity.

| Config | L3 views | Recall | Precision | Challenge FPR | Block FPR |
| --- | --- | ---: | ---: | ---: | ---: |
| E | max(point, sequence) | 80.12% | 61.86% | 0.827% | 0.167% |
| G | point/sequence consensus | 79.02% | 63.12% | 0.724% | 0.248% |
| C | point only | 79.05% | 62.42% | 0.753% | 0.194% |
| D | sequence only | 75.77% | 61.06% | 0.780% | 0.194% |

The consensus candidate lowered normal campaign-like Challenge/Block events
from 165 (E) to 144, but raised Block FPR above the 0.2% point budget.
Pooled rare-device recall was 24/42 (57.14%) in all four candidates; despite
meeting the predeclared minimum sample count of 30, synthetic-only evidence
does not establish real-world sensitivity. No candidate met the 70% precision
gate, per-seed gate or all clustered FPR gates. None may open holdout.

The next blocker is false positive separation: changing the existing L3
views alone did not achieve the required precision while maintaining the
Block budget. Any further score/threshold changes need a new preregistered
validation protocol, larger varied legitimate event sets, and eventual
expert-labeled real shadow data and capacity/service parity checks.
