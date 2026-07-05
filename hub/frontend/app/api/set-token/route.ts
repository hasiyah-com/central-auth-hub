import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { parseJwt, isExpired, TOKEN_COOKIE, REFRESH_TOKEN_COOKIE } from "@/lib/auth";

const HUB_INTERNAL = process.env.HUB_INTERNAL_URL || "http://hub-backend:8000";
// ต้องตรงกับ jwt_refresh_token_expire_days ฝั่ง Hub backend (config.py) — refresh
// token เองไม่มี exp ให้ parse (opaque), เลย hardcode อายุ cookie ให้ยาวพอ
const REFRESH_COOKIE_MAX_AGE_SEC = 30 * 24 * 60 * 60;

/**
 * POST /api/set-token
 * body: { token: string, refresh_token?: string }
 *
 * ตรวจ exp + payload คร่าว ๆ แล้วเก็บใน httpOnly cookie
 * (signature verification จริงทำที่ Hub backend ผ่าน JWKS — เราแค่เก็บ pass-through)
 */
export async function POST(req: NextRequest) {
  let body: { token?: string; refresh_token?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  const token = body.token;
  if (!token || typeof token !== "string") {
    return NextResponse.json({ error: "missing token" }, { status: 400 });
  }

  const payload = parseJwt(token);
  if (!payload || isExpired(payload)) {
    return NextResponse.json({ error: "invalid or expired token" }, { status: 400 });
  }

  // เก็บ token ใน httpOnly cookie — max-age ตาม exp
  const maxAge = Math.max(0, payload.exp - Math.floor(Date.now() / 1000));
  const res = NextResponse.json({ ok: true, expires_at: payload.exp });
  res.cookies.set({
    name: TOKEN_COOKIE,
    value: token,
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  });

  if (body.refresh_token && typeof body.refresh_token === "string") {
    res.cookies.set({
      name: REFRESH_TOKEN_COOKIE,
      value: body.refresh_token,
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: REFRESH_COOKIE_MAX_AGE_SEC,
    });
  }

  return res;
}

/**
 * DELETE /api/set-token — logout
 *
 * เรียก Hub /auth/logout เพื่อ revoke access + refresh token ฝั่ง server ด้วย
 * (ไม่งั้นแค่ลบ cookie ฝั่ง client เฉยๆ — token เดิมยังใช้ /auth/refresh มิ้นท์
 * access token ใหม่ได้อยู่ถ้าหลุดไปก่อนหน้านี้)
 */
export async function DELETE() {
  const cookieStore = cookies();
  const token = cookieStore.get(TOKEN_COOKIE)?.value;
  const refreshToken = cookieStore.get(REFRESH_TOKEN_COOKIE)?.value;

  if (token) {
    try {
      await fetch(`${HUB_INTERNAL}/auth/logout`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ refresh_token: refreshToken || null }),
        cache: "no-store",
      });
    } catch {
      // fail-safe — เคลียร์ cookie ฝั่ง client ต่อได้แม้เรียก backend ไม่ติด
    }
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.delete(TOKEN_COOKIE);
  res.cookies.delete(REFRESH_TOKEN_COOKIE);
  return res;
}
