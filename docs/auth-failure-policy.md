# Recent authentication failures

Live rules use consecutive failures per method (Passkey, TOTP, email OTP) within a rolling 10-minute window. A successful verification resets the method used; another method does not reset it. Counter regression does not reset the counter. Expired/cancelled challenges are excluded. These are operational thresholds, not numbers mandated by NIST.

| Recent failures after the first factor | Rule action |
| --- | --- |
| 0–2 | No failure score |
| 3–4 | +0.20; no failure-driven Challenge floor |
| 5–9 | +0.30 and Challenge floor |
| 10+ | Evidence-based Block, subject to the existing Block shadow policy |

Anonymous email-attributed failures cannot add a score or Block the account. At five recent failures they can request extra verification. The 24-hour feature and raw audit records remain available to the model and analysis. Legacy replay retains the frozen experimental rules.

Risk-step-up Passkey and TOTP routes apply per-account, per-method temporary backoff after three invalid verifications: 30, 60, 120, 240, then at most 300 seconds. Requests during the wait receive HTTP 429 with Retry-After. Counter keys expire after 10 minutes. Successful verification clears that method's retry state. Existing email OTP attempt/expiry limits and IP rate limits remain active.

NIST SP 800-63B-4 section 3.2.2 discusses consecutive failures per authenticator and resetting factors used after successful authentication. This implementation groups by method, rather than individual credential. OWASP recommends considering threshold, observation window, duration, usability and account-lockout denial of service.

Sources: https://pages.nist.gov/800-63-4/sp800-63b.html and https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
