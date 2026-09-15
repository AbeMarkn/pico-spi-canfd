# ソフトウェアインターフェース

文書版: `0.1.0`。開発版の実装インターフェースを記す。検証範囲と制限は[実施結果](test/results/TEST-SPEC-DESN_result_001.md)を参照。PicoはOS／RTOSなし＋MicroPython、ホストは指定Mac／Windows上のCPythonを使用する。対象版の正本はDESN-SW-013。関連: DESN-SW-001〜DESN-SW-014。回答を反映済み。現物・実動作等の確認待ちは[未決事項](open_item.md)に分離する。

## 1. 設定の正本と所有者

### Picoの制御設定（DESN-SW-002、DESN-SW-013）

配置はPico内の`config.py`。機器識別、設定schema版、FW版、発振周波数、SPI0の配線・速度、CAN両フェーズのタイミング、割り込み構成、バッファ上限を保持する。送信データと受信ログをここへ書き込まない。

### ホストの送信設定（DESN-SW-002、DESN-SW-005）

配置はホスト内の`config.py`。一つの設定辞書に次を持たせる。Pythonの任意処理は許さず、許可するリテラル構造だけを検証する。

| フィールド | 型・意味 | 検証／採用制約 |
| :--- | :--- | :--- |
| schema | 整数、設定形式版 | 1に完全一致 |
| revision／device_config_id | 文字列 | 設定一式の版／機器設定識別子。1〜48文字 |
| profiles | 送信パターンの一覧 | 最大32。profile_id重複を拒否 |
| profile_id | 文字列 | ASCII英数字・下線・ハイフン・ピリオド、1〜48文字 |
| start_key | 文字列、開始キー | 1文字。修飾キー・編集欄入力は別扱い |
| stop_key | 文字列、停止キー | 停止対象はideとcan_id。複数パターンから同じ対象への共通停止キーは可、異なる対象の曖昧な共有は不可 |
| ide | bool、拡張IDなら真 | IDの大きさから自動推定しない |
| can_id | 整数 | 標準0〜2047、拡張0〜536870911。bool／float／負数を拒否 |
| fdf／brs | bool | Classicalはfdf=false・brs=false、FDはfdf=true。FDサンプルはbrs=true。ClassicalのBRS=trueを拒否 |
| data | 空白なしの大文字HEX文字列 | 偶数桁、0〜128文字。形式ごとの合法長を検証 |
| period_ms | 整数 | 10〜60000 ms。設定可能範囲であり、全負荷条件での周期達成保証ではない |
| duration_ms | 整数 | 1000〜86400000 ms。初期60000。CLIのdurationだけは秒 |
| log_dir | 文字列 | 書込み可能なホスト保存先 |

通常運用は[DESN-SW-002のT1〜T4](Design.md)を一つのホスト設定へ登録する。10／100 msのClassical8バイトと1000／10000 msの拡張ID・FD64バイトを同時稼働させる。Classical／FDの選択と標準／拡張IDの選択は独立したフィールドとし、64バイトをClassical拡張IDで表現しない。

Classical送信の長さは0〜8、DLCは長さと同値。9バイト以上は拒否する。FDの長さ→DLCは「0〜8は同値、12→9、16→10、20→11、24→12、32→13、48→14、64→15」。DLCをデータ長として誤用しない。根拠: [REF-003 表1-1](references.md)。HEXは大文字・空白なしに限定し、型の暗黙変換をしない。

Picoの制御設定とホストが期待する速度・schemaを照合してから開始する。ホスト設定が機器側のGPIOやクロックを黙って上書きしない。稼働中の設定ファイル変更は行わず、停止・全体再検証を必要とする。登録済みパターン間のデータ／形式置換は稼働中に許可する。

## 2. Module間API（DESN-SW-001、DESN-SW-004、DESN-SW-006、DESN-SW-010）

| API | 入力 | 出力 | 契約・副作用 |
| :--- | :--- | :--- | :--- |
| host.main.load_config | ホスト設定ファイルのパス | 検証済み設定または例外 | 全件を検証。部分的な有効化をしない |
| initialize | 検証済み制御設定 | 機器情報／失敗理由 | CS・SPI・RAM・CANを初期化し停止状態。クロック・モード待ちは有限 |
| read_status | なし | 状態スナップショット | CRC検査済みのINT、TEC／REC、診断、FIFO状態。失敗を0として返さない |
| MCP2518FD.receive | なし | 辞書フレームまたはNone | 新着確認後に読み、確保成功後UINC。呼出しあたり一件 |
| MCP2518FD.submit | slot、profile、metadata | SEQまたは例外 | 完了通知ではない。UINC／TXREQを適切に更新 |
| MCP2518FD.abort | slot | 戻り値なし、中止要求または例外 | ポーリング待機を内包せず後続serviceで終状態を回収 |
| Engine.service | なし（時計・ドライバは構築時注入） | 戻り値なし、内部Queueへemit | 処理予算内でRX／TEF／異常を回収。SPI所有者のみ実行 |
| start_session | 設定照合情報、有限時間 | session_id・起点・期限 | 一度だけ開始。重複で期限を延長しない |
| start_profile | session_id、profile_id、期待する世代 | 受付／重複／拒否 | 同一IDの置換は旧送信の終状態後。期間満了時は拒否 |
| stop_id | session_id、ide、can_id | 停止処理中／停止済み | 他IDとRXは維持。STOPPEDはHW未完了の解消後 |
| stop_session | session_id、終了理由 | 停止処理中／終了イベント | 有限排出、CAN停止確認、集計 |

表のstart_session／start_profile／stop_id／stop_sessionは意味上の操作名。実装はEngine.command→executeで大文字のUSBコマンドを処理する。ホストはLink.rpcを使用する。Engine.flushは部分書込みを続行し、Engine.drainは最終イベントを送出する。

SPIデータのバイト順、SID／EIDのパッキング、DLC、SEQ、RAMアラインメントはMCP2518FDの形式に従う。ホストの連続した29ビットIDをSPIオブジェクトの生のワードへそのまま書かない。移植元FlexCANのシフトマクロを使用しない。レジスタビット位置、CRCの計算詳細はREF-002を正本とし、実装時に対応テストで照合する。

## 3. データ構造（DESN-SW-002、DESN-SW-004、DESN-SW-008）

- CANフレーム: `ide, can_id, fdf, brs, esi, rtr, dlc, length, requested_length, data, device_us`。送信時のesiは実際のコントローラ状態に従う。受信のdlcとlengthを形式別に整合確認する。ClassicalデータはDLC9〜15も実長8、RTRは実データ長0でrequested_length=min(dlc, 8)、dataは空。通常データフレームのrequested_lengthは不適用。ClassicalのBRS／ESIは不適用として表示する。
- 稼働ジョブ: `profile_id, id_key, generation, period_ms, next_due, fifo, inflight_seq, immutable_payload, skipped_count`。同じid_keyを二重所有しない置換方式。id_keyはIDE＋IDのままとし、FDFが異なっても別ジョブを並行作成しない。
- セッション: `boot_id, session_id, start_time, deadline, last_heartbeat, state, end_reason`。start_timeとdeadlineは拡張TBCのμsで統一し、heartbeatと周期のPico単調時刻とは直接比較しない。
- エラー: `type=ERROR, code`を基本とし、原因により`detail, hardware, stop_confirmed`等を付ける。ホストは`host_utc`を追加。全ERRORに機器時刻や重要度を付ける実装ではなく、未記録は不明として扱う。
- 完了イベント: `seq, profile_id, generation, id_key, outcome, device_us`。対応する送信内容が見つからなければTX結果不明として停止・診断する。

データ列はジョブを変えた後も古い完了イベントから参照されるので、送信中バッファを上書きしない。Pico単調時刻はwrap対応の差分で扱い、長時間値はソフトで拡張する。

## 4. USBワイヤプロトコル（DESN-SW-003）

### 4.1 フレーミング

形式はASCIIのJSONオブジェクト一つ＋LF。データは空白なしの大文字HEXとし、日本語説明はホスト側でコードから生成する。行上限はLF込み1024バイト、入れ子深さと各文字列長も検証する。LF込み1024バイト、深さ4、文字列128文字まで。

不完全受信は上限内で持越す。長すぎる行は次のLFまで破棄してエラーを返す。型違い、同じJSONキーの重複、未知コマンド、余分なフィールド、非ASCII、制御文字を拒否する。JSONの重複キーを黙って後勝ちにしないよう、対象パーサで検出できることを採用条件とする。CPythonでは境界検証付きのパーサ、MicroPythonではViper字句走査＋json.loadsで重複キーを検出する。エスケープを使う重複も実機で検証した。

Picoからの部分書込みでは、レコードと現在のオフセットを保持する。一つの行を送り切る前に高優先レコードを途中へ挿入しない。優先送出は行境界で切り替える。書込みが0バイトでも次の一巡へ戻り、CAN回収と停止処理を妨げない。

### 4.2 共通フィールドと再送

コマンドには`v`（整数プロトコルmajor）、`cmd`、`req`（要求番号）、`boot_id`、セッション開始後は`session_id`を付ける。HELLOはboot_idを付けず、既存req窓に入れずにINFOのnext_reqで次番号を交渉する。session_idはboot_idと組にして一意となる短い文字列。データ／応答は`type`、`boot_id`、`session_id`、連番`event_seq`を持ち、応答には`req`を返す。初期プロトコルmajorは1で、FW版の1.0.0とは別。

送信設定変更系コマンドはホスト一件ずつ、同じreqで再送する。Picoは直近16応答をキャッシュし、同一req同一内容なら同じ結果を返す。同一req別内容は拒否。古くキャッシュから失われたreqは「古い要求」として拒否し、再実行しない。停止は通常要求に割り込める別枠とするが、同じreqの再送規則は同じ。heartbeatは独立した連番で、制御コマンドの再送待ちをブロックしない。

応答期限500 ms、再送2回。再送しても効果の回数・周期起点・セッション期限を増やさない。開始の応答が不明のまま新reqで開始を送らず、STATUSで状態を照合するか停止する。

### 4.3 コマンドと応答

| コマンド | 主要入力 | 応答・状態条件 |
| :--- | :--- | :--- |
| HELLO | 対応v | INFO: boot_id、FW／schema版、機器ID、速度、BRS可否、最大長・容量。CAN動作は開始しない |
| LOAD_BEGIN | 設定revision、profile数 | 設定転送用のRAM一時領域を作る。停止状態のみ |
| LOAD_PROFILE | revision、profileのフレームと周期 | 検証してRAM一時領域へ登録。全体が有効になるまでは稼働不可 |
| LOAD_COMMIT | revision、期待profile数 | 全件・参照関係・重複を検証し、RAM内で一括反映。再LOAD_BEGINで未commit領域を破棄 |
| START_SESSION | revision、duration_ms、期待機器設定識別 | ACK: session_id、start_time_us、deadline_us、initial_generation=0。受信開始の境界 |
| START_PROFILE | profile_id、期待generation | ACK: STARTED／ALREADY_ACTIVE／REPLACING、profile_id、generation。CAN個別成功は別のTX_DONE |
| STOP_ID | ide、can_id | ACKでSTOPPING／STOPPEDと新generation。HW終状態後にID_STOPPED。対象に関する古いSTARTを無効化 |
| STOP_SESSION | 終了理由 | ACKでSTOPPING、その後SESSION_END。既に終了なら同じ終結果を返す |
| HEARTBEAT | session_id、生存連番 | hbが前進した場合だけ生存期限を更新。ACKなし。CANセッション期限は更新しない |
| STATUS | なし | 状態、active（profile_id／generation／slot／stopping）、stats、dropped、latest_error、hardware |

送信パターンはRAMだけに置く。heartbeat喪失時は停止し、Picoリセットで消える。USB切断でRAMを物理消去する保証ではなく、再接続では全体を再転送する。ホストに原本があるので再接続時に照合して再転送する。プロトコルには任意Python実行・任意ファイル書込み機能を設けない。

### 4.4 イベント

- `RX`: CANフレームと機器時刻。GUI描画とは独立。
- `TX_DONE`／`TX_FAILED`／`TX_ABORTED`／`TX_UNKNOWN`: SEQ、profile_id、世代、CAN時刻または理由。TEFによる完了と受付を分ける。
- `ERROR`: エラー構造。生の診断情報を解釈文と分ける。
- `SESSION_END`: 停止理由、停止確認状態、最終event_seq、RX／TX／欠落／周期skip集計、時刻。通常終了では期限内の未送信レコードの後に最後に送る。

エラーやSTOPの応答が通常RXを追い越した場合、event_seqは到着順で前後し得る。ホストは番号を記録し、受信途中の番号飛びを即欠落確定とせず、有限の並べ替え窓または終了時の集計で確定する。終了時もUSB断等で確定できなければ不明と記録する。Pico取得前のHW欠落はevent_seqだけでは検出できない。

## 5. イベント・Queue・同期（DESN-SW-006、DESN-SW-007、DESN-SW-011）

| 経路 | 通信方式 | 所有と満杯時 |
| :--- | :--- | :--- |
| GPIO IRQ→Pico通常処理 | 単一保留フラグ＋INTレベル | IRQはセットのみ。交換だけ短く割込禁止。SPI中は割込を長時間止めない |
| Pico受信→USB | 事前確保リング、64フレーム | 通常処理が単独所有。満杯なら欠落記録と全停止を起動 |
| Pico制御・異常→USB | 16枠＋別の最新エラー／停止フラグ | 通常データより優先。予約枠まで満杯なら件数集約、停止フラグを失わない |
| GUI→通信worker | thread-safe Queue、64要求 | 通常要求満杯は拒否表示。STOPは別の停止フラグで優先処理 |
| 通信worker→保存worker | thread-safe Queue、4096イベント | 満杯で停止。通信スレッドは無期限putしない |
| 通信worker→GUI | 上限付き状態通知・最新値スナップショット | 古い描画更新を集約し、ログイベントを削除しない |
| 保存worker→GUI／通信worker | 保存進捗・エラー通知 | 保存停滞を停止とheartbeat継続可否へ反映 |

PicoはOSタスク、Mutex、Semaphore、Shared Memoryを使わない。共有IRQフラグ以外は単一実行コンテキスト。ホストのQueue内部同期は標準実装を使い、ホストの停止意図の世代と要求キューへの登録はthreading.Lockで短く保護する。通常開始64枠とID停止64枠を分離し、古い開始を停止で無効化する。全停止は独立Event。Semaphore、プロセス間Shared Memory、multiprocessingは対象外。コールバックはGPIO IRQ、GUIイベント、USBライブラリ内部を区別し、USBコールバックからCAN処理を直接実行しない。

## 6. ログ形式（DESN-SW-008）

各ファイルの日本語ヘッダに、文書／FW／ホスト版、Git commit ID、機器設定schema、boot_id、session_id、開始UTC、速度・BRS・発振仮定の確定状況、ログ時刻単位、TSEOF設定とRX／TX時刻の捕捉点を記載する。

- `tx.txt`: ホストUTC、機器時刻、event_seq、要求番号、profile_id、SEQ、ID種別、ID、FD／BRS、長さ、HEX、type（要求受付／送信完了／失敗／中止／不明）、理由。長さはHEX文字数の半分から得られる。
- `rx.txt`: ホストUTC、機器時刻、event_seq、ID種別、ID、FD／BRS／ESI／RTR、DLC、実長、RTR要求長（該当時）、HEX。
- `error.txt`: ホストUTC、機器の制御応答・状態・エラーイベント。code、detail、reqやhardwareは該当するイベントにだけ付く。SESSION_ENDに集計・欠落・停止確認を残す。各行に重要度や機器時刻を必須とする実装ではない。

完了を確認できない送信に推定の成功時刻を入れない。TEC／RECはスナップショットであり全ての過去CANエラーフレームを復元した情報ではない。送信データは要求時と完了時で取り違えない。

同種エラー連発は最初の発生と状態変化を即時記録し、継続分は1秒ごとに件数・最終時刻を集約してもよい。ただし最終集約を終了時に排出する。ログが書けない場合はGUIで明示し、そのエラーログ自体の保存保証をしない。

通常のSESSION_ENDで保存workerは残Queueを排出してflush・closeする。排出待ち上限は2秒。時間切れの場合は「ログ未完了」と表示し、停止したCANをログ待ちのために再開しない。期限到来後の排出は有限の既存データ保存であり、新規受信を継続する意味ではない。

## 7. 採用事項と検証待ち

置換、容量、時間上限、リテラル設定、別CDC、有限再送を採用済み。Classical／FDの両形式の送受信を追加回答で確定した。Normal CAN FDモードのままフレームのFDFを選択し、ClassicalのBRSはfalseとする。Classical RTRの送信・自動応答は実装範囲に追加しない。対象OSと最新安定版の選定はOPEN-008で決定済み。依存版・JSON検証は実装済み。実機の検証結果と未達の周期性能はOPEN-015および結果書に記録する。現物の電気確認はOPEN-005としてユーザー指定で保留する。

## 8. 開発版の具体化と制限

TX_DONEのUSB本文にはprofile_id、req、generation、seq、txreq_us、device_us、late_usを載せる。データ本体はLOAD済みの不変profileからホストが復元してtx.txtへ記録する。wireのTXにpayloadを毎回重複させない。txreq_usはWRITE_SAFE発行直前のTBC読値、late_usは周期処理着手の遅れであり、TXREQ反映時刻をオシロで捕捉した値ではない。

RXイベントは辞書で64枠、制御は辞書で16枠へ保管し、USB flush時にJSON化する。固定枠でもPythonオブジェクトの割当てとGCは発生する。最大4 IDの期限順に処理し、未完了が100 ms残ればTX_COMPLETION_TIMEOUTで停止する。100／500 ms±2 msの目標は未達。

ログヘッダは受信有効化前に書くため、その時点のsession_idは未確定。開始ACKと後続行に確定session_idを記録する。source_sha256は配置元ファイルの識別で、Pico読戻し照合とは別の証拠。read_statusのtrecは生値を保持するが、ConfigurationモードのTXBOリセット値を通信中のbus-offと報告しない。
