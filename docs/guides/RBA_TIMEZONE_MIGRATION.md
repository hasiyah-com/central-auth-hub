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
