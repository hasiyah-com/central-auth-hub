import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { parseJwt, TOKEN_COOKIE } from "@/lib/auth";

/**
 * GET /api/me — คืน payload ของ user ปัจจุบัน (จาก cookie)
 * ใช้ใน client component เพื่อแสดงชื่อ/อีเมล/role ใน topbar/sidebar
 */
export async function GET() {
  const cookieStore = cookies();
  const token = cookieStore.get(TOKEN_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ error: "not authenticated" }, { status: 401 });
  }
  const payload = parseJwt(token);
  if (!payload) {
    return NextResponse.json({ error: "invalid token" }, { status: 401 });
  }
  // JWT ของ Hub ใช้ key "name" (= user.full_name) — ไม่ใช่ "full_name"
  // is_hub_admin ไม่ได้อยู่ใน JWT claim → infer จาก user_type === "admin"
  return NextResponse.json({
    sub: payload.sub,
    email: payload.email,
    full_name: payload.name || payload.full_name || null,
    user_type: payload.user_type || null,
    faculty: payload.faculty || null,
    is_hub_admin:
      payload.is_hub_admin === true || payload.user_type === "admin",
    exp: payload.exp,
  });
}
