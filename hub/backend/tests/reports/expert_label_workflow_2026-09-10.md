# Expert Label Workflow (backend) — ผลการสร้างและทดสอบ

วันที่ 10–11 ก.ย. 2569 · แบบที่ล็อกไว้: `docs/design/EXPERT_LABEL_WORKFLOW.md` (§12 = สิ่งที่สร้างจริง)

**สถานะ:** Backend Expert Label Workflow พร้อมสำหรับ integration testing แต่ยังไม่เปิดใช้งาน
operational review บน production — ยังไม่มี UI, retention และการ sync บน production

---

## สรุป

| รายการ | ผล |
|---|---|
| เทสของฟีเจอร์ | **128 passed** — unit 82 · DB/API 31 · integrity 15 |
| RED ก่อนเขียนโค้ด (รอบแรก) | unit และ DB/API fail ตอน import (ยังไม่มี package และ model) |
| RED ของข้อตรวจเพิ่ม (รอบสอง) | 6 จาก 15 fail บน schema เดิม — ตรงกับช่องโหว่ระดับฐานข้อมูลทั้ง 6 ข้อ |
| migration `e5f6a7b8c9d0` | upgrade → downgrade → upgrade ผ่านทั้งรุ่นแรกและรุ่นแก้ |
| ข้อมูลค้างหลังเทส | 0 แถวในทั้ง 3 ตาราง · ผู้ใช้ทดสอบ 0 · ตาราง feedback เดิมยัง 8 แถว |
| pre-commit | ผ่านทุก hook |
| ชุดเต็ม hub-backend (รอบล่าสุด) | 1,109 passed · 62 skipped · 0 failed — ดู §7 ว่าทำไมยังไม่ถือเป็น release gate |

---

## 1. สิ่งที่สร้าง

| ส่วน | ไฟล์ |
|---|---|
| ตาราง + trigger + CHECK + FK | `alembic/versions/e5f6a7b8c9d0_expert_label_workflow.py` |
| model | `app/models.py` — `ExpertAlertGroup` · `SystemDisposition` · `ExpertReview` |
| คำศัพท์ปิด | `app/services/expert_review/vocab.py` |
| provenance | `app/services/expert_review/provenance.py` |
| จัดกลุ่ม | `app/services/expert_review/grouping.py` |
| สร้างกลุ่มจาก shadow decision | `app/services/expert_review/sync.py` |
| มุมมอง blind / unblinded | `app/services/expert_review/views.py` |
| label append-only | `app/services/expert_review/reviews.py` |
| จ่ายงาน | `app/services/expert_review/queue.py` |
| สถิติ + readiness gate | `app/services/expert_review/metrics.py` |
| API | `app/routers/expert_review.py` → `/admin/expert-review` |
| ที่มาของคอนฟิก shadow | `app/config.py` — `shadow_epoch_id` · `risk_config_id` · `calibration_version` · `calibration_sha256` · `scoring_commit` (ค่าเริ่มต้นว่าง) |
| เทส | `tests/test_expert_review_units.py` · `tests/test_expert_review_db.py` · `tests/test_expert_review_integrity.py` |

---

## 2. เงื่อนไขที่ล็อกไว้ และเทสที่พิสูจน์

| เงื่อนไข | เทส |
|---|---|
| ตาราง `expert_alert_groups` · `expert_reviews` · `system_dispositions` | `test_sync_creates_one_group_with_disposition` |
| append-only + `supersedes_id` | `test_update_on_expert_reviews_rejected_by_db` · `test_supersede_appends_and_keeps_original` · `test_cannot_supersede_twice` · `test_duplicate_round1_conflict` · `test_cannot_supersede_other_reviewer` |
| grouping `(user_id, primary_signal, 30 นาที)` | `test_window_start_floors_to_30_minutes` · `test_group_key_format` · `test_build_groups_*` (4) · `test_primary_signal_*` (3) · `test_reason_codes_strip_values_and_sort` · `test_sync_idempotent` · `test_sync_skips_open_window` |
| blind review รอบแรก | `test_blind_payload_has_no_model_keys` · `test_blind_payload_has_no_model_strings_or_raw_identifiers` · `test_blind_view_has_no_model_output` · `test_round1_cannot_claim_model_output_visible` |
| รอบสองจึงเปิดข้อมูลโมเดล | `test_unblinded_forbidden_before_round1` · `test_unblinded_allowed_after_round1` · `test_round2_requires_round1` · `test_round2_requires_unblinding_first` · `test_round2_marked_visible` · `test_round1_locked_after_unblind` |
| แยก provenance demo / test / local / unknown | `test_provenance_classify` (16 กรณี) · `test_provenance_172_prefix_is_not_blanket_local` · `test_eligible_only_external_with_config_and_commit` (7 กรณี) |
| ไม่ migrate ตาราง feedback เดิม 8 แถว | `test_workflow_code_does_not_use_ml_feedback` · `test_review_never_touches_access_state` (นับแถวก่อน/หลัง) |
| reviewer ไม่มี API เปลี่ยน access disposition | `test_route_inventory_has_no_disposition_write` · `test_update_on_system_dispositions_rejected_by_db` · `test_review_never_touches_access_state` |
| ยังไม่คำนวณ production FPR | `test_readiness_thresholds_locked` · `test_readiness_boundaries_inclusive` · `test_readiness_each_gate` (5) · `test_metrics_production_fpr_not_computed` |
| ผู้ตรวจ ≥ 2 · double review 30% · กติกาเห็นต่าง | `test_double_review_pool_deterministic_and_about_30_percent` · `test_queue_*` (3) · `test_consolidate` (9) · `test_kappa_*` (4) |
| คำศัพท์ปิด | `test_verdicts_and_confidence_closed` · `test_reason_codes_closed_list_from_design` · `test_invalid_input_422` (5) |
| audit ทุกครั้งที่เปิดดู · admin เท่านั้น | `test_view_is_audited` · `test_non_admin_forbidden` |

เทส trigger ทั้งสองตัวตรวจข้อความ `append-only` ด้วย — ถ้า driver แปลง UUID ไม่ได้
ข้อผิดพลาดชนิดเดียวกัน (`DBAPIError`) จะทำให้เทสผ่านโดยไม่ได้ชน trigger จริง

---

## 3. ข้อตรวจเพิ่มก่อน commit (`test_expert_review_integrity.py`)

| ข้อตรวจ | ผลบน schema เดิม | การแก้ | เทส |
|---|---|---|---|
| downgrade ลบ trigger ก่อนตาราง | ถูกอยู่แล้ว | — | `test_downgrade_drops_triggers_before_tables` |
| upgrade ซ้ำไม่สร้าง trigger ชื่อชน | ถูกอยู่แล้ว | — | `test_exactly_one_trigger_per_evidence_table` + round-trip migration |
| `supersedes_id` ไม่ชี้ข้ามกลุ่ม | **INSERT ตรงทำได้** (service กันอยู่) | FK แบบ composite `(supersedes_id, group_id, reviewer_id, round)` | `test_service_rejects_supersede_across_group` · `test_db_rejects_supersede_across_group` |
| `supersedes_id` ไม่ชี้ข้ามผู้ตรวจ | **INSERT ตรงทำได้** | FK เดียวกัน | `test_db_rejects_supersede_across_reviewer` |
| `supersedes_id` ไม่ชี้ข้ามรอบ | **INSERT ตรงทำได้** | FK เดียวกัน | `test_db_rejects_supersede_across_round` |
| รอบ 1 ซ้ำโดยเลี่ยง service | **INSERT ตรงทำได้** — service กันได้เฉพาะ request ที่ไม่ชนกัน | unique index บางส่วน `(group_id, reviewer_id, round) WHERE supersedes_id IS NULL` | `test_db_rejects_second_root_round1` · `test_db_allows_linear_supersede_chain` |
| รอบสองอ้างรอบแรกที่มีจริง | บังคับใน service | — (ดู §5) | `test_round2_requires_round1` |
| timestamp เป็น UTC | ORM ถูก · server default ขึ้นกับ timezone ของ session | `timezone('utc', now())` | `test_review_created_at_is_utc` · `test_server_default_is_utc_even_when_session_timezone_differs` |
| ลบผู้ใช้ไม่ cascade หลักฐาน | ถูกอยู่แล้ว (NO ACTION) | — | `test_foreign_keys_never_cascade` · `test_deleting_reviewer_does_not_cascade_reviews` · `test_deleting_subject_user_does_not_cascade_groups` |
| ลบ login session ไม่ทำลายหลักฐาน | ถูกอยู่แล้ว | — | `test_deleting_login_session_keeps_group_evidence` |
| โค้ดไม่มีช่องทาง UPDATE ตารางหลักฐาน | ถูกอยู่แล้ว | — | `test_workflow_code_has_no_update_path` (AST) · เทส trigger ใช้ connection เดียวกับ API |

**RED ของรอบนี้** — 6 fail ได้แก่ 4 เทส composite FK / unique บางส่วน · เทส UTC ของ
server default · และเทส FK รุ่นแรกที่คาดหวัง RESTRICT ทุกตัว

เทส FK ถูกแก้หลัง RED ให้ยอมรับทั้ง RESTRICT และ NO ACTION เพราะ FK ที่อ้างตาราง
`expert_reviews` เองต้องเป็น NO ACTION — RESTRICT ตรวจทีละแถวทันที ทำให้ลบทั้งสายการแก้
ใน statement เดียวไม่ได้ · เทสนี้จึง **ผ่านตั้งแต่ schema เดิม** และทำหน้าที่กันไม่ให้มีใคร
เปลี่ยนเป็น cascade ภายหลัง ไม่ใช่หลักฐานว่ามีการแก้

---

## 4. การบังคับที่ระดับฐานข้อมูล

ไม่พึ่งแค่ "API ไม่มี endpoint" — ถ้ามีโค้ดใหม่หรือ SQL ตรงพยายามแก้ ฐานข้อมูลปฏิเสธเอง

```
expert_reviews_no_update                  BEFORE UPDATE -> RAISE
system_dispositions_no_update             BEFORE UPDATE -> RAISE
expert_reviews.supersedes_id              UNIQUE  (แก้ได้ครั้งเดียว ประวัติเป็นสายเดียว)
fk_expert_reviews_supersedes_same_chain   แถวที่แก้ต้องกลุ่ม ผู้ตรวจ และรอบเดียวกัน
uq_expert_reviews_one_root                label ต้นทางได้แถวเดียวต่อ (กลุ่ม, ผู้ตรวจ, รอบ)
ck_expert_reviews_round_visibility        รอบ 1 = false · รอบ 2 = true
ck_expert_reviews_verdict                 รายการปิด 4 ค่า
ck_expert_reviews_confidence              low | medium | high
ck_expert_alert_groups_provenance         demo | test | unknown | local | external
ck_expert_alert_groups_eligible           eligible ได้เมื่อ external + risk_config_id + scoring_commit
FK ทั้ง 6 ตัว                              NO ACTION — ไม่มี cascade / set null
created_at                                timezone('utc', now())
```

trigger ปฏิเสธเฉพาะ UPDATE · DELETE เว้นไว้ให้ retention ในอนาคตและการล้างข้อมูลทดสอบ
แต่ FK ยังกันการลบแถวที่ถูกอ้างอยู่

---

## 5. Blind review — สิ่งที่ตรวจว่ารั่วไม่ได้

payload รอบแรกสร้างจาก **allowlist** ของข้อเท็จจริง ไม่ใช่การลบฟิลด์โมเดลออก
ฟิลด์ที่ถูกเพิ่มใน `login_sessions` ภายหลังจึงไม่หลุดเข้ามาเอง

| ตรวจว่าไม่มี | วิธี |
|---|---|
| คีย์ของโมเดล | สแกนคีย์ทุกระดับ: `risk_score` `decision` `risk_breakdown` `risk_reasons` `anomaly_score` `primary_signal` `primary_layer` `system_disposition` `model_output` `evidence` `thresholds` `final_risk_score` `group_key` `is_account_takeover` `is_attack_ip` |
| ค่าของโมเดล | สแกนข้อความ: `would_` · ค่าคะแนน · `(+0.` · `-> challenge` · `evidence` · `threshold` · ชื่อสัญญาณ · `rule:` |
| ตัวตนจริง | UUID ผู้ใช้ · อีเมล · IP เต็ม · user agent เต็ม |

---

## 6. ข้อจำกัดและสิ่งที่ยังไม่ได้สร้าง

| ส่วน | สถานะ |
|---|---|
| หน้า UI ใน console | ยังไม่สร้าง — ใช้ผ่าน API ได้ |
| ขอดู IP เต็มพร้อม audit (design §6) | ยังไม่สร้าง |
| retention 180 วัน (design §6) | ยังไม่สร้าง · ต้องทำเป็น DELETE + เก็บสถิติแยก เพราะ trigger ปฏิเสธ UPDATE |
| การ sync บน production | ยังไม่ทำ · migration ยังไม่ apply บน production |
| การคำนวณ production FPR | **ตั้งใจไม่สร้าง** — ต้องเป็นรอบวิเคราะห์ที่ประกาศล่วงหน้าหลังผ่าน readiness gate |
| shadow epoch | ยังไม่มี · `risk_config_id` และ `scoring_commit` ว่าง จึงไม่มีกลุ่มใด eligible |
| รอบสองอ้างรอบแรกที่มีจริง | บังคับใน service เท่านั้น · หลักฐานการเปิดดูผลโมเดลอยู่ใน audit log ซึ่งไม่มี FK มายังตารางนี้ |
| role ของฐานข้อมูล | แอปใช้ role ที่เป็น superuser ใน dev ซึ่งสั่ง `DISABLE TRIGGER` ได้ · trigger กันทุกเส้นทางปกติของแอป แต่ไม่กันผู้มีสิทธิ์ DDL · การแยก role เป็นงานของ production |
| `seed_users.py` | ไม่รู้จักตารางใหม่ · ถ้ามี alert group หรือ review อ้างผู้ใช้ seed อยู่ การ re-seed จะถูก FK ปฏิเสธ (ตั้งใจให้ไม่ลบหลักฐานเงียบ ๆ) |

ยังไม่ได้รัน `sync` กับข้อมูลจริงในฐานข้อมูล dev — เทสทั้งหมดใช้ผู้ใช้และ login ที่สร้างขึ้นเองแล้วลบออก

---

## 7. ชุดเต็มและเทสที่ไม่เสถียร

| รอบ | ผล | เทสที่ fail (ผ่านทุกตัวเมื่อรันแยก) |
|---|---|---|
| 9 ก.ย. (ก่อนงานนี้) | 965 passed · 42 skipped · 2 failed | `test_e2e_subsystem.py::test_e2e_register_bad_redirect_rejected` · `test_scope_conformance.py::test_scope3_monitoring_requires_admin` |
| 10 ก.ย. | 1,078 passed · 42 skipped · 2 failed | `test_activity_online.py::test_stale_session_not_online` · `test_e2e_permission.py::test_e2e_change_status_invalid_negative[removed]` |
| 11 ก.ย. (รอบล่าสุด) | 1,109 passed · 62 skipped · **0 failed** | — |

**รอบล่าสุดที่ 0 failed ยังไม่ถือเป็น release gate** — ชุดที่ fail เปลี่ยนไปทุกรอบและขึ้นกับ
ลำดับการรัน การผ่านหนึ่งรอบจึงไม่ได้พิสูจน์ว่าต้นเหตุหายไป ต้องแก้ test isolation และรันซ้ำ
หลายรอบให้ได้ `0 failed` ทุกรอบ

จำนวนเทสระหว่างรอบ 10 และ 11 ก.ย. เปลี่ยนเกินกว่าที่งานนี้เพิ่ม (+15) เพราะมีไฟล์เทสจากงานอื่น
ที่ยังไม่ถูก track อยู่ใน working tree (`test_monthly_report.py` · `test_global_search.py` ·
`test_dashboard_insights.py` · `test_health_self_target.py` — collect ได้ 66 รายการ)
ไฟล์เหล่านี้ไม่อยู่ใน commit ของงานนี้

---

## 8. วิธีรัน

```bash
docker compose exec hub-backend alembic upgrade head
docker compose exec hub-backend pytest tests/test_expert_review_units.py tests/test_expert_review_db.py tests/test_expert_review_integrity.py -v
```
