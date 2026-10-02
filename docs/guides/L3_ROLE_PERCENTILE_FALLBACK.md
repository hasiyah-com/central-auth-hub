# L3 percentile fallback from main

L1+L2 remain responsible for access decisions. With a configured calibration
artifact, L3 generates a monitoring warning only when the baseline decision is
`allow`. It never changes the access score, reasons, challenge, block or MFA.
Existing raw L3 diagnostics/SHAP remain available for inspection; when enabled,
`monitoring_decision` comes from the calibrated fallback instead of raw cutoffs.
Sequence diagnostics are retained but do not independently trigger a fallback
warning. Hard-block paths still skip L3 entirely.

For each user type (`student`, `teacher`, `staff`, `admin`), the artifact contains
sorted normal point scores and a separate `warn_percentile` threshold. A score's
percentile is the fraction of normal scores **strictly lower** than it. A warning
fires when percentile is **strictly greater** than that role's threshold. Tied
scores do not artificially create an anomalous percentile. These percentiles
are ranks, not attack probabilities.

Calibration requires at least 200 known-benign baseline-allow scores per role
from an independent `validation-calibration` split. Do not infer benign labels
from `allow`: use independently checked labels. Thresholds must be chosen on
separate validation-tuning data before independent evaluation. Different roles
may use different percentile budgets; no unmeasured production values are shipped.
Samples must come from `l3-evaluate.point.anomaly_score`, with its four-decimal
precision, and the same model fingerprint. The fingerprint is SHA256 of the
exact bytes loaded in the ML process, and travels through the Hub client.
Missing/invalid artifacts, unknown roles, model mismatch and unavailable point
scores produce `abstain` and never interrupt login. No pooled-role substitution.

## Build and compare

Input JSON for calibration:

```json
{
  "split": "validation-calibration",
  "model_sha256": "<64 lowercase hex characters>",
  "records": [
    {"user_type":"student", "score":0.57, "baseline_decision":"allow",
     "is_attack":false, "model_sha256":"<same fingerprint>"}
  ]
}
```

Include enough scores for all four roles. Attack and non-allow records are
excluded from calibration; all samples must belong to the same model.
The following thresholds demonstrate syntax only, not validated recommendations.

```bash
cd hub/backend
PYTHONPATH=. python -m scripts.build_l3_role_calibration \
  --input /path/calibration-scores.json --output /path/new-role-calibration.json \
  --thresholds '{"student":0.97,"teacher":0.99,"staff":0.99,"admin":0.99}'

PYTHONPATH=. python -m scripts.evaluate_l3_role_fallback \
  --calibration /path/new-role-calibration.json \
  --input /path/independent-evaluation-scores.json --output /path/new-comparison.json
```

Evaluation uses the same record schema with `split: validation-evaluation` and
reports paired baseline vs fallback warn-inclusive detection and warn FPR for
each role. Challenge recall/FPR and block FPR stay unchanged. Missing role samples
produce null rates; abstentions are explicitly counted. Reports are point
estimates only: user-cluster confidence intervals, independent split provenance,
per-role FPR budgets and fresh final holdout must still be checked before rollout.
Output files are created exclusively and cannot overwrite existing results.

## Activation and visibility

Mount the reviewed calibration file inside the Hub container and set
`L3_ROLE_CALIBRATION_PATH` to its absolute path, then restart Hub. Deploy the ML
service change too, because older services do not report a model fingerprint and
will cause abstention. Restart the ML service after replacing its model; regenerate
calibration for changed model bytes. An empty path preserves legacy monitoring.

Session detail shows fallback status, user type, percentile and that type's
threshold. Results also persist at `risk_breakdown.l3.fallback`, with explicit
`warn`, `normal`, `skipped` or `abstain` statuses and a reason. No database migration.
No private calibration/evaluation dataset or trained replacement model is
included; this change does not claim an accuracy gain or activate a live rollout.
