"""保守REPL用。内部loopbackで4/8 MHzを比較。外部CAN送信なし。

GUI停止・tools/device.py interrupt後、mpremote resume runで実行する。
通常アプリの負荷配分やUSB実転送速度を測るものではない。
"""
import gc
import json
import time

from machine import Pin, SPI
from config import CONFIG
from common import crc16, encode, strict_json
from mcp2518fd import MCP2518FD, CON


def measure(label, function, can, count=200):
    gc.collect()
    # サンプル領域は計測前に確保。GC自体は通常設定を維持。
    samples = [0] * count
    crc_before, tbc_before = can.crc_retries, can.tbc_retries
    for i in range(count):
        start = time.ticks_us()
        function()
        samples[i] = time.ticks_diff(time.ticks_us(), start)
    samples.sort()
    return {"operation": label, "samples": count, "min_us": samples[0],
            "mean_us": sum(samples) / count, "p95_us": samples[(95 * count + 99) // 100 - 1],
            "max_us": samples[-1], "crc_retries_delta": can.crc_retries - crc_before,
            "tbc_retries_delta": can.tbc_retries - tbc_before}


def run():
    cfg = dict(CONFIG)
    spi = SPI(cfg["spi_id"], baudrate=cfg["spi_init_hz"],
              sck=Pin(cfg["sck"]), mosi=Pin(cfg["mosi"]), miso=Pin(cfg["miso"]))
    can = MCP2518FD(spi, Pin(cfg["cs"], Pin.OUT, value=1), cfg)
    obj = {"type": "RX", "boot_id": "probe", "session_id": "1", "event_seq": 1,
           "can_id": 256, "ide": False, "fdf": True, "brs": True,
           "length": 64, "data": "00" * 64, "device_us": 1000000}
    raw = encode(obj)[:-1]
    payload = bytes(76)
    try:
        for index, hz in enumerate((4000000, 8000000, 4000000, 8000000)):
            spi.init(baudrate=cfg["spi_init_hz"])
            cfg["spi_hz"] = hz
            can.initialize()
            can.start(loopback=True)
            can.disable_rx()
            if (can.reg(CON) >> 21) & 7 != 2:
                raise RuntimeError("INTERNAL_LOOPBACK_REQUIRED")
            results = []
            for label, function in (
                    ("clock_baseline", lambda: None), ("register_read", lambda: can.reg(CON)),
                    ("coherent_now_us", can.now_us), ("status_read", can.read_status),
                    ("crc_76bytes", lambda: crc16(payload)),
                    ("encode_rx64", lambda: encode(obj)),
                    ("parse_rx64", lambda: strict_json(raw)), ("gc_collect", gc.collect)):
                results.append(measure(label, function, can))
            # 出力は計測区間の外。設定値を実測クロックと混同しない。
            print(json.dumps({"type": "PERF_PROBE", "round": index + 1,
                              "spi_requested_hz": hz, "mode": "internal_loopback",
                              "heap_free": gc.mem_free(), "results": results}))
    finally:
        spi.init(baudrate=cfg["spi_init_hz"])
        can.reset()
        print("PERF_PROBE_STOPPED")
    print("PERF_PROBE_PASS")


run()
