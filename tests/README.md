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
| `test_keyword_targets.py` | 不要 | キーワードのペアの「対象」（すべての文字／人の発言の本文だけ／お知らせの行だけ／［参加したとき］など）と返信ワードの `{名前}`。監視の本体を、伏せ字にした実物の音声ルームの画面で何周か回す。チャットの入力欄のシートが開いてチャット欄が隠れたときの案内（`fixtures/voiceroom_input_sheet.xml`） |
| `test_gui_keyword_target.py` | 不要 | キーワード設定タブの「対象」の欄（選ぶと検知ワードの欄がどう変わるか、保存・選択・一覧の印）。画面が一瞬出る |
| `test_agent_api_keys.py` | 不要 | AI API のキーの保存（DPAPI の暗号文だけが残る、DB・WAL・ログ・error_log.txt にキーが出ない、壊れた暗号文で止まらない、環境変数の優先、伏せ字、提供元の一覧、模擬の接続確認） |
| `test_gui_ai_api.py` | 不要 | 設定タブの「🤖 AI API」区画（隠す・👁・保存・削除・接続確認・提供元の切り替え）。ボットがキーをログへ渡していないことも確かめる。画面が一瞬出る |
| `test_agent_speech.py` | 不要 | 音声（出す方。`files/agent/speech/`）: AivisSpeech・VOICEVOX のアダプター（にせの HTTP）、途中で止められる再生（にせの sounddevice。10秒の音を0.2秒以内に止める）、読み上げの待ち行列（順番・失敗しても次へ・同時に鳴らない・優先度・上限・終了）、App の読み上げ・「⏹ 止める」・スマホの解析・アラーム。**音は鳴らない** |
| `test_agent_decision.py` | 不要 | AIの判断（段階3）: 規則の関所 R2〜R10、判断の型、出す前の確認 C2〜C4、発言すべき/沈黙すべき場面（T1〜T9）、外の文字を命令として扱わない（T34）。本物の `AgentRuntime` を模擬のAIで動かす |
| `test_agent_guards.py` | 不要 | 同じ出来事を2度処理しない（T29）、1日の回数の上限（T31）、発言の頻度の上限（T32）、判断の間に上限に達したら喋らない（C5）、保留、AIの失敗が続いたら呼ばない状態へ・回復・認証の失敗（T10〜T13 の基本） |
| `test_agent_lifecycle.py` | 不要 | 止める・緊急停止・再開（T36・T37）、再起動で直近の出来事と人格が戻る（T38）、`agent_data.db` が壊れていたらバックアップから戻す/作り直す（T39）、保存期間 |
| `test_gui_agent_tab.py` | 不要 | AIタブ（開始・停止・緊急停止・再開・手入力の出来事・設定・判断のログ）。AIの声がスピーカー（読み上げの出力先ではない）に行くことも。画面が一瞬出る |
| `test_agent_gemini.py` | 不要 | Gemini のアダプター（にせの HTTP。**通信しない**）: 送る形（キーはヘッダーだけ・URL に入れない、responseJsonSchema、役割）、返事の読み方（考えた中身を除く・拒否・途中切れ）、失敗の種類とやり直してよいか、接続確認、費用の見積もり |
| `run_agent_scenarios.py` | **`--live` のとき必要** | AIの判断の場面集（`fixtures/agent_scenarios.json`）を流して、喋るべき/黙るべきと合う割合を出す。ふつうは模擬で流す。`--live` は本物の Gemini（**費用がかかる。本人の了解をとってから**） |
| `test_agent_gravity_bridge.py` | 不要 | GRAVITYのチャット欄の行をAIの出来事にする橋（段階5）: 同じ画面を何周読んでも1回だけ（T30）、始めた時点・上へ戻した昔の行は「前からあった」、自分の発言、AIへつないで前からの行には反応しないこと。監視の本体を にせの端末で回し、キーワード自動返信が今まで通りなことも。チャットしている GRAVITY のアカウントの見分け（本体・アプリ複製の GRAVITY、送った文とまったく同じ行だけ） |
| `test_agent_chat_output.py` | 不要 | AIがチャットに書き込む（段階5b）: チャットに返す・声は使わない（T45）、捨てた下書きは数えない（T46）、長すぎる文（T47）、自分の文に反応しない（T48）、監視していないとき（T49）、緊急停止（T50）、1分1通、監視ワーカーの送信待ち（AIの文だけ捨てる・送った文は自分の発言） |
| `test_fast_input.py` | 不要 | 入力欄へ文字を入れる・消すのを、今選ばれている部品を直接さわるやり方にした（MuMu では uiautomator2 の文字入力の切り替えが止められ、1回の送信で約17秒待っていた）。遅いやり方を呼ばないこと・入らないときは前のやり方へ戻ること |
| `test_agent_memory.py` | 不要 | 記憶（人・この場・自分・印象・関係の値）: OFFなら覚えない、会話に出てこない人・繊細な事柄は覚えない、印象は推定として渡す、関係の値は少しずつ動く、消せる・期限で消える、エージェントの中で整理して次の判断に入る、記憶は GRAVITY のチャットの今のアカウントの発言だけ（AIタブの手入力は入れない） |
| `test_agent_journal.py` | 不要 | 長期記憶ファイル（GRAVITYのアカウントごと＋相手ごと・全文と要約・メモ帳で読める）: OFFなら書かない、その日の全文と相手ごとのファイル、起動前の行・保留から戻った行を2度書かない、要約だけ書き直す、名前が切れても同じファイル、アカウントが違えば記憶もファイルも分ける、書けなくてもエージェントは止まらない |
| `agent_harness.py` | ― | 上のAIのテストが共通で使う器（模擬のAI・にせの声・一時フォルダの `agent_data.db`）。テストそのものではない |

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
python tests/test_agent_speech.py
python tests/test_agent_decision.py
python tests/test_agent_guards.py
python tests/test_agent_lifecycle.py
python tests/test_gui_agent_tab.py
python tests/test_agent_gemini.py
python tests/test_agent_gravity_bridge.py
python tests/test_agent_chat_output.py
python tests/test_fast_input.py
python tests/test_agent_memory.py
python tests/test_agent_journal.py
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

## リリースのときの配布物の確かめ（`release_*.py`）

ふつうのテスト（`test_*.py`）とは別に、リリースの前後で使う。前の版のソースは
`git show v1.8.0:files/auto_reply_app.py > 前の版/auto_reply_app.py` のように取り出しておく。

| ファイル | いつ | 内容 |
|---|---|---|
| `release_db_upgrade.py` | タグの前 | 前の版の DatabaseManager で作った `app_data.db` を今のコードで開き、利用者のデータ（セット・ペアの有効/無効・改行・設定・タイマー・定型文）が変わらないか。2回開いても変わらないか。画面は出ない |
| `release_verify_dist.py` | タグの前（手元のビルド）と、公開の後（CIのzip） | zipの形（exe名・UTF-8の印・アイコン）、利用者のデータ・秘密・開発用のファイル・手元のパスが入っていないか、exe の中に今回の機能の名前と `files/agent/` の全モジュールがあるか、分離した環境で起動して版・`error_log.txt`・前の版の設定の引き継ぎ。**PyInstaller の入った Python で動かす。窓が10秒ほど出る** |
| `release_update_e2e.py` | 公開の後 | 公開中の前の版を分離した環境で起動し、自動アップデートで新しい版に入れ替わるか（裏での用意・終了時の差し替え・バックアップ・設定の引き継ぎ）。**窓が1〜2分出る**。ログインなしの GitHub API を使う |

```bash
python tests/release_db_upgrade.py 前の版 作業フォルダ
python tests/release_verify_dist.py auto_reply_app.zip 作業フォルダ 1.9.0 --strict-paths --old-src 前の版 --allow-error-log "keywordsテーブルにtarget列を追加しました"
python tests/release_update_e2e.py 前の版のzip 新しい版のzip 作業フォルダ 前の版 1.8.0 1.9.0 --allow-error-log "keywordsテーブルにtarget列を追加しました"
```

⚠️ 起動は `LOCALAPPDATA`・`APPDATA`・`TEMP`・`USERPROFILE`・`PATH` を差し替えた環境で行う（スクリプトがやる）。アプリは起動時に、
適用待ちでない `%LOCALAPPDATA%\AutoReplyTool\pending_update` を消すので、差し替えずに起動すると本人のアプリの準備物を消しうる。

⚠️ `release_verify_dist.py` の `--symbols` は、リリースのたびにその版で足した機能の名前に差し替える（既定は v1.9.0 のもの）。

⚠️ リリースしたコミットを取り出したフォルダ（`git worktree add`）から動かす。作業中のフォルダから動かすと、まだコミットしていない
`files/agent/` のモジュールまで「入っているはず」として数え、今のコードでの確かめになってしまう。
