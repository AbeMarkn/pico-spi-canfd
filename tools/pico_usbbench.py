"""CAN停止中にアプリCDCだけの実効転送を3秒測定する。"""
import time
import usb.device

cdc = usb.device.can_cdc
data = b"A" * 255 + b"\n"
offset = sent = 0
start = time.ticks_us()
while time.ticks_diff(time.ticks_us(), start) < 3000000:
    if cdc.ioctl(3, 4) & 4:
        n = cdc.write(memoryview(data)[offset:]) or 0
        sent += n
        offset = (offset + n) % len(data)
    time.sleep_us(50)
print("USB_ONLY", sent, "bytes in", time.ticks_diff(time.ticks_us(), start), "us")
