# RBA User Learning-Curve Experiment

This directory defines the reproducible contract for evaluating the Central Auth Hub's global Isolation Forest together with per-user behavior profiles.

## Scope

- 12 approved user profiles: 11 existing users plus `adminxz@gmail.com`.
- One shared IP: `192.168.10.1`.
- No GeoIP data. Production-compatible geo features are fixed to `is_thailand=1`, `is_new_country=0`, `country_change_count_30d=0`, and `impossible_travel_score=0`.
- Students may use both subsystems.
- Teachers are evaluated under subsystem policy.
- `furafae@gmail.com` may use Library only.
- `xssearo@gmail.com` may use Dorm only.
- Hub admins may use a subsystem only when they own it.
- Every admin login requires MFA; a successful admin login ends as `mfa_passed`.
- Trusted history contains only `allow` and `mfa_passed`.

## Experiment families

1. `normal_staggered`: normal users are spread out so no more than five distinct users share the IP in a rolling hour.
2. `normal_nat_burst`: at least six distinct normal users share the IP in a rolling hour. The ground truth remains normal so any friction is counted as a false positive.
3. `attack_test`: device, user-agent, time, velocity, session, passkey, permission, and combined-takeover scenarios. Geo attacks are excluded.

## Data flow

`config -> raw login events -> isolated experiment database -> 23-feature snapshots -> global Isolation Forest -> four-layer predictions -> metrics`

Raw events must not contain model scores or final decisions. Those values are produced by the real scoring pipeline and written only to prediction outputs.

## Split

For each user and dataset size, events are sorted chronologically. The first 80% form train/profile history and the final 20% form normal test. Attack rows are a separate fixed test set. The 10-row experiment is cold-start diagnostic only.

## Safety

- Never point experiment scripts at the production database.
- Never overwrite `ml-service/models/iforest_v1.pkl`.
- Generated data and run results are ignored by Git.
- Every run records commit SHA, configuration hash, feature-contract hash, seed, thresholds, and model parameters.

## Current phase

This commit contains configuration, JSON Schemas, and validation tests only. Event generation, database loading, training, and evaluation runners are intentionally not implemented yet.
