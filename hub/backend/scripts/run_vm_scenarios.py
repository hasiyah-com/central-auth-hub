"""รันสถานการณ์ทดสอบใน VM ผ่านเส้นทาง login จริง แล้วเก็บหลักฐาน (ระยะที่ 7).

แต่ละ event เรียก `passkey._build_login_session` **ตัวที่ production เรียก** (B66) — ต่างเพียง:
  * `extract_session_features` คืนเวกเตอร์ปกติจริงของผู้ใช้ทดสอบ แล้วทับด้วยค่าของสถานการณ์
  * `maybe_alert_ml_risk` ถูกปิด — ห้ามส่ง Telegram/อีเมลออกนอกระหว่างทดสอบ

L1–L4, ml-service (L3) และแถว `login_sessions` เป็นของจริงทั้งหมด จึงเห็นบน Security Dashboard

**ขอบเขต:** stack ในเครื่อง (APP_ENV=development) กับบัญชีทดสอบ `vm-*@example.test` เท่านั้น ·
IP เป็น private (10.99.x.x) จึงไม่มี geo lookup ภายนอก · label มาจากการสร้าง ไม่ใช่การโจมตีจริง

    docker compose exec hub-backend python -m scripts.run_vm_scenarios --out /app/tests/reports/vm_evidence.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.routers import passkey as PK
from app.security.rule_engine import FEAT
from scripts import vm_scenarios as VS

VM_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 VM-SCENARIO"
)
LOGIN_METHOD = "vm_scenario"


def assert_local_stack() -> None:
    """ปฏิเสธถ้าไม่ใช่ stack พัฒนาในเครื่อง — กันการยิงสถานการณ์ใส่ระบบจริง."""
    if (settings.app_env or "").lower() != "development":
        raise SystemExit(f"ปฏิเสธ: APP_ENV={settings.app_env!r} (ต้องเป็น development)")
    url = settings.database_url
    url = url.get_secret_value() if hasattr(url, "get_secret_value") else str(url)
    host = url.split("@")[-1].split("/")[0].split(":")[0]
    if host not in ("postgres", "localhost", "127.0.0.1", "hub-postgres"):
        raise SystemExit(f"ปฏิเสธ: ฐานข้อมูลไม่ใช่ของ stack ในเครื่อง ({host})")


def user_type_of(alias: str) -> str:
    for t in ("student", "teacher", "staff"):
        if f"-{t}-" in alias:
            return t
    raise ValueError(f"บอก user_type จาก {alias} ไม่ได้")


def ensure_user(db, alias: str) -> User:
    email = VS.test_email(alias)
    u = db.query(User).filter(User.email == email).first()
    if u is None:
        u = User(
            email=email,
            full_name=f"VM Test {alias}",
            user_type=user_type_of(alias),
            identifier=alias,
            status="active",
            is_hub_admin=False,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
    return u


class _Request:
    def __init__(self, ip: str):
        self.headers = {"user-agent": VM_UA, "x-forwarded-for": ip}
        self.client = SimpleNamespace(host=ip)


def _summary(scen: VS.Scenario, ev: VS.Event, sess) -> dict:
    bd = sess.risk_breakdown or {}
    decision = (sess.decision or "allow").removeprefix("would_")
    return {
        "scenario_id": scen.scenario_id,
        "label": scen.label,
        "attack_family": scen.attack_family,
        "severity": scen.severity,
        "user": scen.user_id,
        "subsystem": scen.subsystem_id,
        "scenario_time": ev.at.isoformat(),
        "features_changed": ev.features,
        "session_id": str(sess.id),
        "recorded_at": sess.created_at.isoformat() if sess.created_at else None,
        "actual_decision": sess.decision,
        "risk_score": sess.risk_score,
        "l1_rule": bd.get("rule"),
        "l2_behavior": bd.get("behavior"),
        "l3_anomaly": bd.get("iforest"),
        "l3_eligibility": (bd.get("l3") or {}).get("eligibility"),
        "l3_abstain_reason": (bd.get("l3") or {}).get("abstain_reason"),
        "baseline_shadow": bd.get("baseline_shadow"),
        "hybrid_shadow": bd.get("hybrid_shadow"),
        "conditional_shadow": bd.get("conditional_shadow"),
        "reasons": list(sess.risk_reasons or [])[:8],
        "shap_top": list(bd.get("iforest_explanation") or [])[:5],
        "expected_min": scen.expected_minimum_action,
        "expected_max": scen.expected_maximum_action,
        "decision_rank": VS.rank(decision) if decision in VS.ACTIONS else None,
    }


def meets_expectation(s: dict) -> bool:
    r = s["decision_rank"]
    if r is None:
        return False
    if r < VS.rank(s["expected_min"]):
        return False
    return s["expected_max"] is None or r <= VS.rank(s["expected_max"])


async def run_event(db, scen: VS.Scenario, ev: VS.Event, n: int) -> dict:
    user = ensure_user(db, scen.user_id)
    real_extract = PK.extract_session_features

    def scenario_features(db_, **kw):
        vec = list(real_extract(db_, **kw))
        for name, value in ev.features.items():
            vec[FEAT[name]] = float(value)
        return vec

    result = SimpleNamespace(user=user, counter_regression=False)
    with (
        mock.patch.object(PK, "extract_session_features", scenario_features),
        mock.patch.object(PK, "maybe_alert_ml_risk", lambda **_: None),
    ):
        sess = await PK._build_login_session(
            result,
            _Request(f"10.99.0.{n % 250 + 1}"),
            str(uuid.uuid4()),
            db,
            LOGIN_METHOD,
        )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return _summary(scen, ev, sess)


def reset_test_users(db) -> dict:
    """ลบ session และบัญชีทดสอบ `vm-*@example.test` — สาธิตซ้ำแล้วได้ผลเดิม.

    feature หลายตัวอิงประวัติของผู้ใช้ (login_count_24h, log_minutes_since_last_login, is_new_device)
    รันสองรอบติดโดยไม่ล้างจึงได้คนละผล — เจอจริงตอนสาธิตรอบแรก 2026-09-23
    แตะเฉพาะบัญชีทดสอบที่สคริปต์นี้สร้างเองเท่านั้น
    """
    from app.models import LoginSession

    users = db.query(User).filter(User.email.like("vm-%@" + VS.TEST_DOMAIN)).all()
    n_sessions = 0
    for u in users:
        n_sessions += (
            db.query(LoginSession).filter(LoginSession.user_id == u.id).delete()
        )
        db.delete(u)
    db.commit()
    return {"users": len(users), "sessions": n_sessions}


async def run(out_path: str | None, reset: bool = False) -> int:
    assert_local_stack()
    catalog = VS.load_catalog()
    db = SessionLocal()
    if reset:
        print(f"ล้างข้อมูลบัญชีทดสอบก่อนเริ่ม: {reset_test_users(db)}", flush=True)
    results = []
    try:
        n = 0
        for scen in catalog:
            for ev in scen.events:
                n += 1
                s = await run_event(db, scen, ev, n)
                s["meets_expectation"] = meets_expectation(s)
                results.append(s)
                print(
                    f"{s['scenario_id']:<7} {s['attack_family']:<22} actual={s['actual_decision']:<14} "
                    f"hybrid={(s['hybrid_shadow'] or {}).get('decision')!s:<16} "
                    f"cond={(s['conditional_shadow'] or {}).get('decision')!s:<16} "
                    f"expected>={s['expected_min']} {'ok' if s['meets_expectation'] else 'FINDING'}",
                    flush=True,
                )
    finally:
        db.close()
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "l3_mode": settings.l3_mode,
        "conditional_params": settings.l3_conditional_params or None,
        "note": "labeled by construction · stack ในเครื่อง · บัญชีทดสอบ vm-*@example.test",
        "results": results,
    }
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nเขียน {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument(
        "--reset", action="store_true", help="ล้าง session/บัญชีทดสอบก่อน เพื่อให้ผลทำซ้ำได้"
    )
    args = ap.parse_args()
    return asyncio.run(run(args.out, reset=args.reset))


if __name__ == "__main__":
    raise SystemExit(main())
