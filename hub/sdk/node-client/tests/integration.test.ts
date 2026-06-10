import { test } from "node:test";
import assert from "node:assert/strict";
import { execSync } from "node:child_process";
import { HubClient, Config, Discovery, JwtVerifier, JwtError } from "../src/index.js";

const HUB = "http://localhost:8000";
const CLIENT_ID = "cli_1ded036e86ec4c1b";

function getRealToken(): string {
  const env = process.env.TEST_HUB_TOKEN;
  if (env) return env;
  try {
    const out = execSync(
      `docker exec hub-backend python -c "from app.database import SessionLocal;from app.models import User, Subsystem, AccessList;from app.services.jwt_service import create_subsystem_token;db=SessionLocal();user=db.query(User).filter(User.email.like('%@uni.ac.th')).first();sub=db.query(Subsystem).filter(Subsystem.client_id=='${CLIENT_ID}').first();al=db.query(AccessList).filter(AccessList.subsystem_id==sub.id, AccessList.revoked_at.is_(None)).first();tok,_=create_subsystem_token(user, sub.client_id, ['openid','profile','email'], al.role_in_sub if al else 'user');print(tok, end='')"`,
      { encoding: "utf-8", timeout: 10000 }
    );
    if (!out || out.split(".").length !== 3) throw new Error("invalid token");
    return out;
  } catch (e) {
    throw new Error(`Failed to get real token: ${(e as Error).message}`);
  }
}

test("discovery loads", async () => {
  const cfg = new Config({
    hubUrl: HUB,
    clientId: CLIENT_ID,
    clientSecret: "dummy", // pragma: allowlist secret
    redirectUri: "http://localhost/cb",
  });
  const disc = await new Discovery(cfg).get();
  assert.strictEqual(disc.issuer, "https://hub.local");
  assert.ok(disc.scopes_supported.includes("openid"));
  assert.ok(disc.scopes_supported.includes("profile"));
  assert.ok(disc.id_token_signing_alg_values_supported.includes("RS256"));
  assert.ok(disc.code_challenge_methods_supported.includes("S256"));
});

test("JWT verifier accepts real token", async () => {
  const token = getRealToken();
  const cfg = new Config({
    hubUrl: HUB,
    clientId: CLIENT_ID,
    clientSecret: "dummy", // pragma: allowlist secret
    redirectUri: "http://localhost/cb",
  });
  const jv = new JwtVerifier(cfg, new Discovery(cfg));
  const claims = await jv.verify(token);
  assert.strictEqual(claims.aud, CLIENT_ID);
  assert.strictEqual(claims.iss, "https://hub.local");
  assert.ok(claims.sub);
  assert.ok(claims.email);
  assert.ok(claims.exp);
  assert.ok(claims.jti);
});

test("JWT verifier rejects tampered signature", async () => {
  const token = getRealToken();
  const parts = token.split(".");
  const tampered = `${parts[0]}.${parts[1]}.AAAAAA`;
  const cfg = new Config({
    hubUrl: HUB,
    clientId: CLIENT_ID,
    clientSecret: "dummy", // pragma: allowlist secret
    redirectUri: "http://localhost/cb",
  });
  const jv = new JwtVerifier(cfg, new Discovery(cfg));
  await assert.rejects(jv.verify(tampered), JwtError);
});

test("JWT verifier rejects wrong audience", async () => {
  const token = getRealToken();
  const wrongCfg = new Config({
    hubUrl: HUB,
    clientId: "cli_other_subsystem",
    clientSecret: "x", // pragma: allowlist secret
    redirectUri: "z",
  });
  const jv = new JwtVerifier(wrongCfg, new Discovery(wrongCfg));
  await assert.rejects(jv.verify(token), JwtError);
});

test("buildAuthorizeUrl produces valid URL", async () => {
  const hub = new HubClient({
    hubUrl: HUB,
    clientId: CLIENT_ID,
    clientSecret: "x", // pragma: allowlist secret
    redirectUri: "http://localhost/cb",
  });
  const { url, state, verifier } = await hub.buildAuthorizeUrl();
  assert.ok(url.includes("/oauth/authorize?"));
  assert.ok(url.includes("response_type=code"));
  assert.ok(url.includes("code_challenge_method=S256"));
  assert.ok(url.includes(`client_id=${CLIENT_ID}`));
  assert.ok(url.includes("scope=openid+profile+email"));
  assert.strictEqual(state.length, 32);
  assert.ok(verifier.length >= 43 && verifier.length <= 128);
});
