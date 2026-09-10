"""Expert Label Workflow — ส่วนที่เป็นฟังก์ชันล้วน (ไม่แตะฐานข้อมูล).

แบบที่ล็อกไว้: docs/design/EXPERT_LABEL_WORKFLOW.md
  * จัดกลุ่ม (user_id, primary_signal, หน้าต่าง 30 นาที) แบบ deterministic
  * provenance แยก demo / test / local / external / unknown
  * รอบแรก blind — คะแนน คำตัดสิน และหลักฐานของโมเดลต้องไม่หลุดออกไป
  * กติกาตัดสินเมื่อผู้ตรวจเห็นต่าง + Cohen's kappa
  * ยังไม่คำนวณ production FPR จนผ่านเกณฑ์ขั้นต่ำ

รัน:
  docker compose exec hub-backend pytest tests/test_expert_review_units.py -v
"""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from app.services.expert_review import grouping as G
from app.services.expert_review import metrics as MT
from app.services.expert_review import provenance as PV
from app.services.expert_review import views as V
from app.services.expert_review import vocab as VOC


# ─────────────────────────────────────────────────────────────
# Provenance
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ip, ua, expected",
    [
        ("8.8.8.8", "Mozilla/5.0 RiskDemo/1.0", "demo"),
        ("192.0.2.10", "Mozilla/5.0", "demo"),
        ("198.51.100.7", "Mozilla/5.0", "demo"),
        ("203.0.113.57", "Mozilla/5.0", "demo"),
        ("172.18.0.9", "pytest-incident-highscore", "test"),
        ("8.8.8.8", "testclient", "test"),
        ("127.0.0.1", "Mozilla/5.0", "local"),
        ("::1", "Mozilla/5.0", "local"),
        ("172.18.0.1", "Mozilla/5.0", "local"),
        ("10.1.2.3", "Mozilla/5.0", "local"),
        ("192.168.1.10", "Mozilla/5.0", "local"),
        ("fe80::1", "Mozilla/5.0", "local"),
        ("8.8.8.8", "Mozilla/5.0", "external"),
        (None, "Mozilla/5.0", "unknown"),
        ("", "Mozilla/5.0", "unknown"),
        ("not-an-ip", "Mozilla/5.0", "unknown"),
    ],
)
def test_provenance_classify(ip, ua, expected):
    assert PV.classify(ip, ua) == expected


def test_provenance_172_prefix_is_not_blanket_local():
    """สคริปต์เทียบ distribution เคยใช้ prefix `172.1` ซึ่งกิน 172.100.x ไปด้วย."""
    assert PV.classify("172.100.1.1", "Mozilla/5.0") == "external"


@pytest.mark.parametrize(
    "prov, cfg, commit, expected",
    [
        ("external", "config-b-shadow-v1", "abc123", True),
        ("external", None, "abc123", False),
        ("external", "config-b-shadow-v1", None, False),
        ("local", "config-b-shadow-v1", "abc123", False),
        ("demo", "config-b-shadow-v1", "abc123", False),
        ("test", "config-b-shadow-v1", "abc123", False),
        ("unknown", "config-b-shadow-v1", "abc123", False),
    ],
)
def test_eligible_only_external_with_config_and_commit(prov, cfg, commit, expected):
    assert PV.is_eligible(prov, cfg, commit) is expected


# ─────────────────────────────────────────────────────────────
# Grouping
# ─────────────────────────────────────────────────────────────

REASONS = [
    "hours_diff=12.0 >= 10 (+0.40)",
    "login_count_24h (+0.2)",
    "concurrent_session_count=7 -> challenge",
    "signature_rarity=0.94 (device เคยใช้นานๆ ที, +0.15)",
    "ข้อความภาษาไทยล้วน",
]


def test_constants_locked():
    assert G.WINDOW_MINUTES == 30
    assert G.DOUBLE_REVIEW_PERCENT == 30


def test_reason_codes_strip_values_and_sort():
    assert G.reason_codes(REASONS) == [
        "concurrent_session_count",
        "hours_diff",
        "login_count_24h",
        "signature_rarity",
    ]


def test_primary_signal_uses_layer_and_first_sorted_code():
    assert G.primary_signal({"primary_layer": "rule"}, REASONS) == (
        "rule:concurrent_session_count"
    )


def test_primary_signal_ignores_numeric_values():
    a = G.primary_signal({"primary_layer": "rule"}, ["concurrent_session_count=7"])
    b = G.primary_signal({"primary_layer": "rule"}, ["concurrent_session_count=3"])
    assert a == b


def test_primary_signal_fallbacks():
    assert G.primary_signal(None, None) == "none:none"
    assert G.primary_signal({"primary_layer": None}, []) == "none:none"


@pytest.mark.parametrize(
    "ts, expected",
    [
        (datetime(2026, 9, 9, 14, 0, 0), datetime(2026, 9, 9, 14, 0)),
        (datetime(2026, 9, 9, 14, 29, 59), datetime(2026, 9, 9, 14, 0)),
        (datetime(2026, 9, 9, 14, 30, 0), datetime(2026, 9, 9, 14, 30)),
        (datetime(2026, 9, 9, 23, 59, 59), datetime(2026, 9, 9, 23, 30)),
    ],
)
def test_window_start_floors_to_30_minutes(ts, expected):
    assert G.window_start(ts) == expected


def test_group_key_format():
    uid = uuid.UUID("11111111-2222-3333-4444-555555555555")
    key = G.group_key(uid, "rule:hours_diff", datetime(2026, 9, 9, 14, 0))
    assert key == (
        "user:11111111-2222-3333-4444-555555555555"
        "|sig:rule:hours_diff|w:2026-09-09T14:00:00"
    )


@pytest.mark.parametrize(
    "decision, expected",
    [
        ("would_warn", True),
        ("would_challenge", True),
        ("would_block", True),
        ("would_mfa", True),
        ("allow", False),
        ("warn", False),
        ("challenge", False),
        ("block", False),
        (None, False),
    ],
)
def test_only_shadow_decisions_are_alerts(decision, expected):
    assert G.is_alert(decision) is expected


@dataclass
class _S:
    user_id: uuid.UUID
    created_at: datetime
    decision: str
    risk_breakdown: dict | None = None
    risk_reasons: list | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


def _fixture_sessions() -> list[_S]:
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    base = datetime(2026, 9, 9, 14, 0)
    rule = {"primary_layer": "rule"}
    beh = {"primary_layer": "behavior"}
    return [
        _S(u1, base + timedelta(minutes=3), "would_challenge", rule, ["hours_diff=12"]),
        _S(u1, base + timedelta(minutes=9), "would_warn", rule, ["hours_diff=11"]),
        _S(u1, base + timedelta(minutes=29), "would_block", rule, ["hours_diff=9"]),
        _S(u1, base + timedelta(minutes=31), "would_warn", rule, ["hours_diff=9"]),
        _S(u1, base + timedelta(minutes=5), "would_warn", beh, ["hours_diff=9"]),
        _S(u2, base + timedelta(minutes=4), "would_warn", rule, ["hours_diff=12"]),
        _S(u1, base + timedelta(minutes=6), "allow", rule, ["hours_diff=12"]),
        _S(u1, base + timedelta(minutes=7), "challenge", rule, ["hours_diff=12"]),
    ]


def test_build_groups_splits_by_user_signal_and_window():
    groups = G.build_groups(_fixture_sessions())
    sizes = sorted(g.n_events for g in groups)
    # u1 rule 14:00 (3) · u1 rule 14:30 (1) · u1 behavior 14:00 (1) · u2 rule 14:00 (1)
    assert sizes == [1, 1, 1, 3]


def test_build_groups_every_alert_in_exactly_one_group():
    sessions = _fixture_sessions()
    groups = G.build_groups(sessions)
    alert_ids = {s.id for s in sessions if G.is_alert(s.decision)}
    grouped = [sid for g in groups for sid in g.session_ids]
    assert len(grouped) == len(set(grouped))
    assert set(grouped) == alert_ids


def test_build_groups_order_independent():
    sessions = _fixture_sessions()
    a = G.build_groups(sessions)
    shuffled = list(sessions)
    random.Random(7).shuffle(shuffled)
    b = G.build_groups(shuffled)
    assert [g.__dict__ for g in a] == [g.__dict__ for g in b]


def test_build_groups_records_first_and_last_seen():
    groups = G.build_groups(_fixture_sessions())
    big = next(g for g in groups if g.n_events == 3)
    assert big.first_seen_at == datetime(2026, 9, 9, 14, 3)
    assert big.last_seen_at == datetime(2026, 9, 9, 14, 29)
    assert big.window_start == datetime(2026, 9, 9, 14, 0)
    assert big.primary_signal == "rule:hours_diff"


def test_double_review_pool_deterministic_and_about_30_percent():
    keys = [
        f"user:{uuid.UUID(int=i)}|sig:rule:x|w:2026-09-09T14:00:00" for i in range(3000)
    ]
    assert all(
        G.in_double_review_pool(k) == G.in_double_review_pool(k) for k in keys[:50]
    )
    share = sum(G.in_double_review_pool(k) for k in keys) / len(keys)
    assert 0.26 <= share <= 0.34


# ─────────────────────────────────────────────────────────────
# Vocabulary (รายการปิด)
# ─────────────────────────────────────────────────────────────


def test_verdicts_and_confidence_closed():
    assert VOC.VERDICTS == frozenset(
        {"benign", "suspicious", "confirmed_attack", "insufficient_context"}
    )
    assert VOC.CONFIDENCE == frozenset({"low", "medium", "high"})


def test_reason_codes_closed_list_from_design():
    assert VOC.REASON_CODES == frozenset(
        {
            "expected_new_device",
            "expected_new_location",
            "legitimate_subsystem_use",
            "known_travel",
            "shared_workstation",
            "routine_off_hours",
            "impossible_travel",
            "credential_abuse",
            "unusual_sequence",
            "unexpected_privilege_use",
            "velocity_anomaly",
            "device_farm_pattern",
            "no_user_history",
            "ambiguous_context",
            "missing_geo",
        }
    )


def test_verdict_vocab_does_not_reference_model_output():
    """label ต้องตอบได้โดยไม่รู้ว่าโมเดลตัดสินอะไร (จุดอ่อนของ ml_feedback)."""
    for v in VOC.VERDICTS:
        assert "positive" not in v and "negative" not in v


# ─────────────────────────────────────────────────────────────
# Consolidation (§5.2)
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "verdicts, label, status, fpr_eligible",
    [
        ([], None, "unlabeled", False),
        (["benign"], "benign", "single", True),
        (["benign", "benign"], "benign", "agreed", True),
        (["suspicious", "confirmed_attack"], "suspicious", "conservative", True),
        (["benign", "confirmed_attack"], None, "needs_adjudication", False),
        (["benign", "suspicious", "benign"], "benign", "adjudicated", True),
        (["benign", "suspicious", "suspicious"], "suspicious", "adjudicated", True),
        (
            ["benign", "insufficient_context"],
            "insufficient_context",
            "excluded_insufficient",
            False,
        ),
        (
            ["insufficient_context"],
            "insufficient_context",
            "excluded_insufficient",
            False,
        ),
    ],
)
def test_consolidate(verdicts, label, status, fpr_eligible):
    out = MT.consolidate(verdicts)
    assert out == {"label": label, "status": status, "fpr_eligible": fpr_eligible}


# ─────────────────────────────────────────────────────────────
# Cohen's kappa
# ─────────────────────────────────────────────────────────────


def test_kappa_perfect_agreement():
    pairs = [("benign", "benign"), ("suspicious", "suspicious")] * 5
    assert MT.cohen_kappa(pairs) == pytest.approx(1.0)


def test_kappa_known_value():
    a = ["benign"] * 5 + ["suspicious"] * 5
    b = ["benign"] * 4 + ["suspicious"] * 5 + ["benign"]
    # po = 0.8 · pe = 0.5 -> kappa = 0.6
    assert MT.cohen_kappa(list(zip(a, b))) == pytest.approx(0.6)


def test_kappa_undefined_cases():
    assert MT.cohen_kappa([]) is None
    assert MT.cohen_kappa([("benign", "benign")] * 10) is None


def test_kappa_ci_deterministic():
    a = ["benign"] * 5 + ["suspicious"] * 5
    b = ["benign"] * 4 + ["suspicious"] * 5 + ["benign"]
    pairs = list(zip(a, b))
    r1 = MT.kappa_with_ci(pairs, n_boot=500, seed=3)
    r2 = MT.kappa_with_ci(pairs, n_boot=500, seed=3)
    assert r1 == r2
    assert r1["n"] == 10
    assert r1["kappa"] == pytest.approx(0.6)
    assert r1["ci_low"] <= r1["kappa"] <= r1["ci_high"]


# ─────────────────────────────────────────────────────────────
# Readiness gate — production FPR ยังไม่คำนวณจนผ่านทุกข้อ
# ─────────────────────────────────────────────────────────────


def test_readiness_thresholds_locked():
    assert MT.MIN_EXTERNAL_USERS == 20
    assert MT.MAX_USER_SHARE == 0.40
    assert MT.MIN_LABELED_GROUPS == 100
    assert MT.MIN_DOUBLE_REVIEWED == 30
    assert MT.MIN_REVIEWERS == 2


def test_readiness_boundaries_inclusive():
    r = MT.readiness(
        n_external_users=20,
        max_user_share=0.40,
        n_labeled_groups=100,
        n_double_reviewed=30,
        n_reviewers=2,
    )
    assert r == {"ready": True, "unmet": []}


@pytest.mark.parametrize(
    "override, name",
    [
        ({"n_external_users": 19}, "external_users"),
        ({"max_user_share": 0.41}, "user_concentration"),
        ({"n_labeled_groups": 99}, "labeled_groups"),
        ({"n_double_reviewed": 29}, "double_reviewed"),
        ({"n_reviewers": 1}, "reviewers"),
    ],
)
def test_readiness_each_gate(override, name):
    kw = dict(
        n_external_users=20,
        max_user_share=0.40,
        n_labeled_groups=100,
        n_double_reviewed=30,
        n_reviewers=2,
    )
    kw.update(override)
    r = MT.readiness(**kw)
    assert r["ready"] is False
    assert r["unmet"] == [name]


# ─────────────────────────────────────────────────────────────
# Blind view (§2.1)
# ─────────────────────────────────────────────────────────────

_FORBIDDEN_KEYS = {
    "risk_score",
    "decision",
    "risk_breakdown",
    "risk_reasons",
    "anomaly_score",
    "primary_signal",
    "primary_layer",
    "system_disposition",
    "model_output",
    "evidence",
    "thresholds",
    "final_risk_score",
    "group_key",
    "is_account_takeover",
    "is_attack_ip",
}


def _all_keys(obj) -> set[str]:
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            out |= _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _all_keys(v)
    return out


RAW_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def _event(**kw) -> dict:
    d = dict(
        id=uuid.uuid4(),
        created_at=datetime(2026, 9, 9, 14, 3),
        ip="203.0.113.57",
        user_agent=RAW_UA,
        device_type="desktop",
        os_name="Windows 10",
        browser="Chrome 128.0.0",
        geo_country="TH",
        subsystem_id=None,
        decision="would_challenge",
        risk_score=0.996,
        anomaly_score=0.81,
        risk_breakdown={"primary_layer": "rule", "final_risk_score": 0.9955},
        risk_reasons=[
            "concurrent_session_count=7 -> challenge",
            "hours_diff=12 (+0.40)",
        ],
        is_account_takeover=False,
        is_attack_ip=False,
    )
    d.update(kw)
    return d


def _history(n: int, **kw) -> list[dict]:
    base = datetime(2026, 8, 1, 2, 0)
    return [_event(created_at=base + timedelta(days=i), **kw) for i in range(n)]


def _blind(events, history):
    uid = uuid.UUID("11111111-2222-3333-4444-555555555555")
    group = {
        "id": uuid.uuid4(),
        "user_id": uid,
        "group_key": G.group_key(
            uid, "rule:concurrent_session_count", datetime(2026, 9, 9, 14)
        ),
        "primary_signal": "rule:concurrent_session_count",
        "n_events": len(events),
        "first_seen_at": events[0]["created_at"],
        "last_seen_at": events[-1]["created_at"],
    }
    return V.blind_payload(group, events, history, subsystem_names={})


def test_blind_payload_has_no_model_keys():
    payload = _blind([_event()], _history(10, os_name="macOS 14", browser="Safari 17"))
    leaked = _all_keys(payload) & _FORBIDDEN_KEYS
    assert leaked == set()


def test_blind_payload_has_no_model_strings_or_raw_identifiers():
    payload = _blind([_event()], _history(10, os_name="macOS 14", browser="Safari 17"))
    text = json.dumps(payload, default=str, ensure_ascii=False)
    for needle in (
        "would_",
        "0.9955",
        "0.996",
        "(+0.",
        "-> challenge",
        "evidence",
        "threshold",
        "concurrent_session_count",
        "11111111-2222-3333-4444-555555555555",
        "203.0.113.57",
        RAW_UA,
        "rule:",
    ):
        assert needle not in text, needle


def test_blind_payload_shows_alias_and_masked_ip():
    payload = _blind([_event()], _history(10))
    assert payload["user_alias"].startswith("U-")
    assert payload["events"][0]["ip_masked"] == "203.0.113.x"
    assert payload["events"][0]["browser_family"] == "Chrome"


def test_descriptive_signal_new_device():
    unseen = _blind([_event()], _history(10, os_name="macOS 14", browser="Safari 17"))
    seen = _blind([_event()], _history(10))
    codes_unseen = {s["code"] for s in unseen["events"][0]["observations"]}
    codes_seen = {s["code"] for s in seen["events"][0]["observations"]}
    assert "device_not_seen_90d" in codes_unseen
    assert "device_not_seen_90d" not in codes_seen


def test_descriptive_signal_no_history():
    payload = _blind([_event()], [])
    codes = {s["code"] for s in payload["events"][0]["observations"]}
    assert "no_history_90d" in codes
    assert payload["history_90d"]["n_logins"] == 0


def test_hour_offset_needs_min_history():
    """cold start — ไม่คำนวณระยะห่างจากเวลาปกติเมื่อประวัติน้อยกว่า 5 ครั้ง."""
    few = _blind([_event()], _history(4))
    enough = _blind([_event()], _history(5))
    assert not any(
        s["code"] == "hour_far_from_usual" for s in few["events"][0]["observations"]
    )
    assert any(
        s["code"] == "hour_far_from_usual" for s in enough["events"][0]["observations"]
    )


@pytest.mark.parametrize(
    "ip, expected",
    [
        ("203.0.113.57", "203.0.113.x"),
        ("2001:db8:1:2::5", "2001:db8:1::x"),
        (None, None),
        ("", None),
    ],
)
def test_mask_ip(ip, expected):
    assert V.mask_ip(ip) == expected


def test_alias_deterministic_and_opaque():
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    assert V.alias(u1) == V.alias(u1)
    assert V.alias(u1) != V.alias(u2)
    assert str(u1) not in V.alias(u1)
