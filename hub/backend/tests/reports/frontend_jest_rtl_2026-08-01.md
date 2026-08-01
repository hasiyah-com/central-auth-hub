# Frontend Test (Jest + React Testing Library) — ปิดช่องว่าง Week 13-14 · 2026-08-01

## บริบท

Week 13-14 (Test suite + CI) เหลือช่องว่างเดียว: **frontend ไม่มี test เลย** (ไม่มี jest/RTL,
`playwright.yml` เป็น stub ที่พัง). เพิ่ม Jest + React Testing Library ตาม roadmap.

## สิ่งที่ทำ

### 1. ติดตั้ง + config
- devDeps: `jest@29`, `jest-environment-jsdom`, `@testing-library/react@16`,
  `@testing-library/jest-dom@6`, `@testing-library/user-event@14`, `@types/jest`
- `jest.config.js` (ใช้ `next/jest` — transform TS/JSX + alias `@/*`) + `jest.setup.js`
- `package.json` scripts: `test`, `test:watch`

### 2. lib/format.ts (ใหม่ — canonical + tested)
รวม pure helper ที่เคยกระจาย/ซ้ำในหลายหน้า: `parseUTC`, `relTime`, `formatDuration`,
`riskColor`, `avatarColor`. **migrate `users/[id]/page.tsx` มาใช้** (ลบ inline ซ้ำ) →
เป็นโค้ดที่แอปใช้จริง ไม่ใช่ dead code.

### 3. Test suites (32 tests, positive + edge/negative)
| ไฟล์ | เทส | ครอบคลุม |
|---|---|---|
| `lib/__tests__/format.test.ts` | 23 | **parseUTC กันบั๊ก B53** (naive-UTC ไม่เพี้ยน 7ชม.) · relTime · formatDuration · riskColor (ตรง RBA threshold) · avatarColor |
| `components/__tests__/Badge.test.tsx` | 4 | render children + tone (good/danger/default) |
| `components/__tests__/DataTable.test.tsx` | 5 | render/empty state/custom render/**row click (user-event)** |

### 4. CI
- **ลบ `playwright.yml`** (stub พัง — ไม่มี spec, npm ci ผิด path)
- **เพิ่ม `frontend-ci.yml`** — รันจริง: `npm ci` → `tsc --noEmit` → `npm test` (jest) ที่ `hub/frontend`

## ผลรัน

```
Test Suites: 3 passed, 3 total
Tests:       32 passed, 32 total
```
`tsc --noEmit` — ไม่มี error (migration หน้า users + tests สะอาด)

## จุดเด่น
- **กันบั๊ก B53 (timezone)** — เทส `parseUTC("...T03:30:00").getUTCHours() === 3` + "now → diff ~0 ไม่ใช่ 420 นาที"
- **DataTable row click** ทดสอบ interaction จริงด้วย `user-event`
- lib/format ถูกใช้จริงในหน้า (migrate แล้ว) ไม่ใช่ dead code

## Week 13-14 — สถานะหลังงานนี้
| รายการ | ก่อน | หลัง |
|---|---|---|
| Backend pytest + E2E | ✅ | ✅ |
| GitHub Actions CI (backend) | ✅ | ✅ |
| **Frontend Jest/RTL** | ❌ | ✅ **32 tests** |
| **Frontend CI** | ⚠️ stub | ✅ `frontend-ci.yml` (jest จริง) |

→ **Week 13-14 ปิดครบ** (เหลือแต่ Week 15-16 เขียนเล่ม)

## วิธีรัน
```bash
cd hub/frontend && npm test
```
