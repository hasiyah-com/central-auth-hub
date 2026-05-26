/**
 * Typed fetch wrapper สำหรับเรียก Hub backend
 *
 * Client (browser) — ใช้ fetch ตรงไป /api/hub/* (Next.js rewrite ส่งไป backend)
 *                    cookie ส่งอัตโนมัติเพราะ same-origin
 * Server (RSC / route handler) — import จากฝั่ง server แล้วอ่าน cookie เอง
 */

export type ApiError = {
  status: number;
  detail: string;
};

// ── Client-side fetch ─────────────────────────────────────────
// Browser เรียกผ่าน Next.js rewrite (/api/hub/*) → backend
// cookie httpOnly ที่เก็บ JWT จะถูกแนบโดย /api/proxy แทน

export async function clientFetch<T = unknown>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const res = await fetch(`/api/proxy${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // ignore
    }
    const err: ApiError = { status: res.status, detail };
    throw err;
  }
  // 204 No Content
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
