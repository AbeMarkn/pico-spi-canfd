# pico-spi-canfd

開発版 `0.1.0`。初代Pico＋MCP2518FDを使い、PCからClassical CAN／CAN FDを送受信します。実装をPicoへ配置し、N947との実通信を検証しました。**周期精度は従来目標に未達ですが、2026-09-14のユーザー指示により、実測値・制限を明記する条件で現状性能を許容します。GUI・停止・再接続等の受入確認は継続中です。** [実施結果](docs/test/results/TEST-SPEC-DESN_result_001.md)と[未決事項](docs/open_item.md)を参照してください。

## 利用者向け

### 概要・必要環境

受信はCAN ID・標準／拡張・Classical／FD別にGUIでHEX表示します。送信はキーまたはボタンで開始・停止します。`tx.txt`、`rx.txt`、`error.txt`をセッションごとにPCへ保存します。

- 初代Raspberry Pi Pico（Wi-Fiなし）、MCP2518FD／ATA6563モジュール、USBデータケーブル。
- CANはN947に合わせ、調停500 kbit/s、FDデータ2 Mbit/s、BRS有効。
- 導入済み評価環境: macOS Tahoe 26.6.2（25G83、arm64）、CPython 3.14.7、Tk 9.0、MicroPython 1.29.0。Windows 11は対象ですが未検証。
- [配線](docs/interface_HW.md): ユーザー申告では3ノード、CAN配線30 cm以内、自ノードP3開放・120 Ω非実装。既存の両端で終端を担当します。

電圧・抵抗・波形の測定は指定どおり後日に保留しています。通信成功を電気条件の検証済みとは扱いません。

### 起動と操作

このワークスペースでは次で起動できます。

```sh
.venv314/bin/python -m host.main
```

1. 「セッション開始」を押します。設定転送・検証とログ準備後に受信を有効化します。制限時間は初期60秒です。
2. 各キー／ボタンで周期送信を開始・停止します。
   - `a`／`b`: T1、標準 `0x300`、Classical 8バイト、50 ms。
   - `c`／`d`: T2、標準 `0x301`、Classical 8バイト、500 ms。
   - `e`／`f`: T3、拡張 `0x18FF0101`、FD 64バイト、1000 ms。
   - `g`／`h`: T4、拡張 `0x18FF0102`、FD 64バイト、10000 ms。
3. 画面の受付内容・状態を確認します。同じ稼働データの再入力ではジョブを増やしません。同一IDの別データは旧送信の終了後に置き換えます。
4. `Esc`／「全停止」、時間満了、ウィンドウを閉じる操作で停止・ログ排出します。再接続だけでは送信を自動再開しません。

送信データは[host/config.py](host/config.py)の空白なし大文字HEXで変更します。Classicalは0〜8バイト、FDは0〜8／12／16／20／24／32／48／64バイト。9バイトなどを暗黙に補正しません。標準／拡張IDとClassical／FDの選択は独立しています。RTR送信は対象外です。

### 通信結果と注意事項

- `TX_ACCEPTED`は周期送信要求の受付、`TX_DONE`はTEFで確認した送信成功です。Normalモードの成功は対向ACKを伴います。
- N947から標準 `0x100`（FD64、00埋め、100 ms）と `0x200`（FD64、FF埋め、500 ms）を受信します。
- N947の現行アプリは相互の `0x100`／`0x200`を受信する設定です。Picoの暫定IDを相手アプリが受け取ったことまでは確認していません。N947コードは変更していません。
- 終了時の`dropped`、`stats`、`stop_confirmed`、`drain_complete`とホストの`failure`を確認します。`skipped`は周期の未投入数で、ログ欠落数とは別です。
- バスオフ・SPI／ECC異常・保存失敗・heartbeat喪失時は停止します。PicoだけのリセットやSPI断で外付けCANの物理的な即時停止を保証する設計ではありません。
- Classical専用機器がいるバスへFDを流す場合は、その機器の対応モードを確認してください。PicoのGPIOは5 V入力に対応しません。

## 開発者向け

### 構成・資料

自作の実行コードはPico側5ファイル（boot、config、common、main、mcp2518fd）、ホスト側2ファイルです。`common.py`をホストからも参照します。PicoはOS／RTOSなし、単一コアの協調ループ。ホストはTk主スレッド、USB worker、ログworkerを分離しています。

- [仕様](docs/Specification.md)／[設計](docs/Design.md)／[ソフトウェアIF](docs/interface_SW.md)
- [参照元・謝辞](docs/references.md)／[バージョニング](docs/versioning.md)
- [試験計画](docs/test/Test_common.md)／[Traceability](docs/test/Traceability_Matrix.md)／[レビュー](docs/review.md)

### セットアップ・ビルド

ソースの事前コンパイルと独自UF2ビルドは不要です。評価時に公式の[CPython 3.14.7](https://www.python.org/downloads/release/python-3147/)と[MicroPython 1.29.0 RPI_PICO](https://micropython.org/download/RPI_PICO/)を選定しました。Tkinterが利用できるPythonを用意します。

```sh
python3.14 -m venv .venv314
.venv314/bin/python -m pip install -r requirements-dev.txt
.venv314/bin/python -m tkinter
```

Windowsでは`py -3.14 -m venv .venv314`を使い、`.venv314/bin/python`を`.venv314\Scripts\python.exe`へ読み替えます。Windows実動作は未検証です。通常利用の依存は`requirements.txt`、開発用は`requirements-dev.txt`です。

### Flash・配置・更新

初回は既存ファイルをバックアップし、BOOTSELから初代Pico用の公式UF2を書き込みます。評価機の旧PWMファイルは`.device-backup-20260913/`へ退避済みです。PWMとの同居は未実装です。

以下は評価機のREPLポートを使った更新例です。番号は再列挙で変わり得ます。GUIを停止してから実行します。

```sh
.venv314/bin/python tools/device.py interrupt
.venv314/bin/mpremote connect /dev/cu.usbmodem2301 resume fs cp pico/boot.py pico/config.py pico/common.py pico/main.py pico/mcp2518fd.py :
.venv314/bin/mpremote connect /dev/cu.usbmodem2301 resume fs cp -r pico/lib :
.venv314/bin/python tools/device.py start
```

新規MicroPythonへの初回配置では`interrupt`は不要です。依存の配置先が`/lib/usb/device/`になっていることを確認します。この環境には旧ツール用`.venv/bin/mpremote`もあります。

`interrupt`はCAN停止後、一度だけWDTなしの保守REPLへ再起動します。USB再列挙による切断表示は起こり得ます。再列挙後は`resume`で接続してください。転送は複数ファイルに対して原子的ではないため、一式を転送・読戻し照合してから起動します。通信中のREPL操作は測定に使いません。

同梱USB依存は公式`micropython-lib`の固定commitです。割込み禁止中のバッファ移動をViperへ変更したローカル修正があります。[原ライセンス](pico/lib/LICENSE-micropython-lib.txt)を維持し、出自・変更を[参照資料](docs/references.md)へ記載しています。

### CLI・設定・ログ

```sh
.venv314/bin/python -m host.main --port /dev/cu.usbmodem2303 --duration 60
.venv314/bin/python -m host.main --headless --port /dev/cu.usbmodem2303 --duration 120
```

CLIは`--port`、`--config`、`--duration`（1〜86400秒）、`--headless`。ポート省略時はPicoのCDCを探索します。`--headless`だけは設定パターンを自動開始します。GUIは受信開始後、キーで送信を開始します。ホスト設定は`CONFIG`への辞書リテラル代入のみを許可し、任意Pythonコードを実行しません。

制御設定はPico、送信設定とログ先はホストの`config.py`です。送信パターンは準備時にPicoのRAMへ転送し、フラッシュへ保存しません。ログは`log_dir/日時/`の3ファイル。先頭2行が`#`付き日本語ヘッダ、以降がJSON Linesです。配置元ソースSHA-256、設定、版をヘッダに記録します。開始ACK以降は各行の`boot_id`・`session_id`で所属を識別し、機器集計と保存受付件数を照合します。100 ms flush、1秒fsync、終了時fsyncを実装しています。停電時の損失上限は未検証です。

### テスト・デバッグ

```sh
.venv314/bin/pytest -q
.venv314/bin/ruff check pico host tools tests
.venv314/bin/pytest -q tests/test_hardware.py --can-port /dev/cu.usbmodem2303 -s
```

通常pytestでは実機2試験をskipします。`--can-port`付き試験は実CANへ送信するため、対向設定を合わせ、GUIを閉じて実行します。内部ループバックは保守REPLから`mpremote ... resume run tools/pico_loopback.py`で実行します。外部対向機での受信試験とは別です。

### トラブルシューティング・制限

- 接続不能: ポート占有、アプリCDCとREPLの取り違え、USB再列挙を確認。
- 設定拒否: ID・HEX・合法長・周期・キーを修正して再起動。全件有効になるまでセッションを開始しません。
- 受信なし／TX失敗: N947の動作、500 k／2 M、CANH／CANL／GND、終端、TEC／RECを確認。
- 周期スキップ: 指定4 ID負荷で発生しています。100／500 msの±2 ms評価目標を達成した版ではありません。遅れを隠す追送は行いません。
- 電気測定、Windows 11、GUI操作適合、外部からのClassical受信、相手アプリのPicoデータ受信、停電／高負荷／PWM統合は、結果書に明記した範囲以外は未検証です。

## 2026-09-14 受入方針の変更

現在のロジック・周期性能はユーザーが許容した。性能最適化を優先せず、GUI実操作、停止、再接続、通信断、ログ保存を優先する。120秒試験では送信完了9,977件、受信1,440件、周期スキップ3,351回、ログ欠落0件。T1の10 ms指定に対する投入直前の平均間隔は約13.876 ms、T2の100 ms指定は約74.286〜130.262 ms。これらは測定条件限定の実績で、フル負荷・厳密なリアルタイム性の保証ではない。従来目標のFail記録は保持し、合意による許容と区別する。

GUI追加試験では受信表示、aキー開始、bキー停止を確認した。一方、300秒設定が約36秒でDURATION終了した事象を確認した。原因は未特定で、許容した周期ばらつきとは別の未解決項目。詳細は[第002回結果](docs/test/results/TEST-SPEC-DESN_result_002.md)を参照。

## 2026-09-14 負荷軽減・SPI設定の再評価

ユーザー指示によりT1を10→50 ms、T2を100→500 msへ変更。T3=1000 ms、T4=10000 msは維持。GUI試験用T1Bも50 ms、追加LIMITも500 msとする。SPI定常設定を4→8 MHzへ変更し、初期化時1 MHzは維持する。8 MHzは要求設定値であり、実クロックの計測値ではない。

変更後の実機なし自動試験は79 passed、実機2ケースskip。Ruff通過。**今回の設定はホスト上のファイル更新までで、Picoへの転送・8 MHzでの実通信・GUI再評価は未実施。** USBのopenは成功したがtermios通信設定が権限拒否となり、保守操作は送信前に停止。GUIのアプリ取得もtimeoutした。旧条件の実測値を新条件の測定結果として扱わない。[第003回結果](docs/test/results/TEST-SPEC-DESN_result_003.md)を参照。

## 起動クラッシュの原因と修正（同日追補）
macOSのPicoCANクラッシュ記録（2026-09-14 13:59:19）はDYLD Library missing、libpython3.14.dylib未検出だった。生成バイナリが.tools/python/...という相対依存パスを持ち、通常のアプリ起動時に解決できなかった。tools/macos_app.pyでリンク後にPython dylibの参照先を絶対パスへ修正し、アドホック署名を更新するよう変更。再生成後otool -Lで絶対参照を確認し、cua.getAppでGUI起動成功、画面上でT1=50 ms、T2=500 msを確認した。通信開始は行っていない。GUI起動障害は解消、ボタン試験は未実施、SPI8 MHzのPico配置は引き続き未実施。
