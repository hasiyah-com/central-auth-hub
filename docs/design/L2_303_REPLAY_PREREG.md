# L1+L2 historical shadow replay — preregistration

Frozen 2026-09-29 before computing the new candidate decisions.

Source: protected `login_sessions9.csv`, exactly 303 records, with recorded
legacy `risk_breakdown` floats and `risk_reasons`. Do not commit or print row
identifiers, IP, user agent, timestamps or raw reasons. Recorded labels
`is_attack_ip=False` and `is_account_takeover=False` are **not** expert
confirmation of legitimate login. `mfa_passed` is an actual outcome rather
than a shadow risk decision. Only `would_*` records have comparable recorded
shadow decisions. The file predates the current Policy Gate/L4 evidence
contract and lacks source feature vectors and historical profiles. Replay
from recorded L2 reasons and raw scores is a **bounded legacy counterfactual**,
not production parity or a measured false-positive rate.

Candidate rule set (no threshold tuning on these records):

1. On L2, when `hours_diff` and `hour_rarity` both fired, keep the larger
   contribution, subtracting the smaller from recorded L2 score.
2. `weekend_mismatch` contributes zero when any time reason fired, and zero
   if it is the only L2 reason. Otherwise its original +0.10 remains as
   corroboration with an independent L2 reason.
3. New subsystem requires at least `challenge`. When the only nonzero risk
   contributions are L2 time and/or new subsystem, cap `block` at
   `challenge`. Keep all other recorded L1, L2 and L3 contributions.
4. Recompute legacy total from stored rule + adjusted behavior + stored
   iforest and legacy thresholds warn=0.50/challenge=0.70/block=0.85. Do not
   claim exact action parity when the recorded outcome was lifted by an
   unseen floor or actual MFA.

Report counts of the reason combinations, old versus candidate score bands
on all 303, changes among comparable recorded `would_*` events and fraction
of all 303 whose candidate score would surface. No attack recall estimate.
Review target before any production merge: on independently expert-labeled
normal shadow traffic, challenge-or-block FPR ≤0.5%, block FPR ≤0.2% upper
cluster confidence bound, with attack recall/precision gates preserved.
These targets cannot be declared met by the unlabeled 303-record replay.
