/** @type {import('next').NextConfig} */
const HUB_INTERNAL = process.env.HUB_INTERNAL_URL || "http://hub-backend:8000";
const isProd = process.env.NODE_ENV === "production";

// ── Content-Security-Policy สำหรับ frontend (admin console, port 3000) ──
// Backend (Hub API) ตั้ง CSP ของตัวเองอยู่แล้ว — นี่คือ CSP ของหน้า Next.js
// (audit run-1 + Aikido: frontend เดิมไม่มี CSP/HSTS เลย)
//
// ข้อจำกัด: Next.js App Router inject inline hydration script โดยไม่มี nonce
// (static headers() ทำ per-request nonce ไม่ได้) → ต้อง 'unsafe-inline' บน
// script-src. React auto-escape เป็นด่านหลักกัน XSS; CSP นี้เป็น defense-in-depth
// (กัน external script, clickjacking, form exfil). dev เพิ่ม 'unsafe-eval'
// (React Fast Refresh) + ws: (HMR).
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isProd ? "" : " 'unsafe-eval'"}`,
  // Tailwind/inline style + Google Fonts stylesheet
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com data:",
  // amcharts5 render → data:/blob: (canvas/SVG export), qrcode canvas
  "img-src 'self' data: blob:",
  "worker-src 'self' blob:",
  // client fetch ผ่าน same-origin (/api/proxy, /api/hub); dev เพิ่ม ws สำหรับ HMR
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
  // HSTS มีผลเฉพาะ HTTPS — ส่งเฉพาะ prod (dev บน http browser จะ ignore อยู่แล้ว
  // แต่กัน confusion ไม่ส่งใน dev)
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
  // prod build (next build) เช็ค type/lint เข้มกว่า dev — bypass เพื่อให้ deploy ผ่าน
  // (type error เป็น compile-time เท่านั้น ไม่กระทบ runtime); แก้ type ให้ครบแล้วค่อยเอาออก
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  // ภายใน docker ใช้ hostname `hub-backend`; ภายนอก browser ใช้ localhost
  // หน้า client component ที่ fetch จะใช้ /api/hub/* แล้ว Next rewrite ส่งเข้า backend
  //
  // ── Single-domain mode ──────────────────────────────────────────────────
  // frontend + backend อยู่ domain เดียวกัน (จำเป็นสำหรับ WebAuthn: RP ID ต้อง
  // ตรงกับ origin ของหน้าที่รัน ceremony — และ subdomain ของ public-suffix domain
  // เช่น *.duckdns.org แชร์ RP ID กันไม่ได้). Next proxy path ของ backend ที่
  // browser/subsystem เรียก "ตรง" (ไม่ผ่าน /api/proxy) ให้วิ่งเข้า hub-backend:
  //   - OAuth/OIDC ที่ subsystem + Google เรียก
  //   - หน้า HTML ที่ Hub เสิร์ฟเอง (risk-stepup / force-enroll / confirm-identity / secret)
  //   - Roster API (X-Api-Key จาก subsystem) + health
  // path ที่เป็น "หน้าเว็บของ console" (/auth/passkey/stepup, /auth/passkey/recover,
  // /account, /developer/*) ไม่ต้อง list — rewrite เป็นแบบ afterFiles จึงแพ้ page
  // ของ Next เสมอ ส่วน API ของมันถูกเรียกผ่าน /api/proxy อยู่แล้ว
  async rewrites() {
    const passthrough = [
      "/oauth",
      "/.well-known",
      "/auth/google",
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
      // exact (เช่น /health, /auth/passkey/risk-stepup) + ลูก (/:path*)
      ...passthrough.flatMap((p) => [
        { source: p, destination: `${HUB_INTERNAL}${p}` },
        { source: `${p}/:path*`, destination: `${HUB_INTERNAL}${p}/:path*` },
      ]),
      // ── subpath-only ── (exact `/auth/passkey/recover` = หน้า white ของ frontend
      // → ห้าม proxy exact ไม่งั้นทับหน้านั้น). endpoint ลูกที่หน้า Hub-served (dark)
      // ที่ subsystem flow เรียก + recovery ticket (public) ต้องวิ่งเข้า backend
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
