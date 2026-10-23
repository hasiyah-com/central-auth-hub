# Country-count semantics and SHAP unit correction (2026-10-23)

## What was wrong

Runtime counts distinct non-null countries in the preceding 30 days, excluding
future/current events. A user observed only in Thailand has count 1. The old
feature-level generator assigned ordinary patterns 0 for no country CHANGES.
That made 97% of simulated normal rows zero despite an assumed country history.
This is a semantic mismatch, not justification for changing real inputs to zero.

The default generator now uses `RBA_COUNTRY_COUNT_MODE=distinct-v1`. Ordinary
patterns shift their legacy change counts to distinct counts; the foreign pattern
already represented 2–5 distinct countries. All other feature values and random
stream consumption stay identical. `legacy-v0` reproduces the original vectors
for historical reports; the dataset metadata explicitly records the mode.
These feature-level samples assume known country history; missing GeoIP/cold
history may legitimately be zero in production and needs separate validation.
The mix of ordinary users with 1/2 countries is a synthetic assumption, not
measured population data. No geo country values or IP addresses are fabricated
for real logins.

Training provenance is embedded in newly generated artifacts. Existing server
artifacts are not replaced, retrained or declared verified by this code change.

## Recheck results: not approved for deployment

Plan: `docs/experiments/country_count_recheck_plan_2026-10-23.md`.
Full numeric results: `docs/experiments/results/country_semantics_2026-10-23.json`.
Three new synthetic seeds, each 20,000 normal + 1,000 attack rows. Per seed,
12,000 normal training rows, 4,000 normal calibration rows, and a held-out test
of 4,000 normal + 200 attacks. IF trains on NORMAL ONLY, matching this default
server training recipe; this is not the mixed-fit research model comparison.
Only country count differs in paired old/new data; all other 22 inputs match.
Models are evaluated on the SAME corrected test data. Calibration uses only
independent normal calibration rows and runtime's >= comparison.

| Seed | Old model FPR at .4606 | Corrected model FPR at .4606 | Corrected recall at .4606 |
|---|---:|---:|---:|
| 202610231 | 38.40% | 7.925% | 99.0% |
| 202610232 | 36.25% | 5.950% | 99.5% |
| 202610233 | 37.825% | 6.950% | 99.0% |

Fixed threshold .4606 fails the 1.1% screening budget in every seed. Independently
calibrating to 1% normal FPR gives the following candidate results:

| Seed | Threshold | Precision | Recall | F1 | FPR | ROC-AUC | AP |
|---|---:|---:|---:|---:|---:|---:|---:|
| 202610231 | .52114 | .8213 | .850 | .8354 | .925% | .99471 | .92677 |
| 202610232 | .51488 | .7580 | .830 | .7924 | 1.325% | .99414 | .91802 |
| 202610233 | .51720 | .8396 | .890 | .8641 | .850% | .99425 | .93958 |

Seed 202610232 still exceeds the budget. At independently calibrated thresholds,
the old model on corrected data recalls 91%, 87.5%, 94%, respectively: the new
model loses 4.5–6 percentage points, exceeding the .5pp screening allowance.
The candidate is therefore NOT a final accepted model. These high synthetic
attack recalls do not establish real-server or end-to-end system performance.
Do not report this table as the C3/PG-E F1 result or as independent-user confirmation.

The midnight distribution was NOT changed to fit one user's screenshot. The
cropped screenshot's missing inputs were assumed only in a clearly identified
representative probe; it is not a reconstruction of the actual server event.
Constructed country=0 stress is a one-feature perturbation, not a complete
missing-history scenario. No population weights were tuned after these results.
A floating-point boundary in the initial screening implementation was corrected
using exact TP-count arithmetic (1 lost TP / 200 attacks is exactly .5pp); the
screening allowance itself did not change.

## Correct SHAP interpretation

TreeExplainer for this sklearn IF explains mean corrected tree PATH LENGTH.
Positive raw SHAP increases path length (toward normal); the UI reverses the
sign for anomaly-oriented bars. The sign is correct, but the old comments and
UI tooltip incorrectly called the units decision_function units. They are now
corrected. SHAP is not a probability or an additive term in the risk score.
A regression test reconstructs path length, then the non-linear IF decision
function, independently from the tree paths.

## Reproduce without touching production artifacts

```bash
cd /app
RBA_COUNTRY_COUNT_MODE=distinct-v1 RBA_DATA_DIR=/tmp/country-recheck python -m scripts.generate_data
python -m scripts.evaluate_country_semantics --output /tmp/country-recheck-staged
```

The evaluation only creates `candidate_distinct_<seed>.pkl` under its specified
staging directory. It does not replace `models/iforest_v1.pkl`, change the live
threshold, or produce a new role calibration table. The initial 60/20/20 plan
is a stratified ROW split, not a user-level or chronological evaluation.

## Verify the actual loaded server model

Inside the ML container, after deploying the new script:

```bash
cd /app
python -m scripts.inspect_running_point
```

This sends a synthetic Point-only probe (no user IDs, no sequence-history write)
and reports the live worker's model hash from its HTTP response, the on-disk hash,
score and SHAP count. It never unpickles an unknown artifact. A separate Python
process loading the disk file cannot prove what the serving worker already has
cached; compare these two hashes instead. Repeated requests do not prove that
every replica was sampled. This task had no Dokploy/SSH access and did not verify
the deployed worker or the actual screenshot's complete 23 inputs.

Do not enable a new model using this candidate until fresh-user/temporal tests,
benign subgroups and recall-loss limits pass with model-matched calibration.
