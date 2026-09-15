"""DESN-HW-005: 実機診断用。受信のみ、有限5秒、終了時Configに戻す。"""
from machine import Pin, SPI
import time
import rp2
from config import CONFIG
from mcp2518fd import MCP2518FD


@rp2.asm_pio()
def count_edges():
    mov(x, invert(null))
    label("edge")
    wait(1, pin, 0)
    wait(0, pin, 0)
    jmp(x_dec, "edge")


for n in (20, 21, 22, 26):
    Pin(n, Pin.IN)
spi = SPI(0, baudrate=1000000, polarity=0, phase=0,
          sck=Pin(18), mosi=Pin(19), miso=Pin(16))
can = MCP2518FD(spi, Pin(17, Pin.OUT, value=1), CONFIG)
try:
    print("INITIAL", can.initialize())
    sm = rp2.StateMachine(7, count_edges, freq=125000000, in_base=Pin(20))
    start = time.ticks_us()
    sm.active(1)
    time.sleep_ms(100)
    sm.active(0)
    elapsed = time.ticks_diff(time.ticks_us(), start)
    sm.exec("mov(isr, x)")
    sm.exec("push()")
    edges = (0xFFFFFFFF - sm.get()) & 0xFFFFFFFF
    print("CLKO", edges, elapsed, "Hz", edges * 1000000 // elapsed)
    print("GPIO", [(n, Pin(n).value()) for n in (20, 21, 22, 26)])
    print("START_LISTEN", can.start(listen_only=True))
    start = time.ticks_ms()
    count = 0
    while time.ticks_diff(time.ticks_ms(), start) < 5000:
        frame = can.receive()
        if frame:
            count += 1
            if count <= 10:
                print("RX", frame)
        time.sleep_ms(1)
    print("COUNT", count, "FINAL", can.read_status())
finally:
    can.disable_rx()
    can.mode(4)
    print("STOPPED", can.read_status())
