import { NextRequest, NextResponse } from "next/server";
import {
  parseJwt,
  isExpired,
  isAdmin,
  isDeveloper,
  TOKEN_COOKIE,
} from "@/lib/auth";

// Routes ที่จำกัดเฉพาะ hub_admin (Admin Console)
const ADMIN_PATHS = ["/dashboard", "/users", "/subsystems", "/ml", "/audit"];

// Routes ที่ให้ teacher/staff/admin เข้าได้ (Developer Portal)
const DEV_PATHS = ["/developer"];

function pathMatches(prefixes: string[], pathname: string): boolean {
  return prefixes.some(
    (p) => pathname === p || pathname.startsWith(p + "/")
  );
}

/**
 * Route guard:
 *   - /auth/*, /api/set-token, /_next, favicon → public
 *   - ADMIN_PATHS → ต้อง isAdmin
 *   - DEV_PATHS   → ต้อง isDeveloper (teacher/staff/admin; student blocked)
 *   - อื่น ๆ      → แค่ login ใหม่ก็พอ (ป้องกัน path เผลอ leak)
 */
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (
    pathname.startsWith("/auth/") ||
    pathname.startsWith("/api/set-token") ||
    pathname.startsWith("/_next") ||
    pathname === "/favicon.ico"
  ) {
    // /auth/* รวม /auth/mfa — ปล่อยผ่านเพราะ user ยังไม่ได้ login จริง (ยัง verify OTP)
    return NextResponse.next();
  }

  const token = req.cookies.get(TOKEN_COOKIE)?.value;
  const payload = token ? parseJwt(token) : null;
  if (!payload || isExpired(payload)) {
    return NextResponse.redirect(new URL("/auth/login", req.url));
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

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
