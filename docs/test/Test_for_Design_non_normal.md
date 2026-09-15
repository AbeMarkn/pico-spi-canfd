# 設計テスト — 正常系以外

状態: 検証計画。実施した部分と未実施の区分は[結果書](results/TEST-SPEC-DESN_result_001.md)を参照。内部状態・例外注入を含む将来の計画。[共通方針](Test_common.md)に従う。

## 1. 実機なし自動

| ID | 分類・設計／仕様 | 条件・手順 | 期待結果 |
| :--- | :--- | :--- | :--- |
| TEST-DESN-021 | SPIエラッタ。DESN-SW-011／SPEC-NF-004 | E0。CRC不一致→成功、3回失敗、CRC正しいがFIFOCI不整合、SFR境界、IOCON更新を注入 | 有限再読出し、誤値を採用しない。境界越えなし、単一バイト書込み。FIFOCI安定待ちで無限ループしない |
| TEST-DESN-022 | 通信破損。DESN-SW-003／SPEC-F-001、SPEC-NF-004 | E0。行上限−1／上限／+1、LF欠落、切断途中、重複JSONキー、未知cmd、旧session、同req別内容、キャッシュより古いreqを投入 | 範囲外を拒否して有限メモリを維持。次のLFで復帰し、不正・古い要求を再実行しない |
| TEST-DESN-023 | 状態競合。DESN-SW-004、DESN-SW-005、DESN-SW-009／SPEC-F-005、SPEC-F-008、SPEC-F-009、SPEC-F-011 | E0。同じ一巡に期限、STOP_ID、START、周期満了を全順序で注入。旧世代の応答も戻す | 停止優先と世代無効化を維持。古い応答で再開せず、送信中データを書換えない |
| TEST-DESN-024 | 満杯・メモリ不足。DESN-SW-006、DESN-SW-007、DESN-SW-008、DESN-SW-011／SPEC-F-002、SPEC-F-004、SPEC-F-012、SPEC-NF-004 | E0。各Queueの容量−1／容量／+1、メモリ割当失敗、保存待ち、GUI停止を別々に注入 | STOPと最新エラーを通常Queue外で保持。IRQ内の割当なし、無期限putなし、GUI間引きがログ欠落を隠さない |
| TEST-DESN-025 | 時計・期限境界。DESN-SW-004、DESN-SW-008、DESN-SW-009／SPEC-F-004、SPEC-F-005、SPEC-F-011 | E0。ticks周回、TBCの0xFFFFFFFF→0、読出し途中の周回、周回前FIFO残、長い無通信、UTC補正、再起動、deadline−1／同値／+1のRXを注入 | 単調期限とCAN時刻が正しく継続。古いRXを未来にせず、ticksとTBCを混同しない。期限同値以降のRXを通常ログから除外。新boot_idは別時刻軸、UTC補正で周期を変えない |
| TEST-DESN-026 | ECC・初期化異常。DESN-SW-001、DESN-SW-010、DESN-SW-011／SPEC-F-012、SPEC-NF-004 | E0。SEC、DED、OSC not ready、モード遷移失敗、SPI例外、TX失敗、TEF欠落／未知SEQを注入 | raw状態を退避し停止。SECを訂正済みと扱わず、TEF不明をTX成功にしない。有限期限で初期化・停止確認不能を返す |
| TEST-DESN-027 | 設定破損・更新。DESN-SW-002、DESN-SW-013／SPEC-F-007、SPEC-F-013、SPEC-NF-005 | E0。構文不正、import／関数呼出し、重複キー、schema不一致、途中LOAD切断、FW構成ファイルの版不一致を注入 | 任意コードを実行せず開始拒否。未commit設定を破棄。保存済み制御設定を部分的なホスト設定で上書きしない |

## 2. 実機あり自動

| ID | 分類・設計／仕様 | 条件・手順 | 期待結果 |
| :--- | :--- | :--- | :--- |
| TEST-DESN-121 | SPI障害。DESN-HW-004、DESN-SW-010、DESN-SW-011／SPEC-F-012、SPEC-NF-004 | E2。試験用の安全な信号代替・故障注入層でCRC不一致、INT stuck-Low、ステータス読出し失敗を発生。基板へ過電圧を加えない | 再読出し上限、処理予算、停止動作、latest errorが設計どおり。IRQ stormでも長時間ISRに滞留しない |
| TEST-DESN-122 | bus-off・停止限界。DESN-SW-010／SPEC-F-012、SPEC-NF-004 | E2。bus-offと復帰を発生させ、送信中のFW停止も行う。CAN単独版の2秒Watchdogを確認 | ジョブを再開せず、外付けCANが止まるまでを実測。保証できない経路は停止確認不能として明示し、PicoリセットをCANリセットとみなさない |
| TEST-DESN-123 | RX競合・過負荷。DESN-HW-004、DESN-SW-006、DESN-SW-011／SPEC-F-002、SPEC-NF-002、SPEC-NF-004 | E2。IRQフラグ交換直前／直後にRXを入れ、短フレーム連続と64バイト連続、GC停止を組合わせる | 予算切上げ後も回収を続行。保証範囲内は無欠落、超過は計数または下限と停止を記録 |
| TEST-DESN-124 | USB・保存停滞。DESN-SW-003、DESN-SW-007、DESN-SW-008、DESN-SW-009／SPEC-F-001、SPEC-F-004、SPEC-F-011、SPEC-NF-004 | E1。ホスト読出し停止と書込みゼロ、保存worker停止を与える | Picoの期限・RX・STOPが動く。部分行へ別行を割込ませない。保存停止中にheartbeatだけが無期限継続しない |
| TEST-DESN-125 | 電源断・更新。DESN-SW-001、DESN-SW-009、DESN-SW-013／SPEC-F-013、SPEC-NF-004、SPEC-NF-005 | E2。起動途中・設定転送途中・アプリ更新途中に制御された電源断。旧版へ復旧 | 不整合を検出して送信不可。新セッションで初期化し、未保存ログは不明表示。バックアップした制御設定から復旧できる |
| TEST-DESN-126 | PWM統合異常。DESN-SW-010、DESN-SW-012／SPEC-NF-006 | E3。CAN例外、PWM例外、長い起動通知、統合時の方針を記録したうえでWDTを発生 | OPEN-012の起動・停止・例外の責務どおり。CAN単独のfail-safeをPWMへ無条件に転用しない |

## 3. 実機あり手動

| ID | 分類・設計／仕様 | 条件・手順 | 期待結果 |
| :--- | :--- | :--- | :--- |
| TEST-DESN-221 | 電気条件不一致。DESN-HW-002、DESN-HW-004、DESN-SW-010／SPEC-NF-001、SPEC-NF-004 | 無給電で異なる基板版の回路図／配線を照合し、STBY固定・5 Vプルアップ・P2接続違いを点検。実故障注入は承認した治具でのみ | 未確認の基板をそのまま駆動しない。必要な設定変更・配線変更をOPENへ戻し、ソフト停止できない条件を記録 |
