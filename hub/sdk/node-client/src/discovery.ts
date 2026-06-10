import { Config } from "./config.js";
import { HubError } from "./errors.js";

export interface DiscoveryDoc {
  issuer: string;
  authorization_endpoint: string;
  token_endpoint: string;
  userinfo_endpoint: string;
  jwks_uri: string;
  introspection_endpoint?: string;
  scopes_supported: string[];
  response_types_supported: string[];
  id_token_signing_alg_values_supported: string[];
  code_challenge_methods_supported: string[];
  [k: string]: unknown;
}

/** Fetch + cache /.well-known/openid-configuration. */
export class Discovery {
  private cached: DiscoveryDoc | null = null;
  private cachedAt = 0;

  constructor(private readonly config: Config) {}

  async get(): Promise<DiscoveryDoc> {
    const now = Date.now();
    if (this.cached && (now - this.cachedAt) / 1000 < this.config.jwksCacheTtl) {
      return this.cached;
    }
    const url = `${this.config.hubUrl}/.well-known/openid-configuration`;
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), this.config.httpTimeout);
    try {
      const r = await fetch(url, { signal: ctrl.signal, headers: { Accept: "application/json" } });
      if (!r.ok) throw new HubError(`Discovery HTTP ${r.status}`);
      const doc = (await r.json()) as DiscoveryDoc;
      if (!doc.issuer || !doc.jwks_uri) throw new HubError("Discovery missing required fields");
      this.cached = doc;
      this.cachedAt = now;
      return doc;
    } catch (e) {
      if (e instanceof HubError) throw e;
      throw new HubError(`Discovery fetch failed: ${(e as Error).message}`);
    } finally {
      clearTimeout(t);
    }
  }
}
