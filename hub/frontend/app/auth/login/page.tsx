"use client";

const HUB_URL = process.env.NEXT_PUBLIC_HUB_URL || "http://localhost:8000";

export default function LoginPage() {
  return (
    <main className="min-h-screen grid place-items-center bg-gradient-to-br from-ink-900 via-ink-800 to-brand-900 px-4">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden">
        <div className="px-8 pt-10 pb-8">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-brand-600 to-brand-900 grid place-items-center text-white text-xl font-bold">
              H
            </div>
            <div>
              <div className="text-xs text-ink-500 font-semibold uppercase tracking-wider">
                Central Auth Hub
              </div>
              <div className="text-lg font-bold text-ink-900">Admin Console</div>
            </div>
          </div>

          <h1 className="text-2xl font-extrabold text-ink-900 mb-2">
            เข้าสู่ระบบ
          </h1>
          <p className="text-sm text-ink-500 mb-8">
            สำหรับผู้ดูแลระบบ — ใช้บัญชี Google ที่ลงทะเบียนไว้กับ Hub
          </p>

          <a
            href={`${HUB_URL}/auth/google/login`}
            className="w-full flex items-center justify-center gap-3 px-4 py-3 rounded-xl bg-ink-900 hover:bg-ink-800 text-white font-semibold transition"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path
                d="M21.6 12.227c0-.709-.064-1.39-.182-2.045H12v3.868h5.382a4.6 4.6 0 0 1-1.996 3.018v2.51h3.232c1.891-1.742 2.982-4.305 2.982-7.35Z"
                fill="#4285F4"
              />
              <path
                d="M12 22c2.7 0 4.964-.895 6.618-2.423l-3.232-2.509c-.895.6-2.04.955-3.386.955-2.605 0-4.81-1.76-5.595-4.123H3.064v2.59A9.996 9.996 0 0 0 12 22Z"
                fill="#34A853"
              />
              <path
                d="M6.405 13.9a6.003 6.003 0 0 1 0-3.8V7.51H3.064a9.996 9.996 0 0 0 0 8.98l3.341-2.59Z"
                fill="#FBBC05"
              />
              <path
                d="M12 5.977c1.468 0 2.786.505 3.823 1.496l2.868-2.868C16.96 2.99 14.695 2 12 2A9.996 9.996 0 0 0 3.064 7.51l3.341 2.59C7.19 7.736 9.395 5.977 12 5.977Z"
                fill="#EA4335"
              />
            </svg>
            <span>เข้าสู่ระบบด้วย Google</span>
          </a>

          <div className="mt-6 text-xs text-ink-400 text-center">
            เฉพาะผู้ใช้ที่มีสิทธิ์ <code className="font-mono">is_hub_admin</code> เท่านั้น
          </div>
        </div>

        <div className="px-8 py-5 bg-ink-50 border-t border-ink-100">
          <div className="text-xs text-ink-500 flex items-center justify-between">
            <span>OAuth 2.0 · PKCE · JWT RS256</span>
            <span className="font-mono">v0.5.0</span>
          </div>
        </div>
      </div>
    </main>
  );
}
