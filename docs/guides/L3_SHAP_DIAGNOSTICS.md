# L3 / SHAP diagnostics and risk decision display

## Correct interpretation

- Rule and Behavior can legitimately score 0 when no weighted condition fires.
- The stored `risk_decision` remains the L1+L2 baseline for historical compatibility.
- New `access_decision` records the risk policy result after the optional L3 fallback,
  before any subsequent MFA completion. Neither field is an authentication result.
- The risk score is still L1+L2; a fallback can raise Allow to Warn without increasing it.
- The UI shows both stages. For historical records, it uses the recorded applied
  fallback/trial evidence rather than mistaking baseline Allow for the final outcome.
- SHAP contributions are model explanation units, not risk points or probabilities.
  A positive contribution for country_count=1 does not mean a new country was observed.

## Operational states

New records preserve under `risk_breakdown.l3`:

| Field | Meaning |
| --- | --- |
| point_available | Whether an actual Point IForest score was returned |
| error / point_error | Whole-request and point errors |
| sequence_error | Sequence failure, independent of the Point score |
| explainer | ML's explainer initialization state |
| shap_status / shap_count | Explanation returned, unavailable, or no point score |
| point_model_sha256 | Fingerprint of the actual loaded model |

The independent `/v1/score` recovery endpoint now returns the model fingerprint,
so a recovered Point result can be checked against its role calibration table.
The UI shows a dash for an explicitly unavailable Point score; a genuine available
zero remains zero. Old records without availability metadata remain unverified.
`explanation_unavailable` is not treated as a model score failure.

## Deployment and verification

Deploy both hub-backend and ml-service to receive the diagnostic and recovery
metadata, and hub-frontend for the corrected display. No database migration,
threshold change, retraining or secret change is required.

Use a test account and inspect a new login. In backend logs look for
`l3 degraded`, and in ML logs `SHAP TreeExplainer unavailable` or
`SHAP explain failed`. Check ML `/health` from inside the private service network
for model/explainer readiness. Do not expose the ML port publicly to diagnose it.

The default combined L3 timeout is 0.5 seconds, with independent Point recovery
using the 2-second ML budget. These budgets are unchanged. Startup, concurrent
Sequence fitting, network problems, missing artifacts or incompatible dependencies
must be distinguished using the recorded errors; this patch does not establish
which of them happened on the deployed server or promise a latency bound.

## Validation

- Regression-first: four backend and three UI tests failed before the patch.
- Local backend L3/risk/fallback regression group: 125 passed.
- Local frontend suite: 94 passed; TypeScript and production build passed.
- Added metadata test to the real ML test suite for CI.
- Frontend CI now includes production build, in addition to TypeScript and Jest.
- Full GitHub CI must be green before merging. Real server failure diagnosis and
  login UAT remain separate from these automated tests.
