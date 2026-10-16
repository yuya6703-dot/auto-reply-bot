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

print("■ 言いかけたことは3分で忘れる")
a = Agent(mode=MODE_ENGAGE)
a.runtime._keep_pending("古い話", "テスト")
a.runtime._pending_thought["at"] -= 181
check("3分たったら渡さない", a.runtime._pending_lines(time.time()) == [] and a.runtime._pending_thought is None)
a.close()

finish()
