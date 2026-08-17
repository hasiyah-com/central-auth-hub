import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { TOKEN_COOKIE, REFRESH_TOKEN_COOKIE } from "@/lib/auth";

const HUB_INTERNAL = process.env.HUB_INTERNAL_URL || "http://hub-backend:8000";

/**
 * POST /api/refresh
 *
 * อ่าน hub_refresh_token (httpOnly) → เรียก Hub POST /auth/refresh → ได้
 * access+refresh token คู่ใหม่ (rotation) → set cookie ทั้งคู่ทับของเดิม
 *
 * เรียกจาก: /api/proxy (401 retry-once) และ middleware (page navigation guard)
 * — ทั้งสองจุดไม่ต้องรู้ detail ของ Hub token format เลย แค่เรียก route นี้
 */
export async function POST() {
  const cookieStore = cookies();
  const refreshToken = cookieStore.get(REFRESH_TOKEN_COOKIE)?.value;
  if (!refreshToken) {
    return NextResponse.json({ error: "no refresh token" }, { status: 401 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${HUB_INTERNAL}/auth/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "hub unreachable" }, { status: 502 });
  }

  if (!upstream.ok) {
    // refresh token ผิด/หมดอายุ/ถูก revoke แล้ว — เคลียร์ cookie ทั้งคู่ (dead weight)
    const res = NextResponse.json({ error: "refresh failed" }, { status: 401 });
    res.cookies.delete(TOKEN_COOKIE);
    res.cookies.delete(REFRESH_TOKEN_COOKIE);
    return res;
  }

  const data = (await upstream.json()) as
    | { access_token: string; refresh_token: string; expires_in: number }
    | { stepup_required: true; stepup_url: string };

  // RBA จับ session-hijack ตอน refresh → บอก client ให้ไปยืนยัน Passkey
  if ("stepup_required" in data) {
    return NextResponse.json({
      stepup_required: true,
      stepup_url: data.stepup_url,
    });
  }

  // session cookie (ไม่มี maxAge → ลบตอนปิดเบราว์เซอร์)
  const res = NextResponse.json({ ok: true });
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
  return res;
}
