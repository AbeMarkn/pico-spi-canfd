"""TEST-DESN: 時刻・ドライバを注入し停止境界と再送の副作用を検証。"""
import json
from copy import deepcopy

from pico.common import encode
from pico.main import Engine
from pico.config import CONFIG
from tests.test_protocol import profile


class Clock:
    def __init__(self):
        self.us = 100000

    def __call__(self):
        return self.us


class CAN:
    def __init__(self, clock):
        self.clock = clock
        self.pending, self.rx, self.sent, self.complete = {}, [], [], []
        self.mode_value = 4
        self.starts = self.inits = 0

    def initialize(self):
        self.inits += 1

    def reset(self):
        self.mode_value = 4
        self.pending.clear()

    def start(self):
        self.starts += 1
        self.mode_value = 0
        return self.clock()

    def now_us(self):
        return self.clock()

    def submit(self, slot, p, metadata):
        record = dict(p, **metadata, seq=len(self.sent) + 1, slot=slot)
        self.pending[slot] = record
        self.sent.append(deepcopy(record))

    def abort(self, slot):
        if slot in self.pending:
            self.complete.append(dict(self.pending.pop(slot), type="TX_ABORTED"))

    def completions(self):
        result, self.complete = self.complete, []
        return result

    def receive(self):
        return self.rx.pop(0) if self.rx else None

    def read_status(self):
        return {"mode": self.mode_value, "bus_off": False, "rx_overflow": 0,
                "ecc": 0, "crc": 0, "int": 0, "tec": 0, "rec": 0,
                "bdiag0": 0, "bdiag1": 0}

    def interrupt_status(self):
        return (0x10 if self.complete else 0) | (2 if self.rx else 0)

    def disable_rx(self):
        pass

    def mode(self, value):
        self.mode_value = value


def setup(profiles=None):
    clock = Clock()
    can = CAN(clock)
    engine = Engine(can, CONFIG, "boot", clock)
    engine.profiles = {p["profile_id"]: p for p in (profiles or [profile()])}
    engine.revision, engine.state = "r1", "PREPARED"
    return engine, can, clock


def command(e, req, cmd, **fields):
    obj = {"v": 1, "cmd": cmd, "req": req}
    if cmd != "HELLO":
        obj["boot_id"] = "boot"
    if e.session_id:
        obj["session_id"] = e.session_id
    obj.update(fields)
    e.command(encode(obj)[:-1])
    return e.controls.get()


def start(e):
    return command(e, 1, "START_SESSION", revision="r1", duration_ms=1000,
                   device_config_id=CONFIG["device_config_id"])


def empty(e):
    result = []
    while e.controls.count:
        result.append(e.controls.get())
    while e.frames.count:
        result.append(e.frames.get())
    return result


def test_duplicate_start_session_and_req_reuse():
    e, can, clock = setup()
    first = start(e)
    clock.us += 200
    replay = command(e, 1, "START_SESSION", revision="r1", duration_ms=1000,
                     device_config_id=CONFIG["device_config_id"])
    # 初回はsession_id無しなので、同じワイヤ本文を明示して再送する。
    assert replay["code"] == "REQ_REUSED"
    obj = {"v": 1, "cmd": "START_SESSION", "req": 1, "boot_id": "boot",
           "revision": "r1", "duration_ms": 1000, "device_config_id": CONFIG["device_config_id"]}
    e.command(encode(obj)[:-1])
    assert e.controls.get() == first
    assert can.starts == 1 and can.inits == 1


def test_four_slots_fifth_rejected_and_classic_fd_same_id_replaces():
    profiles = [profile(profile_id=str(i), can_id=i) for i in range(5)]
    profiles.append(profile(profile_id="replacement", can_id=0, fdf=False, brs=False))
    e, can, clock = setup(profiles)
    start(e)
    for i in range(4):
        assert command(e, i + 2, "START_PROFILE", profile_id=str(i), generation=0)["result"] == "STARTED"
    assert command(e, 6, "START_PROFILE", profile_id="4", generation=0)["code"] == "ACTIVE_CAPACITY"
    e.service()
    assert len(can.sent) == 4
    assert command(e, 7, "START_PROFILE", profile_id="replacement", generation=0)["result"] == "REPLACING"
    e.service()
    assert len(e.jobs) == 4
    assert can.sent[-1]["fdf"] is False
    assert can.sent[0]["fdf"] is True  # 古い完了用のメタデータを改変しない。
    assert can.sent[-1]["generation"] == 1
    empty(e)
    assert command(e, 8, "START_PROFILE", profile_id="0", generation=0)["code"] == "STALE_GENERATION"


def test_stop_generation_prevents_old_start():
    e, can, _ = setup()
    start(e)
    command(e, 2, "START_PROFILE", profile_id="X", generation=0)
    e.service()
    stop = command(e, 3, "STOP_ID", ide=False, can_id=0x123)
    assert stop["generation"] == 1
    stale = command(e, 4, "START_PROFILE", profile_id="X", generation=0)
    assert stale["code"] == "STALE_GENERATION"
    e.service()
    assert not e.jobs
    assert len(can.sent) == 1


def test_deadline_rx_exclusive_and_no_post_deadline_tx():
    e, can, clock = setup()
    start(e)
    command(e, 2, "START_PROFILE", profile_id="X", generation=0)
    end = e.deadline_us
    can.rx = [{"device_us": end - 1}, {"device_us": end}, {"device_us": e.start_us - 1}]
    clock.us = end
    e.service()
    assert not can.sent
    events = empty(e)
    assert [r["device_us"] for r in events if r["type"] == "RX"] == [end - 1]
    assert can.mode_value == 4
    e.drain()
    assert e.controls.get()["type"] == "SESSION_END"


def test_heartbeat_timeout_and_overflow_stop():
    for overflow in (False, True):
        e, _, clock = setup()
        start(e)
        e.deadline_us += 10000000
        if overflow:
            for _ in range(65):
                e.emit(e.event("RX", device_us=1))
        else:
            clock.us += 1000000
        e.service()
        assert e.state == "DRAINING"
        assert e.stop_reason == ("USB_QUEUE_OVERFLOW" if overflow else "HEARTBEAT_LOST")


def test_period_no_catch_up_burst_and_no_reset_on_repeat():
    e, can, clock = setup()
    start(e)
    command(e, 2, "START_PROFILE", profile_id="X", generation=0)
    e.service()
    due = next(iter(e.jobs.values()))["due"]
    command(e, 3, "START_PROFILE", profile_id="X", generation=0)
    assert next(iter(e.jobs.values()))["due"] == due
    can.pending.clear()
    clock.us += 350000
    e.service()
    assert len(can.sent) == 2
    assert e.stats["skipped"] == 2


def test_partial_writes_never_interleave_lines():
    e, _, _ = setup()
    e.emit(e.event("RX", data="AA"))

    class USB:
        data = bytearray()

        def ioctl(self, _request, flags):
            return flags

        def write(self, data):
            self.data.extend(data[:3])
            return min(3, len(data))

    usb = USB()
    e.flush(usb)
    e.error("STOP")
    for _ in range(200):
        e.flush(usb)
    events = [json.loads(x) for x in usb.data.splitlines()]
    assert [x["type"] for x in events] == ["RX", "ERROR"]


def test_load_commit_atomic_and_hello_reconnect():
    e, _, _ = setup()
    old = e.profiles
    command(e, 1, "LOAD_BEGIN", revision="new", count=2)
    command(e, 2, "LOAD_PROFILE", revision="new", profile=profile())
    assert command(e, 3, "LOAD_COMMIT", revision="new", count=2)["type"] == "NACK"
    assert e.profiles is old
    hello = command(e, 0, "HELLO")
    assert hello["next_req"] == 4


def test_driver_fault_resets_can_and_reports_unconfirmed_logs():
    e, can, _ = setup()
    start(e)
    command(e, 2, "START_PROFILE", profile_id="X", generation=0)
    e.service()
    e.fault("RUNTIME", "injected SPI exception")
    assert can.mode_value == 4 and not can.pending and not e.jobs
    events = empty(e)
    assert any(r["type"] == "TX_UNKNOWN" for r in events)
    e.drain()
    final = e.controls.get()
    assert final["stop_confirmed"] and not final["drain_complete"]


def test_alias_with_same_data_keeps_original_schedule():
    e, can, _ = setup([profile(), profile(profile_id="alias")])
    start(e)
    command(e, 2, "START_PROFILE", profile_id="X", generation=0)
    e.service()
    due = e.jobs[(False, 0x123)]["due"]
    ack = command(e, 3, "START_PROFILE", profile_id="alias", generation=0)
    assert ack["result"] == "ALREADY_ACTIVE" and ack["profile_id"] == "X"
    assert e.jobs[(False, 0x123)]["due"] == due and len(can.sent) == 1


def test_missing_tef_times_out_and_stops():
    e, can, clock = setup()
    start(e)
    command(e, 2, "START_PROFILE", profile_id="X", generation=0)
    e.service()
    clock.us += 100001
    e.service()
    assert e.stop_reason == "TX_COMPLETION_TIMEOUT"
    assert len(can.sent) == 1
