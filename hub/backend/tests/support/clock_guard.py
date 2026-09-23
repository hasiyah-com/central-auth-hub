"""ตรวจนาฬิกาของคอนเทนเนอร์ก่อนเริ่ม gate (B77).

นาฬิกาที่กระโดดทำให้ token ที่เพิ่งออกถูกปฏิเสธด้วย `iat` → 401 ในเทสที่ไม่เกี่ยวกัน
ตัวตรวจนี้วัดก่อนเริ่มแล้วหยุดทันที พร้อมบอกว่าเป็นปัญหาของเครื่อง ไม่ใช่ของโค้ด

    python -m tests.support.clock_guard --seconds 10     # HOST_EPOCH มาจาก run_tests.sh

ตรวจสองอย่าง:
- การกระโดดของ `time.time() - time.monotonic()` ระหว่างวัด
- ความต่างกับเวลาของเครื่องหลักที่ส่งเข้ามาใน `HOST_EPOCH` (รวมความหน่วงของ
  `docker exec` ไว้แล้วในเพดาน `max_host_offset`)

stdlib อย่างเดียว — import ได้ก่อน conftest และไม่แตะฐานข้อมูล
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Sequence

MAX_STEP_S = 1.0
# ความหน่วงของ `docker compose exec` + start python วัดได้ +0.67 ถึง +0.85 วินาที
# (2026-09-21) · เหตุการณ์จริงคลาด 7–10 วินาที · เพดาน 3 จึงเหลือช่องว่างทั้งสองฝั่ง
# ถ้าเรียกผ่าน `docker run` จะหน่วงราว +2.3 วินาที ใกล้เพดานเกินไป — ใช้ exec เท่านั้น
MAX_HOST_OFFSET_S = 3.0
MIN_STEP_S = 0.05

_HOW_TO_FIX = (
    "นาฬิกาของเครื่องไม่นิ่ง — ไม่ใช่ปัญหาของโค้ด\n"
    "  1) ตรวจนาฬิกาของ Windows: w32tm /stripchart /computer:time.windows.com "
    "/samples:3 /dataonly\n"
    "  2) ถ้าคลาดเกินครึ่งวินาที: Settings > Time & language > Date & time > Sync now\n"
    "     (หรือ PowerShell แบบ admin: w32tm /resync /force)\n"
    "  3) รอให้ VM ของ Docker ตามทันราว 1 นาที แล้วรันใหม่"
)


def find_steps(
    offsets: Sequence[float], *, min_step: float = MIN_STEP_S
) -> list[float]:
    """จุดกระโดดจากลำดับ (wall - monotonic) — คืนขนาดพร้อมเครื่องหมาย."""
    steps = []
    for prev, cur in zip(offsets, offsets[1:]):
        d = cur - prev
        if abs(d) > min_step:
            steps.append(round(d, 3))
    return steps


def evaluate(
    *,
    steps: Sequence[float],
    host_offset: float | None,
    max_step: float = MAX_STEP_S,
    max_host_offset: float = MAX_HOST_OFFSET_S,
) -> list[str]:
    problems = []
    big = [s for s in steps if abs(s) > max_step]
    if big:
        problems.append(f"นาฬิกาในคอนเทนเนอร์กระโดด {big} วินาที (เพดาน ±{max_step})")
    if host_offset is not None and abs(host_offset) > max_host_offset:
        problems.append(
            f"นาฬิกาในคอนเทนเนอร์ต่างจากเครื่องหลัก {host_offset:+.2f} วินาที "
            f"(เพดาน ±{max_host_offset})"
        )
    return problems


def measure(seconds: float, interval: float = 0.02) -> list[float]:
    offsets = [time.time() - time.monotonic()]
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(interval)
        offsets.append(time.time() - time.monotonic())
    return offsets


def main(
    argv: Sequence[str] | None = None,
    *,
    measure: Callable[[float, float], list[float]] = measure,
    now: Callable[[], float] = time.time,
    host_epoch: float | None = None,
) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--max-step", type=float, default=MAX_STEP_S)
    ap.add_argument("--max-host-offset", type=float, default=MAX_HOST_OFFSET_S)
    a = ap.parse_args(argv)

    if host_epoch is None:
        raw = os.environ.get("HOST_EPOCH", "").strip()
        host_epoch = float(raw) if raw else None
    # วัดความต่างกับเครื่องหลักก่อน — ใกล้เวลาที่ HOST_EPOCH ถูกอ่านที่สุด
    host_offset = None if host_epoch is None else now() - host_epoch

    steps = find_steps(measure(a.seconds, 0.02))
    problems = evaluate(
        steps=steps,
        host_offset=host_offset,
        max_step=a.max_step,
        max_host_offset=a.max_host_offset,
    )
    if problems:
        print("clock guard: ไม่เริ่ม gate", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(_HOW_TO_FIX, file=sys.stderr)
        return 1
    shown = "ไม่ทราบ" if host_offset is None else f"{host_offset:+.2f}s"
    print(
        f"clock guard: ผ่าน ({a.seconds:g}s · กระโดด {steps or 'ไม่มี'} · "
        f"ต่างจากเครื่องหลัก {shown})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
