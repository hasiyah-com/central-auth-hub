"""Manual test driver — access_updated webhook (role/scope change → re-auth).

รัน: docker compose exec hub-backend python -m tests.manual_access_updated_driver

ทดสอบ:
  1. dispatcher send_access_updated — payload + event + signature ถูก (mock subsystem)
  2. notify_subsystem_after_apply — role change → ยิงให้ user เฉพาะคน;
     config edit (edit_scope) → ยิง hub_user_id=None (kick all)
  3. dorm receiver จริง — ยิง access_updated → mark hub_access_revoked_at

ใช้ subsystem จริง (dorm ถ้า up) + mock dispatch เพื่อตรวจ payload.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

from app.database import SessionLocal
from app.models import Subsystem
from app.services import change_request_service as crs

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    db = SessionLocal()
    sub = db.query(Subsystem).filter(Subsystem.status == "active").first()
    if not sub:
        print("ไม่พบ active subsystem")
        return 1
    print(f"\nsubsystem = {sub.name}\n")

    # ── Group 1: notify — role change → user เฉพาะคน ──
    print("── Group 1: notify_subsystem_after_apply — role change ──")
    calls: list[dict] = []

    def fake_send(subsystem, payload):
        calls.append(payload)
        return True

    with patch(
        "app.services.webhook_dispatcher.send_access_updated", side_effect=fake_send
    ):
        req = SimpleNamespace(request_type="change_whitelist_role")
        crs.notify_subsystem_after_apply(
            req, sub, {"user_id": "u-123", "new_role": "staff"}
        )
    check("T1.1 role change → ยิง 1 ครั้ง", len(calls) == 1, f"calls={len(calls)}")
    check(
        "T1.2 ยิงให้ user เฉพาะคน (hub_user_id=u-123)",
        calls and calls[0].get("hub_user_id") == "u-123",
        str(calls[0]) if calls else "none",
    )
    check(
        "T1.3 reason=role_changed + new_role",
        calls
        and calls[0].get("reason") == "role_changed"
        and calls[0].get("new_role") == "staff",
    )

    # ── Group 2: notify — bulk role change ──
    print("\n── Group 2: bulk role change → ยิงทุกคนที่เปลี่ยน ──")
    calls.clear()
    with patch(
        "app.services.webhook_dispatcher.send_access_updated", side_effect=fake_send
    ):
        req = SimpleNamespace(request_type="bulk_change_whitelist_roles")
        crs.notify_subsystem_after_apply(
            req,
            sub,
            {
                "changes": [
                    {"user_id": "u-1", "new_role": "staff"},
                    {"user_id": "u-2", "new_role": "member"},
                ]
            },
        )
    check("T2.1 bulk 2 คน → ยิง 2 ครั้ง", len(calls) == 2, f"calls={len(calls)}")
    check(
        "T2.2 ยิงแยกตาม user",
        {c["hub_user_id"] for c in calls} == {"u-1", "u-2"},
        str([c["hub_user_id"] for c in calls]),
    )

    # ── Group 3: notify — edit scope → kick ALL ──
    print("\n── Group 3: edit_scope → hub_user_id=None (kick ทุกคน) ──")
    calls.clear()
    with patch(
        "app.services.webhook_dispatcher.send_access_updated", side_effect=fake_send
    ):
        req = SimpleNamespace(request_type="edit_scope")
        crs.notify_subsystem_after_apply(req, sub, {"new_scope": ["email", "phone"]})
    check("T3.1 edit_scope → ยิง 1 ครั้ง", len(calls) == 1, f"calls={len(calls)}")
    check(
        "T3.2 hub_user_id=None (= kick ทุกคน)",
        calls and calls[0].get("hub_user_id") is None,
        str(calls[0]) if calls else "none",
    )
    check(
        "T3.3 reason=config_changed:edit_scope",
        calls and calls[0].get("reason") == "config_changed:edit_scope",
    )

    # ── Group 4: rotate_secret → ไม่ยิง ──
    print("\n── Group 4: rotate_secret → ไม่กระทบ session (ไม่ยิง) ──")
    calls.clear()
    with patch(
        "app.services.webhook_dispatcher.send_access_updated", side_effect=fake_send
    ):
        req = SimpleNamespace(request_type="rotate_secret")
        crs.notify_subsystem_after_apply(req, sub, {"client_id": sub.client_id})
    check("T4.1 rotate_secret → ไม่ยิง", len(calls) == 0, f"calls={len(calls)}")

    # ── Group 5: dispatcher payload shape (event + signing) ──
    print("\n── Group 5: send_access_updated payload + event ──")
    from app.services import webhook_dispatcher as wd

    sent: dict = {}

    class FakeResp:
        status_code = 200
        text = "ok"

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, content, headers):
            sent["url"] = url
            sent["headers"] = headers
            import json as _j

            sent["body"] = _j.loads(content)
            return FakeResp()

    with patch.object(wd, "httpx", SimpleNamespace(Client=FakeClient)):
        # ต้องมี webhook_shared_key + resolvable url
        with (
            patch.object(wd.settings, "webhook_shared_key", "testkey123"),
            patch.object(
                wd,
                "_resolve_webhook_url",
                return_value="http://sub/internal/access-updated",
            ),
        ):
            ok = wd.send_access_updated(
                sub, {"hub_user_id": "u-9", "reason": "role_changed"}
            )
    check("T5.1 ส่งสำเร็จ (200)", ok is True)
    check(
        "T5.2 event=access_updated",
        sent.get("body", {}).get("event") == "access_updated",
        str(sent.get("body")),
    )
    check(
        "T5.3 header X-Hub-Event",
        sent.get("headers", {}).get("X-Hub-Event") == "access_updated",
    )
    check("T5.4 มี signature header", "X-Hub-Signature-256" in sent.get("headers", {}))
    check(
        "T5.5 payload มี hub_user_id", sent.get("body", {}).get("hub_user_id") == "u-9"
    )

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'='*52}\nRESULT: {passed}/{total} passed\n{'='*52}")
    if passed < total:
        print("\nFAILED:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name} ({detail})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
