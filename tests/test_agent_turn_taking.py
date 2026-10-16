# -*- coding: utf-8 -*-
"""
話を譲る・続きを話す・自分の声を知る（2026-10-16 本人「割り込みされた時に、会話の機会を相手に譲って、それまでの話したかったことを
一旦停止して、相手が会話を終わらせたタイミングで会話を再開する仕組み」「自身の声はこーゆう声だって自己認識する仕組み」）。

模擬の AI・にせの声（鳴らさない）・作った音。通信しない。テストの名前・内容は作り物（リポジトリは公開）。
"""
import time

from agent_harness import Agent, check, finish, wait_until
from agent.hearing import to_wav
from agent.llm.mock import MODE_ENGAGE

WAV = to_wav(b"\0" * 32000, 16000)

print("■ 自分の声を知る")
a = Agent(mode=MODE_ENGAGE, start=False, output_mode="voice_room", ai_name="アイ")
a.runtime.deps.voice_profile = lambda: "テストの声（ノーマル）"
a.runtime.start()
a.say("アイ、こんにちは", speaker="たろう")
check("AI に「あなたの声」を伝える", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
      and "あなたの声: テストの声（ノーマル）" in a.decide_calls()[0].messages[0].content)
a.close()

print("■ 自分が喋っている間に聞こえた自分の声")
a = Agent(mode=MODE_ENGAGE, output_mode="voice_room", hearing_enabled=True, ai_name="アイ", play_seconds=3.0,
          max_utterances_per_minute=10, min_gap_after_speaking=0.0)
a.mock.script_decide = [{"action": "engage", "reason": "呼ばれた", "target": "たろう",      # 呼ばれたので判断と文を1回で
                         "text": "今日は星がきれいに見えるらしいよ", "emotion": "joy"}]
a.say("アイ、なにか話して", speaker="たろう")
check("喋り始める", a.speaker.speaking.wait(5.0))
a.runtime.on_voice_activity(True)
check("自分が喋っている間の「話している」は、自分の声なので数えない", not a.runtime._snapshot(time.time()).listening)
a.mock.script_transcribe = [{"heard": "星がきれいに見えるらしい", "text": "星がきれいに見えるらしい", "confidence": "high"}]
check("聞こえた声が自分の言っている文なら、自分の声として使わない", a.runtime.hear(WAV, 2.0) is None
      and any("自分の声なので使いません" in line for line in a.logs) and a.speaker.cancelled == [])

print("■ 喋っている途中で、ほかの人が話し始めたら譲る")
a.mock.script_transcribe = [{"heard": "ちょっと待って、それ私も見たい", "text": "ちょっと待って、それ私も見たい", "confidence": "high"}]
a.mock.script_decide = [{"action": "engage", "reason": "続き", "target": "はなこ"}]
check("聞こえた声は使う", a.runtime.hear(WAV, 2.0) == "ちょっと待って、それ私も見たい")
check("喋るのをやめて譲る", wait_until(lambda: a.speaker.cancelled == ["今日は星がきれいに見えるらしいよ"], 3.0),
      (a.speaker.cancelled, a.logs[-3:]))
check("譲ったことを判断のログに", any("話を譲りました" in line for line in a.logs))
check("相手が話している間は待つ", a.runtime._snapshot(time.time()).listening)
a.runtime.on_voice_activity(False)
check("相手が話し終えたら判断する。言いかけたことを渡す（続けるか考える）", wait_until(
    lambda: any("## 言いかけて止めたこと" in r.messages[0].content and "今日は星がきれいに見えるらしいよ" in r.messages[0].content
                for r in a.decide_calls()), 5.0))
check("「さっきの続きだけど」などと続けてよい、合わなければ忘れてよい", "さっきの続きだけど" in a.decide_calls()[-1].messages[0].content)
check("話せたら、言いかけたことは終わり", wait_until(lambda: len(a.speaker.spoken) >= 1, 8.0)
      and wait_until(lambda: a.runtime._pending_thought is None, 3.0))
a.close()

print("■ チャット: 作っている間に会話が進んで出さなかった返事も、言いかけたこととして渡す")
a = Agent(mode=MODE_ENGAGE, output_mode="chat", ai_name="アイ", chat_send_mode="auto", conversation_min_gap_seconds=0.0)
a.mock.delay_seconds = 0.8
a.say("アイ、映画の話しよう", speaker="たろう")
time.sleep(0.5)
a.say("やっぱりゲームの話にしよう", speaker="たろう")
check("出さなかった返事を覚える", wait_until(lambda: a.runtime._pending_thought is not None
                                           or any("言いかけて止めたこと" in r.messages[0].content for r in a.decide_calls()), 8.0),
      a.logs[-4:])
check("次の判断に渡す", wait_until(lambda: any("会話が進んだので出さなかった" in r.messages[0].content for r in a.decide_calls()), 8.0))
a.close()

print("■ 笑い声・相づちは割り込みにしない（2026-10-16 本人「笑い声を会話の割り込みとして捉えないように」「草」「くさ」も）")
from agent.hearing import is_backchannel, is_laughter
check("笑い声を見分ける", all(is_laughter(t) for t in ("あはは", "あっはっは", "www", "（笑）", "草", "くさ", "草生える",
                                                        "大草原", "わろた", "ウケる", "ふふっ")))
check("笑いでない言葉は笑いにしない", not any(is_laughter(t) for t in ("くさい", "草むしり", "はい", "ほんと？", "あははそれ面白い")))
check("相づちも見分ける（割り込みにはしない）", all(is_backchannel(t) for t in ("うんうん", "へー", "なるほど", "そうなんだ", "えー"))
      and not is_backchannel("ちょっと待って"))
a = Agent(mode=MODE_ENGAGE, output_mode="voice_room", hearing_enabled=True, ai_name="アイ", play_seconds=2.0,
          max_utterances_per_minute=10, min_gap_after_speaking=0.0)
a.mock.script_decide = [{"action": "engage", "reason": "呼ばれた", "target": "たろう", "text": "それでね、昨日おもしろいことがあって",
                         "emotion": "joy"}]
a.say("アイ、なにか話して", speaker="たろう")
a.speaker.speaking.wait(5.0)
a.mock.script_transcribe = [{"heard": "あはは", "text": "あはは", "confidence": "high", "kind": "laugh"}]
check("喋っている途中の笑い声では止まらない（話し続ける）", a.runtime.hear(WAV, 1.0) is None and a.speaker.cancelled == []
      and any("割り込みにしません" in line for line in a.logs))
a.mock.script_transcribe = [{"heard": "うんうん", "text": "うんうん", "confidence": "high", "kind": "backchannel"}]
check("相づちでも止まらない", a.runtime.hear(WAV, 1.0) is None and a.speaker.cancelled == [])
check("話し終える", wait_until(lambda: len(a.speaker.spoken) == 1, 5.0))
calls = len(a.decide_calls())
a.mock.script_transcribe = [{"heard": "草", "text": "草", "confidence": "high", "kind": "laugh"}]
a.runtime.hear(WAV, 1.0)
check("喋っていないときの笑い声だけには返事をしない（記録だけ）", wait_until(lambda: any("R9" in line for line in a.logs), 5.0)
      and len(a.decide_calls()) == calls, a.logs[-3:])
a.close()

print("■ チャットで気持ちを絵文字で表す（2026-10-16 本人「チャットで感情を出す時、絵文字で表現する仕組み」）")
a = Agent(mode=MODE_ENGAGE, output_mode="chat", ai_name="アイ", chat_send_mode="auto")
a.say("アイ、合格したよ", speaker="たろう")
check("チャットのときは、気持ちに合う絵文字を1〜2個使ってよいと伝える", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
      and "気持ちに合う絵文字を1〜2個" in a.decide_calls()[0].messages[0].content
      and "絵文字の使い方は「## 絵文字」に従う" in a.decide_calls()[0].system)
a.close()
a = Agent(mode=MODE_ENGAGE, output_mode="chat", ai_name="アイ", chat_send_mode="auto", chat_emoji=False)
a.say("アイ、合格したよ", speaker="たろう")
check("OFFなら「絵文字は使わない」", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
      and "絵文字は使わない" in a.decide_calls()[0].messages[0].content)
a.close()

print("■ 心の中（2026-10-16 本人「考えながら話をする仕組み…いわゆる心の中」）")
import os, tempfile
from agent.decision import DECISION_SCHEMA, parse_decision
from agent.events import SOURCE_GRAVITY
from agent.memory.journal import ConversationJournal
from agent_harness import make_event
check("判断の形に「心の中」（口に出さない）", "inner" in DECISION_SCHEMA["properties"]
      and parse_decision({"action": "silent", "reason": "x", "inner": " 今は言わなくていいかも "}, "t").inner == "今は言わなくていいかも")
a = Agent(mode=MODE_ENGAGE, start=False, journal_enabled=True, ai_name="アイ", min_gap_after_speaking=0.0)
root = os.path.join(tempfile.mkdtemp(), "AIの記憶")
a.runtime.deps.journal = ConversationJournal(root, lambda: True)
a.runtime.start()
a.mock.script_decide = [{"action": "silent", "reason": "様子見", "inner": "この話は深掘りしないほうがよさそう"},
                        {"action": "engage", "reason": "呼ばれた", "target": "たろう", "inner": "さっき黙ったけど、今なら聞ける",
                         "text": "どうしたの？", "emotion": "calm"}]
a.runtime.submit(make_event("ちょっと疲れたな", speaker="たろう", source=SOURCE_GRAVITY, account="テスト垢"))
check("心の中を判断のログに（口に出さない）", wait_until(lambda: any("💭 心の中:「この話は深掘りしないほうがよさそう」" in line
                                                         for line in a.logs), 5.0) and a.speaker.spoken == [])
a.runtime.submit(make_event("アイ、聞いてる？", speaker="たろう", source=SOURCE_GRAVITY, account="テスト垢"))
check("次の判断に「さっきの心の中」を渡す（考えの続き）", wait_until(lambda: len(a.decide_calls()) >= 2, 5.0)
      and "## さっきの心の中" in a.decide_calls()[-1].messages[0].content
      and "この話は深掘りしないほうがよさそう" in a.decide_calls()[-1].messages[0].content)
check("固定の指示に「inner は口に出さない本音」", "口に出さない本音" in a.decide_calls()[-1].system)
day_file = os.path.join(root, "テスト垢", "心の中", time.strftime("%Y-%m-%d") + ".md")
check("会話をファイルに残すがONなら「心の中/日付.md」にも", wait_until(lambda: os.path.exists(day_file), 3.0)
      and "この話は深掘りしないほうがよさそう" in open(day_file, encoding="utf-8").read())
a.runtime._thoughts = [(t - 1300, x) for t, x in a.runtime._thoughts]
check("20分で忘れる", a.runtime._thought_lines(time.time()) == [])
a.close()

print("■ 考え中のつなぎ言葉（2026-10-16 本人「考えてる最中にあーとか、えーととかをいうとか、うーんとかもね」）")
FILLERS = ("えーと", "うーん", "あー", "んーと")
a = Agent(mode=MODE_ENGAGE, output_mode="voice_room", ai_name="アイ", filler_after_seconds=0.3, hearing_enabled=True)
a.mock.delay_seconds = 1.0
a.say("アイ、ちょっと難しい質問なんだけど", speaker="たろう")
check("返事を作るのに時間がかかったら、先に「えーと」などを言う", wait_until(lambda: len(a.speaker.spoken) >= 2, 6.0)
      and a.speaker.spoken[0] in FILLERS and a.speaker.spoken[1] not in FILLERS, a.speaker.spoken)
check("判断のログに 🤔", any("🤔 考え中:" in line for line in a.logs))
a.mock.script_transcribe = [{"heard": a.speaker.spoken[0], "text": a.speaker.spoken[0], "confidence": "high"}]
check("聞こえた自分のつなぎ言葉は、自分の声として使わない", a.runtime.hear(WAV, 1.0) is None)
a.close()
a = Agent(mode=MODE_ENGAGE, output_mode="voice_room", ai_name="アイ", filler_after_seconds=0.3)
a.say("アイ、こんにちは", speaker="たろう")
check("すぐ返せるときは言わない", wait_until(lambda: len(a.speaker.spoken) >= 1, 5.0)
      and a.speaker.spoken[0] not in FILLERS and len(a.speaker.spoken) == 1)
a.close()
a = Agent(mode=MODE_ENGAGE, output_mode="chat", ai_name="アイ", filler_after_seconds=0.3, chat_send_mode="auto")
a.mock.delay_seconds = 1.0
a.say("アイ、ちょっと難しい質問", speaker="たろう")
check("チャットでは言わない", wait_until(lambda: len(a.chat.posted) >= 1, 6.0) and a.speaker.spoken == []
      and not any(p in FILLERS for p in a.chat.posted))
a.close()
a = Agent(mode=MODE_ENGAGE, output_mode="voice_room", ai_name="アイ", filler_after_seconds=0.3, thinking_fillers=False)
a.mock.delay_seconds = 1.0
a.say("アイ、ちょっと難しい質問", speaker="たろう")
check("OFFなら言わない", wait_until(lambda: len(a.speaker.spoken) >= 1, 6.0) and a.speaker.spoken[0] not in FILLERS)
a.close()

print("■ 言いかけたことは3分で忘れる")
a = Agent(mode=MODE_ENGAGE)
a.runtime._keep_pending("古い話", "テスト")
a.runtime._pending_thought["at"] -= 181
check("3分たったら渡さない", a.runtime._pending_lines(time.time()) == [] and a.runtime._pending_thought is None)
a.close()

finish()
