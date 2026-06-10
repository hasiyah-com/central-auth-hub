# Central Auth Hub — Node.js Client SDK

Official Node.js SDK for **Central Auth Hub** — OAuth 2.0 + PKCE + JWT verification via OIDC Discovery

TypeScript-first · ESM-only · Node 18+ · `jose` for JWKS handling

---

## ✅ Features

- **Auto-discovery** — `/.well-known/openid-configuration` (OIDC Discovery 1.0)
- **PKCE S256** auto (RFC 7636)
- **CSRF state** verify via `crypto.timingSafeEqual` (RFC 6749 §10.12)
- **JWT verify** via `jose.createRemoteJWKSet` — auto JWKS cache + key rotation
- **Webhook receiver** — HMAC-SHA256 + replay protection
- **Framework-agnostic** — works with Express, Fastify, Next, Hono, etc.
- **TypeScript** strict mode + full types

---

## 📦 Install

```bash
npm install @central-auth-hub/node-client
```

---

## 🚀 Quick start (Express)

```ts
import express from "express";
import session from "express-session";
import { HubClient } from "@central-auth-hub/node-client";

const app = express();
app.use(session({ secret: "x", resave: false, saveUninitialized: false }));

const hub = new HubClient({
  hubUrl: "http://localhost:8000",
  clientId: "cli_xxx",
  clientSecret: "sec_xxx", // pragma: allowlist secret
  redirectUri: "http://localhost:3000/auth/callback",
});

app.get("/auth/login", async (req, res) => {
  const { url, state, verifier } = await hub.buildAuthorizeUrl();
  (req.session as any).oauth = { state, verifier };
  res.redirect(url);
});

app.get("/auth/callback", async (req, res) => {
  const { state: expected, verifier } = (req.session as any).oauth ?? {};
  delete (req.session as any).oauth;
  try {
    const claims = await hub.handleCallback(
      String(req.query.code),
      String(req.query.state),
      expected,
      verifier
    );
    (req.session as any).user = claims;
    res.redirect("/");
  } catch (e) {
    res.status(400).send((e as Error).message);
  }
});

app.get("/", (req, res) => {
  const user = (req.session as any).user;
  res.send(user ? `Hello ${user.name}` : `<a href="/auth/login">Login</a>`);
});

app.listen(3000);
```

→ Login flow ครบใน ~30 บรรทัด (เทียบ ~165 ใน raw PHP)

---

## 📡 Webhook receiver

```ts
import express from "express";
import { verifyWebhook } from "@central-auth-hub/node-client";

app.post("/internal/access-revoked",
  express.raw({ type: "application/json" }),
  (req, res) => {
    try {
      const payload = verifyWebhook(
        process.env.HUB_WEBHOOK_SHARED_KEY!,
        req.body,
        req.headers
      );
      if (payload.event === "access_revoked") {
        // ลบ user session, mark DB
      }
      res.json({ status: "ok" });
    } catch (e) {
      res.status(401).send((e as Error).message);
    }
  }
);
```

---

## 🔐 Security model

| Concern | Defense |
|---|---|
| CSRF state | `crypto.timingSafeEqual` constant-time |
| Auth code interception | PKCE S256 (RFC 7636) |
| JWT tampering | RS256 + JWKS (jose certified library) |
| Key rotation | `createRemoteJWKSet` auto-refresh on unknown kid |
| Webhook spoofing | HMAC-SHA256 timing-safe verify |
| Replay attack | timestamp + max-age tolerance |

---

## 📚 References

- [OpenID Connect Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html)
- [RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749) (OAuth 2.0)
- [RFC 7636](https://datatracker.ietf.org/doc/html/rfc7636) (PKCE)
- [RFC 7517](https://datatracker.ietf.org/doc/html/rfc7517) (JWK)
- [RFC 7519](https://datatracker.ietf.org/doc/html/rfc7519) (JWT)
- [jose library](https://github.com/panva/jose) — used for JWKS + JWT verify

## 📜 License

MIT
