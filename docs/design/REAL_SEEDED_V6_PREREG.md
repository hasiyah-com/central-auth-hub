# V6 independent synthetic pilot — preregistered candidate

Frozen 2026-09-28 after V5 attribution, before generating V6 outcomes.

V5 diagnostic: 160 normal Blocks, 142 campaign-like; among all normal Blocks
149 had both hour mismatch and hour rarity, and 114 had fast cadence. Of 30
rare-device attacks, rarity fired 24 times yet 23 of those were Allowed.

Candidate for an offline experiment only: when `hours_diff` and `hour_rarity`
co-occur in L2, subtract 0.30 from L2 raw score (one correlated temporal
signal remains). When `signature_rarity` fires, add 0.20 to the raw L2 score,
making its total contribution 0.35. No rule/Policy Gate/L3/fusion change and
no special treatment of the `campaign_like_normal` label. Control is the
unmodified V5 L2. Do not alter production defaults before independent review.

- New population seed `810929`, 48 aliases `Z01`–`Z48`, validation 32 and
  unopened holdout 16; data seeds `751,752,753`. Same source prototypes and
  V5 canonicalized generator. Synthetic resampling from the same aggregate
  source is not a true independent real-world sample.
- Both candidates use behavioral 10 features, training history 100 and 2,000,
  normal-only training/calibration, same Config E and gamma 0.35.
- Rebuild behavior ECDF from normal calibration for the candidate. Calibrate
  action thresholds on normal-only calibration across all seeds/sizes, freeze
  before tuning. Test mixed tuning with ≤7% anomaly; campaign-like normals
  remain in tuning only. Never tune on V6 outcomes.
- Report precision, recall, family recall, normal Block attribution, FPR,
  per-seed and cluster gates. Pilot must meet all original quality and FPR
  gates to justify a later full nine-size validation; holdout remains closed
  regardless. The point model still has no service parity or capacity gate.
