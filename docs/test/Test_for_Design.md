# 設計テスト — 正常系

状態: 検証計画。実施した部分と未実施の区分は[結果書](results/TEST-SPEC-DESN_result_001.md)を参照。実装開始後のホワイトボックスを含む検証計画。[共通方針](Test_common.md)を適用する。

## 1. 実機なし自動

| ID | 設計／仕様 | 条件・手順 | 期待結果 |
| :--- | :--- | :--- | :--- |
| TEST-DESN-001 | DESN-SW-002／SPEC-F-007、SPEC-F-010、SPEC-F-013 | E0。リテラル設定を解析し機器設定とホスト設定を個別に検証。サンプル二件を読込む | 配置と所有を混同せず、型・ID・長さ・キー検証が一致。全件有効になるまでcommitされない |
| TEST-DESN-002 | DESN-SW-004、DESN-SW-006／SPEC-F-006、SPEC-F-007 | E0。標準／拡張ID、合法DLC全種、非対称なバイトパターンをSPIオブジェクトと往復変換 | REF-002形式の既知の期待バイト列と一致。実装側の変換を逆に呼ぶだけの自己一致試験にせず、独立期待値を使う |
| TEST-DESN-003 | DESN-SW-004／SPEC-F-005、SPEC-NF-002 | E0。仮想時計でt0、t0+周期、複数期限を進め、TEFの完了を異なる時刻で返す | 初回即時、次期限はt0+nP。完了時刻基準のドリフトなし。未完了SEQの内容は不変 |
| TEST-DESN-004 | DESN-SW-005／SPEC-F-006、SPEC-F-008、SPEC-F-009 | E0。開始→重複→同一ID別profile→停止→解放→開始の全正常遷移を与える | req、世代、id_keyが整合。置換方式に従い旧完了前に新しいデータを投入せず、標準／拡張同値を別所有 |
| TEST-DESN-005 | DESN-SW-003／SPEC-F-001、SPEC-F-013 | E0。HELLOからLOAD、START、STATUS、STOPまで、一バイトずつ／複数行一括の入力と部分書込みを組合わせる | 行が混ざらず、全転送を一度だけ処理。同一req再送でも期限・効果が変わらない |
| TEST-DESN-006 | DESN-HW-004、DESN-SW-006／SPEC-F-002、SPEC-NF-004 | E0。INTの単一立下り後に16件を保持し、RX8件ごとのserviceで回収。初期Lowも再現 | 二度目のエッジなしで全件回収。IRQ内にSPI／割当て／ログなし。割込禁止はフラグ交換のみ |
| TEST-DESN-007 | DESN-SW-007、DESN-SW-008／SPEC-F-003、SPEC-F-004、SPEC-F-012 | E0。通信・GUI・保存のworkerを別々の速度で進める。描画を集約しログ全件を検証 | GUI所有スレッド以外の操作なし。GUI集約でログを失わず、最新エラーを正常受信で消さない |
| TEST-DESN-008 | DESN-SW-009／SPEC-F-009、SPEC-F-011 | E0。START_SESSIONで起点を保存し、ID停止と全停止を実行。仮想HWに中止／完了を返し、RX／TEF残も用意 | 状態順が設計どおり。対象FIFOのTXREQを解除し、停止終状態後にACK。全停止ではフィルタ無効化→残RX／TEF回収→Configuration・OPMOD確認。モード遷移前に未回収データを失わない |
| TEST-DESN-009 | DESN-SW-001、DESN-SW-010／SPEC-F-012、SPEC-NF-004 | E0。初期化成功、接続待ち、開始、停止、再開始、保守復帰の各経路 | 状態図の遷移・禁止操作が一致。再初期化前のジョブやセッションを再利用しない |
| TEST-DESN-010 | DESN-HW-003、DESN-SW-012／SPEC-NF-006 | E0。CAN側GPIO操作を記録する代替で初期化〜終了を進める。統合案の待機イベントを仮想時計で進める | GP0〜GP4・25をCAN側から変更しない。長いsleepをCAN処理の途中へ持ち込まない |
| TEST-DESN-011 | DESN-SW-013、DESN-SW-014／SPEC-NF-005 | E0。将来のソース・文書・版情報・依存記録を静的解析する | ファイルと関数の日本語概要・DESN ID、必要な出典、互換性定義、設定配置が揃う。全SPEC／DESNがテストと接続 |
| TEST-DESN-012 | DESN-SW-011／SPEC-NF-002、SPEC-NF-004 | E0。RAM割当と容量定義を独立計算し、バッファ所有を追跡 | 1672+288+48=2008バイトで2 KiB以内。TX深さ1、同時未完了4、TEF4の所有が一致。範囲外UAを使わない |
| TEST-DESN-013 | DESN-SW-002、DESN-SW-004、DESN-SW-006／SPEC-F-006、SPEC-F-007 | E0。Classicalデータ長0〜8と受信DLC9〜15、FDの合法DLC全種、Classical RTRを独立期待値で変換。FDF／BRSの不正組合せも入力 | Classicalデータは最大8、受信生DLCを保持。RTRは実長0・要求長を別管理し自動応答なし。FD長と混同せず、ClassicalのBRS=trueとRTR送信を拒否 |
| TEST-DESN-014 | DESN-SW-002、DESN-SW-004、DESN-SW-009、DESN-SW-011／SPEC-F-005、SPEC-F-006、SPEC-F-007、SPEC-F-011、SPEC-NF-002 | E0。T1〜T4を時刻0で開始、60秒の仮想時計と次周期前に完了する独立HWモデルを用いる。10秒ごとの同一期限と期限同値を観測 | 予定投入6000／600／60／6、合計6666件。各周期のデータ・形式と不変SEQが一致。4件同一期限を有限処理し短周期を優先、停止時刻60秒の投入なし、4 FIFO／TEFの容量超過なし |

## 2. 実機あり自動

| ID | 設計／仕様 | 条件・手順 | 期待結果 |
| :--- | :--- | :--- | :--- |
| TEST-DESN-101 | DESN-HW-001、DESN-HW-002、DESN-HW-003、DESN-SW-001／SPEC-F-001、SPEC-NF-001 | E2。初期化のSPIトレース、DEVID、OSC、OPMOD、GPIO設定を採取。電源は確定条件内 | 写真識別と読出した機器情報が整合。明示SPI0ピン、初期CS High、意図した停止モード。DEVIDだけで水晶周波数を認定しない |
| TEST-DESN-102 | DESN-HW-005、DESN-SW-011／SPEC-NF-002、SPEC-NF-004 | E2。CAN動作中にSPI信号を採取し、設定読戻しとCS timingを測る | mode 0、実SPI速度、CSのsetup／holdが採用値と資料の条件内。READ_CRC、単一バイトIOCON、境界分割が確認できる |
| TEST-DESN-103 | DESN-SW-004、DESN-SW-006、DESN-SW-011／SPEC-F-002、SPEC-F-004、SPEC-F-005、SPEC-NF-002 | E1。T1〜T4とN947のRXを同時稼働し、全SEQとTEF、RX UA、UINCをトレース。期限が近接する位相も観測 | 送信投入とTEFが一対一。RX確保後にUINCし、TEF消費前のTXスロット再利用なし。10 ms系列をGUI更新・ログflush待ちで停止しない |
| TEST-DESN-104 | DESN-HW-004、DESN-SW-006／SPEC-F-002、SPEC-NF-004 | E2。連続RXと同時TX完了でINTをLow維持。初期IRQ有効時のLowも発生 | 総合INTだけのIRQで全要因を回収。CLK／INT0／INT1に不要なISRなし。クリアによる新着要因の消失なし |
| TEST-DESN-105 | DESN-HW-005、DESN-SW-004、DESN-SW-009／SPEC-F-005、SPEC-F-009、SPEC-F-011、SPEC-NF-002 | E2。T1〜T4の実bit time、投入締切、中止、モード遷移を測る。従来100／500 ms条件も別に評価 | 実クロックとレジスタ計算が一致。各指定周期の投入遅延を記録し、採用済みの100／500 ms目標と未確定の新周期閾値を区別。期限で新規投入を止め、停止遅延と最終フレームを区別 |
| TEST-DESN-106 | DESN-SW-003、DESN-SW-007／SPEC-F-001、SPEC-F-003 | E1。Mac／WindowsでCDCを開き、再列挙と大きさの異なるI/Oを実施 | アプリ用CDCを特定でき、REPLとデータが混ざらない。部分I/Oとポート再発見が正常 |
| TEST-DESN-107 | DESN-SW-012／SPEC-NF-006 | E3。起動LED通知中とPWM出力中にCAN刺激を与え、ループ最大停止時間を測る | 起動通知とPWM仕様を維持しつつ、合意したCAN受信開始境界・周期条件を満たす |
| TEST-DESN-108 | DESN-HW-005、DESN-SW-004、DESN-SW-006／SPEC-F-002、SPEC-F-006、SPEC-NF-002 | E2。Normal CAN FDのOPMODと両タイミング・TDC設定を読戻し、Classical／FDを交互に送受信。BRS=0のFDも加える | OPMOD=000を維持。FDFで形式が変わりClassicalは全区間500 k、FDのBRS=1はデータ2 M、BRS=0は全区間500 k。自動TDCと波形を確認し、TDC候補が不適合ならOPEN-005へ記録 |

## 3. 実機あり手動

| ID | 設計／仕様 | 条件・手順 | 期待結果 |
| :--- | :--- | :--- | :--- |
| TEST-DESN-201 | DESN-HW-001、DESN-HW-002、DESN-HW-003、DESN-HW-004、DESN-HW-005／SPEC-F-001、SPEC-NF-001、SPEC-NF-003 | interface_HW.md §4に従い、無給電の電源経路・P2・INT0–STBY・プルアップ先を確認してから電圧・CLKを測る。3台接続時のH–L抵抗と各配線長を記録 | ピンごとの値と回路の解釈が一致しOPEN-005の証拠を得る。CLK初期値換算の成立条件を記録。不一致なら給電・送信を中止し設計を更新。P3開放・120 Ω非実装を維持 |
