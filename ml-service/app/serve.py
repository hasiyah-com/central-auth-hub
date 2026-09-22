"""เปิด ml-service หลาย worker โดยให้แต่ละตัวมี socket ของตัวเอง (SO_REUSEPORT).

    python -m app.serve --workers 4 --port 9000

ทำไมไม่ใช้ `uvicorn --workers`: uvicorn ให้ทุก worker แย่งกัน accept จาก socket ตัวเดียว
วัดจริงแล้วงานไม่เท่ากัน (2,406 / 1,277 / 714 / 403 request · ML Capacity Gate
2026-09-22) — worker บางตัวแทบไม่ได้งานจนค้างอยู่ในสภาพเย็น และ p95 แกว่งมากระหว่างรอบ
ที่นี่แต่ละ worker bind พอร์ตเดียวกันด้วย `SO_REUSEPORT` แล้ว kernel กระจาย connection
ใหม่ตาม hash ของผู้เรียก (hub เปิด connection ใหม่ทุก request จึงกระจายได้จริง)

คุม worker เอง (ไม่เพิ่ม gunicorn): ตาย → เปิดใหม่ในช่องเดิม · พังซ้ำเกิน `max_restarts`
→ เลิกเปิด (กันวนไม่รู้จบตอน import พัง) · SIGTERM/SIGINT → หยุดทุกตัว

Linux เท่านั้น — ไม่มี SO_REUSEPORT จะไม่ยอมเปิด (ไม่แอบถอยไปใช้ socket ร่วม)
"""

from __future__ import annotations

import argparse
import multiprocessing
import signal
import socket
import sys
import time
from collections.abc import Callable


def make_socket(host: str, port: int) -> socket.socket:
    if not hasattr(socket, "SO_REUSEPORT"):
        raise RuntimeError("ระบบนี้ไม่มี SO_REUSEPORT — ใช้ตัวเปิดนี้ไม่ได้")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    s.bind((host, port))
    s.listen(2048)
    return s


def make_shard_socket(host: str, port: int) -> socket.socket:
    """พอร์ตเฉพาะของ worker หนึ่งตัว (L3 แยกตามผู้ใช้) — **ไม่ใช้** SO_REUSEPORT.

    ถ้าให้ reuseport process อื่นจะ bind พอร์ตเดียวกันได้ แล้วงานของ shard ถูกแบ่งเงียบๆ ·
    SO_REUSEADDR พอให้ worker ที่เปิดใหม่ bind พอร์ตเดิมได้ทันทีหลังตัวเก่าตาย
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(2048)
    return s


def worker_ports(slot: int, a: argparse.Namespace) -> tuple[int, int | None]:
    """(พอร์ตร่วม, พอร์ตเฉพาะของช่องนี้) — ช่องเดิมได้พอร์ตเดิมเสมอแม้ worker ถูกเปิดใหม่."""
    shard = None if a.shard_base_port is None else a.shard_base_port + slot
    return a.port, shard


def _run_worker(
    app: str, host: str, port: int, log_level: str, shard_port: int | None = None
) -> None:
    import uvicorn

    socks = [make_socket(host, port)]  # เปิดหลัง fork — socket ของ worker นี้เท่านั้น
    if shard_port is not None:
        socks.append(make_shard_socket(host, shard_port))
    config = uvicorn.Config(app, log_level=log_level)
    uvicorn.Server(config).run(sockets=socks)


class Supervisor:
    def __init__(
        self,
        workers: int,
        spawn: Callable[[int], object],
        max_restarts: int = 10,
    ):
        self.workers = workers
        self.spawn = spawn
        self.max_restarts = max_restarts
        self.procs: list = []
        self.restarts = 0
        self.stopping = False
        self.gave_up = False

    def start(self) -> None:
        self.procs = [self.spawn(i) for i in range(self.workers)]

    def check_once(self) -> list[int]:
        """เปิด worker ที่ตายแล้วใหม่ในช่องเดิม — คืนช่องที่เปิดใหม่."""
        if self.stopping or self.gave_up:
            return []
        restarted = []
        for i, p in enumerate(self.procs):
            if p.is_alive():
                continue
            if self.restarts >= self.max_restarts:
                self.gave_up = True
                print(
                    f"serve: worker พังซ้ำเกิน {self.max_restarts} ครั้ง — เลิกเปิดใหม่",
                    file=sys.stderr,
                    flush=True,
                )
                return restarted
            print(
                f"serve: worker {i} หยุด (exit {p.exitcode}) — เปิดใหม่",
                file=sys.stderr,
                flush=True,
            )
            self.procs[i] = self.spawn(i)
            self.restarts += 1
            restarted.append(i)
        return restarted

    def stop(self) -> None:
        self.stopping = True
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            p.join(timeout=10)


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m app.serve")
    ap.add_argument("--app", default="app.main:app")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--log-level", default="info")
    ap.add_argument(
        "--shard-base-port",
        type=int,
        default=None,
        help="worker ช่อง i ฟังพอร์ต base+i เพิ่ม (L3 แยกตามผู้ใช้) — ไม่ระบุ = ไม่มี",
    )
    a = ap.parse_args(argv)
    if a.workers < 1:
        ap.error("--workers ต้องมากกว่า 0")
    if a.shard_base_port is not None:
        lo, hi = a.shard_base_port, a.shard_base_port + a.workers - 1
        if lo < 1 or hi > 65535:
            ap.error(f"--shard-base-port ทำให้ได้พอร์ต {lo}–{hi} ซึ่งเกินช่วง 1–65535")
        if lo <= a.port <= hi:
            ap.error(f"พอร์ต shard {lo}–{hi} ทับพอร์ตร่วม {a.port}")
    return a


def main(argv=None) -> int:
    a = parse_args(argv)
    make_socket(a.host, a.port).close()  # ตรวจตั้งแต่ต้นว่าใช้ SO_REUSEPORT ได้

    ctx = multiprocessing.get_context("spawn")

    def spawn(i: int):
        shared, shard = worker_ports(i, a)
        p = ctx.Process(
            target=_run_worker,
            args=(a.app, a.host, shared, a.log_level, shard),
            name=f"ml-worker-{i}",
        )
        p.start()
        return p

    sup = Supervisor(a.workers, spawn)

    def _stop(signum, frame):
        sup.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    sup.start()
    print(
        f"serve: {a.workers} worker บน {a.host}:{a.port} (SO_REUSEPORT)"
        + (
            ""
            if a.shard_base_port is None
            else f" · shard {a.shard_base_port}–{a.shard_base_port + a.workers - 1}"
        ),
        file=sys.stderr,
        flush=True,
    )
    while not sup.gave_up:
        time.sleep(1.0)
        sup.check_once()
    sup.stop()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
