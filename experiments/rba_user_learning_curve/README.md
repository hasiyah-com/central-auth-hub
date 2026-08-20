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

## Train and evaluate every feature-ready run

```bash
python experiments/rba_user_learning_curve/scripts/evaluate_runs.py
```

To evaluate only selected runs, repeat `--run-id`:

```bash
python experiments/rba_user_learning_curve/scripts/evaluate_runs.py \
  --run-id rba_user_learning_curve_v1-normal_staggered-n10-s42 \
  --run-id rba_user_learning_curve_v1-normal_nat_burst-n10-s42
```

Each run trains one global Isolation Forest using only its normal `train`
split. No scaler is used. The requested `max_samples=256` is capped at the
available train-row count for small runs and recorded in model metadata. The
runner writes `model/iforest.pkl`, `model/metadata.json`, `predictions.jsonl`,
and `metrics.json` inside the ignored run directory, then updates that run's
existing row in `results/combined_run_results.csv`.

The final score mirrors the production contribution rules:

- Rule score: new device, user-agent family, failed-login, impossible-travel,
  and shared-IP multi-account rules.
- Per-user behavior score: 30-day temporal, country, and weekend profile;
  fewer than five prior events uses the production cold-start score. New-device
  scoring stays only in the Rule layer, matching production fix B56.
- Isolation Forest score: production sigmoid conversion followed by the
  0.1/0.2/0.4 contribution bands.
- Aggregator: sum capped at 1.0 with warn/challenge/block thresholds
  0.5/0.7/0.85. Experimental decisions use shadow labels `would_*`.

The primary confusion matrix and F1 use `challenge+` as the positive decision.
The same combined row also stores false-positive and attack-recall rates for
`warn+`, `challenge+`, and `block`, plus the decision distribution. Normal test
events update normal history sequentially; every attack event is evaluated
against the same frozen completed-normal snapshot and never updates history.

Cross-subsystem risk propagation is deliberately excluded from this replay.
That production layer feeds previous risk scores back into later logins, which
would violate the experiment's frozen, memoryless comparison unless evaluated
as a separate stateful experiment.

## Run the complete 60-run matrix

```bash
python experiments/rba_user_learning_curve/scripts/run_matrix.py \
  --git-commit-sha <40-character-commit-sha>
```

This command runs 2 normal scenarios × 6 dataset sizes × 5 seeds. It resumes
completed runs, rebuilds a run when its manifest commit SHA differs, and keeps
exactly one row per run in the combined CSV. Use `--force` only when every
selected artifact must be rebuilt. For a smaller diagnostic subset, repeat
`--dataset-size`, `--seed`, or `--normal-scenario` with the desired values.

## Current phase

This phase contains configuration, JSON Schemas, mapping preflight, the
deterministic raw-event generator, isolated SQLite loading, point-in-time
23-feature extraction, production-shaped Isolation Forest training, four-layer
evaluation, combined-result upsert, and validation tests.

## Feature Contract V2 experiment

The V2 runner is an isolated follow-up; it does not replace the production-
shaped V1 replay or train a production model. It adds varied normal timing,
browser-version drift, session duration, benign retries, and rare benign
overlap while preserving the 12 alias profiles, fixed `192.168.10.1` private
IP, no Geo, chronological 80:20 split, five seeds, and frozen attacks.

```bash
python experiments/rba_user_learning_curve/scripts/run_feature_contract_v2.py
```

It writes one combined result set under
`results/feature_contract_v2/` for six stages: diverse V1, disjoint V2, full
V2, Rule-only, Behavior-only, and ML-only. Feature ownership is exclusive at
the scored-feature level:

- Rule: deterministic security and policy facts.
- Behavior: user-relative rarity and sequence deviation from trusted normal
  history.
- ML: continuous residual and multivariate features only.

The reportable metrics include standard challenge recall/FPR, warn/block FPR,
ROC-AUC, PR-AUC, and severity-aware policy success. Contextual off-hours and OS
changes require at least a warning; combined ATO requires a block; the other
simulations require challenge or block.
