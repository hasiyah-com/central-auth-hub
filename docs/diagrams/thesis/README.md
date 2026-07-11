# Thesis Architecture Diagrams

6 แผนภาพสำหรับเล่มจบ — เขียนด้วย Mermaid (text-based, แก้ง่าย, version control ได้)

## ไฟล์

| # | File | คำอธิบาย |
|---|------|---------|
| 1 | `1-system-architecture.mermaid` | องค์ประกอบทั้งหมด: Hub, Subsystems, ML, DB, IdPs |
| 2 | `2-system-workflow.mermaid` | Sequence: Login → IdP → RBA → JWT → แสดงผล |
| 3 | `3-authentication-flow.mermaid` | Google OAuth + Passkey (WebAuthn) + RBA |
| 4 | `4-hybrid-rbac-workflow.mermaid` | Layer 1 Static RBAC + Layer 2 ML 4-Layer RBA |
| 5 | `5-ml-pipeline.mermaid` | Log → Preprocess → 12 features → IForest/OCSVM → SHAP → Decision |
| 6 | `6-deployment-architecture.mermaid` | Nginx + 3 Docker stacks + 3 Postgres + volumes |
| 📺 | `index.html` | เปิดใน browser → render ทุก diagram + ปุ่ม download PNG/SVG |

## วิธีใช้ (3 ทาง)

### ทาง 1 — เปิด `index.html` ใน browser (ง่ายสุด)
ดับเบิลคลิก `index.html` → render ทุก diagram → กดปุ่ม **⬇ ดาวน์โหลด PNG** ที่ขวาบนแต่ละกล่อง

### ทาง 2 — แก้ใน VS Code
ติดตั้ง extension **Markdown Preview Mermaid Support** หรือ **Mermaid Preview** → เปิด `.mermaid` → preview live

### ทาง 3 — Export ผ่าน mermaid.live
ก๊อปเนื้อหา `.mermaid` ไปวางที่ <https://mermaid.live> → **Actions → PNG/SVG**

## ข้อดีของ Mermaid (vs draw.io / Visio)

- Plain text → diff ใน git ได้, code review ได้
- ไม่ต้องเปิดโปรแกรมหนัก ๆ
- เปลี่ยน label / box / สีได้ใน 5 วินาที
- Export PNG/SVG/PDF ได้หลายช่อง (mermaid.live, mmdc, VS Code, index.html นี้)
- รองรับ ภาษาไทย เต็มรูป (Noto Sans Thai)

## Theme

ทุกไฟล์ใช้ Mermaid theme `base` + กำหนดสีเอง → กลาง ๆ พิมพ์เล่มก็อ่านง่าย, นำเสนอจอก็คมชัด
