# V5 history extension — preregistration

Frozen on 2026-09-28 before scoring history sizes beyond 2,000.

- Use the existing V5 validation aliases only, seeds 741–743, and unchanged
  population, generator, attack mix, 23-feature contract and fusion logic.
- Examine `all_23` and `behavioral` at 2,000, 3,000, 4,000, 5,000 nested
  training logins. The source contains exactly 5,000 training rows per alias.
- Reuse each group's V5 pilot thresholds from `pilot_frozen.json`, frozen on
  normal-only calibration for 100/2,000. Do not recalibrate after reading
  extension results. This is diagnostic extrapolation of those thresholds.
- Report recall, precision, warn/challenge/block FPR and per-family recall at
  each size; retain the same tuning events and closed holdout.
- Define stabilization prospectively: for both consecutive transitions
  2,000→3,000→4,000 or 3,000→4,000→5,000, absolute changes in recall and
  precision must each be <1 percentage point and block FPR <0.05 percentage
  point; require this in each seed and in pooled results. If no two intervals
  satisfy it by 5,000, report inconclusive and the fixed 5,000-row limit.
- This offline point model still lacks production service parity. Even if
  stable, stability alone cannot authorize holdout or enforcement.
