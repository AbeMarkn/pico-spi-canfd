"""保守状態のPicoで、2本のCDCを別々に使って帯域だけを測る。"""
import subprocess
import threading
import time

import serial

connection = serial.Serial("/dev/cu.usbmodem2303", 115200, timeout=0.01)
stop = threading.Event()
received = 0


def reader():
    global received
    while not stop.is_set():
        received += len(connection.read(4096))


t = threading.Thread(target=reader)
t.start()
try:
    subprocess.run([".venv/bin/mpremote", "connect", "/dev/cu.usbmodem2301", "resume",
                    "run", "tools/pico_usbbench.py"], check=True, timeout=15)
    time.sleep(0.3)
finally:
    stop.set()
    t.join(1)
    connection.close()
print("HOST_RECEIVED", received)
