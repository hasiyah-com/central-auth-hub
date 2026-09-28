# V6 offline pilot — correlated time evidence and rare-device signal

Date: 2026-09-28. Protocol frozen in `REAL_SEEDED_V6_PREREG.md` before V6
outcomes. New synthetic population seed 810929, 32 validation aliases,
16 unopened holdout aliases, event seeds 751–753; anomaly 6.481% per seed.
Production L2 and resolver were not changed. The candidate modifies only
offline L2 raw scores, then recalibrates behavior ECDF and action thresholds
from normal-only calibration before scoring mixed tuning data.

| Candidate | History | Recall | Precision | Warn FPR | Challenge FPR | Block FPR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Control | 100 | 68.48% | 58.50% | 2.743% | 0.623% | 0.171% |
| Time dedup + rare bonus | 100 | 69.20% | 59.40% | 2.661% | 0.617% | 0.155% |
| Control | 2,000 | 79.02% | 60.69% | 2.851% | 0.697% | 0.182% |
| Time dedup + rare bonus | 2,000 | 78.69% | 62.17% | 2.539% | 0.780% | 0.140% |

At 2,000, normal campaign-like Blocks fell from 57 to 43. Rare-device recall
rose from 1/6 to 4/6, but **six events across three seeds are too few to
infer reliable family performance**. Challenge FPR increased. Precision
remains below 70%, calibration-budget FPR and cluster upper-bound gates fail,
and no candidate passed the preregistered gate at either history size.

V6 samples new synthetic users from the same aggregate source, so this is
useful development evidence but not independent real-world validation. The
candidate adjusts a previously clipped L2 score; production changes would
need an explicit score formula and separate service parity verification.
Do not use this result to open holdout, shadow, Step-up or Block. The next
version needs a preregistered design for challenge false positives and larger,
expert-labeled rare-device examples, followed by full validation and capacity
measurement. No threshold or candidate was chosen retrospectively on V6.
