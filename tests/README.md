# テスト

⚠️ これまでテストは一時フォルダ(scratchpad)に置かれており、**セッションが消えると一緒に消えていた**。
実際 v1.6.0 までの50本は失われている。残したいテストは必ずここへ置くこと。

| ファイル | 実機 | 内容 |
|---|---|---|
| `test_manual_send.py` | 不要 | キーワード自動返信のON/OFF、手入力の送信待ち、自分の発言への誤返信防止、改行の比較 |
| `test_gui_widgets.py` | 不要 | キーワード設定タブが本物のコードのまま組み立つか。スイッチ・手入力送信欄の位置、説明文の出し分け、Ctrl+Enterの発火（画面が一瞬出る） |
| `test_live_newline.py` | **必要** | GRAVITYの実際の入力欄で改行が保たれるか（**送信ボタンは押さない**）。`--live` を付けたときだけ動く |
| `test_daily_tasks.py` | 不要 | GRAVITYのタスク・ルーレットの「画面を読む」関数。タスクの行と回数、こなすかの判定、押してよい画面か、押してはいけないボタン、目当ての部品の探し方。`fixtures/` の実機ダンプを使う |
| `test_daily_task_worker.py` | 不要 | タスク・ルーレットの実行役 `GravityTaskWorker` を「にせのMuMu」で通しで動かす。守り（広告・音声ルーム・ポイント消費ボタンの近くでは何も送らない）と、各タスクの流れ |
| `test_chat_rows.py` | 不要 | 音声ルームのチャット欄を「意味で読む」関数（`parse_chat_rows`）。発言・お知らせ・アナウンスの見分け方。⚠️ 今の自動返信はまだ使っていない |
| `test_gui_daily_task.py` | 不要 | メインタブのタスク・ルーレットのボタンと、設定タブの区画。監視と同時に動かさないこと（画面が一瞬出る） |
| `test_keyword_targets.py` | 不要 | キーワードのペアの「対象」（すべての文字／人の発言の本文だけ／お知らせの行だけ／［参加したとき］など）と返信ワードの `{名前}`。監視の本体を、伏せ字にした実物の音声ルームの画面で何周か回す |
| `test_gui_keyword_target.py` | 不要 | キーワード設定タブの「対象」の欄（選ぶと検知ワードの欄がどう変わるか、保存・選択・一覧の印）。画面が一瞬出る |
| `test_agent_api_keys.py` | 不要 | AI API のキーの保存（DPAPI の暗号文だけが残る、DB・WAL・ログ・error_log.txt にキーが出ない、壊れた暗号文で止まらない、環境変数の優先、伏せ字、提供元の一覧、模擬の接続確認） |
| `test_gui_ai_api.py` | 不要 | 設定タブの「🤖 AI API」区画（隠す・👁・保存・削除・接続確認・提供元の切り替え）。ボットがキーをログへ渡していないことも確かめる。画面が一瞬出る |

## 実行

```bash
python tests/test_manual_send.py
python tests/test_gui_widgets.py
python tests/test_daily_tasks.py
python tests/test_daily_task_worker.py
python tests/test_gui_daily_task.py
python tests/test_chat_rows.py
python tests/test_keyword_targets.py
python tests/test_gui_keyword_target.py
python tests/test_agent_api_keys.py
python tests/test_gui_ai_api.py
```

## テスト用の画面（fixtures/）の作り方

`fixtures/` の `*.xml` は、MuMuの実機で取った画面ダンプ（`uiautomator2` の `dump_hierarchy()`）。
⚠️ **このリポジトリは公開されている。** 画面には他の人の名前や投稿が出ているので、
そのまま置かず、必ず `make_fixture.py` を通して伏せ字にすること。

```bash
python tests/make_fixture.py 取ったダンプ.xml 保存する名前.xml
```

決まった文言（ボタン名など）・数字・時刻以外はすべて「伏せ字N」になる。
名前で探す処理を試したいときだけ `--name 元の名前=仮の名前` で特定の名前を仮の名前に置き換えて残す。
作った後に表示される「残った文言」を目で確かめること。

お知らせの行（「〜が音声ルームに参加しました」など）は、名前の部分だけを伏せ字にして決まった文言を残す。
同じ名前には同じ伏せ字を付ける（「同じ人の発言か」をテストで確かめられるように）。

チャット欄の行を集めるときは `tools/chat_recorder.py` を使う（読むだけ。記録は `recordings/` に置かれ、リポジトリには入らない）。

実機テストは MuMu を起動し、GRAVITY の音声ルームを表示してから:

```bash
python tests/test_live_newline.py --live
```

⚠️ `--live` が無いと何もせずに終わる。`tests/test_*.py` をまとめて流したときに、本人がMuMuを操作している
最中の入力欄へ文字を入れてしまったことがあるため（2026-10-13）。しかもMuMuは uiautomator2 の文字入力への
切り替えを止めるので、後片付けの `clear_text` が失敗して、入れた文字が残る。動かした後は入力欄を目で確かめること。

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
