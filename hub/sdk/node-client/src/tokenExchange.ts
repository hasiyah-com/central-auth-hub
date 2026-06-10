import { Config } from "./config.js";
import { TokenError } from "./errors.js";

export interface TokenResponse {
  access_token: string;
  token_type?: string;
  expires_in?: number;
  scope?: string;
  [k: string]: unknown;
}

/** Exchange auth code → access_token via POST /oauth/token. */
export async function exchangeCode(
  config: Config,
  tokenEndpoint: string,
  code: string,
  codeVerifier: string
): Promise<TokenResponse> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), config.httpTimeout);
  try {
    const body = new URLSearchParams({
      grant_type: "authorization_code",
      code,
      client_id: config.clientId,
      client_secret: config.clientSecret,
      redirect_uri: config.redirectUri,
      code_verifier: codeVerifier,
    });
    const r = await fetch(tokenEndpoint, {
      method: "POST",
      signal: ctrl.signal,
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Accept: "application/json",
      },
      body,
    });
    if (!r.ok) {
      const txt = await r.text();
      throw new TokenError(`Token exchange HTTP ${r.status}: ${txt.slice(0, 200)}`);
    }
    const data = (await r.json()) as TokenResponse;
    if (!data.access_token) throw new TokenError("Response missing access_token");
    return data;
  } catch (e) {
    if (e instanceof TokenError) throw e;
    throw new TokenError(`Token endpoint unreachable: ${(e as Error).message}`);
  } finally {
    clearTimeout(t);
  }
}
