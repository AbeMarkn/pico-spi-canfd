"""DESN-SW-013: 専用のUSB保守操作。CAN試験中はREPLを操作しない。"""
import argparse
import time

import serial
from serial.tools import list_ports


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("start", "console", "interrupt"))
    parser.add_argument("--port")
    args = parser.parse_args()
    ports = sorted(p.device for p in list_ports.comports() if p.vid == 0x2E8A)
    port = args.port or (ports[0] if ports else None)
    if port is None:
        raise SystemExit("Pico REPLが見つかりません")
    print(port, flush=True)
    connection = serial.Serial(port, 115200, timeout=0.1, write_timeout=1)
    try:
        if args.operation == "start":
            connection.write(b"\x02\x04")  # friendly REPLでsoft reset、main.py実行。
        elif args.operation == "interrupt":
            connection.write(b"\x03")
            time.sleep(0.1)
            # native実行中のCtrl-Cがアプリのexceptを迂回した場合にも、
            # REPLからCANをSPI RESETし、WDT再起動より前に保守起動を確定。
            connection.write(b"\x01")
            time.sleep(0.1)
            connection.write(
                b"import machine,time; "
                b"s=machine.SPI(0,baudrate=1000000,sck=machine.Pin(18),"
                b"mosi=machine.Pin(19),miso=machine.Pin(16)); "
                b"c=machine.Pin(17,machine.Pin.OUT,value=1); "
                b"c(0); s.write(b'\\x00\\x00'); c(1); time.sleep_ms(3); "
                b"f=open('.maintenance','w'); f.write('1'); f.close(); machine.reset()\x04"
            )
        end = time.monotonic() + 3
        while time.monotonic() < end:
            data = connection.read(1024)
            if data:
                print(data.decode("utf-8", "replace"), end="", flush=True)
    except (OSError, serial.SerialException) as exc:
        print("USB再列挙:", str(exc))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
