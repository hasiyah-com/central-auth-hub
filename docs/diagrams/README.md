# Diagrams — แผนภาพหลัก 18 รูปสำหรับบทที่ 3 (Thesis)

ไฟล์ SVG แบบ **self-contained** — เปิด/แทรกได้ใน Word, PowerPoint, เบราว์เซอร์
แปลงเป็น PNG: เปิดในเบราว์เซอร์ → screenshot หรือใช้ inkscape

**อธิบายรายละเอียดแต่ละรูป (สิ่งที่แสดง, องค์ประกอบ, แหล่งอ้างอิงโค้ด):** ดู [DIAGRAM_GUIDE.md](DIAGRAM_GUIDE.md)

ชุดนี้แทนที่ `fig3-1`..`fig3-10` เดิมทั้งหมด (2026-07-02) จากนั้นขยายเป็น 16 รูป (ครอบคลุม flow ทุกส่วนของระบบ) แล้วเพิ่มอีก 2 รูป (2026-07-12) — เลขรูปและเนื้อหาอ้างอิงตรงกับ `../บทที่ 3.md`

---

## บทที่ 3 — ออกแบบระบบ (18 รูปหลัก)

| ไฟล์ | รูปที่ | หัวข้อ |
|---|---|---|
| [fig3-1_system_overview.svg](fig3-1_system_overview.svg) | 3.1 | System Architecture Overview |
| [fig3-2_business_architecture.svg](fig3-2_business_architecture.svg) | 3.2 | Business Architecture |
| [fig3-3_logical_architecture.svg](fig3-3_logical_architecture.svg) | 3.3 | Logical Architecture |
| [fig3-4_component_diagram.svg](fig3-4_component_diagram.svg) | 3.4 | Component Diagram |
| [fig3-5_subsystem_registration_flow.svg](fig3-5_subsystem_registration_flow.svg) | 3.5 | Subsystem Registration Flow |
| [fig3-6_access_policy_flow.svg](fig3-6_access_policy_flow.svg) | 3.6 | Access Policy Flow (4 modes) |
| [fig3-7_deployment_diagram.svg](fig3-7_deployment_diagram.svg) | 3.7 | Deployment Diagram (VM + Docker) |
| [fig3-8_database_er_diagram.svg](fig3-8_database_er_diagram.svg) | 3.8 | Database ER Diagram |
| [fig3-9_authentication_flow.svg](fig3-9_authentication_flow.svg) | 3.9 | Authentication Flow |
| [fig3-10_oauth_oidc_flow.svg](fig3-10_oauth_oidc_flow.svg) | 3.10 | OAuth/OIDC Flow |
| [fig3-11_jwt_verification_flow.svg](fig3-11_jwt_verification_flow.svg) | 3.11 | JWT Verification Flow |
| [fig3-12_login_sequence_diagram.svg](fig3-12_login_sequence_diagram.svg) | 3.12 | Login Sequence Diagram |
| [fig3-13_old_vs_new_comparison.svg](fig3-13_old_vs_new_comparison.svg) | 3.13 | Old vs New Risk Scoring |
| [fig3-14_hybrid_rba_flow.svg](fig3-14_hybrid_rba_flow.svg) | 3.14 | Hybrid RBA Flow |
| [fig3-15_ml_pipeline.svg](fig3-15_ml_pipeline.svg) | 3.15 | Machine Learning Pipeline |
| [fig3-16_feature_engineering_diagram.svg](fig3-16_feature_engineering_diagram.svg) | 3.16 | Feature Engineering Diagram |
| [fig3-17_passkey_risk_decision_flow.svg](fig3-17_passkey_risk_decision_flow.svg) | 3.17 | Passkey + Risk Decision Flow |
| [fig3-18_incident_response_flow.svg](fig3-18_incident_response_flow.svg) | 3.18 | Risk Detection & Incident Response Flow |

## แผนภาพเสริม (legacy, ไม่ผูกกับเลขรูปในบทที่ 3)

| ไฟล์ | หัวข้อ |
|---|---|
| [deployment-architecture.svg](deployment-architecture.svg) | Deployment Architecture (ต้นฉบับที่ fig3-7 ปรับมาใช้) |
| [er-diagram.svg](er-diagram.svg) | ER รวม (ฉบับก่อนรวมเป็น fig3-8) |
| [system-architecture.svg](system-architecture.svg) | System Architecture (layered, งานวิจัย) |
| [system-overview.svg](system-overview.svg) | ภาพรวมเชิงแนวคิด (flow) |
| [auth-flow.svg](auth-flow.svg) | Authentication Flow ฉบับก่อนหน้า (sequence แบบสั้น) |
| [rbac.svg](rbac.svg) | การตรวจสอบสิทธิ์ (RBAC) 3 ชั้น |
| [ml-model.svg](ml-model.svg) | โมเดล ML / RBA 4 ชั้น |
| [case-normal.svg](case-normal.svg) / [case-anomaly.svg](case-anomaly.svg) | ตัวอย่าง use case ปกติ/ผิดปกติ |
| [workflow-zones-normal.svg](workflow-zones-normal.svg) / [workflow-zones-anomaly.svg](workflow-zones-anomaly.svg) | Swim-lane 3 โซน |

---

**3 โซน (swim-lane) ที่ใช้อ้างอิงในหลายรูป:**
- ⬜ **ระบบภายนอก** — ผู้ใช้ + Google OAuth
- 🟦 **ระบบหลัก (Hub + ML)** — auth, RBAC, ML, JWT, audit
- 🟩 **ระบบย่อย** — หอพัก, ห้องสมุด

ดูข้อมูล Dataset/Input/Output ที่ [../thesis-scope-and-io.md](../thesis-scope-and-io.md)
