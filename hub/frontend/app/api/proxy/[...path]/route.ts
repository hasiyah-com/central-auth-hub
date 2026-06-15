import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { TOKEN_COOKIE } from "@/lib/auth";

const HUB_INTERNAL =
  process.env.HUB_INTERNAL_URL || "http://hub-backend:8000";

/**
 * /api/proxy/<path> → Hub backend
 *
 * อ่าน JWT จาก httpOnly cookie แล้วแนบเป็น Authorization: Bearer
 * — client ไม่ต้องเห็น token เลย
 *
 * ใช้แทน Next.js rewrites เพราะ rewrites ไม่ยุ่ง cookie/header
 */

async function forward(req: NextRequest, path: string[]) {
  const cookieStore = cookies();
  const token = cookieStore.get(TOKEN_COOKIE)?.value;

  const targetPath = "/" + path.join("/");
  const url = new URL(req.url);
  const target = `${HUB_INTERNAL}${targetPath}${url.search}`;

  const headers: Record<string, string> = {};
  // forward ส่วน content-type ของ request เดิม
  const ct = req.headers.get("content-type");
  if (ct) headers["content-type"] = ct;
  if (token) headers["authorization"] = `Bearer ${token}`;

  // forward browser user-agent — ไม่งั้น backend เห็น UA ของ Next.js (undici)
  // → LoginSession.os_name/browser parse เป็น "other" (passkey login session)
  const ua = req.headers.get("user-agent");
  if (ua) headers["user-agent"] = ua;

  // forward client IP → backend get_client_ip() อ่าน X-Forwarded-For ก่อน
  // (ไม่งั้น audit/ML เห็น IP ของ Next.js container 172.x แทน client จริง)
  //
  // ลำดับ fallback:
  //   1. x-forwarded-for  — มีเมื่ออยู่หลัง reverse proxy (nginx/cloudflare) = prod
  //   2. x-real-ip        — บาง proxy ใช้ header นี้
  //   3. req.ip           — Next.js derive จาก connection (Vercel/edge)
  // หมายเหตุ: dev ที่รันใน Docker published-port (browser→localhost:3000) ตัว
  // Docker NAT จะ rewrite source เป็น gateway (172.18.0.1) ตั้งแต่ hop แรก →
  // ทั้ง Next.js และ backend จะเห็น 172.x (กู้ client จริงไม่ได้ใน dev).
  // prod ที่มี reverse proxy ตั้ง XFF ให้ → ได้ IP จริง.
  const xff = req.headers.get("x-forwarded-for");
  const realIp = xff || req.headers.get("x-real-ip") || req.ip || "";
  if (realIp) headers["x-forwarded-for"] = realIp;

  const init: RequestInit = {
    method: req.method,
    headers,
    cache: "no-store",
  };
  // GET/HEAD ห้ามมี body
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }

  const upstream = await fetch(target, init);
  const respBody = await upstream.arrayBuffer();
  const respHeaders = new Headers();
  upstream.headers.forEach((v, k) => {
    // strip hop-by-hop + content-encoding (fetch already decompressed)
    if (
      ["transfer-encoding", "content-encoding", "content-length", "connection"].includes(
        k.toLowerCase()
      )
    )
      return;
    respHeaders.set(k, v);
  });

  return new NextResponse(respBody, {
    status: upstream.status,
    headers: respHeaders,
  });
}

export async function GET(req: NextRequest, ctx: { params: { path: string[] } }) {
  return forward(req, ctx.params.path);
}
export async function POST(req: NextRequest, ctx: { params: { path: string[] } }) {
  return forward(req, ctx.params.path);
}
export async function PUT(req: NextRequest, ctx: { params: { path: string[] } }) {
  return forward(req, ctx.params.path);
}
export async function DELETE(req: NextRequest, ctx: { params: { path: string[] } }) {
  return forward(req, ctx.params.path);
}
export async function PATCH(req: NextRequest, ctx: { params: { path: string[] } }) {
  return forward(req, ctx.params.path);
}
