import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { TOKEN_COOKIE, REFRESH_TOKEN_COOKIE } from "@/lib/auth";

const HUB_INTERNAL =
  process.env.HUB_INTERNAL_URL || "http://hub-backend:8000";
const REFRESH_COOKIE_MAX_AGE_SEC = 30 * 24 * 60 * 60; // ดู set-token/route.ts

/**
 * /api/proxy/<path> → Hub backend
 *
 * อ่าน JWT จาก httpOnly cookie แล้วแนบเป็น Authorization: Bearer
 * — client ไม่ต้องเห็น token เลย
 *
 * ใช้แทน Next.js rewrites เพราะ rewrites ไม่ยุ่ง cookie/header
 *
 * Access token อายุสั้น (15 นาที) — ถ้า upstream ตอบ 401 (token หมดอายุ/revoke)
 * และมี refresh cookie อยู่ → ลอง refresh ครั้งเดียวผ่าน Hub /auth/refresh แล้ว
 * retry request เดิมด้วย token ใหม่ ก่อนจะยอม fail จริง (transparent ต่อ caller —
 * clientFetch ฝั่ง browser ไม่ต้องรู้เรื่อง refresh เลย)
 */

type RefreshedTokens = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

// Hub /auth/refresh คืน 200 ได้ 2 แบบ: token คู่ใหม่ หรือ {stepup_required} เมื่อ
// RBA จับ session-hijack (IP/ประเทศ/device เปลี่ยน) → ต้องยืนยัน Passkey ก่อน
type RefreshOutcome =
  | { kind: "ok"; tokens: RefreshedTokens }
  | { kind: "stepup"; stepupUrl: string }
  | { kind: "fail" };

async function tryRefresh(): Promise<RefreshOutcome> {
  const refreshToken = cookies().get(REFRESH_TOKEN_COOKIE)?.value;
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
      | RefreshedTokens
      | { stepup_required: true; stepup_url: string };
    if ("stepup_required" in data) {
      return { kind: "stepup", stepupUrl: data.stepup_url };
    }
    return { kind: "ok", tokens: data };
  } catch {
    return { kind: "fail" };
  }
}

function attachTokenCookies(res: NextResponse, tokens: RefreshedTokens) {
  res.cookies.set({
    name: TOKEN_COOKIE,
    value: tokens.access_token,
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: tokens.expires_in,
  });
  res.cookies.set({
    name: REFRESH_TOKEN_COOKIE,
    value: tokens.refresh_token,
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: REFRESH_COOKIE_MAX_AGE_SEC,
  });
}

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

  let upstream = await fetch(target, init);
  let refreshed: RefreshedTokens | null = null;

  // 401 + มี access token เดิม (ไม่ใช่ anonymous request) → ลอง refresh ครั้งเดียว
  if (upstream.status === 401 && token) {
    const outcome = await tryRefresh();
    if (outcome.kind === "ok") {
      refreshed = outcome.tokens;
      headers["authorization"] = `Bearer ${refreshed.access_token}`;
      upstream = await fetch(target, { ...init, headers });
    } else if (outcome.kind === "stepup") {
      // RBA จับความเสี่ยงตอน refresh → บอก browser ให้ไปยืนยัน Passkey
      // (clientFetch อ่าน code นี้แล้ว window.location.href = stepup_url)
      return NextResponse.json(
        {
          detail: {
            code: "risk_stepup_required",
            stepup_url: outcome.stepupUrl,
          },
        },
        { status: 401 }
      );
    }
    // kind === "fail" → ปล่อย 401 เดิม propagate (clientFetch redirect ไป login)
  }

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

  const res = new NextResponse(respBody, {
    status: upstream.status,
    headers: respHeaders,
  });
  if (refreshed && upstream.status !== 401) {
    attachTokenCookies(res, refreshed);
  }
  return res;
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
