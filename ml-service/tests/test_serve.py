"""ตัวเปิด worker หลายตัวด้วย SO_REUSEPORT — เขียนก่อน implementation (RED).

ที่มา (ML Capacity Gate 2026-09-21/22): `uvicorn --workers 4` ใช้ socket ร่วมตัวเดียว
แล้วให้ worker แย่งกัน accept · วัดจริงช่วง steady ได้ 2,406 / 1,277 / 714 / 403 request
(ตัวที่มากสุด = 2.0 เท่าของค่าเฉลี่ย, 6 เท่าของตัวที่น้อยสุด) · warm-up 40 รอบไม่นิ่ง
เพราะ worker บางตัวแทบไม่ได้งาน · p95 ที่ c=20 แกว่ง 180–365 ms ระหว่างรอบ

ทางแก้: ให้ worker แต่ละตัวเปิด socket ของตัวเองบนพอร์ตเดียวกันด้วย `SO_REUSEPORT`
kernel จะกระจาย connection ใหม่ตาม hash ของ (ip, port) ฝั่งผู้เรียก · ไม่เพิ่ม dependency
(ไม่ใช้ gunicorn) จึงต้องคุม worker เอง: worker ตาย → เปิดใหม่ · ได้รับสัญญาณหยุด → หยุดทุกตัว

`SO_REUSEPORT` มีบน Linux (คอนเทนเนอร์) ไม่มีบน Windows host — เทสส่วนที่ใช้ socket จริง
ข้ามบน host และพิสูจน์ในคอนเทนเนอร์ผ่าน ML Capacity Gate
"""

from __future__ import annotations

import socket

import pytest

from app import serve


class FakeProc:
    def __init__(self, idx):
        self.idx = idx
        self.alive = True
        self.terminated = False
        self.exitcode = None

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.terminated = True
        self.alive = False

    def join(self, timeout=None):
        return None


def test_arguments_have_safe_defaults():
    a = serve.parse_args([])
    assert a.host == "0.0.0.0"
    assert a.port == 9000
    assert a.workers == 1
    assert a.app == "app.main:app"


def test_workers_must_be_positive():
    with pytest.raises(SystemExit):
        serve.parse_args(["--workers", "0"])


def test_starts_the_requested_number_of_workers():
    spawned = []

    def spawn(i):
        p = FakeProc(i)
        spawned.append(p)
        return p

    sup = serve.Supervisor(workers=4, spawn=spawn)
    sup.start()
    assert len(spawned) == 4
    assert [p.idx for p in spawned] == [0, 1, 2, 3]


def test_a_dead_worker_is_replaced_in_the_same_slot():
    spawned = []

    def spawn(i):
        p = FakeProc(i)
        spawned.append(p)
        return p

    sup = serve.Supervisor(workers=3, spawn=spawn)
    sup.start()
    spawned[1].alive = False
    spawned[1].exitcode = 1
    restarted = sup.check_once()
    assert restarted == [1]
    assert len(spawned) == 4 and spawned[-1].idx == 1
    assert sup.check_once() == []  # ไม่เปิดซ้ำเมื่อทุกตัวยังอยู่


def test_stop_terminates_every_worker_and_does_not_restart():
    spawned = []
    sup = serve.Supervisor(
        workers=2, spawn=lambda i: spawned.append(FakeProc(i)) or spawned[-1]
    )
    sup.start()
    sup.stop()
    assert all(p.terminated for p in spawned)
    assert sup.check_once() == []


def test_restart_storm_is_bounded():
    """worker ที่พังทันทีทุกครั้ง (เช่น import error) ต้องไม่ถูกเปิดวนไม่รู้จบ."""
    spawned = []

    def spawn(i):
        p = FakeProc(i)
        p.alive = False
        p.exitcode = 1
        spawned.append(p)
        return p

    sup = serve.Supervisor(workers=1, spawn=spawn, max_restarts=3)
    sup.start()
    for _ in range(10):
        sup.check_once()
    assert len(spawned) == 1 + 3
    assert sup.gave_up


@pytest.mark.skipif(
    not hasattr(socket, "SO_REUSEPORT"), reason="ไม่มี SO_REUSEPORT (Windows host)"
)
def test_two_worker_sockets_share_one_port():
    a = serve.make_socket("127.0.0.1", 0)
    port = a.getsockname()[1]
    b = serve.make_socket("127.0.0.1", port)  # ไม่มี SO_REUSEPORT จะ EADDRINUSE
    try:
        assert b.getsockname()[1] == port
        assert a.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT) == 1
    finally:
        a.close()
        b.close()


def test_refuses_to_run_without_reuseport(monkeypatch):
    """ถ้าไม่มี SO_REUSEPORT อย่าแอบถอยไปใช้ socket ร่วม — พฤติกรรมที่วัดไว้จะไม่ตรง."""
    monkeypatch.delattr(socket, "SO_REUSEPORT", raising=False)
    with pytest.raises(RuntimeError, match="SO_REUSEPORT"):
        serve.make_socket("127.0.0.1", 0)
