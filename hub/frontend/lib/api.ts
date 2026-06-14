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

// init เพิ่ม field พิเศษ:
//   stepupMode: "redirect" (default) = 403 stepup_required → พาไปหน้า stepup (เดิม)
//              "throw"               = โยน ApiError ให้ caller จัดการ inline
//                                      (ใช้กับ runWithStepup — verify ในหน้าไม่ redirect)
export type ClientFetchInit = RequestInit & {
  stepupMode?: "redirect" | "throw";
};

export function isStepupRequired(detail: unknown): boolean {
  return (
    typeof detail === "object" &&
    detail !== null &&
    (detail as { code?: string }).code === "stepup_required"
  );
}

export async function clientFetch<T = unknown>(
  path: string,
  init: ClientFetchInit = {}
): Promise<T> {
  const { stepupMode = "redirect", ...rest } = init;
  const res = await fetch(`/api/proxy${path}`, {
    ...rest,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // ignore
    }
    // Step-up required (Phase 5 — critical action gate):
    // backend 403 {code: "stepup_required"} → พาไปยืนยันตัวตน แล้วกลับมาหน้าเดิม
    // ยกเว้น stepupMode="throw" → ปล่อยให้ caller verify inline (ไม่ redirect)
    if (
      stepupMode === "redirect" &&
      res.status === 403 &&
      isStepupRequired(detail) &&
      typeof window !== "undefined"
    ) {
      const returnTo = encodeURIComponent(
        window.location.pathname + window.location.search
      );
      window.location.href = `/auth/passkey/stepup?return_to=${returnTo}`;
    }
    const err: ApiError = { status: res.status, detail: detail as string };
    throw err;
  }
  // 204 No Content
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
