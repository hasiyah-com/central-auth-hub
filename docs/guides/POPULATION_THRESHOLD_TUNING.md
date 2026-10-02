# Population-aware threshold tuning

This is validation tooling built on `feature/hybrid-risk-round2`, not a new
trained model or a passed final gate. Round 2c exceeded the challenge FPR budget
at history size 50 (1.18% vs 1%). Its report identifies underestimated population
variance across the five validation seeds as the next problem to investigate.

## What the new command measures

`tune-population` requires at least 20 distinct validation populations and a
complete seed × history-size grid. Normal-score quantiles are computed separately
for each cell. The grid includes both P95 across populations and the worst
population, taking the most conservative size for each threshold. Equal weights
prevent a large population from hiding a smaller population's tail.

Every operating point is evaluated by `hybrid_experiment.tune.stat_direct`, which
calls production `resolve_action`. Policy denies, mandatory step-up, and the L3
solo-block cap remain part of the measurement. Every seed/size must respect the
existing warn/challenge/block FPR budgets (5% / 1% / 0.2%); P95 is reported for
diagnosis and never excuses a worst-population failure.

Among eligible points, selection prioritizes challenge-or-block recall, then
warn-inclusive recall, then precision. Thus additional soft warnings do not win
over actual attack step-up. Thresholds preserve full precision and move strictly
above benign quantile ties because production compares scores with `>=`.
At the score ceiling, use 1.0 and let the real resolver/budget checks determine
eligibility. Normal ties at 1.0 may leave no eligible threshold: report failure
rather than inventing a deployable threshold above 1.0.

The report includes macro metrics, per-size metrics, population P95/worst FPR,
policy-only floors, the complete candidate grid, commit, scoring fingerprint,
and split fingerprint. Missing benign/attack data, invalid scores, incomplete
grids, and corrupt provenance fail closed. Existing report files cannot be
overwritten. Nothing is written to tune/freeze/final artifacts.

## Run on the ML development host

Use the same private users workbook and generator configuration as the existing
experiment. First register a new validation seed set and independent final
holdout in the experiment protocol. Do not use opened holdout or Round 3's
reserved seeds 201–205. The command checks both the committed provenance
snapshot and the local holdout ledger. The generator/cache must be generated
from the intended population and current code: the legacy pickle cache does not
contain a scoring fingerprint, so this command cannot prove old caches are fresh.

The following seed range is a syntax example, not an approved experiment split.
Declare the actual splits before generating or viewing experimental results.

```bash
cd hub/backend
python ../../ml-service/scripts/exp_hybrid_gate.py prepare \
  --seeds $(seq 10001 10020) --sizes 50 100 500 1000 5000 \
  --users /path/to/private/users.xlsx

python ../../ml-service/scripts/exp_hybrid_gate.py tune-population \
  --seeds $(seq 10001 10020) --sizes 50 100 500 1000 5000 \
  --config B --gamma 1.0 --output /path/to/new/population-validation.json
```

Exit 0 means a validation candidate exists; exit 1 means no eligible candidate
or missing prepared cells. **Neither exit code certifies final generalization.**
The command never opens final holdout and always writes `deploy_ready: false`.
Its output is not consumed automatically by the old `freeze` command. Review
validation, run parity/shortcut/leakage checks, pre-register and freeze the
candidate, then evaluate an independent final holdout once using the existing
gate procedure. Existing failed-gate results and production scoring stay intact.

## Verification in this checkout

```bash
python -m pytest --noconftest \
  hub/backend/tests/test_population_tuning.py \
  hub/backend/tests/test_round2_statistics.py \
  hub/backend/tests/test_scoring_freeze.py -q
```

This command isolates the offline harness/statistics tests; it does not certify
the live PostgreSQL/Redis integration suite. CLI adapter tests require the ML
host dependencies and skip when that harness cannot be imported. No private
users workbook, prepared cells, trained candidate, or final experiment results
are included in this change. Accuracy gains must be measured on the declared
validation and independent holdout before making a claim.
