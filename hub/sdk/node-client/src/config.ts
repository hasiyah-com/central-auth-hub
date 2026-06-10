import { HubError } from "./errors.js";

export interface ConfigOptions {
  hubUrl: string;
  clientId: string;
  clientSecret: string;
  redirectUri: string;
  scope?: string[];
  jwksCacheTtl?: number; // seconds
  httpTimeout?: number; // ms
}

export class Config {
  readonly hubUrl: string;
  readonly clientId: string;
  readonly clientSecret: string;
  readonly redirectUri: string;
  readonly scope: string[];
  readonly jwksCacheTtl: number;
  readonly httpTimeout: number;

  constructor(opts: ConfigOptions) {
    for (const k of ["hubUrl", "clientId", "clientSecret", "redirectUri"] as const) {
      if (!opts[k]) throw new HubError(`Config: missing required '${k}'`);
    }
    this.hubUrl = opts.hubUrl.replace(/\/+$/, "");
    this.clientId = opts.clientId;
    this.clientSecret = opts.clientSecret;
    this.redirectUri = opts.redirectUri;
    this.scope = opts.scope ?? ["openid", "profile", "email"];
    this.jwksCacheTtl = opts.jwksCacheTtl ?? 600;
    this.httpTimeout = opts.httpTimeout ?? 10000;
  }
}
