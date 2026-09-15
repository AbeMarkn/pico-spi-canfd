"""TEST-DESN-108の補助: 内部ループバックの全DLC・両ID種別。外部疎通と区別。"""
import time
from machine import SPI, Pin
from config import CONFIG
from common import DLC_LENGTHS
from mcp2518fd import MCP2518FD

spi = SPI(0, baudrate=1000000, sck=Pin(18), mosi=Pin(19), miso=Pin(16))
can = MCP2518FD(spi, Pin(17, Pin.OUT, value=1), CONFIG)
passed = 0
try:
    can.initialize()
    can.start(loopback=True)
    for ide in (False, True):
        for fdf in (False, True):
            for length in (DLC_LENGTHS if fdf else range(9)):
                p = dict(profile_id="loop", can_id=0x1ABCDE1 if ide else 0x7A0,
                         ide=ide, fdf=fdf, brs=fdf, period_ms=100,
                         data="".join("%02X" % i for i in range(length)))
                can.submit(2, p, {})
                start = time.ticks_ms()
                received = complete = None
                while received is None or complete is None:
                    if time.ticks_diff(time.ticks_ms(), start) > 1000:
                        raise RuntimeError("LOOPBACK_TIMEOUT", p, can.read_status())
                    frames = can.completions()
                    if frames:
                        assert len(frames) == 1 and frames[0]["type"] == "TX_DONE"
                        complete = frames[0]
                    frame = can.receive()
                    if frame:
                        received = frame
                for field in ("can_id", "ide", "fdf", "brs", "data"):
                    assert received[field] == p[field], (field, received, p)
                passed += 1
    status = can.read_status()
    assert status["tec"] == status["rec"] == status["rx_overflow"] == 0
    print("INTERNAL_LOOPBACK_PASS", passed, status)
finally:
    can.disable_rx()
    can.mode(4)
    print("STOP_MODE", can.read_status()["mode"])
