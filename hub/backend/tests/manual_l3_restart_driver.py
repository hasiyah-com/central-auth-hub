"""L3 restart resilience — driver ที่รันบน **host** (ต้องสั่ง docker ได้).

pytest รันอยู่ในคอนเทนเนอร์จึง restart คอนเทนเนอร์อื่นไม่ได้ — ไฟล์นี้เลยแยกออกมา
เป็น driver ฝั่ง host ตามแบบเดียวกับ manual_*_driver.py ตัวอื่นในโฟลเดอร์นี้

พิสูจน์ว่า:
  1. residual history อยู่รอดข้าม restart (อยู่ใน Redis ไม่ใช่หน่วยความจำ process)
  2. คะแนนหลัง restart **เท่าเดิมทุกหลัก** (refit deterministic -> การตัดสินไม่เปลี่ยน)
  3. ระหว่าง ml-service ดับ L3 เงียบแบบ fail-safe ไม่ทำ login พัง (B21)
  4. หลัง restart ระบบกลับมาเองโดยไม่ต้องแตะอะไร

Run (บน host, ที่ repo root):
    py hub/backend/tests/manual_l3_restart_driver.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

USER = "manual-l3-restart"
DRIFT = [12.0, 1.0, 8.0, 0.0, 9.0, 0.99]
N_HISTORY = 1500

PROBE = """
import asyncio, json, random, sys
from app.security import l3_sequence as L3
from app.services.l3_sequence_client import get_sequence_score
from app.redis_client import redis_client

USER = %r
mode = sys.argv[1]
key = L3._REDIS_KEY.format(user_id=USER)

if mode == "seed":
    redis_client.delete(key)
    rng = random.Random(42)
    for _ in range(%d):
        L3.record_residual(redis_client, USER, [
            rng.gauss(4.0,0.6), rng.gauss(0.3,0.05), rng.gauss(3.0,0.3),
            rng.gauss(0.8,0.1), rng.gauss(0.5,0.4), rng.gauss(0.2,0.05)])

out = asyncio.run(get_sequence_score(USER, %r))
out["llen"] = redis_client.llen(key)
if mode == "cleanup":
    redis_client.delete(key)
print("RESULT " + json.dumps(out))
""" % (USER, N_HISTORY, DRIFT)


def probe(mode: str) -> dict:
    r = subprocess.run(
        ["docker", "exec", "-i", "hub-backend", "python", "-c", PROBE, mode],
        capture_output=True,
        text=True,
    )
    for line in r.stdout.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[7:])
    raise SystemExit(f"probe ล้มเหลว ({mode}):\n{r.stdout}\n{r.stderr}")


def docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True)


def main() -> int:
    print("=" * 68)
    print("L3 restart resilience")
    print("=" * 68)

    print("\n[1] seed history + วัดคะแนนก่อน restart")
    before = probe("seed")
    print(
        f"    llen={before['llen']} n_history={before['n_history']} "
        f"elig={before['eligibility']} fired={before['fired']} "
        f"raw={before['raw_score']:.6f} tier={before['tier']}"
    )

    print("\n[2] หยุด ml-service -> L3 ต้องเงียบแบบ fail-safe")
    docker("compose", "stop", "ml-service")
    down = probe("score")
    print(f"    error={down['error']} fired={down['fired']}")
    ok_down = down["fired"] is False and bool(down["error"])

    print("\n[3] start ml-service กลับมา (cache ในหน่วยความจำหายหมด)")
    docker("compose", "start", "ml-service")
    for _ in range(30):
        time.sleep(1)
        try:
            probe("score")
            break
        except SystemExit:
            continue

    print("\n[4] วัดคะแนนหลัง restart (ต้อง refit จาก Redis)")
    after = probe("score")
    for _ in range(5):  # เผื่อรอบแรกยัง fit ไม่เสร็จ (timeout 0.5 วิ)
        if after["error"] is None:
            break
        time.sleep(2)
        after = probe("score")
    print(
        f"    llen={after['llen']} n_history={after['n_history']} "
        f"elig={after['eligibility']} fired={after['fired']} "
        f"raw={after['raw_score']:.6f} tier={after['tier']}"
    )

    probe("cleanup")

    checks = [
        ("history อยู่รอดข้าม restart", after["llen"] == before["llen"] == N_HISTORY),
        ("ml-service ดับ -> L3 เงียบ ไม่ raise", ok_down),
        ("กลับมาเองหลัง restart", after["error"] is None),
        ("n_history เท่าเดิม", after["n_history"] == before["n_history"]),
        ("คะแนนเท่าเดิมทุกหลัก", after["raw_score"] == before["raw_score"]),
        (
            "การตัดสินเท่าเดิม",
            (after["fired"], after["tier"]) == (before["fired"], before["tier"]),
        ),
    ]
    print("\n" + "=" * 68)
    failed = 0
    for name, ok in checks:
        print(f"  {'[PASS]' if ok else '[FAIL]'} {name}")
        failed += 0 if ok else 1
    print("=" * 68)
    print(f"  {len(checks) - failed}/{len(checks)} ผ่าน")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
