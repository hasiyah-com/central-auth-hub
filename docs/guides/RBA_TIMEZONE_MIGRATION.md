# RBA calendar timezone: Asia/Bangkok

Database timestamps remain naive UTC. Only calendar interpretation (hour, weekday,
personalized hour distance, weekday usage, profile hour histogram and weekend
pattern) uses Asia/Bangkok. Aware inputs are normalized to naive UTC before DB
queries. Rolling 24-hour/30-day windows and elapsed credential ages remain UTC.

Profiles are calculated from raw session timestamps on each request, so no stored
histogram migration is required. Existing saved feature vectors, SHAP values and
risk reasons describe historical evaluations and must not be rewritten.

## Deployment gate

This change alters the feature contract for the point and sequence models.
API requests now require `feature_contract: rba-23-bangkok-v1`. Upgrade Hub and
ML service together; Hub rejects responses from old ML services. The point loader
rejects estimators without the matching `rba_feature_contract_` attribute instead
of reporting a misleading score. Health reports an unready point model.

Sequence residuals now use `l3resid:bangkok-v1:{user_id}` on both services.
Old keys remain intact for rollback; no data is deleted or relabeled. Sequence
models build fresh history and abstain until their existing eligibility tiers
are met. Restart both services so process-local caches are discarded.

Before deploying, regenerate labeled features via `export_labeled_data.py` (which
calls the production extractor), rebuild temporal training inputs from timestamped
sources, retrain and recalibrate the models, and evaluate normal/attack holdouts.
Do not merely rotate an already extracted hour column: weekday boundaries and
the median-based personalized hour feature also change.

Frozen experiment scripts and their synthetic timestamp conventions are historical
evidence. They remain unchanged; their previous metrics must not be presented as
validation of the Bangkok feature contract. Any new synthetic pipeline must
explicitly declare whether its timestamps are UTC or Bangkok wall time.

Check 2026-10-02 20:49 UTC -> 2026-10-03 03:49 Bangkok (Saturday), and
2026-10-02 16:59 UTC -> Friday 23:59 Bangkok, with unchanged 24-hour durations.

## Training and activation workflow

1. Run `python -m scripts.export_labeled_data` in hub-backend. Transfer BOTH
   `real_labeled.csv` and `real_labeled.csv.meta.json` to ml-service.
2. Run `python -m scripts.train_bangkok_model --data /app/data/real_labeled.csv
   --output /app/models/bangkok-candidate` in ml-service. This stages a candidate
   and validation report without overwriting the active model.
3. Evaluate independent users/time periods and rebuild role calibration records
   using this candidate's actual point scores/hash and updated L1+L2 decisions.
   Use the existing `build_l3_role_calibration.py` and
   `evaluate_l3_role_fallback.py`; don't invent role thresholds without data.
4. Activate the validated candidate as `/app/models/iforest_v1.pkl`, deploy both
   services together and restart them. Configure the NEW matching calibration
   artifact; the old hash-bound artifact abstains rather than using old percentiles.

`generate_data.py` creates explicit Bangkok wall-clock synthetic features with a
checksum-bound sidecar. `train_model.py` also requires the same contract sidecar,
so a legacy UTC CSV cannot be silently mixed into new training. Do not change an
old sidecar or tag an old estimator to bypass checks: rebuild from sources.

## Smoke experiment, 2026-10-03

Synthetic feature-level data only (10,000 normal / 500 anomaly, seed 42).
Split rows 60/20/20: 6,300 training, 2,100 calibration, 2,100 test. Fit only
training normals; select p99 from calibration normals, never test labels.
Runtime: sklearn 1.5.2, numpy 2.1.3, joblib 1.4.2.

| Test operating point | FPR (2,000 normal rows) | Recall (100 attack rows) |
| --- | --- | --- |
| Calibration p99, score >0.5171205 | 1.30% | 85% |
| Existing point score >0.50 | 2.15% | 92% |
| Existing monitoring score >0.70 | 0% | 0% |

ROC-AUC: 0.98947. The pipeline works, but this candidate is NOT approved for
production: the 0.70 operating point detects nothing in this synthetic holdout,
and calibrated FPR exceeds a 1% point target. Thresholds were not adjusted after
seeing test results. These are row-level synthetic results, not independent-user
or real-traffic validation. The previous production model was not available for a
paired model comparison. The archived experiment ZIP contains derived vectors,
not the source timestamp history needed to rebuild temporal features.

Timezone conversion does not automatically lower hour rarity: rotating current
and historical hour bins together preserves their frequencies. It fixes the hour
label and weekday interpretation; weekend and median-based hour features can
change. A login at 03:49 can still be rare for that user.
