import { NextRequest, NextResponse } from "next/server";
import {
  parseJwt,
  isExpired,
  isAdmin,
  isDeveloper,
  TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  type JwtPayload,
} from "@/lib/auth";

const HUB_INTERNAL = process.env.HUB_INTERNAL_URL || "http://hub-backend:8000";

// Routes ที่จำกัดเฉพาะ hub_admin (Admin Console)
// /account/security = passkey management — admin เท่านั้น (teacher/staff/นักศึกษา
// ลง passkey ผ่าน subsystem enroll interstitial แทน)
const ADMIN_PATHS = [
  "/dashboard",
  "/users",
  "/subsystems",
  "/ml",
  "/audit",
  "/account",
];

// Routes ที่ให้ teacher/staff/admin เข้าได้ (Developer Portal)
const DEV_PATHS = ["/developer"];

// Single-domain mode — prefix ที่ next.config.js rewrites ส่งตรงเข้า hub-backend.
// ต้อง sync กับ `passthrough` ใน next.config.js (`/auth/*` ครอบด้วย rule แยกอยู่แล้ว)
const BACKEND_PASSTHROUGH = [
  "/oauth",
  "/.well-known",
  "/account/passkeys",
  "/secret",
  "/api/v1",
  "/health",
];

function pathMatches(prefixes: string[], pathname: string): boolean {
  return prefixes.some(
    (p) => pathname === p || pathname.startsWith(p + "/")
  );
}

/**
 * Access token อายุสั้น (15 นาที) — หมดอายุระหว่าง session ปกติ (ไม่ใช่แค่ตอน
 * ไม่ได้ใช้งานนาน) ถ้าเจอ expired + มี refresh cookie อยู่ → ลอง refresh ที่นี่
 * เลยก่อนตัดสินใจ redirect ไป login (กัน user โดนเด้งออกทุก 15 นาทีทั้งที่ยัง
 * มี refresh token ที่ใช้ได้อีกตั้ง 30 วัน)
 */
type RefreshOutcome =
  | { kind: "ok"; payload: JwtPayload; res: NextResponse }
  | { kind: "stepup"; stepupUrl: string }
  | { kind: "fail" };

async function tryRefresh(req: NextRequest): Promise<RefreshOutcome> {
  const refreshToken = req.cookies.get(REFRESH_TOKEN_COOKIE)?.value;
  if (!refreshToken) return { kind: "fail" };
  try {
    const r = await fetch(`${HUB_INTERNAL}/auth/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    });
    if (!r.ok) return { kind: "fail" };
    const data = (await r.json()) as
      | { access_token: string; refresh_token: string; expires_in: number }
      | { stepup_required: true; stepup_url: string };

    // RBA จับ session-hijack ตอน refresh → ต้องยืนยัน Passkey ก่อน (Hub-served page)
    if ("stepup_required" in data) {
      return { kind: "stepup", stepupUrl: data.stepup_url };
    }

    const payload = parseJwt(data.access_token);
    if (!payload) return { kind: "fail" };

    // session cookie (ไม่มี maxAge → ลบตอนปิดเบราว์เซอร์)
    const res = NextResponse.next();
    res.cookies.set({
      name: TOKEN_COOKIE,
      value: data.access_token,
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
    });
    res.cookies.set({
      name: REFRESH_TOKEN_COOKIE,
      value: data.refresh_token,
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
    });
    return { kind: "ok", payload, res };
  } catch {
    return { kind: "fail" };
  }
}

/**
 * Route guard:
 *   - /auth/*, /api/set-token, /_next, favicon → public
 *   - ADMIN_PATHS → ต้อง isAdmin
 *   - DEV_PATHS   → ต้อง isDeveloper (teacher/staff/admin; student blocked)
 *   - อื่น ๆ      → แค่ login ใหม่ก็พอ (ป้องกัน path เผลอ leak)
 */
export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (
    pathname.startsWith("/auth/") ||
    pathname.startsWith("/api/set-token") ||
    // Passkey login + recovery proxy — public flows (user ยังไม่มี token)
    //   /api/proxy/auth/passkey/login/*   (Phase 2)
    //   /api/proxy/auth/passkey/recover/* (Phase 4)
    // แยกจาก /api/proxy/account/passkeys/* (register/manage) ที่ยังต้อง auth
    pathname.startsWith("/api/proxy/auth/passkey/") ||
    // Single-domain mode: path ที่ next.config rewrites ส่งตรงเข้า hub-backend
    // (OAuth/OIDC ที่ subsystem+Google เรียก, Roster API, หน้า HTML ที่ Hub เสิร์ฟเอง).
    // ต้องข้าม middleware เพราะเป็น server-to-server / cross-origin ที่ไม่มี cookie
    // ของ console — เจอ redirect ไป /auth/login จะกลายเป็น 307 กลางคัน token exchange.
    // ปลอดภัย: backend บังคับ auth เองทุก endpoint (client_secret / Bearer / X-Api-Key)
    pathMatches(BACKEND_PASSTHROUGH, pathname) ||
    pathname.startsWith("/_next") ||
    pathname === "/favicon.ico"
  ) {
    // /auth/* รวม /auth/mfa — ปล่อยผ่านเพราะ user ยังไม่ได้ login จริง (ยัง verify OTP)
    return NextResponse.next();
  }

  const token = req.cookies.get(TOKEN_COOKIE)?.value;
  let payload = token ? parseJwt(token) : null;
  let refreshedResponse: NextResponse | null = null;

  if (!payload || isExpired(payload)) {
    const refreshed = await tryRefresh(req);
    if (refreshed.kind === "stepup") {
      // ไปหน้า Passkey re-auth ที่ Hub (finalize จะพากลับ /auth/callback เอง)
      return NextResponse.redirect(refreshed.stepupUrl);
    }
    if (refreshed.kind === "fail") {
      return NextResponse.redirect(new URL("/auth/login", req.url));
    }
    payload = refreshed.payload;
    refreshedResponse = refreshed.res;
  }

  if (pathMatches(ADMIN_PATHS, pathname) && !isAdmin(payload)) {
    const url = new URL("/auth/login", req.url);
    url.searchParams.set("error", "not_admin");
    return NextResponse.redirect(url);
  }

  if (pathMatches(DEV_PATHS, pathname) && !isDeveloper(payload)) {
    const url = new URL("/auth/login", req.url);
    url.searchParams.set("error", "not_developer");
    return NextResponse.redirect(url);
  }

  return refreshedResponse ?? NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
