# -*- coding: utf-8 -*-
"""
話しかけられたら続けて話す（2026-10-16 本人「ルームで話しかけられた時に間を空けなくても連続して会話できるように…
たくさん話したい人からしたら寂しいからね」）。

模擬の AI・にせのチャット。音は鳴らさない・通信しない。テストの名前・内容は作り物（リポジトリは公開）。
⚠️ 守り: 多く返すのは「呼ばれた・話している相手」のときだけ（ふだんの上限は変えない）・1分に4回まで・前の発言から3秒あける・
   話している相手は90秒で終わり・スイッチでOFFにできる
"""
import time

from agent_harness import Agent, check, finish, make_event, wait_until
from agent.config import AgentConfig
from agent.gate import HOLD, OBSERVE, PASS, Gate, GateSnapshot
from agent.llm.mock import MODE_ENGAGE

now = time.time()


def ev(text, speaker="たろう"):
    return make_event(text, speaker=speaker)


print("■ 関所: 呼ばれたら、ふだんより多く返せる")
check("既定はON", AgentConfig().conversation_enabled is True)
g = Gate(AgentConfig(ai_name="アイ", output_mode="chat"))
check("チャットは1分1通でも、呼ばれたら55秒前に送っていても返す", g.check([ev("アイ、それでさ")],
      GateSnapshot(now, utterance_times=[now - 55])).outcome == PASS)
r = g.check([ev("アイ、ねえねえ")], GateSnapshot(now, utterance_times=[now - 1]))
check("ただし前の発言から3秒はあける（連投に見えないように）", r.outcome == HOLD and r.rule_id == "R7" and 2 <= r.wait_seconds <= 2.3, r)
r = g.check([ev("アイ、まだいる？")], GateSnapshot(now, utterance_times=[now - 50, now - 40, now - 30, now - 20]))
check("1分に4回まで（5回目は空くまで待つ）", r.outcome == HOLD and 10 <= r.wait_seconds <= 11, r)
check("呼ばれていない発言は、今まで通りふだんの上限（記録だけ）", g.check([ev("今日は暑いね")],
      GateSnapshot(now, utterance_times=[now - 55])).outcome == OBSERVE)
check("話している相手なら、名前を呼ばれなくても返す", g.check([ev("そうなんだよね", speaker="たろう")],
      GateSnapshot(now, utterance_times=[now - 55], last_utterance_end=now - 1, partners=("たろう",))).outcome == PASS)
check("話している相手でない人は、今まで通り（喋った直後は待つ）", g.check([ev("そうなんだよね", speaker="はなこ")],
      GateSnapshot(now, last_utterance_end=now - 1, partners=("たろう",))).rule_id == "R6")
off = Gate(AgentConfig(ai_name="アイ", output_mode="chat", conversation_enabled=False))
check("OFFなら、呼ばれても1分1通（今まで通り）", off.check([ev("アイ、それでさ")],
      GateSnapshot(now, utterance_times=[now - 55])).rule_id == "R7")

print("■ エージェントの中で: チャットで続けて話す")
a = Agent(mode=MODE_ENGAGE, output_mode="chat", ai_name="アイ", conversation_min_gap_seconds=0.5,
          chat_send_mode="auto")
a.say("アイ、こんばんは！", speaker="たろう")
check("1通目", wait_until(lambda: len(a.chat.posted) == 1, 5.0))
a.say("最近なにしてた？", speaker="たろう")
check("名前を呼ばれなくても、返事をした相手には続けて返す（1分1通を待たない）", wait_until(lambda: len(a.chat.posted) == 2, 5.0),
      a.logs[-3:])
content = a.decide_calls()[-1].messages[0].content
check("AI には［あなたと話している相手］の目印", "たろう: 最近なにしてた？ ［あなたと話している相手］" in content, content[-300:])
a.say("ねえ聞いて", speaker="はなこ")
time.sleep(1.5)
check("ほかの人の、呼ばれていない発言は今まで通り（1分1通で記録だけ）", len(a.chat.posted) == 2
      and any("R7" in line or "R6" in line for line in a.logs[-3:]), a.logs[-3:])
a.runtime._partners["たろう"] = time.time() - 1
a.say("ところでさ", speaker="たろう")
time.sleep(1.5)
check("話している相手は時間が過ぎたら終わり（ふだんの上限に戻る）", len(a.chat.posted) == 2, a.logs[-3:])
a.close()

print("■ 特定の人にチャットで返すときはメンション（2026-10-16 本人「特定の誰かにチャットで返信する場合メンションするように」）")
check("既定はON", AgentConfig().chat_mention is True)
a = Agent(mode=MODE_ENGAGE, output_mode="chat", ai_name="アイ", chat_send_mode="auto", conversation_min_gap_seconds=0.0,
          conversation_max_per_minute=10, max_decisions_per_minute=20)
a.mock.script_decide = [{"action": "engage", "reason": "x", "target": "ながいなまえの", "text": "こんばんは！", "emotion": "joy"}]
a.say("アイ、こんばんは", speaker="ながいなまえのひと")
check("文の頭に @名前 を付ける（切れて出た名前は、切れていない名前に）", wait_until(lambda: a.chat.posted, 5.0)
      and a.chat.posted[-1] == "@ながいなまえのひと こんばんは！", a.chat.posted)
a.mock.script_decide = [{"action": "engage", "reason": "x", "target": "たろう", "text": "@たろう もう付いてる", "emotion": "joy"}]
a.say("アイ、ねえ", speaker="たろう")
check("もう @名前 があれば付けない", wait_until(lambda: len(a.chat.posted) == 2, 5.0) and a.chat.posted[-1] == "@たろう もう付いてる",
      a.chat.posted)
a.mock.script_decide = [{"action": "engage", "reason": "x", "target": None, "text": "みんなおつかれ！", "emotion": "joy"}]
a.say("アイ、みんなに一言", speaker="たろう")
check("場全体に向けた文には付けない", wait_until(lambda: len(a.chat.posted) == 3, 5.0) and a.chat.posted[-1] == "みんなおつかれ！")
a.mock.script_decide = [{"action": "engage", "reason": "x", "target": "はなこ"}]
a.mock.script_generate = [{"text": "わかった", "emotion": "calm"}]
a.say("アイ、聞いて", speaker="はなこ")
check("文を作るときに「@ はツールが付ける」と伝える", wait_until(lambda: len(a.chat.posted) == 4, 5.0)
      and "ツールが文の頭に @相手の名前 を付ける" in a.generate_calls()[-1].messages[0].content
      and a.chat.posted[-1] == "@はなこ わかった", a.chat.posted)
a.mock.script_decide = [{"action": "engage", "reason": "x", "target": "はなこさん", "text": "呼び方で返した", "emotion": "calm"}]
a.say("アイ、ねえねえ", speaker="はなこ")
check("AI が「はなこさん」と呼び方で返しても、アカウント名（@はなこ）にする", wait_until(lambda: len(a.chat.posted) == 5, 5.0)
      and a.chat.posted[-1] == "@はなこ 呼び方で返した", a.chat.posted)
a.mock.script_decide = [{"action": "engage", "reason": "x", "target": "知らない人", "text": "だれ？", "emotion": "calm"}]
a.say("アイ、あの人だれ？", speaker="はなこ")
check("チャット欄に出ていない名前には付けない（作った名前でメンションしない）", wait_until(lambda: len(a.chat.posted) == 6, 5.0)
      and a.chat.posted[-1] == "だれ？", a.chat.posted)
a.runtime.config.chat_mention = False
a.mock.script_decide = [{"action": "engage", "reason": "x", "target": "はなこ", "text": "メンションなし", "emotion": "calm"}]
a.say("アイ、もう一回", speaker="はなこ")
check("OFFなら付けない", wait_until(lambda: len(a.chat.posted) == 7, 5.0) and a.chat.posted[-1] == "メンションなし",
      (a.chat.posted[-2:], a.logs[-4:]))
a.close()

finish()
