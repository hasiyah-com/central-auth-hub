import { createRemoteJWKSet, jwtVerify } from "jose";
import type { JWTPayload } from "jose";

import { Config } from "./config.js";
import { Discovery } from "./discovery.js";
import { JwtError } from "./errors.js";

/**
 * Verify JWT via JWKS — sig + aud + iss + exp.
 *
 * `jose.createRemoteJWKSet` handles JWKS fetching + caching + auto-refresh
 * on unknown kid (key rotation).
 */
export class JwtVerifier {
  private jwks: ReturnType<typeof createRemoteJWKSet> | null = null;
  private jwksFor: string | null = null;

  constructor(private readonly config: Config, private readonly discovery: Discovery) {}

  async verify(token: string): Promise<JWTPayload> {
    const disc = await this.discovery.get();
    if (!this.jwks || this.jwksFor !== disc.jwks_uri) {
      this.jwks = createRemoteJWKSet(new URL(disc.jwks_uri), {
        cacheMaxAge: this.config.jwksCacheTtl * 1000,
        // cooldownDuration กัน fetch flood ตอน key rotation
        cooldownDuration: 30_000,
      });
      this.jwksFor = disc.jwks_uri;
    }
    try {
      const { payload } = await jwtVerify(token, this.jwks, {
        issuer: disc.issuer,
        audience: this.config.clientId,
        algorithms: ["RS256"],
        clockTolerance: 30,
      });
      return payload;
    } catch (e) {
      throw new JwtError(`JWT verify failed: ${(e as Error).message}`);
    }
  }
}
