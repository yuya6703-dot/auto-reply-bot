# -*- coding: utf-8 -*-
"""
AI がチャットに書き込む（段階5b、設計書/08 の T45〜T50）。2026-10-15 本人「チャットモードと音声応答モードを切り替えられるように」。
本物の AgentRuntime と、本物の監視ワーカーの送信待ち（AgentChatText）で確かめる。音は鳴らさない・通信しない。
"""
import os, tempfile, time

from agent_harness import Agent, check, finish, make_event, wait_until
import auto_reply_app as A
from agent.config import AgentConfig, OUTPUT_CHAT, OUTPUT_VOICE
from agent.context import GENERATE_CHAT_SYSTEM
from agent.llm.mock import MODE_ENGAGE
from agent.runtime import CHAT_DISCARDED, CHAT_FAILED, STATE_EMERGENCY, STATE_POSTING

print("■ 設定")
c = AgentConfig.load(lambda key, default=None: {"agent.output_mode": "chat", "agent.chat_send_mode": "auto"}.get(key))
check("応答のしかた・送る前の確認を読む", c.output_mode == OUTPUT_CHAT and c.chat_send_mode == "auto")
c = AgentConfig.load(lambda key, default=None: {"agent.output_mode": "???", "agent.chat_send_mode": "???"}.get(key))
check("知らない値なら既定（声・毎回確認）", c.output_mode == OUTPUT_VOICE and c.chat_send_mode == "approve")
check("チャットの上限は声より厳しい（1分1通・1時間20通）", AgentConfig(output_mode=OUTPUT_CHAT).utterance_limits == (1, 20)
      and AgentConfig().utterance_limits == (2, 30))

print("■ T45 チャットに返す（声は使わない）")
a = Agent(mode=MODE_ENGAGE, output_mode=OUTPUT_CHAT)
a.say("アイ、今日なにしてた？")
check("T45 チャットに1通", wait_until(lambda: len(a.chat.posted) == 1), a.logs[-3:])
check("T45 音声合成・再生は呼ばれない", a.speaker.spoken == [])
combined = a.decide_calls()[0]
check("呼ばれたので1回で頼む。そのときもチャット用の文の作り方で頼む", combined.hints.get("combined")
      and "改行は2つまで" in combined.system and "チャットに書き込む文" in combined.messages[0].content
      and a.generate_calls() == [])
check("判断にも「今の応答のしかた: チャット」を伝える", "チャット欄に書き込む" in a.decide_calls()[0].messages[0].content)
check("発言の記録は posted", wait_until(lambda: a.utterance_rows() and a.utterance_rows()[-1][1] == "posted"),
      a.utterance_rows())
check("送れた文は自分の直近の発言になる", a.runtime.window.own_utterances()[-1].text == a.chat.posted[0])

b = Agent(mode=MODE_ENGAGE, output_mode=OUTPUT_CHAT)
b.say("最近どう？", speaker="C")
check("呼ばれていなければ、チャット用の文の作り方で文だけ頼む", wait_until(lambda: len(b.chat.posted) == 1)
      and b.generate_calls()[0].system == GENERATE_CHAT_SYSTEM
      and "チャットに書き込む文" in b.generate_calls()[0].messages[0].content)
b.close()

print("■ チャットは1分に1通")
a.runtime._last_utterance_end = time.time() - 60      # 直後の間（R6）は過ぎたことにする
a.say("アイ、もう1つ聞いていい？", speaker="B")
check("2通目は規則で記録だけ（R7）", a.wait_decisions(2) and a.decisions()[-1][3] == "R7" and len(a.chat.posted) == 1,
      a.decisions())
a.close()

print("■ 呼ばれたのに1分の上限に当たったら、空くのを待って返事する（2026-10-16 実物で返事をしなかった）")
a = Agent(mode=MODE_ENGAGE, output_mode=OUTPUT_CHAT, ai_name="テストちゃん", self_names="テストちゃ👼",
          conversation_enabled=False)      # ふだんの上限（チャットは1分1通）で確かめる
a.runtime._utterance_times = [time.time() - 58.5]      # 58.5秒前に送った（あと約2秒で空く）
a.runtime._last_utterance_end = time.time() - 58.5
a.say("@テストちゃ.. 起動テストしてるけど調子どう？", speaker="テスト2")
check("まず保留（R7）", a.wait_decisions(1) and a.decisions()[-1][0] == "hold" and a.decisions()[-1][3] == "R7", a.decisions())
check("空いたら判断して返事する", wait_until(lambda: len(a.chat.posted) == 1, 6.0), a.logs[-4:])
check("判断のログに保留と見直す時間が出る", any("⏸ 保留（R7" in line and "秒後に見直す" in line for line in a.logs), a.logs)
check("呼ばれた出来事は長く待てる（90秒）", a.runtime._hold_limit(make_event("@テストちゃ.. ねえ")) == 90.0
      and a.runtime._hold_limit(make_event("ねえ")) == 30.0)
a.close()

print("■ チャットは改行を残し、声より長く書ける（2026-10-16）")
a = Agent(mode=MODE_ENGAGE, output_mode=OUTPUT_CHAT)
a.mock.script_generate = [{"text": "それいいね！\n" + "あ" * 150 + "\nまた教えて", "emotion": "joy"}]
a.say("最近どう？", speaker="C")
check("改行入り・150字を超える文もチャットに送る（上限200）", wait_until(lambda: len(a.chat.posted) == 1)
      and a.chat.posted[0].count("\n") == 2, a.utterance_rows())
a.close()

print("■ T46 捨てた下書きは数えない")
a = Agent(mode=MODE_ENGAGE, output_mode=OUTPUT_CHAT, min_gap_after_speaking=0.0)
a.chat.answer = CHAT_DISCARDED
a.mock.script_generate = [{"text": "一つ目の下書き", "emotion": "calm"}, {"text": "二つ目の下書きです", "emotion": "calm"}]
a.say("ねえ？")
check("T46 捨てたら送らない（記録は discarded）", wait_until(lambda: a.utterance_rows() != [])
      and a.utterance_rows()[-1][1] == "discarded" and a.chat.posted == [], a.utterance_rows())
a.chat.answer = "posted"
a.say("じゃあこれは？", speaker="B")
check("T46 捨てた分は回数に数えないので、次は送れる", wait_until(lambda: len(a.chat.posted) == 1), a.decisions())
a.close()

print("■ T47 長すぎる文は送らない（途中で切らない）")
a = Agent(mode=MODE_ENGAGE, output_mode=OUTPUT_CHAT)
a.mock.script_generate = [{"text": "あ" * 300, "emotion": "calm"}]
a.say("ねえ？")
check("T47 確認にも出さず、送らない", wait_until(lambda: a.utterance_rows() != [])
      and a.utterance_rows()[-1][1] == "dropped:C2" and a.chat.asked == [], a.utterance_rows())
a.close()

print("■ T48 送った文がチャット欄に出ても反応しない")
a = Agent(mode=MODE_ENGAGE, output_mode=OUTPUT_CHAT)
a.runtime.submit(make_event("さっきAIが書いた文", speaker="自分", is_self=True))
check("T48 自分の発言だけなら記録だけ（R3）", a.wait_decisions(1) and a.decisions()[-1][3] == "R3" and a.decide_calls() == [])
a.close()

print("■ T49 監視していないとき")
a = Agent(mode=MODE_ENGAGE, output_mode=OUTPUT_CHAT)
a.chat.answer = CHAT_FAILED
a.say("ねえ？")
check("T49 送れなかったことを記録し、止まらない", wait_until(lambda: a.utterance_rows() != [])
      and a.utterance_rows()[-1][1] == "chat_failed" and any("送れませんでした" in line for line in a.logs)
      and a.runtime._thread.is_alive(), a.logs[-2:])
check("T49 送れなかった分は回数に数えない", a.runtime._utterance_times == [])
a.close()

print("■ T50 緊急停止（確認の途中）")
a = Agent(mode=MODE_ENGAGE, output_mode=OUTPUT_CHAT)
a.chat.answer = "wait"
a.say("ねえ？")
check("確認を待っている", a.chat.waiting.wait(3.0) and a.runtime.state == STATE_POSTING, a.runtime.state)
t0 = time.monotonic()
a.runtime.emergency_stop()
check("T50 緊急停止で確認の途中でもすぐやめる", wait_until(lambda: a.utterance_rows() != [], 1.0)
      and a.utterance_rows()[-1][1] == "cancelled" and time.monotonic() - t0 < 1.0, a.utterance_rows())
check("T50 状態は緊急停止中", a.runtime.state == STATE_EMERGENCY)
a.close()

print("■ 監視ワーカーの送信待ち（AgentChatText）")
db = A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db"))
w = A.AutoReplyWorker(db, lambda m: None)
check("監視していなければ積まない", w.enqueue_agent_text("こんにちは") == (False, "監視中ではないため送信できません。"))
w.is_running = True
w.thread = type("T", (), {"is_alive": lambda self: True})()
check("空は積まない", w.enqueue_agent_text("   ")[0] is False)
w.enqueue_manual_texts(["本人の手入力1"])
check("監視中なら積む", w.enqueue_agent_text("AIの文1") == (True, ""))
w.enqueue_manual_texts(["本人の手入力2"])
w.enqueue_agent_text("AIの文2")
check("AIの文には印が付く（ふつうの文字列としても使える）",
      [isinstance(t, A.AgentChatText) for t in w._manual_queue] == [False, True, False, True]
      and w._manual_queue[1] == "AIの文1")
check("T50 緊急停止では AI の文だけ捨てる（本人の手入力は残す）", w.discard_agent_texts() == 2
      and w._manual_queue == ["本人の手入力1", "本人の手入力2"])
w._manual_queue = []
for i in range(w.MAX_MANUAL_QUEUE):
    w._manual_queue.append(f"x{i}")
check("送信待ちが一杯なら積まない", w.enqueue_agent_text("あふれ") == (False, "送信待ちが一杯です。"))

print("■ 送るのは監視スレッド（手入力と同じ経路）・送った文は自分の発言")
w._manual_queue = [A.AgentChatText("AIが書いた文")]
logs, sent = [], []
w.log = logs.append
w._execute_reply = lambda d, nodes, half_y, y1, y2, text, fc, thr, all_nodes=None, prefix=None: (sent.append(text), (fc, True))[1]
w._drain_manual_sends(None, [], 0, 0, 960, 0, 3)
check("監視スレッドが送る", sent == ["AIが書いた文"])
check("ログで AI の文と分かる", any("🤖 AIの文を送信します" in m for m in logs), logs)
check("送った文は自分の発言として覚える（自動返信しない）", w._is_own_manual_text("自分: AIが書いた文"))
notes = []
w.agent_note = notes.append
w._manual_queue = [A.AgentChatText("届いた文"), "本人の手入力"]
w._drain_manual_sends(None, [], 0, 0, 960, 0, 3)
check("AIの文を実際に送れたことを、AIタブの判断のログにも出す（本人の手入力の分は出さない）",
      notes == ["✉️ チャットに送りました:「届いた文」"], notes)
w._execute_reply = lambda d, nodes, half_y, y1, y2, text, fc, thr, all_nodes=None, prefix=None: (fc + 1, False)
w._manual_queue = [A.AgentChatText("届かなかった文")]
w._drain_manual_sends(None, [], 0, 0, 960, 0, 3)
check("送れなかったときも出す", notes[-1].startswith("⚠️ チャットに送れませんでした") and "届かなかった文" in notes[-1], notes)

print("■ メンション付きの文は、文を入れてからアイコンをダブルタップして送る（2026-10-22 実機で確かめた順番）")
calls = []
w._send_with_mention = lambda d, text, name: (calls.append((text, name)), True)[1]
w._restore_target_app_if_left = lambda d: None
w._scroll_down = lambda d, y1, y2, silent=False: None
w._extract_chat_texts = lambda xml, y1, y2: (None, None, ["読み直した欄"], ["読み直した全部"])
d = type("D", (), {"dump_hierarchy": lambda self, compressed=True: "<hierarchy/>"})()
got, notes = [], []
w.agent_note = notes.append
w._execute_reply = lambda d, nodes, half_y, y1, y2, text, fc, thr, all_nodes=None: (
    got.append((str(text), nodes, all_nodes)), (fc, True))[1]
item = A.AgentChatText("こんばんは")
item.mention = "たろう"
w._manual_queue = [item, A.AgentChatText("みんなへ"), "本人の手入力"]
w._drain_manual_sends(d, ["前の欄"], 0, 0, 960, 0, 3)
check("メンションする相手がいる文だけ、メンション付きの送り方で送る（ふつうの送り方は使わない）",
      calls == [("こんばんは", "たろう")] and [g[0] for g in got] == ["みんなへ", "本人の手入力"], (calls, got))
check("送れたことを判断のログに", "✉️ チャットに送りました:「こんばんは」" in notes, notes)
w._send_with_mention = lambda d, text, name: None
got.clear()
item = A.AgentChatText("こんばんは")
item.mention = "いない人"
w._manual_queue = [item]
w._drain_manual_sends(d, ["前の欄"], 0, 0, 960, 0, 3)
check("メンションを付けられなかったら、画面を読み直して、メンションなしのふつうの送り方で送る（文に @ を書き足さない）",
      got == [("こんばんは", ["読み直した欄"], ["読み直した全部"])], got)
w._send_with_mention = lambda d, text, name: False
got.clear()
item = A.AgentChatText("こんばんは")
item.mention = "たろう"
w._manual_queue = [item]
w._drain_manual_sends(d, ["前の欄"], 0, 0, 960, 0, 3)
check("メンション付きで送ろうとして失敗したら、二重に送らない（送れなかったと知らせる）",
      got == [] and notes[-1].startswith("⚠️ チャットに送れませんでした"), (got, notes[-1:]))

finish()
