import { NextRequest, NextResponse } from "next/server";
import { parseJwt, isExpired, TOKEN_COOKIE } from "@/lib/auth";

/**
 * POST /api/set-token
 * body: { token: string }
 *
 * ตรวจ exp + payload คร่าว ๆ แล้วเก็บใน httpOnly cookie
 * (signature verification จริงทำที่ Hub backend ผ่าน JWKS — เราแค่เก็บ pass-through)
 */
export async function POST(req: NextRequest) {
  let body: { token?: string };
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
  return res;
}

/**
 * DELETE /api/set-token — logout
 */
export async function DELETE() {
  const res = NextResponse.json({ ok: true });
  res.cookies.delete(TOKEN_COOKIE);
  return res;
}
