"""DESN-SW-003: REPLを残し、アプリケーション専用CDCを追加する。"""

import usb.device
from usb.device.cdc import CDCInterface

# 同梱core.pyのデータ移動は、割込み禁止中に割当てないViperループへ修正。
usb.device.can_cdc = CDCInterface(timeout=0, txbuf=2048, rxbuf=1024)
usb.device.get().init(
    usb.device.can_cdc, builtin_driver=True, product_str="Pico SPI CAN FD"
)
