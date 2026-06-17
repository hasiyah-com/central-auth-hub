# ML Real-Data Evaluation — 2026-06-17

วัดผลโมเดลปัจจุบันบน **login_sessions จริง** (re-score ด้วย risk engine ปัจจุบัน, shadow).

## ผล
- sessions ทั้งหมด: **243** (extract error 0)
- normal (label=0): **243** · attack (label=1): **0**
- **FPR (decision challenge/block): 46.9%** (114/243)
  - rule hard-block: 106 (login_count≥50 ฯลฯ — dev/test burst, ปรับ threshold ไม่ได้)
  - **FPR(ML-driven, ตัด hard-block): 5.8%** ← calibrate (2.1) คุมตัวนี้
- normal score เฉลี่ย: 0.656
- **Recall: วัดไม่ได้** — attack label จริง = 0 (ต้อง label ผ่าน admin toggle-attack-ip / MLFeedback)

## Decision distribution
| decision | count |
|---|---|
| allow | 104 |
| would_block | 109 |
| would_challenge | 5 |
| would_warn | 25 |

## ข้อจำกัด (เขียนใน thesis ตามตรง)
- โมเดลเทรนบน synthetic; eval นี้วัดบน real normal เป็นหลัก (FPR)
- ยังไม่มี attack จริงใน DB → recall ยังพิสูจน์บน real ไม่ได้
- ขั้นต่อไป (2.2): สะสม label จาก admin → eval recall ได้
