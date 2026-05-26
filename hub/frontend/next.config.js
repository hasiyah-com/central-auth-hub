/** @type {import('next').NextConfig} */
const HUB_INTERNAL = process.env.HUB_INTERNAL_URL || "http://hub-backend:8000";

const nextConfig = {
  reactStrictMode: true,
  // ภายใน docker ใช้ hostname `hub-backend`; ภายนอก browser ใช้ localhost
  // หน้า client component ที่ fetch จะใช้ /api/hub/* แล้ว Next rewrite ส่งเข้า backend
  async rewrites() {
    return [
      {
        source: "/api/hub/:path*",
        destination: `${HUB_INTERNAL}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
