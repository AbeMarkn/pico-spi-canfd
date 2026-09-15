# 実装・実機評価結果 第001回

文書／Firmware／Host Version: `0.1.0`（未リリースの開発版）。実施: 2026-09-13〜14 JST。Tester: Codexによる自動実行。配線条件と対向機稼働はユーザー提供。

**総合判定: 受入未完了。通信・停止の実施条件はPass、周期性能はFail、電気測定・Windows・GUI操作適合等は未実施。** 設計した73 Test IDとpytestのパラメータ展開後のケース数は別である。

## 1. 対象と環境

- Git基点: `e0457c3d91e4e3e5f9169fc710bb2b6414c87fed`。実装は未コミット。基点commitだけを実行ソースの識別に使わず、ログヘッダの`source_sha256`と[配置読戻し](device-manifest-001.json)で識別する。
- Hardware Version: 初代Raspberry Pi Pico、RP2040、125 MHz。写真のMCP2518FD／ATA6563モジュール。モジュール基板revision・製造情報は不明。
- Pico USB: VID `2e8a`、PID `0005`、serial `e660c062131e5629`。試験時REPL `/dev/cu.usbmodem2301`、アプリCDC `/dev/cu.usbmodem2303`。
- macOS Tahoe 26.6.2、build `25G83`、arm64。OS版は`sw_vers`で確認。CPython 3.14.7、Tk 9.0、pySerial 3.5。Windows 11は未実施。
- MicroPython 1.29.0、`RPI_PICO-20260824-v1.29.0.uf2`。SHA-256 `e1160e602e277d85920adb5fe741435edccba9ba6ecadc85fdab75252eeff4e9`。旧1.27.0から更新。既存PWMファイルをホスト`.device-backup-20260913/`へバックアップ済み。
- ツール: pytest 9.1.1、pytest-cov 7.1.0、Ruff 0.16.7、mpremote 1.29.0。USB依存の出自と修正は[参照資料](../../references.md)。
- 対向設定: N947_CAN_test commit `5759ae46ab5f21e1b760e862c70bab2b36af38ef`を参照。調停500 kbit/s、FDデータ2 Mbit/s、BRS=1。参照リポジトリは変更していない。
- 構成はユーザー申告で3ノード、CAN配線30 cm以内、自ノードP3開放・120 Ω非実装。H–L抵抗、各電圧、波形、STBY配線、保護性能は測定していない（OPEN-005）。

## 2. 実施コマンドと判定

### 実機なし自動: Pass（79ケース）

```sh
.venv314/bin/pytest -q --cov=pico --cov=host --cov-branch --cov-report=json:docs/test/results/coverage-001.json --cov-report=term
.venv314/bin/ruff check pico host tools tests
```

2026-09-14、79 passed、実機2ケースは明示ポートなしのためskip。RuffはAll checks passed。

対象は設定型・ID／合法長、JSONの重複キー・上限、CRC既知ベクトル、SPIの3回上限と復帰、独立期待バイト列のSID/EID・DLC、時刻周回、4スロット・5件目拒否、同一ID置換・別名同一データの重複抑制、停止世代、セッション再送、期限の半開区間、heartbeat、キュー満杯、部分書込み、ログ3ファイルの排出・保存失敗、再接続時の旧ログ排除、キー保持／再押下の抑制。

対応する計画の部分: TEST-DESN-001〜005、008〜009、012〜014、021〜027、TEST-SPEC-001、003〜005、008〜009、021〜025。これらの計画の全条件を実行したという意味ではない。各関数の実施内容は`tests/`が正本。

[カバレッジ](coverage-001.json): CPythonで観測した文863/1682＝51.31%、分岐302/702＝43.02%。ネイティブMicroPythonや実機SPI部分、Tkの画面描画はこの計測に含まれない。未到達のGUI・USB worker・ドライバ経路が残る。網羅率を十分と判断した記録ではない。

### 内部ループバック: Pass（50条件、外部受信の代用にはしない）

2026-09-13、保守REPLから`tools/pico_loopback.py`を実行。標準／拡張の各IDについてClassical 0〜8バイト、FD全16合法長を往復し、ID・FDF・BRS・データを照合した。FDのBRSはtrue。

実出力: `INTERNAL_LOOPBACK_PASS 50`、TEC=0、REC=0、RX overflow=0、CRC retry=0、mode=2。finallyで`STOP_MODE 4`を確認。TEST-SPEC-103、TEST-DESN-002／108の補助検証。Normalモードの外部全長受信、FD BRS=0、波形・TDCの試験は未実施。

MicroPython専用JSON／CRC／USB Bufferの`tools/pico_selftest.py`も成功。USB単体は3,000,466 usで471,040バイトを送り、ホスト受信も471,040バイトだった（約157 kB/s）。これはCAN混在時の保証帯域ではない。

### 実バスの制御操作: Pass（2ケース）

```sh
.venv314/bin/pytest -q tests/test_hardware.py --can-port /dev/cu.usbmodem2303 -s
```

初回: 2026-09-13 23:33 JST、2 passed。最終配置後の再実施: 2026-09-14 07:53 JST、2 passed in 2.67s。

- START_SESSIONの同一req／同一本文再送でsession_id・開始時刻・期限が不変。受信のみで開始し、明示STARTまで送信なし。
- T1開始、重複開始、同一IDのT1B（31〜38）への置換、世代0の旧開始拒否、ID停止、世代2で再開を確認。
- ID_STOPPED後の観測150 msで対象TX_DONEなし。全停止後のSTATUSはactiveなし、Configuration mode=4。TX/RXログ件数と機器集計が一致。
- 全停止要求から最終通知まで70.86 ms（初回72.38 ms）。USB往復・排出を含むホスト測定で、外部波形による停止時刻ではない。
- heartbeat送信を止め、CDCの読み取りだけを継続。831.20 msでHEARTBEAT_LOSTの終了通知（初回800.30 ms）。最後のheartbeatからの1秒期限の残り時間を観測した値。再接続・STATUSだけで自動送信しない。

対応: TEST-SPEC-104／124／127、TEST-DESN-004／008／023の制御操作部分、TEST-SPEC-122の生存監視部分。停止操作を全調停位相へ注入した試験、USBケーブル物理断、他ID継続の全組合せ、標準／拡張同値IDの実バス試験は未実施。

証拠は`evidence-001.zip`内の`logs/hardware/20260913-233346-033797`、`233347-003760`、`20260914-075301-503399`、`075302-478658`。

## 3. 指定4 ID・120秒の実通信

対応: TEST-SPEC-110、TEST-DESN-103／105／108。**通信内容・保存・期限終了は実施条件でPass。周期目標はFail。対向アプリ受信・波形・GUIの照合を含む計画全体は未完了。**

実施: 2026-09-14 07:41:49〜07:43:49 JST。コマンドは`python -m host.main --headless --port /dev/cu.usbmodem2303 --duration 120`。GUIは操作ツールがウィンドウを取得できなかったため本測定に使っていない。

設定T1〜T4、受信有効化から120秒。結果は`failure=null`、終了理由DURATION、RX=1,440、TX_DONE=9,977、TX_FAILED=0、周期skip=3,351、dropped=0、stop_confirmed=true、drain_complete=true。

- T1: 標準0x300、Classical8、10 ms。完了8,645件。TXREQ直前時刻の間隔は最小6,666／平均13,875.99／最大44,892 us。
- T2: 標準0x301、Classical8、100 ms。完了1,200件。間隔74,286／99,987.11／130,262 us。
- T3: 拡張0x18FF0101、FD64、1000 ms。完了120件。間隔982,827／999,891.81／1,021,693 us。
- T4: 拡張0x18FF0102、FD64、10000 ms。完了12件。間隔9,983,955／9,999,323.36／10,018,108 us。

TEFのSEQ重複なし、TXログのID・形式・データ・周期が全件configに一致。各T1〜T4の`txreq_us >= deadline_us`は0件。RXは0x100が1,200件（00×64）、0x200が240件（FF×64）。全1,440件の形式・内容・受信時刻の半開区間を照合した。固定payloadのため、対向の連番による独立した全生成数の証明ではない。

終了直前のNormalモードでTEC=0、REC=0、bus_off=false、RX overflow=0、BDIAG0=0、ECC=0。SPI CRCの再読出しは2回あり、いずれも復帰した。**CANエラー0をSPI再試行0という意味には使わない。** 停止時にConfiguration modeへの遷移を確認してから終了通知を送っている。

`TX_DONE`はNormalモードのTEFによる外部バス送信成功の確認。N947のアプリ受信フィルタはPicoの暫定IDに対応しておらず、相手アプリが全送信データを復号・保存した証拠は取得していない。外部からのClassical受信も未実施。

### Failure analysis: 周期性能

T2は1,200回すべてで、予定期限から**送信処理着手まで**が2 msを超えた。最大35,736 us。TXREQの実反映を待つ前の段階で既に目標を超えているため、100 ms±2 ms目標は未達と判断する。500 msの独立条件は未測定。新しい10／1000／10000 msの許容ジッタはOPEN-015で未決だが、T1の周期skipは明記する。

`txreq_us`はWRITE_SAFE発行直前のTBC読値、`late_us`は予定期限から処理着手まで。GPIO／CAN波形で捕捉したTXREQ反映時刻ではない。Pythonの協調処理、JSON／USBとGCの処理時間が影響すると考えられるが、内訳の厳密な上限は未確定。GCを期限で遅延させた試作は12秒でTX_DONE=685／skip=646となり悪化したため不採用。現在はGC有効・有限キュー・追送なしを維持する。要求周期を遅い値へ変更して合格にしていない。

## 4. 証跡・配置・未実施

- [生ログと120秒試験時ソース](evidence-001.zip)
- [再集計結果・全ソースSHA](analysis-120s-001.json)。`tools/analyze_logs.py`で再実行可能。
- [最終Pico配置読戻し](device-manifest-001.json): 8/8ファイルのSHA-256一致、Configuration mode=4。120秒試験後は自作関数へ設計IDのコメントだけを追加し、AST不変を確認した。最終配置で実CAN2ケースを再実行した。
- [CPythonカバレッジ](coverage-001.json)。MicroPython実機の網羅率ではない。

GUIプロセスの起動は成功したが、操作ツールがPythonアプリを取得できず、外観・実キー・描画遅延の適合は未確認。キー状態は3ケースの実機なし試験で確認した。GUIプロセスは今回起動したものだけを終了済み。

電圧・抵抗・オシロ波形、BRS=0の外部実通信、外部Classical受信、相手アプリ受信、Windows 11、ホスト交換、電源断耐性、バスオフ故障注入、SPI物理断、最大24時間、最大受信負荷、PWM統合は未実施。TEST-SPEC-106／107／108／121／201、TEST-DESN-102／104／107／121／122／201等に関連する。**ここで実施内容を明記していない計画条件は未実施**とする。

最終状態はPicoアプリが待機し、CANはConfiguration mode、稼働送信IDなし。利用者の新しいセッション開始を待つ。OPEN-005／010／011／012／015／018を残し、正式受入の完了は宣言しない。
