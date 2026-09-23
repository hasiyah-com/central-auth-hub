/** @type {import('next').NextConfig} */
const HUB_INTERNAL = process.env.HUB_INTERNAL_URL || "http://hub-backend:8000";
const isProd = process.env.NODE_ENV === "production";
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isProd ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com data:",
  "img-src 'self' data: blob:",
  "worker-src 'self' blob:",
  `connect-src 'self'${isProd ? "" : " ws:"}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
]
  .join("; ")
  .concat(isProd ? "; upgrade-insecure-requests" : "");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "geolocation=(), microphone=(), camera=(), payment=()",
  },
  ...(isProd
    ? [
        {
          key: "Strict-Transport-Security",
          value: "max-age=63072000; includeSubDomains",
        },
      ]
    : []),
];

const nextConfig = {
  reactStrictMode: true,
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    const passthrough = [
      "/oauth",
      "/.well-known",
      "/auth/google",
      "/auth/credentials",
      "/auth/account",
      "/auth/stepup",
      "/auth/confirm-identity",
      "/auth/passkey/risk-stepup",
      "/auth/passkey/force-enroll",
      "/account/passkeys",
      "/secret",
      "/api/v1",
      "/health",
    ];
    return [
      { source: "/api/hub/:path*", destination: `${HUB_INTERNAL}/:path*` },
      ...passthrough.flatMap((p) => [
        { source: p, destination: `${HUB_INTERNAL}${p}` },
        { source: `${p}/:path*`, destination: `${HUB_INTERNAL}${p}/:path*` },
      ]),
      {
        source: "/auth/passkey/recover/:path*",
        destination: `${HUB_INTERNAL}/auth/passkey/recover/:path*`,
      },
      {
        source: "/auth/passkey/backup-codes/:path*",
        destination: `${HUB_INTERNAL}/auth/passkey/backup-codes/:path*`,
      },
      {
        source: "/auth/recovery/:path*",
        destination: `${HUB_INTERNAL}/auth/recovery/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
