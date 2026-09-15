"""TEST-SPEC/TEST-DESNの実CAN試験。通常pytestではskipする。"""
import time

import pytest

from host.main import Link, LogWriter, load_config, source_manifest, wire_profile


def pump_until(link, predicate, timeout=2, heartbeat=True):
    end = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < end, "実機応答の期限超過"
        link.pump(heartbeat=heartbeat)
        time.sleep(0.001)


def pump_for(link, seconds, heartbeat=True):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        link.pump(heartbeat=heartbeat)
        time.sleep(0.001)


@pytest.fixture
def session(request):
    port = request.config.getoption("--can-port")
    if not port:
        pytest.skip("実CAN試験は --can-port の明示が必要")
    cfg = load_config("host/config.py")
    cfg["profiles"].append(dict(cfg["profiles"][0], profile_id="T1B", data="3132333435363738"))
    rows = []
    logger = LogWriter("logs/hardware", {"試験": request.node.name, "config": cfg,
                                       "source_sha256": source_manifest()})
    logger.start()
    assert logger.ready.wait(3) and not logger.failure

    def receive(e):
        if e["type"].startswith("TX_") and "profile_id" in e:
            p = next(p for p in cfg["profiles"] if p["profile_id"] == e["profile_id"])
            e = dict(wire_profile(p), **e)
        rows.append(e)
        logger.put(e)

    link = Link(port, receive)
    try:
        link.rpc("HELLO")
        assert link.info["nominal_bitrate"] == 500000 and link.info["data_bitrate"] == 2000000
        link.rpc("LOAD_BEGIN", revision="hardware-test", count=len(cfg["profiles"]))
        for p in cfg["profiles"]:
            link.rpc("LOAD_PROFILE", revision="hardware-test", profile=wire_profile(p))
        link.rpc("LOAD_COMMIT", revision="hardware-test", count=len(cfg["profiles"]))
        ack = link.rpc("START_SESSION", revision="hardware-test", duration_ms=8000,
                       device_config_id=cfg["device_config_id"])
        yield link, rows, ack
    finally:
        try:
            if link.session_id and not link.ended:
                link.rpc("STOP_SESSION", reason="TEST_CLEANUP")
                pump_until(link, lambda: link.ended, timeout=2.2)
            if link.boot_id:
                status = link.rpc("STATUS")
                assert status["hardware"]["mode"] == 4 and not status["active"]
        finally:
            link.close()
            logger.close()
            print("HARDWARE_LOG", logger.directory)


def test_real_can_replace_stop_restart_and_replay(session):
    link, rows, ack = session
    # START_SESSIONの同一req・同一本文再送でも時刻とセッションは不変。
    request = dict(v=1, cmd="START_SESSION", req=ack["req"], boot_id=link.boot_id,
                   revision="hardware-test", duration_ms=8000,
                   device_config_id=link.info["device_config_id"])
    pump_for(link, 0.05)
    link.inflight = ("START_SESSION", ack["req"])
    link.queue_write(request)
    pump_until(link, lambda: ack["req"] in link.responses)
    replay = link.responses.pop(ack["req"])
    link.inflight = None
    assert replay == ack
    assert not any(e["type"] == "TX_DONE" for e in rows)  # 受信のみで起動。
    assert link.rpc("START_PROFILE", profile_id="T1", generation=0)["result"] == "STARTED"
    pump_until(link, lambda: any(e["type"] == "TX_DONE" for e in rows))
    assert link.rpc("START_PROFILE", profile_id="T1", generation=0)["result"] == "ALREADY_ACTIVE"
    replace = link.rpc("START_PROFILE", profile_id="T1B", generation=0)
    assert replace["result"] == "REPLACING" and replace["generation"] == 1
    pump_until(link, lambda: any(e["type"] == "TX_DONE" and e["profile_id"] == "T1B" for e in rows))
    replacement = next(e for e in rows if e["type"] == "TX_DONE" and e["profile_id"] == "T1B")
    assert replacement["generation"] == 1 and replacement["data"] == "3132333435363738"
    with pytest.raises(ValueError, match="STALE_GENERATION"):
        link.rpc("START_PROFILE", profile_id="T1", generation=0)
    stop = link.rpc("STOP_ID", ide=False, can_id=0x300)
    assert stop["generation"] == 2
    pump_until(link, lambda: any(e["type"] == "ID_STOPPED" and e["generation"] == 2 for e in rows))
    boundary = len(rows)
    pump_for(link, 0.15)
    assert not any(e["type"] == "TX_DONE" for e in rows[boundary:])
    link.rpc("START_PROFILE", profile_id="T1", generation=2)
    pump_until(link, lambda: any(e["type"] == "TX_DONE" and e["generation"] == 2 for e in rows[boundary:]))
    started_stop = time.monotonic()
    link.rpc("STOP_SESSION", reason="TEST_STOP")
    pump_until(link, lambda: link.ended)
    final = next(e for e in rows if e["type"] == "SESSION_END")
    assert final["reason"] == "TEST_STOP" and final["stop_confirmed"] and final["drain_complete"]
    assert final["dropped"] == 0 and final["hardware"]["tec"] == final["hardware"]["rec"] == 0
    assert final["stats"]["tx_done"] == sum(e["type"] == "TX_DONE" for e in rows)
    assert final["stats"]["rx"] == sum(e["type"] == "RX" for e in rows)
    assert any(e["type"] == "RX" and e["can_id"] in (0x100, 0x200) for e in rows)
    print("STOP_NOTIFICATION_SECONDS", time.monotonic() - started_stop)


def test_real_can_heartbeat_loss_stops_without_auto_restart(session):
    link, rows, _ = session
    link.rpc("START_PROFILE", profile_id="T2", generation=0)
    pump_for(link, 0.2)
    # 書込み途中の最後のheartbeatを排出した後、CDCを読み続けて送信だけ止める。
    pump_until(link, lambda: not link.tx, heartbeat=False)
    began = time.monotonic()
    pump_until(link, lambda: link.ended, timeout=1.3, heartbeat=False)
    elapsed = time.monotonic() - began
    final = next(e for e in rows if e["type"] == "SESSION_END")
    assert final["reason"] == "HEARTBEAT_LOST" and final["stop_confirmed"] and not final["dropped"]
    status = link.rpc("STATUS")
    assert status["hardware"]["mode"] == 4 and not status["active"]
    boundary = len(rows)
    pump_for(link, 0.2)
    assert not any(e["type"] == "TX_DONE" for e in rows[boundary:])
    print("HEARTBEAT_STOP_NOTIFICATION_SECONDS", elapsed)
