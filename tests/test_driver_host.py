"""TEST-DESN: SPI障害の有限処理とログの完全保存・容量超過通知。"""
import json
import queue
import struct

import pytest

from host.main import LogWriter
from pico.config import CONFIG
from pico.mcp2518fd import MCP2518FD, CANError, TEFUA


def reference_crc(data):
    crc = 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x8005 if crc & 0x8000 else 0)) & 0xFFFF
    return crc.to_bytes(2, "big")


class SPI:
    def __init__(self, failures=0, value=0x81234567):
        self.failures, self.value = failures, value
        self.writes = []
        self.reads = 0

    def write(self, data):
        self.writes.append(bytes(data))

    def readinto(self, buffer):
        self.reads += 1
        payload = struct.pack("<I", self.value)
        crc = reference_crc(self.writes[-1] + payload)
        if self.reads <= self.failures:
            crc = bytes((crc[0] ^ 1, crc[1]))
        buffer[:] = payload + crc


def driver(spi):
    cs = []
    can = MCP2518FD(spi, cs.append, CONFIG, clock=lambda: 0, sleep=lambda _: None)
    return can, cs


def test_crc_read_recovers_once_and_keeps_cs_high():
    spi = SPI(failures=1)
    can, cs = driver(spi)
    assert can.reg(0xE14) == 0x81234567
    assert spi.writes == [b"\xBE\x14\x04"] * 2
    assert can.crc_retries == 1 and cs[-1] == 1


def test_spi_crc_has_exactly_three_attempts():
    spi = SPI(failures=10)
    can, cs = driver(spi)
    with pytest.raises(CANError, match="SPI_READ_CRC"):
        can.reg(0)
    assert spi.reads == 3 and can.crc_retries == 3 and cs[-1] == 1


def test_safe_write_and_ram_word_count():
    spi = SPI()
    can, _ = driver(spi)
    can.byte(0xE04, 3)
    header = b"\xCE\x04\x03"
    assert spi.writes[-1] == header + reference_crc(header)
    can.write_ram(0xAB8, bytes(16))
    assert spi.writes[-3] == b"\xAA\xB8\x04"
    assert spi.writes[-1] == reference_crc(b"\xAA\xB8\x04" + bytes(16))


@pytest.mark.parametrize("address,size", [(0x3FC, 4), (0x400, 3), (0x401, 4), (0xBFC, 8)])
def test_ram_range_before_spi(address, size):
    spi = SPI()
    can, _ = driver(spi)
    with pytest.raises(ValueError):
        can.write_ram(address, bytes(size))
    assert not spi.writes


def test_shadow_address_detects_bad_ua_with_valid_crc():
    spi = SPI(value=12)
    can, _ = driver(spi)
    can.addresses[TEFUA] = 0x400
    with pytest.raises(CANError, match="FIFO_ADDRESS"):
        can._ua(TEFUA, 12)


def test_logger_drains_all_three_files(tmp_path):
    logger = LogWriter(tmp_path, {"試験": "保存"})
    logger.start()
    assert logger.ready.wait(2) and not logger.failure
    for kind in ("RX", "TX_DONE", "ERROR"):
        for i in range(80):
            logger.put({"type": kind, "event_seq": i})
    logger.close()
    for filename, kind in (("rx.txt", "RX"), ("tx.txt", "TX_DONE"), ("error.txt", "ERROR")):
        rows = [json.loads(s) for s in (logger.directory / filename).read_text().splitlines() if not s.startswith("#")]
        assert len(rows) == 80
        assert all(row["type"] == kind and "host_utc" in row for row in rows)
    assert logger.closed.is_set() and logger.count == 240


def test_full_log_queue_does_not_block(tmp_path):
    logger = LogWriter(tmp_path, {})
    logger.events = queue.Queue(1)
    logger.put({"type": "RX"})
    with pytest.raises(OSError, match="満杯"):
        logger.put({"type": "RX"})


def test_log_open_failure_is_reported(tmp_path):
    path = tmp_path / "not_a_directory"
    path.write_text("x")
    logger = LogWriter(path, {})
    logger.start()
    assert logger.ready.wait(2)
    with pytest.raises(OSError):
        logger.close()
