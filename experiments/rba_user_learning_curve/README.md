# RBA User Learning-Curve Experiment

This directory defines the reproducible contract for evaluating the Central Auth Hub's global Isolation Forest together with per-user behavior profiles.

## Privacy boundary

- Git-tracked files use stable, non-identifying `profile_id` aliases only.
- Real user UUIDs, emails, names, identifiers, and subsystem UUIDs belong only in `config/local_identity_mapping.json` on the machine that runs the experiment.
- The local mapping file is ignored by Git. Copy `config/local_identity_mapping.example.json`, replace every example value, and run mapping preflight before generation or database loading.
- Exported events, features, predictions, metrics, and reports keep aliases; they never contain resolved identities.
- Run manifests record only the SHA-256 hash of the canonical local mapping, so a run can be reproduced with the same mapping without exposing it.

## Scope

- 12 approved behavior profiles: six students, two teachers, two staff, and two Hub admins.
- One shared IP: `192.168.10.1`.
- No GeoIP data. Production-compatible geo features are fixed to `is_thailand=1`, `is_new_country=0`, `country_change_count_30d=0`, and `impossible_travel_score=0`.
- Students may use both subsystems.
- Teachers are evaluated under subsystem policy.
- One staff profile is Library-only; one is Dorm-only.
- Hub admins may use a subsystem only when they own it.
- Every admin login requires MFA; a successful admin login ends as `mfa_passed`.
- Trusted history contains only `allow` and `mfa_passed`.

## Experiment families

1. `normal_staggered`: normal users are spread out so no more than five distinct users share the IP in a rolling hour.
2. `normal_nat_burst`: at least six distinct normal users share the IP in a rolling hour. The ground truth remains normal so any friction is counted as a false positive.
3. `attack_test`: device, user-agent, time, velocity, session, passkey, permission, and combined-takeover scenarios. Geo attacks are excluded.

The two normal conditions are generated as separate isolated runs using the same dataset size and seed. This prevents NAT-burst history from contaminating the staggered baseline. The full matrix is 2 normal conditions × 6 sizes × 5 seeds = 60 runs.

## Data flow

`alias config + local mapping preflight -> raw login events -> isolated SQLite store -> 23-feature snapshots -> global Isolation Forest -> four-layer predictions -> combined results`

Raw events must not contain model scores or final decisions. Those values are produced by the real scoring pipeline and written only to prediction outputs.

## Split

For each profile, normal condition, and dataset size, events are sorted chronologically. The first 80% form train/profile history and the final 20% form normal test. Attack rows are a separate fixed test set evaluated against a frozen normal snapshot and never update history. The 10-row experiment is cold-start diagnostic only.

## Safety

- Never point experiment scripts at the production database.
- Never overwrite `ml-service/models/iforest_v1.pkl`.
- Generated data and run results are ignored by Git.
- Every run records commit SHA, configuration hash, feature-contract hash, local-mapping hash, seed, thresholds, and model parameters.

## Local mapping preflight

Copy the example to the ignored local filename, replace every example identity and subsystem UUID, then run:

```bash
python experiments/rba_user_learning_curve/scripts/preflight_mapping.py
```

The command fails on missing aliases, extra aliases, invalid or duplicate UUIDs/emails, placeholder values, and subsystem-key mismatches. Successful output contains counts and the mapping SHA-256 only.

## Generate one run

```bash
python experiments/rba_user_learning_curve/scripts/generate_events.py \
  --dataset-size 10 \
  --seed 42 \
  --normal-scenario normal_staggered \
  --git-commit-sha <40-character-commit-sha>
```

Run the same size and seed again with `normal_nat_burst` for the paired NAT comparison. Each run writes ignored `events.jsonl` and `manifest.json` files under `data/<run_id>/`. Generated outputs contain aliases only.

## Build features and combined results

```bash
python experiments/rba_user_learning_curve/scripts/build_features.py
```

The command discovers every generated run, creates an isolated
`experiment.sqlite3` and `feature_snapshots.jsonl` inside each run directory,
then upserts one row per `run_id` into:

`results/combined_run_results.csv`

Rerunning a run updates its existing row instead of creating a duplicate. At
this phase the row status is `features_ready`; model metrics remain empty until
the training/evaluation phase writes real values. The same row later receives
TP, FP, TN, FN, Precision, Recall, F1, ROC-AUC, PR-AUC, FPR, allow rate, and risk
distribution values.

## Current phase

This phase contains configuration, JSON Schemas, mapping preflight, the deterministic raw-event generator, isolated SQLite loading, point-in-time 23-feature extraction, combined-result upsert, and validation tests. Training and four-layer evaluation runners are not implemented yet.
