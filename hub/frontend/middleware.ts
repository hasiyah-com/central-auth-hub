import { NextRequest, NextResponse } from "next/server";
import { parseJwt, isExpired, TOKEN_COOKIE } from "@/lib/auth";

/**
 * Route guard
 * - public: /auth/*, /api/set-token (POST), favicon, _next assets
 * - everything else: ต้องมี cookie + JWT ที่ยังไม่ expired
 */
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // ปล่อย public paths
  if (
    pathname.startsWith("/auth/") ||
    pathname.startsWith("/api/set-token") ||
    pathname.startsWith("/_next") ||
    pathname === "/favicon.ico"
  ) {
    return NextResponse.next();
  }

  const token = req.cookies.get(TOKEN_COOKIE)?.value;
  const payload = token ? parseJwt(token) : null;
  if (!payload || isExpired(payload)) {
    const loginUrl = new URL("/auth/login", req.url);
    return NextResponse.redirect(loginUrl);
  }

  // ตรวจสิทธิ์ admin (ทุกหน้าใน console = admin only)
  if (!payload.is_hub_admin) {
    const loginUrl = new URL("/auth/login", req.url);
    loginUrl.searchParams.set("error", "not_admin");
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  // match ทุก request ยกเว้น static assets
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
