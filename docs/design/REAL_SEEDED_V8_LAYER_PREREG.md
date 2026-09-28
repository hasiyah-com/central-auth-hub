# V8 layer contribution comparison — frozen before V8 outcomes

Date: 2026-09-28. New synthetic population seed 810931, aliases `V01`–`V48`,
validation 32 / sealed holdout 16, data seeds 771–773, history 2,000.
Normal-only training and calibration; mixed tuning anomaly fraction ≤7%.

Use the **unchanged production L1 and L2 scores** and 23-feature extraction
throughout. Compare Policy + L1 alone, Policy + L2 alone, Policy + L1+L2
(Config B), and Policy + L1+L2 with L3 point (C), sequence (D), max (E),
consensus (G). Policy remains in every arm. Personal point model remains
offline without production service parity. Use production evidence, fusion
and resolver code for every arm; do not recreate access decisions in harness.
For every arm calibrate thresholds from normal calibration across three seeds
before reading mixed tuning. Keep gamma 0.35 fixed. Report recall, precision,
warn/challenge/block FPR, family recall, per-seed and cluster gates. Show
absolute incremental true positives and false positives for L3 arms relative
to B on exactly the same events, with the arm-specific frozen thresholds
clearly noted; these differences include threshold recalibration and are not
pure causal L3 effects. Include same-threshold counterfactual uniquely
surfaced events when available for a more direct L3 comparison.

Original gates: recall/precision ≥70%, every family recall ≥50%, cluster upper
warn ≤5%, challenge ≤1%, block ≤0.2%, every seed must pass. No holdout,
shadow or production enforcement from this synthetic-only comparison.
