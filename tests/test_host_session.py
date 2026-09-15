"""再接続のUSB滞留データと、GUI操作競合の回帰試験。"""
import queue

import pytest

from host.main import Link, Worker, load_config
from pico.common import encode


class Serial:
    def __init__(self, *args, **kwargs):
        self.input = b""

    def read(self, _):
        data, self.input = self.input, b""
        return data


def event(kind, seq, session="old", **fields):
    return dict(type=kind, event_seq=seq, boot_id="boot", session_id=session, **fields)


def test_reconnect_ignores_old_end_and_preserves_first_new_rx(monkeypatch):
    monkeypatch.setattr("host.main.serial.Serial", Serial)
    received = []
    link = Link("fake", received.append)
    link.inflight = ("HELLO", 0)
    link.serial.input = b"".join(encode(e) for e in (
        event("RX", 1), event("SESSION_END", 2), event("INFO", 3, req=0),
        event("RX", 4), event("SESSION_END", 5)))
    link.pump(heartbeat=False)
    assert [e["type"] for e in received] == ["INFO"]
    assert not link.ended and link.session_id is None
    link.inflight = ("START_SESSION", 10)
    link.serial.input = b"".join(encode(e) for e in (
        event("SESSION_END", 6),
        event("ACK", 7, "new", req=10, command="START_SESSION"),
        event("RX", 8, "new"), event("RX", 8, "new"), event("RX", 9)))
    link.pump(heartbeat=False)
    assert [e["type"] for e in received] == ["INFO", "ACK", "RX"]
    assert link.session_id == "new" and not link.ended
    link.serial.input = encode(event("SESSION_END", 10, "new"))
    link.pump(heartbeat=False)
    assert link.ended


def test_stop_priority_cancels_older_start_but_allows_later_explicit_start():
    worker = Worker(load_config("host/config.py"))
    worker.request("start", "T1")
    worker.request("start", "T2")
    worker.request("stop_id", (False, 0x300))
    worker.request("start", "T1")
    assert worker.next_command() == ("stop_id", (False, 0x300))
    assert worker.next_command() == ("start", "T2")
    assert worker.next_command() == ("start", "T1")
    with pytest.raises(queue.Empty):
        worker.next_command()
