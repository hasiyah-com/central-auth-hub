# V8 layer comparison — production L1/L2 and offline personal L3

Date: 2026-09-28. Pre-registered in `REAL_SEEDED_V8_LAYER_PREREG.md`.
Validation uses 32 new synthetic aliases, seeds 771–773, 2,000 normal
training events per alias, normal-only calibration, and 6.481% attack events
per seed in tuning. The 16 holdout aliases remain unopened. The unchanged
production L1 and L2 scores, Policy Gate, L4 fuse and resolver were used.
L3 personal point fitting is offline and has no production service parity.

| Layers (Policy in all arms) | Recall | Precision | Warn FPR | Challenge FPR | Block FPR |
| --- | ---: | ---: | ---: | ---: | ---: |
| L1 only | — | — | — | — | — |
| L2 only | 69.26% | 60.61% | 2.533% | 0.586% | 0.254% |
| L1 + L2 (B) | 71.82% | 61.14% | 2.708% | 0.456% | 0.278% |
| B + L3 point (C) | 76.46% | 59.17% | 2.692% | 0.965% | 0.268% |
| B + L3 sequence (D) | 66.90% | 57.01% | 2.715% | 0.782% | 0.266% |
| B + L3 max (E) | 75.15% | 58.60% | 2.770% | 0.910% | 0.266% |
| B + L3 consensus (G) | 75.45% | 59.51% | 2.762% | 0.796% | 0.305% |

L1 alone had no threshold satisfying the normal-only calibration budget,
so there is **no gate-eligible L1 row**. For context only, evaluating L1 with
B's threshold gave 44.67% recall, 93.87% precision, and 0.012% Block FPR;
that threshold was not calibrated for L1 and this number cannot be claimed as
L1 validation success.

The mixed tuning set contained the same events for every arm. B surfaced
2,413 attacks and 1,534 normals. C surfaced 2,569 attacks and 1,773 normals;
E surfaced 2,525 attacks and 1,784 normals. Each arm has separately frozen
normal-only thresholds, so differences between arms include threshold
recalibration. At **E's own fixed thresholds**, an L3-off counterfactual
within E shows 612 additional attacks surfaced and 1,246 additional normal
events surfaced when enabling L3. This direct comparison shows why adding
L3 currently harms precision even as it helps recall.

No arm reached 70% precision. The upper user/seed cluster Block FPR bound
was 0.394% for B and 0.377% for E, exceeding the 0.2% budget; neither
passed the full gate. The result supports continued offline investigation,
not holdout, shadow or L3 enforcement. A future evaluation should add
expert-labeled legitimate lookalike events and verify service parity and
capacity before any deployment decision.
