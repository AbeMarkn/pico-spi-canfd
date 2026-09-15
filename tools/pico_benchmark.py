"""DESN-SW-011: 保守REPLから実行する有限の性能診断。送信しない。"""
import time
import gc
from machine import SPI, Pin
from config import CONFIG
from mcp2518fd import MCP2518FD
from common import crc16, encode, strict_json
import main
import json

spi = SPI(0, baudrate=1000000, sck=Pin(18), mosi=Pin(19), miso=Pin(16))
can = MCP2518FD(spi, Pin(17, Pin.OUT, value=1), CONFIG)
can.initialize()
engine = main.Engine(can, CONFIG, "bench", time.ticks_us)
gc.collect()
print("HEAP", gc.mem_free(), gc.mem_alloc())
print("CRC_REFERENCE", hex(crc16(b"123456789")))
data = bytes(76)
obj = {"v": 1, "cmd": "START_PROFILE", "req": 10, "boot_id": "131e562995be1391",
       "session_id": "131e562995be1391-1", "profile_id": "T1", "generation": 0}
raw = encode(obj)[:-1]
for label, func in (("CRC76", lambda: crc16(data)), ("REG", lambda: can.reg(0)),
                    ("STATUS", can.read_status), ("ENCODE", lambda: encode(obj)),
                    ("PARSE", lambda: strict_json(raw)), ("JSON_ONLY", lambda: json.loads(raw)),
                    ("GC", gc.collect)):
    samples = []
    for _ in range(30):
        start = time.ticks_us()
        func()
        samples.append(time.ticks_diff(time.ticks_us(), start))
    print(label, "us min/mean/max", min(samples), sum(samples) // len(samples), max(samples))
print("HEAP_FINAL", gc.mem_free(), gc.mem_alloc())
