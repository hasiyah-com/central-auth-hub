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

          {/* Google login — บัญชีที่ Hub seed ไว้ตามทะเบียน */}
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
            <span>Sign in with Google</span>
          </a>

          {/* LINE login — alt IdP สำหรับ user ที่สะดวกใช้ LINE
              ใช้ brand color #06C755 (LINE Green) + chat-bubble icon */}
          <a
            href={`${HUB_URL}/auth/line/login`}
            className="mt-3 w-full flex items-center justify-center gap-3 px-4 py-3 rounded-xl bg-[#06C755] hover:bg-[#05A647] text-white font-semibold transition"
          >
            <svg width="20" height="20" viewBox="0 0 320 320" fill="currentColor">
              <path d="M160 0C71.6 0 0 58.2 0 130c0 64.4 56.8 118.4 133.6 128.6 5.2 1.1 12.3 3.4 14.1 7.9 1.6 4 1 10.3.5 14.4l-2.3 13.6c-.7 4-3.2 15.7 13.7 8.6 17-7.1 91.3-53.7 124.5-92 23-25.2 33.9-50.7 33.9-79.1C320 58.2 248.4 0 160 0z" />
              <path
                d="M93 105h-6c-1.1 0-2 .9-2 2v40c0 1.1.9 2 2 2h6c1.1 0 2-.9 2-2v-40c0-1.1-.9-2-2-2zm44 0h-6c-1.1 0-2 .9-2 2v23.7L110.7 106c-.1 0-.1-.1-.2-.1l-.2-.2-.2-.1h-.2c-.1 0-.1-.1-.2-.1h-6.7c-1.1 0-2 .9-2 2v40c0 1.1.9 2 2 2h6c1.1 0 2-.9 2-2v-23.6l18.3 24.7c.1.2.3.3.4.4.1.1.2.1.2.2.1 0 .2.1.2.1h7.2c1.1 0 2-.9 2-2v-40c.1-1.1-.8-2.4-1.9-2.4zm-65 35.6h-17.5V107c0-1.1-.9-2-2-2h-6c-1.1 0-2 .9-2 2v40c0 .5.2 1 .6 1.4l.1.1c.4.3.8.5 1.4.5h25.5c1.1 0 2-.9 2-2v-6c0-1.1-.9-2.4-2.1-2.4zm103.2-25.6c1.1 0 2-.9 2-2v-6c0-1.1-.9-2-2-2h-25.6c-.5 0-1 .2-1.4.6l-.1.1c-.3.4-.5.8-.5 1.4v40c0 .5.2 1 .6 1.4l.1.1c.4.3.8.5 1.4.5h25.5c1.1 0 2-.9 2-2v-6c0-1.1-.9-2-2-2h-17.5v-6.8h17.5c1.1 0 2-.9 2-2v-6c0-1.1-.9-2-2-2h-17.5V115h17.5z"
                fill="#06C755"
              />
            </svg>
            <span>Sign in with LINE</span>
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
