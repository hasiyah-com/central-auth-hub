"""Calibration — แปลงคะแนนดิบของแต่ละชั้นให้อยู่บนสเกลเดียวกันก่อนส่งเข้า L4.

**ปัญหาที่แก้:** เดิม L4 บวกคะแนนดิบของสามชั้นเข้าด้วยกันตรงๆ ทั้งที่แต่ละชั้นมี
สเกลคนละแบบ — L1 เป็นผลรวมน้ำหนักของกฎ, L2 เป็นผลรวมของสัญญาณพฤติกรรม,
L3 เป็นค่า `-score_samples()` ของ IsolationForest ซึ่งไม่มีความหมายเชิงความน่าจะเป็นเลย
การบวกของที่วัดคนละหน่วยทำให้ "0.3 ของ L1" กับ "0.3 ของ L3" ถูกนับเท่ากันโดยไม่มีเหตุผล

**วิธี:** empirical CDF ของคะแนนชั้นนั้นบน login **ปกติ** ในชุด validation

    evidence = percentile ของคะแนนนี้เทียบกับ login ปกติ
              = สัดส่วนของ login ปกติที่คะแนนต่ำกว่าค่านี้อย่างเคร่งครัด

อ่านได้ตรงๆ ว่า "หายากแค่ไหนถ้าเป็นคนปกติ" — 0.99 คือหายากระดับ 1 ใน 100
ทุกชั้นจึงเทียบกันได้จริงหลัง calibrate

**เรียกว่า percentile evidence ไม่ใช่ probability** — ค่านี้ไม่ได้ปรับเทียบกับ
อัตราการเกิด attack จริง จึงไม่ใช่ "ความน่าจะเป็นที่เป็นการโจมตี" · การเรียกผิด
จะทำให้ผู้อ่านตีความ 0.99 ว่า "มั่นใจ 99% ว่าเป็นการโจมตี" ซึ่งไม่ถูกต้อง

**กติกาที่ห้ามละเมิด:** ตาราง calibration ต้องสร้างจาก **validation เท่านั้น**
ห้ามใช้ final holdout หรือชุด campaign ปรับค่า ไม่งั้นตัวเลขที่รายงานจะมองโลกในแง่ดี
เกินจริงโดยที่ไม่มีใครเห็น (บทเรียนเดียวกับ optimism bias ที่วัดไว้แล้วในรอบก่อน)

**ไม่มีตาราง = ต้องรู้ตัว (B61):** ถ้าโหลดไฟล์ไม่ได้ ระบบจะไม่แอบใช้ค่าดิบแทนเงียบๆ
แต่จะตั้ง `calibrated=False` ติดไปกับหลักฐาน และ L4 บันทึกไว้ใน breakdown

**การเปิดใช้ตารางต้องประกาศชัด:** โหลดเฉพาะไฟล์ที่ตั้งไว้ใน `CALIBRATION_PATH`
ไม่ใช่ไฟล์ที่บังเอิญวางอยู่ข้าง ๆ — ตารางเปลี่ยนสเกลของหลักฐานทุกชั้น ถ้าเปิดใช้
โดยที่เกณฑ์ยังเป็นชุดเก่า การตัดสินจริงเกือบทุกครั้งจะกลายเป็น block · ตอน start
`validate_startup()` จึงบังคับให้ sha256, version, gamma และเกณฑ์ตรงกับตารางเสมอ
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# None = ไม่ได้ประกาศใช้ตาราง · เทสและการทดลองชี้ไฟล์เองโดยตั้งค่านี้ตรง ๆ
CALIBRATION_FILE: Path | None = (
    Path(settings.calibration_path) if settings.calibration_path else None
)
LAYERS = ("rule", "behavior", "anomaly_point", "anomaly_sequence")
# ความคลาดที่ยอมได้ตอนเทียบเกณฑ์ใน env กับเกณฑ์ในตาราง (เลขทศนิยมจาก JSON)
_THRESHOLD_TOL = 1e-9


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
        self.state: str = "not_loaded"
        self.sha256: str | None = None
        self.path: Path | None = None
        self._loaded = False

    def load(self) -> None:
        """โหลดตาราง · สถานะที่เป็นไปได้

        not_configured  ไม่ได้ประกาศใช้ตาราง (พฤติกรรมเดิม — หลักฐานยังไม่ calibrate)
        missing         ประกาศไว้แต่ไม่พบไฟล์
        sha_mismatch    ไฟล์ไม่ตรงกับ `CALIBRATION_SHA256` — **ไม่ใช้ตาราง**
        unverified      โหลดแล้วแต่ไม่มี hash ให้เทียบ (เทส/การทดลองที่ชี้ไฟล์เอง)
        ok              โหลดแล้วและ hash ตรง
        error           อ่านไม่ได้
        """
        if self._loaded:
            return
        self._loaded = True
        self.path = CALIBRATION_FILE
        if CALIBRATION_FILE is None:
            self.state = "not_configured"
            return
        try:
            blob = Path(CALIBRATION_FILE).read_bytes()
        except FileNotFoundError:
            self.state = "missing"
            logger.warning(
                "[calibration] ไม่พบ %s — หลักฐานจะถูกทำเครื่องหมาย calibrated=False",
                CALIBRATION_FILE,
            )
            return
        self.sha256 = hashlib.sha256(blob).hexdigest()
        expected = getattr(settings, "calibration_sha256", None)
        if expected and expected.lower() != self.sha256:
            self.state = "sha_mismatch"
            logger.error(
                "[calibration] sha256 ไม่ตรง (คาด %s ได้ %s) — ไม่ใช้ตาราง",
                expected[:12],
                self.sha256[:12],
            )
            return
        try:
            raw = json.loads(blob.decode("utf-8"))
            self.version = str(raw.get("version") or "unknown")
            for layer in LAYERS:
                vals = raw.get("quantiles", {}).get(layer)
                if isinstance(vals, list) and len(vals) >= 2:
                    self.quantiles[layer] = sorted(float(v) for v in vals)
            self.state = "ok" if expected else "unverified"
            if self.quantiles:
                logger.info(
                    "[calibration] loaded %s (%d layers, %s)",
                    self.version,
                    len(self.quantiles),
                    self.state,
                )
        except Exception as e:  # noqa: BLE001
            self.state = "error"
            self.quantiles = {}
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


def status() -> dict:
    """สถานะของตารางที่ระบบกำลังใช้ — สำหรับ health check และการตรวจย้อน."""
    _TABLE.load()
    return {
        "state": _TABLE.state,
        "path": str(_TABLE.path) if _TABLE.path else None,
        "sha256": _TABLE.sha256,
        "version": _TABLE.version,
        "layers": sorted(_TABLE.quantiles),
    }


def validate_startup(cfg) -> None:
    """ปฏิเสธการ start เมื่อตารางกับคอนฟิกไม่ใช่ชุดเดียวกัน — fail closed.

    ตรวจจากไฟล์ที่ `cfg.calibration_path` ชี้ (ไม่ใช่ตารางที่โหลดค้างในหน่วยความจำ)
    เพื่อให้ผลขึ้นกับคอนฟิกที่ส่งเข้ามาเท่านั้น

    * `shadow_hybrid` ต้องมีตารางเสมอ — ผลจำลองที่ไม่ calibrate เทียบข้ามชั้นไม่ได้
    * ประกาศ path แล้ว (ทุกโหมด) ต้องมีไฟล์, มี sha256, sha256 ตรง, version ตรง
    * gamma และเกณฑ์ทั้งสามระดับใน env ต้องตรงกับที่ตารางผลิตมา — หลักฐานที่เป็น
      เปอร์เซ็นไทล์กับเกณฑ์ชุดเก่า = การตัดสินจริงกลายเป็น block เกือบทุกครั้ง
    """
    mode = (getattr(cfg, "l3_mode", "") or "").strip().lower()
    path_value = getattr(cfg, "calibration_path", None)
    if not path_value:
        if mode == "shadow_hybrid":
            raise RuntimeError(
                "L3_MODE=shadow_hybrid ต้องมีตาราง calibration — ตั้ง CALIBRATION_PATH "
                "และ CALIBRATION_SHA256 ก่อน หรือใช้โหมด shadow ไปก่อน"
            )
        return

    path = Path(path_value)
    expected = getattr(cfg, "calibration_sha256", None)
    if not expected:
        raise RuntimeError(
            f"ตั้ง CALIBRATION_PATH={path} แล้วแต่ไม่ได้ตั้ง CALIBRATION_SHA256 — "
            "ต้องระบุ hash ที่คาดไว้เสมอ"
        )
    if not path.exists():
        raise RuntimeError(f"ไม่พบตาราง calibration ที่ {path}")
    blob = path.read_bytes()
    actual = hashlib.sha256(blob).hexdigest()
    if actual != expected.lower():
        raise RuntimeError(
            f"sha256 ของตาราง calibration ไม่ตรง: คาด {expected[:12]} ได้ {actual[:12]}"
        )
    art = json.loads(blob.decode("utf-8"))

    want_version = getattr(cfg, "calibration_version", None)
    if want_version and want_version != art.get("version"):
        raise RuntimeError(
            f"calibration version ไม่ตรง: env {want_version} แต่ไฟล์ {art.get('version')}"
        )

    derived = art.get("derived_thresholds")
    if not isinstance(derived, dict):
        raise RuntimeError(
            "ตาราง calibration ไม่มี derived_thresholds — ตรวจไม่ได้ว่าเกณฑ์ใน env "
            "มาจากตารางนี้ (สร้างด้วย build_calibration.py)"
        )
    wrong = []
    for level in ("warn", "challenge", "block"):
        env_value = float(getattr(cfg, f"l4_threshold_{level}"))
        table_value = derived.get(level)
        if table_value is None or abs(env_value - float(table_value)) > _THRESHOLD_TOL:
            wrong.append(f"{level} env={env_value} ตาราง={table_value}")
    if wrong:
        raise RuntimeError(
            "threshold ใน env ไม่ได้มาจากตาราง calibration นี้: " + " · ".join(wrong)
        )

    fusion = art.get("fusion") or {}
    if "gamma" not in fusion:
        raise RuntimeError("ตาราง calibration ไม่ได้บันทึก gamma ที่ใช้สร้างเกณฑ์")
    if abs(float(cfg.l4_gamma) - float(fusion["gamma"])) > _THRESHOLD_TOL:
        raise RuntimeError(
            f"gamma ใน env ({cfg.l4_gamma}) ไม่ตรงกับตาราง ({fusion['gamma']})"
        )


def reload_for_tests() -> None:
    """บังคับโหลดใหม่ — ใช้ในเทสที่เขียนไฟล์ calibration ชั่วคราว."""
    global _TABLE
    _TABLE = _Table()


def tail_transform(percentile: float, tau: float) -> float:
    """หลักฐานเฉพาะหางขวาของ login ปกติ — 0 จนกว่าจะเกิน `tau` แล้วยืดเป็น 0..1.

    ที่มา (Accuracy Gate §9, 2026-09-23): percentile evidence ให้ค่าสูงกับ login ปกติโดยโครงสร้าง —
    ปกติ 10% ได้หลักฐาน >= 0.9 เสมอ · เมื่อรวมด้วย max + corroboration การเพิ่มชั้นที่สามจึงดันคะแนน
    ของ login ปกติขึ้นทั้งแถบ ทำให้ threshold ที่คุม FPR เท่าเดิมต้องสูงขึ้น และการจับที่มาจากคะแนนหายไป
    (วัดได้ใน §8: ทุกแขนที่มี L3 แพ้ baseline ที่ FPR เท่ากัน)

    การแปลงนี้ทำให้ L3 "ออกเสียง" เฉพาะเมื่อคะแนนสุดโต่งเทียบกับ login ปกติเท่านั้น
    **ยังไม่ใช่ค่าเริ่มต้นของระบบ** — เป็น candidate ที่ต้องผ่านการวัดก่อน
    """
    if not 0.0 < tau < 1.0:
        raise ValueError(f"tau ต้องอยู่ใน (0, 1) (ได้ {tau})")
    p = min(max(float(percentile), 0.0), 1.0)
    return 0.0 if p <= tau else (p - tau) / (1.0 - tau)
