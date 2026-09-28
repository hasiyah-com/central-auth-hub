# V5 pilot — production-compatible device signatures

Date: 2026-09-28. Protocol: `REAL_SEEDED_V5_SIGNATURE_PREREG.md`.

V5 used a new synthetic population (48 aliases, 32 validation and 16 unopened
holdout), seeds 741–743, history sizes 100 and 2,000, and the existing
23-feature extraction and fusion paths. Calibration was normal-only and
thresholds were written to `pilot_frozen.json` before evaluating tuning events.
The offline personal point model has **no service parity**. This is an offline
diagnostic pilot, not a deployment gate or full history-size validation.

| Features | History | Recall | Precision | Block FPR | Rare-device recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| all 23 | 100 | 64.3% | 61.4% | 0.281% | 6.7% |
| all 23 | 2,000 | 73.3% | 60.5% | 0.328% | 6.7% |
| behavioral | 100 | 67.7% | 62.9% | 0.285% | 3.3% |
| behavioral | 2,000 | 78.6% | 61.9% | 0.330% | 3.3% |
| behavioral + trust | 2,000 | 77.4% | 61.6% | 0.332% | 3.3% |
| behavioral + geo | 2,000 | 78.2% | 61.4% | 0.324% | 3.3% |

The `signature_rarity` reason was present for 24/30 rare-device attacks at
history 2,000 (16/30 at 100), yet 28–29/30 were allowed and the remainder
warned. Correcting the signature representation repaired signal detection,
but the current L2 score and resolver did not turn that signal into detection.
For all 23 features at history 2,000, 141/159 normal Blocks were legitimate
campaign-like events; for behavioral, 142/160. The Block FPR budget is 0.2%
at the upper cluster confidence bound; the observed point estimates already
exceed 0.2%. Precision is below the 70% target and rare-device recall below
the 50% per-family target. No tested candidate passes the pilot gate.

The V4 and V5 populations and seeds differ; their metric differences cannot
be attributed solely to canonicalization. This V5 result does not justify
threshold tuning on this tuning sample, opening holdout, shadow operation,
Step-up or Block. Next experiment should preregister a separate data set and
investigate L2 reason weights and legitimate campaign handling, with an
independent service parity and capacity check before any deployment decision.

Reproduction: run `population_real_seeded_v5.py` on the protected aggregate
source, then `exp_real_seeded_validation_v5.py` with its artifact, frozen, and
result paths. Private synthetic roster/results remain outside the repository.
