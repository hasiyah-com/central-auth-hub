"""Export labeled real data (Phase 2.2) — feedback loop step 1.

ดึง login_sessions จริงที่มี label (admin MLFeedback / is_account_takeover / is_attack_ip)
→ extract 22 features → เขียน CSV รูปแบบเดียวกับ synthetic (train_model อ่านต่อได้)

label:
  1 (anomaly) = true_positive (MLFeedback) | is_account_takeover | is_attack_ip
  0 (normal)  = normal_confirmed / false_positive (MLFeedback)

ทำไม: ปิด feedback loop — โมเดลเทรนบน synthetic อย่างเดียว ทำ FPR สูงบน real (1.1).
เพิ่ม real normal เข้า training → model เห็น distribution จริง → FPR ลด.
real attack → ใช้วัด recall (2.2 + eval).

Run (step 1):
    docker compose exec hub-backend python -m scripts.export_labeled_data
    # → /app/tests/reports/real_labeled.csv
Step 2 (ย้ายไป ml-service + retrain):
    docker compose cp hub-backend:/app/tests/reports/real_labeled.csv ml-service:/app/data/
    docker compose exec ml-service python -m scripts.train_model
"""

import csv
from pathlib import Path

from app.database import SessionLocal
from app.models import LoginSession, MLFeedback
from app.security.rule_engine import FEAT
from app.services.feature_extraction import extract_session_features

OUT = Path("/app/tests/reports/real_labeled.csv")

# MLFeedback.label → numeric (1=anomaly, 0=normal)
FEEDBACK_TO_LABEL = {
    "true_positive": 1,
    "false_positive": 0,
    "normal_confirmed": 0,
}


def main() -> None:
    db = SessionLocal()
    try:
        # admin feedback (priority) → session_id : label
        fb = {
            str(f.session_id): FEEDBACK_TO_LABEL.get(f.label)
            for f in db.query(MLFeedback).all()
            if f.label in FEEDBACK_TO_LABEL
        }

        sessions = db.query(LoginSession).all()
        names = [n for n, _ in sorted(FEAT.items(), key=lambda kv: kv[1])]
        rows: list[list] = []
        n_pos = n_neg = 0

        for s in sessions:
            # label: MLFeedback ก่อน, ไม่งั้นดู ground-truth flag
            label = fb.get(str(s.id))
            if label is None:
                if s.is_account_takeover or s.is_attack_ip:
                    label = 1
                else:
                    continue  # ไม่มี label ชัดเจน → ข้าม (ไม่เดา)
            feats = extract_session_features(
                db,
                s.user_id,
                s.ip,
                s.user_agent,
                s.geo_country,
                now=s.created_at,
                subsystem_id=s.subsystem_id,
            )
            rows.append(feats + [label])
            n_pos += label == 1
            n_neg += label == 0

        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(names + ["label"])
            w.writerows(rows)

        print(f"✅ export real labeled → {OUT}")
        print(f"   total: {len(rows)}  (normal={n_neg}, anomaly={n_pos})")
        if n_pos == 0:
            print("   ⚠️ ยังไม่มี attack label จริง — loop จะเพิ่มแค่ real normal (ช่วยลด FPR)")
            print(
                "      label attack ผ่าน admin: toggle-attack-ip / MLFeedback=true_positive"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
