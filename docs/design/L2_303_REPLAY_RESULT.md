# L1+L2 shadow calibration: 303 historical logins

Date: 2026-09-29. Candidate rules and evaluation limits were frozen in
`L2_303_REPLAY_PREREG.md` before replay. The source is a protected CSV; only
aggregate results are reported. There are no expert-confirmed attack or
legitimate labels. All rows say `is_attack_ip=False` and
`is_account_takeover=False`, which is **not** evidence that all are normal.

| Measure | Count |
| --- | ---: |
| Total login records | 303 |
| Comparable recorded `would_*` outcomes | 119 |
| Actual/non-shadow outcomes (`allow`, `mfa_passed`) | 184 |
| Both `hours_diff` and `hour_rarity` in reasons | 22 |
| `weekend_mismatch` in reasons | 58 |
| `new_subsystem` in reasons | 9 |
| L2 raw score reduced by proposed evidence rules | 73 |
| Total legacy score decreased | 57 |

Recorded shadow outcomes were 61 `would_block`, 45 `would_challenge`, and
13 `would_warn`. Within these 119, only 93 recorded decisions matched a
decision derived from the stored legacy score and thresholds alone; other
records can have floors or incomplete historical context. The bounded replay
would move seven recorded Blocks to Challenge, but also predicts one
Challenge as Block and several other transitions because it cannot reconstruct
their floors. **These are hypothetical score comparisons, not validated
decision changes.** No change was made to production, UI scores or `main`.

This CSV stores legacy `rule`, `behavior`, `iforest` floats, not current L4
Evidence, calibrated ECDF, Policy Gate provenance, feature vectors or
historical per-user profiles. Some stored behavior totals may already be
clipped. It cannot establish exact replay parity, current-system FPR,
precision, recall or a safe challenge floor for new subsystems.

Before merging any scoring change, obtain expert labels for normal login
lookalikes and attacks; retain normal-only temporal calibration, evaluate
the full current Policy/L1/L2/L4 path on a chronological replay, and require
challenge-or-block FPR ≤0.5% and clustered upper Block FPR ≤0.2% among
expert-confirmed normals. Also require the existing attack recall, precision,
per-family and per-seed gates. Validate the new-subsystem challenge floor
separately as a Policy Gate change and check that time-only evidence cannot
block. Existing L3 capacity and service-parity gates still apply.
