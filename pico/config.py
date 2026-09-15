"""DESN-SW-002/HW-003/005: 機器設定。電気測定済みという意味ではない。"""

CONFIG = {
    "schema": 1,
    "device_config_id": "pico-mcp2518fd-20m-v1",
    "oscillator_hz": 20000000,
    "electrical_verified": False,
    "spi_id": 0,
    "sck": 18,
    "mosi": 19,
    "miso": 16,
    "cs": 17,
    "int": 26,
    "clk": 20,
    "int0": 21,
    "int1": 22,
    "spi_init_hz": 1000000,
    "spi_hz": 8000000,
    "nominal_bitrate": 500000,
    "data_bitrate": 2000000,
    "watchdog_ms": 2000,
    "heartbeat_timeout_ms": 1000,
}
