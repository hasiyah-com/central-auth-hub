"""สร้าง golden ของกฎ ณ freeze 2026-08-29 สำหรับตรวจ mode='legacy_replay' (ไม่ต้องใช้ DB).

ใช้ซอร์สของ rule_engine จาก tag โดยตรง (ไม่ใช่โค้ดปัจจุบัน):

    git show rba-freeze-2026-08-29:hub/backend/app/security/rule_engine.py > /tmp/frozen_rule_engine.py
    PYTHONPATH=. python scripts/make_rule_engine_legacy_golden_2026-09-26.py /tmp/frozen_rule_engine.py

เวกเตอร์สุ่มด้วยเมล็ดคงที่จากชุดค่าที่ทำให้กฎทุกข้อยิง/ไม่ยิง · db=None ip=None geo=None
(กฎที่ต้องใช้ DB/IP/geo ไม่ถูกเรียกในโหมดนี้)
"""

import hashlib
import importlib.util
import json
import random
import sys
from pathlib import Path

OUT = (
    Path(__file__).resolve().parents[1]
    / "tests/data/rule_engine_legacy_golden_2026-08-29.json"
)
SEED = 20260926
N_RANDOM = 600

VALUES = {
    "is_new_device": [0.0, 1.0],
    "is_new_user_agent_family": [0.0, 1.0],
    "is_new_country": [0.0, 1.0],
    "is_thailand": [0.0, 1.0],
    "impossible_travel_score": [0.0, 0.4, 0.5, 1.0],
    "failed_logins_24h": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 9.0, 10.0, 12.0, 30.0],
    "login_count_24h": [0.0, 4.0, 5.0, 14.0, 15.0, 49.0, 50.0, 80.0],
    "log_minutes_since_last_login": [0.5, 2.0, 2.5, 6.0],
    "country_change_count_30d": [0.0, 1.0, 7.0, 8.0],
    "concurrent_session_count": [0.0, 2.0, 3.0],
    "active_subsystem_count": [0.0, 1.0, 2.0],
    "new_passkey_recently_added": [0.0, 1.0],
    "permission_change_age": [0.0, 1.0, 2.0, 7.0, 8.0, 9999.0],
    "confirmed_incident_count": [0.0, 1.0],
}


def main(frozen_path: str) -> None:
    spec = importlib.util.spec_from_file_location("frozen_rule_engine", frozen_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    feat = mod.FEAT
    dim = max(feat.values()) + 1
    rng = random.Random(SEED)

    def vec(over):
        v = [0.0] * dim
        v[feat["is_thailand"]] = 1.0
        v[feat["permission_change_age"]] = 9999.0
        v[feat["log_minutes_since_last_login"]] = 6.0
        for k, x in over.items():
            v[feat[k]] = x
        return v

    vectors = [vec({"failed_logins_24h": f}) for f in VALUES["failed_logins_24h"]]
    for _ in range(N_RANDOM):
        vectors.append(vec({k: rng.choice(vs) for k, vs in VALUES.items()}))

    cases = []
    for v in vectors:
        r = mod.evaluate_rules(v, None, "u", None, None)
        cases.append(
            {
                "features": v,
                "blocked": r.blocked,
                "score": r.score,
                "reasons": r.reasons,
                "min_action": r.min_action,
            }
        )
    src = Path(frozen_path).read_bytes()
    OUT.write_text(
        json.dumps(
            {
                "source": "rba-freeze-2026-08-29:hub/backend/app/security/rule_engine.py",
                "seed": SEED,
                "cases": cases,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    # sha ของซอร์สพิมพ์ไว้บันทึกในรายงาน (ไม่เก็บใน JSON — detect-secrets มองเป็น hex entropy)
    print(
        len(cases), "cases ->", OUT, "source sha256:", hashlib.sha256(src).hexdigest()
    )


if __name__ == "__main__":
    main(sys.argv[1])
