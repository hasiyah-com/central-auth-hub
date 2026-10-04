# Contextual risk policy trial

Enable in the backend environment: `RISK_CONTEXTUAL_TRIAL_ENABLED=true`, then redeploy/restart the backend. Default is false. The compose backend reads `.env`. Set false and restart to restore baseline scoring. No migration or history deletion is required.

The saved `LoginSession.risk_breakdown.risk_policy` is `contextual-trial-v1` when enabled, `baseline` otherwise. Compare only new events after the restart; old scores remain historical observations.

| Controlled example | Baseline | Trial |
| --- | --- | --- |
| 11-hour temporal departure and unseen hour | 0.70 / Challenge | 0.40 / Allow |
| New device plus new browser family | 0.50 / Challenge | 0.30 / Challenge |
| Three concurrent authenticated sessions alone | 0.25 / Challenge | 0.25 / Allow |
| Two active subsystems alone | 0.20 / Challenge | 0.20 / Allow |
| First use of an authorized subsystem alone | 0.30 / Challenge | 0.30 / Allow |
| Three sessions plus new device | Challenge | Challenge |
| Confirmed incident | Challenge | Challenge |

These are isolated unit scenarios with other signals neutral, not production false-positive/recall measurements. Other independent signals can still raise the total to Challenge.

Changes: environment novelty uses the strongest device/browser score; the hour departure/rarity group uses the strongest score; country is no longer duplicated in L2. The trial removes unconditional session/subsystem novelty floors. Multi-session activity still gates when corroborated by device/country novelty, five consecutive failures, or recent recovery/reset. Velocity now means at most two real minutes (`log(minutes) <= log(2)`), adds score, and requires failures/country/recovery context for a mandatory floor. Personalized cadence is not added again when the velocity rule already applies.

Active session counts exclude pending challenges and Block attempts. Completed token-bearing Warn sessions may count as active, while they do not become trusted device history automatically. Behavior profiles use trusted history. Cross-system score propagation is resolved only by server-verified Passkey with UV or TOTP step-up, with no counter regression, attack/takeover label or Block risk assessment. Merely marking an event normal does not resolve propagation.

Hard attack checks and 5/10-failure rules remain. Strong primary authentication remains governed by the existing MFA policy. L3 stays monitoring-only; this change does not grant L3 Challenge authority. `legacy_replay` scoring remains frozen.

## Optional L3 percentile decision trial

Set `L3_DECISION_TRIAL_ENABLED=true` only with a registered role calibration artifact in
`L3_ROLE_CALIBRATION_PATH`. The trial applies only when L1+L2 return Allow. A point score above the
role's calibrated warning percentile becomes Warn. It becomes Challenge at
`L3_DECISION_TRIAL_CHALLENGE_PERCENTILE` (default P99), or when the warning percentile is reached
and the enabled Sequence view independently returns `l3_investigate`. Missing calibration, model
hash mismatch, unavailable point score, or insufficient Sequence history abstains rather than
changing access. `L3_FALLBACK_WARN_ENABLED` is ignored while this trial is enabled.

Suggested verification: same known device/time, new browser/device, multiple normal subsystems, retry after successful MFA, and an independent high-risk scenario. Record policy marker, L1/L2 contributions, reasons, risk decision and authentication evidence for each. Do not replace chapter 4 experiment numbers with these scenario results; rerun the held-out evaluation before making performance claims.

New device or browser family always sets a Challenge floor in both live policies. Trial scoring remains deduplicated. Browser version changes alone retain the same signature. Existing strong-authentication handling can satisfy Challenge; risk assessment remains Challenge. Passkey/permission-only changes retain contextual handling.
