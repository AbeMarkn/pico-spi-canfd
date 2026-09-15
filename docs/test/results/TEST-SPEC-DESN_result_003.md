# 再評価 第003回: 設定変更・権限事前確認

実施日: 2026-09-14。実行者: Codex。対象: 初代Pico＋MCP2518FD、macOSホスト。

## 設定変更
- T1:10→50 ms、T2:100→500 ms。T3=1000 ms、T4=10000 ms維持。
- GUI試験の同一ID置換T1Bも50 ms、LIMITも500 msへ更新。
- pico/config.pyのspi_hz:4,000,000→8,000,000。spi_init_hz=1,000,000維持。要求設定値であり実測値ではない。
- サンプル設定検査の期待周期を新ユーザー要求に合わせて変更。任意周期に関する既存境界値試験は変更していない。

## テスト前の権限確認
- プロジェクト書込: 追加権限を取得し、作成・削除で確認済み。
- USB: /dev/cu.usbmodem2301と2303の読書権限を取得し、O_RDWRのopen/close成功。通信は送信しなかった。
- シリアル設定: tools/device.py interruptはserial.Serial初期化のtermios.tcsetattrでOperation not permitted。open許可だけでは通信設定まで許可されないことを確認。コマンドの送信処理へ到達せず、Pico転送は未実施。
- 許可済みprefixによる制限外実行も試行したが、sandbox_approval=falseのポリシーで要求自体が拒否された。
- GUI: cua.getState成功。Pico CAN.app取得は5秒程度でtimeoutReached。ボタン操作の復旧・画面確認は未検証。

## 結果
.venv314/bin/pytest -q:79 passed,2 skipped（実機）。
.venv314/bin/ruff check pico host tools tests:All checks passed。
Picoへの配置、新条件での実通信、GUI操作、300秒満了の再現、再接続・通信断の再試験は未実施。総合判定は実機評価保留。前回の早期DURATION事象OPEN-020は未解決。

## 再開手順
1. シリアル通信設定まで許可された実行環境で、GUIによる通信口占有がないことを確認する。
2. tools/device.py interruptで保守モードへ移行し、pico/config.pyをPicoのconfig.pyへ配置する。配置前後のSHAを照合し、既存ファイル一式の不一致があれば先に整理する。
3. tools/device.py startで再起動。Picoの設定読戻しとSPI設定を確認する。
4. GUIを新設定で再起動し、セッション開始・受信・各ボタン／キー・置換・枠超過・全停止・終了・再接続を画面とログで照合する。
5. 300秒終了をホスト経過時間でも確認。周期ばらつきの許容と早期終了の機能不具合は分ける。
6. 新条件で実CAN2ケース、一定時間の混在通信、ログ件数・データ・欠落・停止を再評価。旧証跡を上書きしない。

変更ファイルSHAはconfig-change-003.json。コード・設定の変更をPicoで実行済みとは記録しない。

## 起動クラッシュの原因と修正（同日追補）
macOSのPicoCANクラッシュ記録（2026-09-14 13:59:19）はDYLD Library missing、libpython3.14.dylib未検出だった。生成バイナリが.tools/python/...という相対依存パスを持ち、通常のアプリ起動時に解決できなかった。tools/macos_app.pyでリンク後にPython dylibの参照先を絶対パスへ修正し、アドホック署名を更新するよう変更。再生成後otool -Lで絶対参照を確認し、cua.getAppでGUI起動成功、画面上でT1=50 ms、T2=500 msを確認した。通信開始は行っていない。GUI起動障害は解消、ボタン試験は未実施、SPI8 MHzのPico配置は引き続き未実施。
