# Pipeline: เรียนรู้พฤติกรรมรายคน (Per-User Behavior RBA)

ชุดสคริปต์ครบวงจร — anchor จากผู้ใช้จริง → สร้างโปรไฟล์ → เทรนโมเดลรายคน → ทดสอบด้วย anomaly → ประเมินผล
**(เตรียมไว้แล้ว ยังไม่รัน — รันตามลำดับ 1→6)**

## เตรียมข้อมูล anchor (ทำครั้งเดียว, ต้องการ DB รันอยู่)
สคริปต์อ่าน anchor 2 ไฟล์นี้ (ดึงจาก DB จริงไว้แล้ว):
- `data/real_user_profiles.csv` — ผู้ใช้จริง + อัตรา login/วัน จริง
- `data/real_access.csv` — สิทธิ์ subsystem จริงต่อคน

ถ้าต้อง refresh anchor ใหม่ (docker ต้องขึ้น):
```bash
docker exec hub-postgres psql -U hub -d hub_db -c "COPY (SELECT u.email,u.user_type,COUNT(*) n_logins,GREATEST(1,(MAX(ls.created_at)::date-MIN(ls.created_at)::date)) days_span,ROUND(COUNT(*)::numeric/GREATEST(1,(MAX(ls.created_at)::date-MIN(ls.created_at)::date)),2) logins_per_day FROM login_sessions ls JOIN users u ON u.id=ls.user_id GROUP BY 1,2 HAVING COUNT(*)>=2) TO STDOUT WITH CSV HEADER" > ml-service/data/real_user_profiles.csv
```

## ลำดับการรัน

| # | คำสั่ง | Input | Output | ทำอะไร |
|---|---|---|---|---|
| 1 | `py ml-service/scripts/build_user_profiles.py` | real_user_profiles.csv, real_access.csv | `user_profiles.json`, `user_logins.csv` | สร้างโปรไฟล์รายคน + login **คนละ 1000** (6018 มีทั้ง mobile+desktop) |
| 2 | `py ml-service/scripts/pipe_clean.py` | user_logins.csv | `user_logins_clean.csv` | ทำความสะอาด (dedup/missing/timestamp/normalize) |
| 3 | `py ml-service/scripts/pipe_features.py` | user_logins_clean.csv | `user_features.csv` | สกัด 23 ฟีเจอร์ (online-RBA ต่อคน), label=0 |
| 4 | `py ml-service/scripts/pipe_train.py` | user_features.csv | `models/user_models.joblib` | เทรน IsolationForest **รายคน** (80% แรก) + global เทียบ |
| 5 | `py ml-service/scripts/pipe_gen_anomalies.py` | user_logins_clean.csv | `user_anomalies_features.csv` | สร้าง anomaly 6 ชนิดต่อคน (label=1) + สกัดฟีเจอร์ |
| 6 | `py ml-service/scripts/pipe_evaluate.py` | user_models.joblib, user_features.csv, user_anomalies_features.csv | `hub/backend/tests/reports/per_user_eval_<date>.md` | ประเมิน per-user + รวม + แยก anomaly type |

**รันทีเดียวทั้งชุด (bash):**
```bash
cd /e/hub/central-auth-starter && \
py ml-service/scripts/build_user_profiles.py && \
py ml-service/scripts/pipe_clean.py && \
py ml-service/scripts/pipe_features.py && \
py ml-service/scripts/pipe_train.py && \
py ml-service/scripts/pipe_gen_anomalies.py && \
py ml-service/scripts/pipe_evaluate.py
```

## สถาปัตยกรรม
- **โมเดล = per-user IsolationForest** (1 ตัว/คน) — เทรนบน login ปกติของคนนั้นเท่านั้น → เรียนพฤติกรรมเฉพาะคน
- **23 ฟีเจอร์** ลำดับ/สูตรตรงกับ `hub/backend/app/services/feature_extraction.py` (โมดูลกลาง `pipe_featurelib.py`)
- **test**: normal held-out 20% ท้าย (แยกตามเวลา) + anomaly ของคนนั้น → วัดด้วยโมเดลของคนนั้น
- ค่าคงที่ฟีเจอร์: MIN_HISTORY=5, PERM_AGE_CAP=365, CONCURRENT cap=50, scope weights (email/name .1, faculty .3, student_id/employee_id .6)

## หมายเหตุ
- `passkey_*`, `permission_change_age` = สังเคราะห์คงที่ต่อ user (log ที่ generate ไม่มี) — deterministic ต่อ email
- ไฟล์ output ทั้งหมดมี **email จริง (PII)** → gitignored
- ต้องมี: `numpy, scikit-learn, joblib` (ติดตั้งแล้ว)

## Requirements แต่ละสคริปต์
- 1: `real_user_profiles.csv` + `real_access.csv` (มีแล้ว)
- 2–6: กินไฟล์จากขั้นก่อนตามตาราง
- `pipe_features.py` และ `pipe_gen_anomalies.py` import `pipe_featurelib` → ต้องรันจากโฟลเดอร์ `ml-service/scripts/` หรือให้ dir นั้นอยู่ใน PYTHONPATH (คำสั่ง `py ml-service/scripts/xxx.py` จาก repo root ใช้ได้ เพราะ Python เพิ่ม dir ของสคริปต์เข้า sys.path อัตโนมัติ)
