"""Calibration — แปลงคะแนนดิบของแต่ละชั้นให้อยู่บนสเกลเดียวกันก่อนส่งเข้า L4.

**ปัญหาที่แก้:** เดิม L4 บวกคะแนนดิบของสามชั้นเข้าด้วยกันตรงๆ ทั้งที่แต่ละชั้นมี
สเกลคนละแบบ — L1 เป็นผลรวมน้ำหนักของกฎ, L2 เป็นผลรวมของสัญญาณพฤติกรรม,
L3 เป็นค่า `-score_samples()` ของ IsolationForest ซึ่งไม่มีความหมายเชิงความน่าจะเป็นเลย
การบวกของที่วัดคนละหน่วยทำให้ "0.3 ของ L1" กับ "0.3 ของ L3" ถูกนับเท่ากันโดยไม่มีเหตุผล

**วิธี:** empirical CDF ของคะแนนชั้นนั้นบน login **ปกติ** ในชุด validation

    evidence = P(คะแนนของ login ปกติ < คะแนนที่เห็นตอนนี้)

อ่านได้ตรงๆ ว่า "หายากแค่ไหนถ้าเป็นคนปกติ" — 0.99 คือหายากระดับ 1 ใน 100
ทุกชั้นจึงเทียบกันได้จริงหลัง calibrate

**กติกาที่ห้ามละเมิด:** ตาราง calibration ต้องสร้างจาก **validation เท่านั้น**
ห้ามใช้ final holdout หรือชุด campaign ปรับค่า ไม่งั้นตัวเลขที่รายงานจะมองโลกในแง่ดี
เกินจริงโดยที่ไม่มีใครเห็น (บทเรียนเดียวกับ optimism bias ที่วัดไว้แล้วในรอบก่อน)

**ไม่มีตาราง = ต้องรู้ตัว (B61):** ถ้าโหลดไฟล์ไม่ได้ ระบบจะไม่แอบใช้ค่าดิบแทนเงียบๆ
แต่จะตั้ง `calibrated=False` ติดไปกับหลักฐาน และ L4 บันทึกไว้ใน breakdown
"""

from __future__ import annotations

import bisect
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CALIBRATION_FILE = Path(__file__).with_name("calibration_v1.json")
LAYERS = ("rule", "behavior", "anomaly_point", "anomaly_sequence")


@dataclass(frozen=True)
class Calibrated:
    value: float
    calibrated: bool
    version: str


class _Table:
    """ควอนไทล์ของคะแนน login ปกติในชุด validation — เรียงจากน้อยไปมาก."""

    def __init__(self) -> None:
        self.version: str = "uncalibrated"
        self.quantiles: dict[str, list[float]] = {}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
            self.version = str(raw.get("version") or "unknown")
            for layer in LAYERS:
                vals = raw.get("quantiles", {}).get(layer)
                if isinstance(vals, list) and len(vals) >= 2:
                    self.quantiles[layer] = sorted(float(v) for v in vals)
            if self.quantiles:
                logger.info(
                    "[calibration] loaded %s (%d layers)",
                    self.version,
                    len(self.quantiles),
                )
        except FileNotFoundError:
            logger.warning(
                "[calibration] ไม่พบ %s — หลักฐานจะถูกทำเครื่องหมาย calibrated=False",
                CALIBRATION_FILE.name,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[calibration] โหลดไม่สำเร็จ: %s", e)

    def cdf(self, layer: str, raw_score: float) -> Calibrated:
        self.load()
        q = self.quantiles.get(layer)
        if not q:
            # ไม่มีตาราง -> ใช้ค่าดิบที่ clamp ไว้ แต่**ประกาศว่ายังไม่ calibrate**
            return Calibrated(
                value=min(max(float(raw_score), 0.0), 1.0),
                calibrated=False,
                version=self.version,
            )
        # สัดส่วนของ login ปกติที่คะแนน **ต่ำกว่า** ค่านี้อย่างเคร่งครัด
        # คะแนนที่ตรงกับค่าที่พบบ่อย (เช่น 0.0 ซึ่ง login ปกติส่วนใหญ่ได้)
        # ต้องได้ evidence ต่ำ ไม่ใช่สูง จึงใช้ bisect_left
        # ถ้าใช้ bisect_right ค่าที่พบบ่อยที่สุดจะถูกนับว่าสูงกว่าทุกคนที่เท่ากัน
        # -> login ปกติที่สุดได้หลักฐาน 1.0 -> block ทุกเหตุการณ์
        # (บั๊กจริงที่ smoke test จับได้ 2 ก.ย. 2569)
        idx = bisect.bisect_left(q, float(raw_score))
        return Calibrated(value=idx / len(q), calibrated=True, version=self.version)


_TABLE = _Table()


def calibrate(layer: str, raw_score: float) -> Calibrated:
    """คะแนนดิบ -> evidence 0..1 บนสเกลเดียวกันทุกชั้น."""
    return _TABLE.cdf(layer, raw_score)


def calibration_version() -> str:
    _TABLE.load()
    return _TABLE.version


def is_calibrated(layer: str) -> bool:
    _TABLE.load()
    return layer in _TABLE.quantiles


def reload_for_tests() -> None:
    """บังคับโหลดใหม่ — ใช้ในเทสที่เขียนไฟล์ calibration ชั่วคราว."""
    global _TABLE
    _TABLE = _Table()
