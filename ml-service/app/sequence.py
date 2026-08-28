"""L3 sequence channel — numeric core (per-user IsolationForest บน residual window).

ย้ายมาจาก hub-backend เพราะ **hub-backend image ไม่มี numpy/sklearn โดยตั้งใจ**
(แยก ML ออกเป็น container ของตัวเองตั้งแต่ Week 5 — เหมือน IForest 23 ฟีเจอร์ที่อยู่ที่นี่แล้ว)

การแบ่งหน้าที่:
    hub-backend : residual_raw() · apply_channel() · to_contract() · record_residual()
                  (pure python — ไม่ต้องใช้ numpy)
    ml-service  : fit / score / model cache  <- ไฟล์นี้
                  อ่าน history จาก Redis เอง (อยู่ compose network เดียวกัน)

ค่าคงที่ในไฟล์นี้ต้องตรงกับ `hub/backend/app/security/l3_sequence.py` เสมอ
(DIMS, WINDOW, MAX_HISTORY, CAL_FPR, EXTREME_FPR, TIER_*, MODEL_VERSION) —
มี `hub/backend/tests/test_l3_sequence_client.py::test_constants_parity_hub_vs_ml_service`
กันไว้ ต่างกันเมื่อไหร่ = คนละโมเดลโดยไม่รู้ตัว (บทเรียนเดียวกับ B49)

Config ที่ล็อกจากการทดลอง (hub/backend/tests/reports/exp_final_gate_2026-08-26.md):
    residual 6 มิติ x [mean, slope, ptp] · W=5 · threshold p99.9 · abstention tiers
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)

DIMS = 6  # [gap_log, scope, passkey_age_log, weekday_usage, hours_from_typical, sub_rarity]
WINDOW = 5
MAX_HISTORY = 2000
CAL_FPR = 0.001  # p99.9 — จุดเดียวบน holdout ที่ FPR <= 1% (วัดจริง 0.79%)
EXTREME_FPR = 0.0003
MODEL_VERSION = "iforest-l3-seq-v1"

TIER_DIAGNOSTIC = 100  # 100-999: ให้คะแนน+log แต่ห้ามเปลี่ยน decision
TIER_WARN = 1000  # 1000+: ยก warn ได้จริง
TIER_CHALLENGE = 2000  # 2000+: บันทึก would_challenge (shadow)

REDIS_KEY = "l3resid:{user_id}"
CACHE_TTL_SEC = 3600
# user -> (ts, n_raw ตอน fit, model, n_parsed)
_MODEL_CACHE: dict[str, tuple[float, int, Any, int]] = {}
_LOCKS: dict[str, threading.Lock] = {}  # fit ครั้งเดียวต่อคน (B63)
_LOCKS_GUARD = threading.Lock()

QUIET = {
    "fired": False,
    "score": 0.0,
    "raw_score": 0.0,
    "percentile": 0.0,
    "tier": "none",
    "eligibility": "abstain",
    "shadow_decision": None,
    "n_history": 0,
    "model_version": MODEL_VERSION,
}


def eligibility(n_history: int) -> str:
    """L3 ได้รับอนุญาตให้ทำอะไรบ้าง ตามปริมาณ history ของผู้ใช้คนนี้."""
    if n_history >= TIER_CHALLENGE:
        return "challenge"
    if n_history >= TIER_WARN:
        return "warn"
    if n_history >= TIER_DIAGNOSTIC:
        return "diagnostic"
    return "abstain"


@dataclass
class L3Model:
    forest: Any
    keep: Any
    threshold: float
    scale: float
    n_history: int
    extreme_threshold: float = 0.0
    dist: Any = None
    base: list[tuple[float, float]] = field(default_factory=list)


def _center_scale(col) -> tuple[float, float]:
    med = float(np.median(col))
    iqr = float(np.quantile(col, 0.75) - np.quantile(col, 0.25))
    return med, max(iqr, 1e-6)


def _to_residual(raw, base: list[tuple[float, float]]):
    """z-score รายมิติ เทียบ median/IQR ของ "คนนี้" (robust กว่า mean/std)."""
    out = np.empty_like(raw)
    for j, (med, scale) in enumerate(base):
        out[:, j] = (raw[:, j] - med) / scale
    return out


def _windows(res):
    """rolling window -> 18 มิติ: [mean, slope(last-first), ptp] ต่อ residual dim.

    ใช้เฉพาะ window ที่เต็มความยาว WINDOW ทั้งตอน fit และตอน score —
    เคยผสม padded window เข้ามาตอน fit แล้ว FPR กระโดด 0.9% -> 5.8%
    """
    n = len(res)
    if n < WINDOW:
        return np.empty((0, DIMS * 3))
    out = np.empty((n - WINDOW + 1, DIMS * 3))
    for i in range(WINDOW - 1, n):
        w = res[i - WINDOW + 1 : i + 1]
        out[i - WINDOW + 1] = np.concatenate(
            [w.mean(axis=0), w[-1] - w[0], w.max(axis=0) - w.min(axis=0)]
        )
    return out


def fit_user_model(
    history_raw: list[list[float]], n_history: int | None = None
) -> L3Model | None:
    """เทรน IForest รายคนบน window ของ history (normal ล้วน). คืน None = abstain."""
    try:
        if not history_raw or len(history_raw) < TIER_DIAGNOSTIC:
            return None
        raw = np.asarray(history_raw[-MAX_HISTORY:], dtype=float)
        if raw.ndim != 2 or raw.shape[1] != DIMS or not np.isfinite(raw).all():
            return None
        base = [_center_scale(raw[:, j]) for j in range(DIMS)]
        X = _windows(_to_residual(raw, base))
        if len(X) < 20:
            return None
        keep = X.std(axis=0) > 1e-9
        if not keep.any():
            return None
        forest = IsolationForest(
            n_estimators=100, contamination=0.02, random_state=42
        ).fit(X[:, keep])
        a = -forest.score_samples(X[:, keep])
        thr = float(np.quantile(a, 1 - CAL_FPR))
        return L3Model(
            forest=forest,
            keep=keep,
            threshold=thr,
            scale=float(max(np.quantile(a, 0.999) - thr, 1e-6)),
            n_history=n_history if n_history is not None else len(raw),
            extreme_threshold=float(np.quantile(a, 1 - EXTREME_FPR)),
            dist=np.quantile(a, np.linspace(0.0, 1.0, 101)),
            base=base,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[sequence] fit error: %s", e)
        return None


def evaluate_window(model: L3Model | None, window_raw: list[list[float]]) -> dict:
    """ให้คะแนน window ล่าสุด (ยาว WINDOW, เก่า->ใหม่) — คืน dict พร้อมส่งเป็น JSON."""
    try:
        if model is None or not window_raw or len(window_raw) < WINDOW:
            return dict(QUIET)
        raw = np.asarray(window_raw[-WINDOW:], dtype=float)
        if raw.shape != (WINDOW, DIMS) or not np.isfinite(raw).all():
            return dict(QUIET)
        X = _windows(_to_residual(raw, model.base))
        if len(X) == 0:
            return dict(QUIET)
        a = float(-model.forest.score_samples(X[:, model.keep])[0])
        elig = eligibility(model.n_history)
        pct = (
            float(np.searchsorted(model.dist, a) / 100.0)
            if model.dist is not None
            else 0.0
        )
        pct = min(max(pct, 0.0), 1.0)
        out = {
            **QUIET,
            "raw_score": a,
            "percentile": pct,
            "eligibility": elig,
            "n_history": model.n_history,
        }
        if a < model.threshold:
            return out
        tier = "extreme" if a >= model.extreme_threshold else "anomaly"
        # shadow_decision = สิ่งที่ "จะทำ" ถ้าอนุญาตเต็มที่ (บันทึกไว้วิเคราะห์ ไม่ enforce)
        shadow = (
            "would_challenge"
            if (tier == "extreme" and elig == "challenge")
            else ("would_warn" if elig in ("warn", "challenge") else None)
        )
        return {
            **out,
            "fired": True,
            "score": float(np.clip((a - model.threshold) / model.scale, 0.0, 1.0)),
            "tier": tier,
            "shadow_decision": shadow,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("[sequence] evaluate error: %s", e)
        return dict(QUIET)


# ═══════════════ Redis adapter (อ่านอย่างเดียว — hub เป็นคนเขียน history) ═══════════════
def _parse_rows(raw) -> list[list[float]]:
    """แปลงแถวดิบเป็น residual — ข้ามแถวเสียเงียบๆ (history อาจมีขยะปน)."""
    out = []
    for item in raw:
        try:
            v = json.loads(item)
            if isinstance(v, list) and len(v) == DIMS:
                row = [float(x) for x in v]
                if all(math.isfinite(x) for x in row):
                    out.append(row)
        except Exception:  # noqa: BLE001,S112
            continue
    return out


def load_history(redis, user_id: str) -> list[list[float]]:
    """residual ดิบล่าสุดของผู้ใช้ (เก่า->ใหม่) — hub เขียนไว้ด้วย record_residual()."""
    return _parse_rows(
        redis.lrange(REDIS_KEY.format(user_id=user_id), -MAX_HISTORY, -1)
    )


def _load_tail(redis, key: str) -> list[list[float]] | None:
    """ดึงเฉพาะท้าย window (WINDOW-1 แถว) — ใช้เมื่อ cache อุ่นแล้ว.

    เหตุผลด้านความจุ (B63): ทาง warm ไม่ควรอ่าน+parse history 2000 แถวทุก request
    (วัดแล้วเป็นคอขวดจริงเมื่อมี request พร้อมกันหลายอัน จน L3 timeout ทั้งชุด)
    ดึงเผื่อ 4 เท่าเพื่อกันกรณีท้ายลิสต์มีแถวเสียปน · ไม่พอค่อย fallback ไปอ่านเต็ม
    """
    need = WINDOW - 1
    rows = _parse_rows(redis.lrange(key, -(WINDOW * 4), -1))
    return rows[-need:] if len(rows) >= need else None


def _cache_hit(user_id: str, n: int):
    """คืน entry ที่ยังใช้ได้ หรือ None — แยก "ไม่มี cache" ออกจาก "cache เป็น None" (abstain).

    ต้องเช็คขนาดทั้งสองทิศทาง: โต >=10% (มีข้อมูลใหม่พอให้โมเดลดีขึ้น) **และ** หด (B62) —
    history หดได้จาก Redis eviction / key ถูกลบ / รีเซ็ตผู้ใช้ ถ้าไม่ refit โมเดลเก่า
    จะค้างพร้อม n_history เดิมนานถึง 1 ชม. ซึ่ง n_history เป็นตัวกำหนด eligibility
    -> ผู้ใช้ที่ประวัติหายไปแล้วยังถูกตัดสินด้วย tier สูงเกินจริง
    """
    hit = _MODEL_CACHE.get(user_id)
    if hit and time.time() - hit[0] < CACHE_TTL_SEC and hit[1] <= n < hit[1] * 1.1:
        return hit
    return None


def _user_lock(user_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(user_id, threading.Lock())


def get_model(redis, user_id: str, key: str, n_raw: int) -> tuple[L3Model | None, int]:
    """โมเดลรายคนจาก cache — fit ครั้งเดียวต่อคนแม้มี request พร้อมกันหลายอัน (B63).

    fit ใช้เวลา ~270ms ที่ history 2000 แถว · uvicorn รัน endpoint แบบ sync ใน
    threadpool -> ถ้าไม่ล็อก request ที่มาพร้อมกัน N อันจะ fit ซ้ำ N ครั้ง กิน CPU
    จนเกิน timeout ของ login path (วัดได้จริง: 20 request พร้อมกัน -> timeout ทุกอัน)

    คืน (model, n_parsed) — n_parsed คือจำนวนแถวที่ใช้ได้จริง (ต่างจาก n_raw ถ้ามีขยะปน)
    """
    with _user_lock(user_id):
        hit = _cache_hit(user_id, n_raw)  # double-check: อาจมีคนอื่น fit เสร็จระหว่างรอ
        if hit is not None:
            return hit[2], hit[3]
        history = load_history(redis, user_id)
        model = fit_user_model(history, n_history=len(history))
        _MODEL_CACHE[user_id] = (time.time(), n_raw, model, len(history))
        return model, len(history)


def score(redis, user_id: str, residual: list[float]) -> dict:
    """จุดเข้าหลัก — ให้คะแนน window ที่จบด้วย residual นี้.

    residual ตัวปัจจุบัน **ยังไม่อยู่ใน history** (hub บันทึกหลังตัดสิน) จึงต่อท้ายเอง

    ทางเดินสองแบบ (B63):
      warm — cache อุ่น: llen (O(1)) + อ่านท้าย window ~20 แถว   -> ~2-5ms
      cold — cache miss: อ่าน+parse history เต็ม แล้ว fit         -> ~300ms (ล็อกต่อคน)
    """
    try:
        if (
            not residual
            or len(residual) != DIMS
            or not all(math.isfinite(x) for x in residual)
        ):
            return dict(QUIET)
        key = REDIS_KEY.format(user_id=user_id)
        n_raw = int(redis.llen(key) or 0)
        # ตัดจบเร็วสุดสำหรับผู้ใช้ใหม่ — parsed <= raw เสมอ จึง abstain แน่นอน
        if eligibility(n_raw) == "abstain":
            return {**QUIET, "eligibility": "abstain", "n_history": n_raw}

        hit = _cache_hit(user_id, n_raw)
        if hit is not None:
            model, n_parsed = hit[2], hit[3]
            tail = _load_tail(redis, key) if model is not None else None
        else:
            model, n_parsed = get_model(redis, user_id, key, n_raw)
            tail = None
        if model is None:
            return {
                **QUIET,
                "eligibility": eligibility(n_parsed),
                "n_history": n_parsed,
            }
        if tail is None:  # cold path หรือท้ายลิสต์มีแถวเสียจนไม่ครบ window
            tail = load_history(redis, user_id)[-(WINDOW - 1) :]
        return evaluate_window(model, tail + [list(residual)])
    except Exception as e:  # noqa: BLE001
        logger.warning("[sequence] score error: %s", e)
        return dict(QUIET)
