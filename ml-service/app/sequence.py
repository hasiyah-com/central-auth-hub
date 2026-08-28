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
_MODEL_CACHE: dict[str, tuple[float, int, Any]] = {}

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
def load_history(redis, user_id: str) -> list[list[float]]:
    """residual ดิบล่าสุดของผู้ใช้ (เก่า->ใหม่) — hub เขียนไว้ด้วย record_residual()."""
    raw = redis.lrange(REDIS_KEY.format(user_id=user_id), -MAX_HISTORY, -1)
    out = []
    for item in raw:
        try:
            v = json.loads(item)
            if isinstance(v, list) and len(v) == DIMS:
                out.append([float(x) for x in v])
        except Exception:  # noqa: BLE001,S112
            continue
    return out


def get_model(user_id: str, history: list[list[float]]) -> L3Model | None:
    """โมเดลรายคนจาก cache — refit เมื่อหมดอายุ หรือ history โต >10% (fit ~50-150ms)."""
    now = time.time()
    hit = _MODEL_CACHE.get(user_id)
    if hit and now - hit[0] < CACHE_TTL_SEC and len(history) < hit[1] * 1.1:
        return hit[2]
    model = fit_user_model(history, n_history=len(history))
    _MODEL_CACHE[user_id] = (now, len(history), model)
    return model


def score(redis, user_id: str, residual: list[float]) -> dict:
    """จุดเข้าหลัก — อ่าน history, fit/cache, ให้คะแนน window ที่จบด้วย residual นี้.

    residual ตัวปัจจุบัน **ยังไม่อยู่ใน history** (hub บันทึกหลังตัดสิน) จึงต่อท้ายเอง
    """
    try:
        if (
            not residual
            or len(residual) != DIMS
            or not all(math.isfinite(x) for x in residual)
        ):
            return dict(QUIET)
        history = load_history(redis, user_id)
        elig = eligibility(len(history))
        if elig == "abstain":
            return {**QUIET, "eligibility": elig, "n_history": len(history)}
        model = get_model(user_id, history)
        if model is None:
            return {**QUIET, "eligibility": elig, "n_history": len(history)}
        window = history[-(WINDOW - 1) :] + [list(residual)]
        return evaluate_window(model, window)
    except Exception as e:  # noqa: BLE001
        logger.warning("[sequence] score error: %s", e)
        return dict(QUIET)
