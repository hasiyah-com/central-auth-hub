# V7: L3 view aggregation pilot, frozen before V7 outcomes

Date 2026-09-28. V6 diagnostic found 185/310 normal Challenges with L3 as
primary layer and 105/310 campaign-like normals. V6 rare-device sample had
only six events; do not assert that this family passed on that basis.

- New synthetic population seed `810930`, aliases `W01`–`W48`, validation
  32/holdout 16; data seeds `761,762,763`, training history 2,000.
- All candidates use behavioral 10 features and the frozen V6 L2 adjustment
  (subtract 0.30 for correlated hour mismatch + rarity, add 0.20 when
  signature rarity fires). Compare production Config E (max of point/sequence),
  G (consensus of both), C (point only), D (sequence only). Same gamma 0.35,
  Policy, rules, fusion and 23-feature vector; no new model loss.
- Each candidate gets normal-only behavior ECDF and normal-only action
  threshold calibration across three seeds, frozen before mixed tuning.
  No tuning thresholds on attack or normal tuning examples.
- Attack fraction ≤7% per seed, and report aggregate/per-seed recall,
  precision, family recall and FPR with cluster bounds and source attribution.
  Fewer than 30 rare-device events in pooled tuning means its recall is
  explicitly underpowered regardless of percentage.
- Original gates: recall/precision ≥70%; family recall ≥50%; cluster upper
  bounds warn ≤5%, challenge ≤1%, block ≤0.2%; every seed passes. Only if
  these pass consider full history sweep. Synthetic resampling of the same
  source is not independent real-world expert validation. Holdout remains
  unopened; no production enforcement/shadow or parity/capacity claim.
