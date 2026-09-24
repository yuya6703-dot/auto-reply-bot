# テスト

⚠️ これまでテストは一時フォルダ(scratchpad)に置かれており、**セッションが消えると一緒に消えていた**。
実際 v1.6.0 までの50本は失われている。残したいテストは必ずここへ置くこと。

| ファイル | 実機 | 内容 |
|---|---|---|
| `test_manual_send.py` | 不要 | キーワード自動返信のON/OFF、手入力の送信待ち、自分の発言への誤返信防止、改行の比較 |
| `test_gui_widgets.py` | 不要 | キーワード設定タブが本物のコードのまま組み立つか。スイッチ・手入力送信欄の位置、説明文の出し分け、Ctrl+Enterの発火（画面が一瞬出る） |
| `test_live_newline.py` | **必要** | GRAVITYの実際の入力欄で改行が保たれるか（**送信ボタンは押さない**） |

## 実行

```bash
python tests/test_manual_send.py
python tests/test_gui_widgets.py
```

実機テストは MuMu を起動し、GRAVITY の音声ルームを表示してから:

```bash
python tests/test_live_newline.py
```

## 文字化けする場合

日本語・中国語を含む出力があるため、cp932 の端末では落ちることがある。

```bash
PYTHONIOENCODING=utf-8 python tests/test_manual_send.py
```

## ⚠️ ウィジェットを書き写さないこと

`test_gui_widgets.py` は `App.build_keywords_tab` を**本物のまま借りて**呼んでいる。
同じウィジェットをテスト側に書き写して組み立てると、本体を変えてもテストが通り続ける。
（このコードベースが `_select_pending_replies` を関数に切り出したときの理由と同じ。）

## 実機テストの前提

`test_live_newline.py` は **GRAVITYの音声ルームが表示されていること**が前提。
表示されていないと「入力欄が見つかりません」と出て止まる。これは失敗ではなく前提不足。
