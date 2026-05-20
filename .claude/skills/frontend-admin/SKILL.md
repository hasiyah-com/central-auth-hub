# Frontend Admin Dashboard Skill

**Domain**: Next.js Admin Dashboard (Week 8) — http://localhost:3000
**Invoke**: `/frontend-admin` หรือเมื่อทำงานใน `hub/frontend/`
**Security rules**: ดู `/central-auth-hub` (shared)

---

## Project Setup (ยังไม่สร้าง — Week 8)

```
hub/frontend/          ← สร้างที่นี่
├── app/               Next.js 14 App Router
│   ├── layout.tsx
│   ├── page.tsx       redirect → /dashboard
│   ├── dashboard/     KPI overview
│   ├── users/         user list + filter by type/faculty
│   ├── subsystems/    list + pending registrations
│   │   └── pending/   approve/reject
│   └── audit/         audit log viewer
├── components/
├── lib/
│   ├── api.ts         Hub API client (typed)
│   └── auth.ts        JWT verify + cookie handling
├── package.json
└── tailwind.config.ts
```

**Stack**: Next.js 14 + TypeScript + Tailwind CSS + shadcn/ui (หรือ Radix)

## Hub API Endpoints ที่ Dashboard ใช้

| Page | Method | Endpoint | Auth |
|------|--------|----------|------|
| Dashboard | GET | `/admin/overview` | require_hub_admin |
| Users | GET | `/admin/users?type=&faculty=` | require_hub_admin |
| Subsystems | GET | `/admin/subsystems` | require_hub_admin |
| Pending | GET | `/admin/subsystems/pending` | require_hub_admin |
| Approve | POST | `/admin/subsystems/{id}/approve` | require_hub_admin |
| Reject | POST | `/admin/subsystems/{id}/reject` | require_hub_admin |
| Audit | GET | `/admin/audit` (เพิ่มถ้ายังไม่มี) | require_hub_admin |

Base URL: `http://localhost:8000` (dev) — env var `NEXT_PUBLIC_HUB_URL`

## Auth Pattern

```typescript
// Dashboard ต้องการ Hub JWT aud=hub.internal
// แนะนำ: middleware.ts อ่าน cookie "hub_token"
// → verify aud === "hub.internal"
// → ถ้า expired/invalid → redirect /login

// Login page: redirect ไป Hub /auth/google/login
// Hub callback → issue JWT → set cookie → redirect back to dashboard
```

## Design Consistency

- **Theme color**: ยังไม่กำหนด (Hub ใช้ gray/blue, Dorm ใช้ indigo, Library ใช้ emerald)
  → แนะนำ Admin Dashboard ใช้ **slate/blue** (professional, admin feel)
- **Font**: System font stack (Tailwind default)
- **Table pattern**: ใช้ `<table>` + Tailwind สอดคล้องกับ subsystem templates
- **Responsive**: Mobile-friendly (md: breakpoint)

## TDD สำหรับ Frontend

```bash
# Unit tests
npm test                          # Jest + React Testing Library

# E2E (Week 13+)
npx playwright test               # OAuth login flow, table rendering

# Type check
npm run type-check                # tsc --noEmit
```

## Common Tasks

**Init project** (Week 8 เริ่ม):
```bash
cd hub
npx create-next-app@14 frontend --typescript --tailwind --app --eslint
```

**Dev server**:
```bash
cd hub/frontend && npm run dev    # localhost:3000
```

**Build check**:
```bash
npm run build                     # ตรวจ type errors + bundle size
```
