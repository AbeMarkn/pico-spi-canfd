# 参照資料・出典・謝辞

文書版: `0.1.0`。資料調査日: 2026-09-13。前版までのN947再確認・現物測定方法に加え、今回はPython／MicroPythonの公式最新安定版を確認。調査日はテスト実施日ではない。

## 1. 入力資料

- REF-001: ユーザー添付の開発・設計プロンプトと基板写真。MCP2518FD、ATA6563の刻印、P1配線表、P2／P3説明を読取り。メーカー原本の回路図ではない。水晶の「0200」に見える刻印から20 MHzを候補とするが、周波数確定には使わない。
- 写真は会話添付を出典とし、今回のリポジトリに画像ファイルは複製していない。部品の真贋、基板型番、内部の配線・保護回路は画像から保証できない。

## 2. 一次資料

- REF-002: Microchip [MCP2518FDデータシート DS20006027B](https://ww1.microchip.com/downloads/aemDocuments/documents/OTH/ProductDocuments/DataSheets/External-CAN-FD-Controller-with-SPI-Interface-DS20006027B.pdf)。参照箇所: §1.2／§1.3（端子・3.3 V接続例）、§3（レジスタ・RAM・メッセージ形式）、§4（SPI）、§5（クロック）、§6（IO）、表7-6（SPI条件）。CLKとSCKの区別、INTの極性・出力形式、設定値の根拠。表7-6の制限を冒頭の最大SPI表記より優先する。
- REF-003: Microchip [MCP25XXFDファミリリファレンスマニュアル DS20005678E](https://ww1.microchip.com/downloads/aemDocuments/documents/OTH/ProductDocuments/ReferenceManuals/MCP25XXFD-CAN-FD-Controller-Module-Family-Reference-Manual-DS20005678E.pdf)。参照箇所: 表1-1（DLC）、§2（動作モード）、§3.4／§3.5（ビットタイミング・RAM）、§4.10／§4.14（送信中止とFIFOリセット）、§5（TEF）、§7（受信）、§10／§11（割り込み・異常）。
- REF-004: Microchip [MCP2518FDエラッタ DS80000789E](https://www.microchip.com/content/dam/mchp/documents/APID/ProductDocuments/Errata/MCP2518FD-Errata-DS80000789.pdf)。2023年11月改訂。項目1〜6とCRCレジスタ補足を確認。設計ではREAD_CRC、有限再読出し、ECC異常停止、単一バイトIOCON書込み、SPI速度制限、FIFO状態の妥当性確認に反映する。
- REF-005: Microchip [ATA6562/3データシート DS20005790E](https://ww1.microchip.com/downloads/en/DeviceDoc/ATA6562.3-Data-Sheet-20005790E.pdf)、[ATA6563製品ページ](https://www.microchip.com/en-us/product/ATA6563)。端子図・VIO・Standby・CAN FD対応を検索抽出で確認。PDF全文の直接取得は失敗したため、全電気表を確認済みとはしない。今回、ピン表・STBY・電気表は公式[DS20005790C 表1-2／表2-1](https://ww1.microchip.com/downloads/en/DeviceDoc/ATA6562-6563-High-Speed-CAN-Transceiver-with-Standby-Mode-20005790C.pdf)の本文抽出で照合した。E版の全文確認とは区別する。実物品番に適用される最新電気条件の全文照合はOPEN-005。
- REF-006: Raspberry Pi [Pico公式資料](https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html)。非無線Picoのピン図、GP25、電源端子を参照。[Picoデータシート](https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf)は直接取得できず、電源の利用可能電流を未確認事項として残す。
- REF-007: MicroPython [USBDevice v1.26.0](https://docs.micropython.org/en/v1.26.0/library/machine.USBDevice.html)、[割り込み処理](https://docs.micropython.org/en/latest/reference/isr_rules.html)、[select](https://docs.micropython.org/en/latest/library/select.html)。実行時USB構成、再起動時の再列挙、IRQ内の制約を参照。latest文書は開発版であり、採用版の保証に使わない。この項目は初期設計時の調査資料。今回の採用版選定とUSBDeviceの版付き確認はREF-016を参照。
- REF-008: MicroPython公式 [usb-device-cdcの実装](https://github.com/micropython/micropython-lib/blob/9ec1830baa96aa8cad12324f45ff9f952016aac7/micropython/usb/usb-device-cdc/usb/device/cdc.py)。調査時commit `9ec1830baa96aa8cad12324f45ff9f952016aac7`。`write`の部分書込みと`timeout`、`readinto`、`ioctl`を参照。これは調査版であり、MicroPython本体の採用方針はOPEN-008で決定済みだが、同じcommitを実装時にも採用した。
- REF-009: Python [Tkinter公式文書](https://docs.python.org/ja/3/library/tkinter.html)、[pySerial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html)。GUIのイベント処理とシリアル読書きタイムアウトの根拠。
- REF-010: [SemVer 2.0.0日本語公式文書](https://semver.org/lang/ja/)。公開API、0.y.z、1.0.0、互換性、プレリリース、公開済み版の不変性を参照。文書変更によるPatch更新などは本プロジェクト独自規則として区別する。

## 3. 指定された既存リポジトリ

### REF-011: pwm_50hz_pico

[参照commit](https://github.com/AbeMarkn/pwm_50hz_pico/tree/c2518c391a403b97b78d7ea3fe3327312a7b9ff9): `c2518c391a403b97b78d7ea3fe3327312a7b9ff9`。

README、`docs/interface_HW.md`、`docs/interface_SW.md`、`main.py`、`pwm_controller.py`を読んだ。GP0は50 Hz PWM、GP1〜GP4はDIP、GP25はLED。起動LED点灯0.5秒、待機1秒、値に応じた点滅、追加待機1秒、運転中1秒待機がある。100%ではPWMを解除して固定Highとする。

**設計への反映**: GP0〜GP4とGP25を予約する。PWM出力はハードウェアに任せ、同居時の長い待機を状態と期限による進行へ変える必要がある。PWMの開始順、停止・例外動作は既存仕様を維持する方法を別途決定する。別リポジトリの「実機確認済み」はこのシステムの試験結果ではない。

### REF-012: N947_CAN_test

[参照commit](https://github.com/AbeMarkn/N947_CAN_test/tree/5759ae46ab5f21e1b760e862c70bab2b36af38ef): `5759ae46ab5f21e1b760e862c70bab2b36af38ef`。アクセス権が必要なリポジトリ。ユーザー指定範囲の設定・ソースを認証済みGitHub APIで読取り、外部検索へ内容を送信していない。

最新HEADをGitHub APIで再取得し、参照commitと同一であることを確認。`source/app_config.h`と、それを使用する`source/flexcan_loopback_test.c`の関連箇所を再確認。調停500000 bit/s、データ2000000 bit/s、BRS有効、DLC15（64バイト）、標準ID 0x100／0x200、周期100／500 ms。タイムアウト1000 ms、動作時間0は無期限という設定がある。

**設計への反映**: ユーザー回答に従い調停500 kbit/s・FDデータ2 Mbit/s、FDサンプルBRS=1を採用する。周期送信、エラーカウンタの観点も参考にする。今回の最大時間の要求から無期限既定値は引き継がない。MCXN947のFlexCANレジスタ値や自動算出結果をMCP2518FDにコピーしない。同リポジトリには別のSDK例`flexcan_interrupt_transfer.c`もあり、設定の異なる例を今回の正本と混同しない。

`docs/interface_HW.md`も再確認。N947のCAN0／CAN1は共通バスで、CAN0側と外付けCAN1側に各120 Ωの終端を置く記述がある。今回の相手2台がこの2チャネルに相当する場合の接続参考とする。先行プロジェクトの実測記録を今回の3台構成の試験結果として流用しない。

## 4. 追加確認資料

- REF-013: Bosch [CAN FD Protocol](https://www.bosch-semiconductors.com/products/ip-modules/can-protocols/can-fd/)、Microchip [CAN Peripherals](https://www.microchip.com/en-us/products/microcontrollers/8-bit-mcus/peripherals/communication-connectivity/can)。FDコントローラによるClassical通信と、Classical専用コントローラへFDフレームを流した場合のエラーについて確認。MCP2518FDの具体的な混在モードはREF-003 §2が正本。
- REF-002 CiTDCとREF-003 §3.4を再参照し、自動TDCのSSPが測定遅延とオフセットの和になることを確認。20 MHz・2 Mbit/s用のTDCO=8は設計上の初期計算値であり実測値ではない。
- REF-012の同一commitにあるInitFlexCANChannelで、受信は標準IDの完全一致であることを確認。送信速度の一致、相手のCAN ACK、相手アプリの受信は別の確認項目とする。

- REF-014: Texas Instruments [TCAN CAN EVM User Guide §2.2](https://www.ti.com/lit/ug/sllu231/sllu231.pdf)。二つの120 Ωによる60 Ω負荷と終端構成の根拠。約120／60／40 Ωの目安は抵抗の並列計算であり、実測結果ではない。
- REF-002のOSC／IOCON初期値を再確認。PLL無効、CLKO分周10、SOF無効を前提としたP1-2での周波数確認手順を追加。基板の導通と電源投入リセットの成立は別に確認する。

- REF-015: Python公式[ダウンロード一覧](https://www.python.org/downloads/)と[CPython 3.14.7リリース](https://www.python.org/downloads/release/python-3147/)。2026-09-13時点の最新安定版は3.14.7（2026-08-05公開）。3.15はプレリリースとして区別した。ホスト用Pythonの選定根拠であり、指定OS上で本アプリを実行した結果ではない。
- REF-016: MicroPython公式[初代Pico用RPI_PICOダウンロード](https://micropython.org/download/RPI_PICO/)。2026-09-13時点の最新安定版は1.29.0（2026-08-24公開）、1.30.0-previewは開発版。1.29.0のUSBDevice HTML文書は直接取得できなかったため、公式GitHubの[v1.29.0タグのUSBDevice文書](https://github.com/micropython/micropython/blob/v1.29.0/docs/library/machine.USBDevice.rst)を読んでRP2対応・boot.py構成・soft reset時の再列挙を照合した。採用UF2とusb-device-cdcのmacOSでの実通信結果は結果書へ別記する。

OS無し／ベアメタル、macOS Tahoe 26.6.2、Windows 11は今回のユーザー指定を出典とする。ここではローカルPCのOSを測定・変更しておらず、申告版を別の版へ読み替えていない。

## 5. 出自と謝辞

AbeMarkn氏の二つの先行プロジェクト、Microchip、Raspberry Pi、MicroPython、Python、pySerialの公開資料を設計判断の参考にした。MCP2518FDドライバはデータシートを根拠とした本プロジェクトの実装で、FlexCANドライバを移植していない。公式USB依存は以下のとおり同梱し、原ライセンスと著作権表記を維持する。

### 同梱依存とローカル修正

micropython-lib commit `9ec1830baa96aa8cad12324f45ff9f952016aac7`のusb-device、usb-device-cdcを採用。配置は`pico/lib/usb/device/__init__.py`、`core.py`、`cdc.py`。MITライセンスを`pico/lib/LICENSE-micropython-lib.txt`に同梱する。原ソースの英文コメント・権利表示は原文を維持し、自作部分の説明は日本語とする。

`core.py`だけ、Buffer.finish_read／finish_write内のPythonによるバイト移動を、割込み禁止中に割り当てないViperの前方移動関数へ置き換えた。重なりを含む移動方向、部分読出し、保留中のproducer書込みの意味を維持し、実機のBuffer検証とUSB単体転送を行った。変更前core.pyのSHA-256は`b1402506cda2ac3dbd0d488d63fc9c1cd9c1d62c35cf3ffabb4d37e85941db8b`、同梱版は`9801c923f268579a0077c9d95f5e71e0982f0506a260e7f68e14e0aa0ff88392`。その他ファイルのSHAは配置記録を参照。

UF2は`RPI_PICO-20260824-v1.29.0.uf2`、SHA-256 `e1160e602e277d85920adb5fe741435edccba9ba6ecadc85fdab75252eeff4e9`。MicroPython旧1.27.0から更新した。ホストCPython 3.14.7はプロジェクト内`.tools`と`.venv314`へ導入し、システムPythonを置き換えていない。
