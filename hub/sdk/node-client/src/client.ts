import type { JWTPayload } from "jose";

import { Config, type ConfigOptions } from "./config.js";
import { Discovery } from "./discovery.js";
import { JwtVerifier } from "./jwtVerifier.js";
import { generateVerifier, challengeFor } from "./pkce.js";
import { generateState, verifyState } from "./state.js";
import { exchangeCode } from "./tokenExchange.js";

export interface AuthorizeUrlResult {
  url: string;
  state: string;
  verifier: string;
}

/**
 * Central Auth Hub Node.js Client — main facade.
 *
 * Framework-agnostic. Caller manages session storage of state+verifier.
 * Example with Express: see examples/express-app.ts
 */
export class HubClient {
  readonly config: Config;
  readonly discovery: Discovery;
  readonly jwtVerifier: JwtVerifier;

  constructor(opts: ConfigOptions) {
    this.config = new Config(opts);
    this.discovery = new Discovery(this.config);
    this.jwtVerifier = new JwtVerifier(this.config, this.discovery);
  }

  /**
   * Build authorize URL — caller stores state + verifier in session.
   */
  async buildAuthorizeUrl(): Promise<AuthorizeUrlResult> {
    const disc = await this.discovery.get();
    const state = generateState();
    const verifier = generateVerifier();
    const challenge = challengeFor(verifier);
    const params = new URLSearchParams({
      client_id: this.config.clientId,
      redirect_uri: this.config.redirectUri,
      response_type: "code",
      scope: this.config.scope.join(" "),
      state,
      code_challenge: challenge,
      code_challenge_method: "S256",
    });
    return {
      url: `${disc.authorization_endpoint}?${params.toString()}`,
      state,
      verifier,
    };
  }

  /**
   * Handle callback — verify state, exchange code, verify JWT → return claims.
   *
   * @throws StateError | TokenError | JwtError
   */
  async handleCallback(
    code: string,
    receivedState: string,
    expectedState: string,
    verifier: string
  ): Promise<JWTPayload & { _access_token: string }> {
    verifyState(expectedState, receivedState);
    const disc = await this.discovery.get();
    const tokenResp = await exchangeCode(this.config, disc.token_endpoint, code, verifier);
    const claims = await this.jwtVerifier.verify(tokenResp.access_token);
    return { ...claims, _access_token: tokenResp.access_token };
  }
}
