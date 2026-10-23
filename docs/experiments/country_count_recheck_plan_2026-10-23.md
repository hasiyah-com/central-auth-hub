# Country-count semantic correction: evaluation plan

Written before running corrected-model evaluation. Baseline source: main 631b72a.
The previous synthetic-only audit already exposed the country-count problem;
this round is targeted development, not preregistered independent-user confirmation.

- Generate paired legacy-v0 / distinct-v1 rows, seeds 202610231–202610233.
- Per seed: 20,000 normal and 1,000 attack rows, same random stream except country count.
- Assert the other 22 features and labels match exactly before measuring.
- Hold out 20% calibration and 20% test by stratified row splits (42/43).
- Fit two normal-only IFs on the same 60% train indices; parameters unchanged
  (100 trees, max_samples 256, contamination .02, model seed 42).
- Compare both models on the SAME corrected test vectors; also report legacy
  holdout results separately, so correcting the evaluation data cannot be mistaken
  for model improvement. Neither fit nor threshold selection sees test rows.
- Report Precision/Recall/F1/FPR, TP/FP/TN/FN, ROC-AUC and AP for Point IF alone.
- Compare existing warn .4606, Point .50 and a per-model benign-only calibration
  threshold targeting 1% FPR. Use >= consistently with runtime, choosing a value
  just above the higher 99th percentile to avoid equality inflating calibration FPR.
- Report normal midnight, 0–5h, country 1 and >=2 slices with denominators.
- Stress missing GeoIP/history country count 0 separately; these are constructed
  inputs and must not be called real-traffic FPR.
- Replay the cropped-screenshot REPRESENTATIVE vector (missing fields assumed,
  never call it the actual server session) and verify SHAP path-length additivity.
- Flag corrected-test FPR >1.1%, midnight FPR >3%, and recall loss >0.5pp versus
  the old model on the corrected test. These are screening checks, not permission
  to deploy; do not relax them after results.
- No automatic model replacement, production threshold change, training on real
  user sessions, or new claim about end-to-end C3/PG-E F1.
- Time distributions remain unchanged: the screenshot alone cannot establish a
  realistic population mix. A full per-user/raw-event generator is a separate study.
