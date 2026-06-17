# ML Real-Data Evaluation — 2026-06-17

วัดผลโมเดลปัจจุบันบน **login_sessions จริง** (re-score ด้วย risk engine ปัจจุบัน, shadow).

## ผล
- sessions ทั้งหมด: **243** (extract error 0)
- normal (label=0): **243** · attack (label=1): **0**
- **False-Positive Rate: 57.2%** (139/243 normal ถูก flag ที่ score ≥ 0.5)
- normal score เฉลี่ย: 0.656
- **Recall: วัดไม่ได้** — attack label จริง = 0 (ต้อง label ผ่าน admin toggle-attack-ip / MLFeedback)

## Decision distribution
| decision | count |
|---|---|
| allow | 38 |
| would_block | 110 |
| would_challenge | 29 |
| would_warn | 66 |

## ข้อจำกัด (เขียนใน thesis ตามตรง)
- โมเดลเทรนบน synthetic; eval นี้วัดบน real normal เป็นหลัก (FPR)
- ยังไม่มี attack จริงใน DB → recall ยังพิสูจน์บน real ไม่ได้
- ขั้นต่อไป (2.2): สะสม label จาก admin → eval recall ได้
