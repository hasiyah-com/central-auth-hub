# ML Service Skill

**Domain**: ML Verifier — Isolation Forest anomaly detection (port 9000)
**Invoke**: `/ml-service` หรือเมื่อทำงานใน `ml-service/`
**Security rules**: ดู `/central-auth-hub` (shared)

---

## Architecture

```
ml-service/app/
├── main.py      FastAPI, POST /v1/score, GET /v1/features-info, GET /health
├── features.py  FEATURE_NAMES (12), FEATURE_RANGES — นี่คือ contract กับ Hub
└── model.py     load IsolationForest pkl, sigmoid score (0.0–1.0)

ml-service/scripts/
├── generate_data.py   สร้าง synthetic sessions (normal + anomaly distribution)
└── train_model.py     train + save models/iforest_v1.pkl
```

## Feature Contract (สำคัญมาก)

**FEATURE_NAMES** ใน `ml-service/app/features.py` ต้องตรงกับ order ใน `hub/backend/app/services/feature_extraction.py` เสมอ (B27)

| # | Feature | Category |
|---|---------|----------|
| 1 | hour_of_day | Temporal |
| 2 | day_of_week | Temporal |
| 3 | is_weekend | Temporal |
| 4 | hours_from_typical_login_time | Temporal (personalized) |
| 5 | is_thailand | Geographic |
| 6 | is_new_country | Geographic |
| 7 | country_change_count_30d | Geographic |
| 8 | is_new_device | Device |
| 9 | is_new_user_agent_family | Device |
| 10 | log_minutes_since_last_login | Velocity |
| 11 | login_count_24h | Velocity |
| 12 | failed_logins_24h | Brute Force |

**Cold-start policy**: feature #4 (`hours_from_typical_login_time`) ต้องการ history ≥ 5 sessions → ต่ำกว่า = return 0.0 (neutral)

## Score Endpoint

```
POST /v1/score
Body: {"features": [12 floats ตามลำดับข้างบน]}
Response: {
  "data": {
    "anomaly_score": 0.0–1.0,   # sigmoid-transformed
    "decision": "pass|mfa|block|would_mfa|would_block",
    "thresholds": {"mfa": 0.6, "block": 0.85}
  },
  "meta": {"model_version": "...", "latency_ms": ...}
}
```

## Training Pipeline

```bash
# ต้องรันตามลำดับ — ทุกครั้งที่เปลี่ยน feature
docker compose exec ml-service python -m scripts.generate_data
docker compose exec ml-service python -m scripts.train_model
docker compose restart hub-backend   # Hub โหลด feature list ใหม่
```

## Shadow Mode

```
ML_SHADOW_MODE=true ใน .env
→ ML scores but ไม่ block
→ decision = "would_mfa" หรือ "would_block" แทน "mfa"/"block"
→ login_sessions.decision บันทึก would_* ไว้ analyze ภายหลัง
```

## Fail-Safe Rule (B21)

```python
# ml_client.py ใน Hub — ต้อง catch ทุก exception
try:
    result = await httpx.post("/v1/score", ...)
    return result.json()
except Exception:
    return {"score": 0.0, "decision": "pass", "error": "ml_unavailable"}
# Hub ไม่ crash ถ้า ML down
```

## Critical Bugs

| Bug | อาการ | กฎ |
|-----|------|-----|
| B26 | cold-start → score สูง/ไม่เสถียร | ใช้ MIN_HISTORY=5, neutral=0.0 |
| B27 | feature count mismatch → crash | เปลี่ยน feature → regenerate + retrain |

## Common Tasks

**Test score endpoint**:
```bash
curl -X POST http://localhost:9000/v1/score \
  -H "Content-Type: application/json" \
  -d '{"features": [14, 2, 0, 0.5, 1, 0, 0, 0, 0, 4.5, 1, 0]}'
```

**Check model loaded**:
```bash
curl http://localhost:9000/health
# → {"model_loaded": true}
```
