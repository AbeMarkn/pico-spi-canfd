"""性能切分け: ログ転送を除いた4 ID送受信を3秒だけ測定する。"""
import time
import gc
from machine import Pin, SPI
from config import CONFIG
from mcp2518fd import MCP2518FD
from main import Engine

spi = SPI(0, baudrate=1000000, sck=Pin(18), mosi=Pin(19), miso=Pin(16))
can = MCP2518FD(spi, Pin(17, Pin.OUT, value=1), CONFIG)
engine = Engine(can, CONFIG, "bench", time.ticks_us)
engine.emit = lambda event: None
engine.profiles = {}
for i, period in enumerate((10, 100, 1000, 10000)):
    p = {"profile_id": "T%d" % (i + 1), "can_id": (0x300 + i) if i < 2 else (0x18FF0101 + i - 2),
         "ide": i >= 2, "fdf": i >= 2, "brs": i >= 2,
         "data": "11" * (8 if i < 2 else 64), "period_ms": period}
    engine.profiles[p["profile_id"]] = p
engine.revision, engine.state = "bench", "PREPARED"
engine.execute("START_SESSION", {"revision": "bench", "duration_ms": 3000,
                               "device_config_id": CONFIG["device_config_id"]})
for i in range(4):
    engine.execute("START_PROFILE", {"profile_id": "T%d" % (i + 1), "generation": 0, "req": i})
gc.collect()
gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
start = time.ticks_us()
maximum = total = calls = 0
try:
    while time.ticks_diff(time.ticks_us(), start) < 3300000 and engine.state != "ENDED":
        engine.last_hb = time.ticks_us()
        t = time.ticks_us()
        engine.service()
        elapsed = time.ticks_diff(time.ticks_us(), t)
        maximum = max(maximum, elapsed)
        total += elapsed
        calls += 1
        engine.drain()
    print("CAN_ONLY", engine.stats, "SERVICE_US", total // calls, maximum, "CALLS", calls)
    print("RESULT", engine.final_event, engine.latest_error, can.read_status())
finally:
    can.disable_rx()
    can.mode(4)
