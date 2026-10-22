# -*- coding: utf-8 -*-
"""
話を譲る・続きを話す・自分の声を知る（2026-10-16 本人「割り込みされた時に、会話の機会を相手に譲って、それまでの話したかったことを
一旦停止して、相手が会話を終わらせたタイミングで会話を再開する仕組み」「自身の声はこーゆう声だって自己認識する仕組み」）。

模擬の AI・にせの声（鳴らさない）・作った音。通信しない。テストの名前・内容は作り物（リポジトリは公開）。
"""
import time

from agent_harness import Agent, check, finish, make_event, wait_until
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

print("■ 喋り終えた自分の声が、漢字とかなの違う文になって聞こえても、自分の声（2026-10-22 本人「声聞こえてないのに声聞こえてるとか嘘ついてる」）")
# 実物: AI が「たしかにまだ朝だもんね、眠気も残るよね。」と喋り、5秒後に「確かにまだ朝だもんね。」と文字になった。
# 文字の似方が 0.64 で、自分の声と見分けられず、オーナーの声（オーナーのマイク経由）として渡っていた
a = Agent(mode=MODE_ENGAGE, output_mode="voice_room", hearing_enabled=True, ai_name="アイ", owner_names="オーナー",
          max_utterances_per_minute=10, min_gap_after_speaking=0.0)
a.mock.script_decide = [{"action": "engage", "reason": "呼ばれた", "target": "たろう",
                         "text": "たしかにまだ朝だもんね、眠気も残るよね。", "emotion": "calm"}]
a.say("アイ、ねむたい", speaker="たろう")
check("喋り終える", wait_until(lambda: a.speaker.spoken == ["たしかにまだ朝だもんね、眠気も残るよね。"]
                               and a.runtime._current_text is None, 5.0), a.speaker.spoken)
a.mock.script_transcribe = [{"heard": "確かにまだ朝だもんね。", "text": "確かにまだ朝だもんね。", "confidence": "high"}]
check("漢字とかなが違っても、喋った文の一部なら自分の声として使わない", a.runtime.hear(WAV, 1.9) is None, a.logs[-2:])
a.mock.script_transcribe = [{"heard": "確かにまだ朝だもんね。", "text": "確かにまだ朝だもんね。", "confidence": "high"}]
check("オーナーのマイク経由で聞こえても、自分の声はオーナーの声にしない", a.runtime.hear(WAV, 1.9, speaker="オーナー") is None)
a.mock.script_transcribe = [{"heard": "朝だね", "text": "朝だね", "confidence": "high"}]
check("短い・一部だけ同じ人の声は使う（自分の声と取り違えない）", a.runtime.hear(WAV, 1.0) == "朝だね")
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

print("■ チャットで気持ちを GRAVITY の顔で表す（2026-10-16「絵文字で表現」→ 2026-10-22 本人「グラビティアプリ内で使える顔文字」を「使う」）")
# GRAVITY の顔は文字の符号（「[無表情]」など）でチャット欄に入り、GRAVITY が顔の絵にする（実機の一覧で71個の符号を読んだ）
from agent.gravity_faces import ALL_CODES, clean_faces
check("顔の符号は71個（実機の一覧で読んだもの）", len(ALL_CODES) == 71 and "[無表情]" in ALL_CODES and "[パチパチ]" in ALL_CODES)
a = Agent(mode=MODE_ENGAGE, output_mode="chat", ai_name="アイ", chat_send_mode="auto")
a.mock.script_decide = [{"action": "engage", "reason": "お祝い", "target": "たろう",
                         "text": "おめでとう！🎉 すごいね[おめでとう][パチパチ][拍手][にこやか]", "emotion": "joy"}]
a.say("アイ、合格したよ", speaker="たろう")
check("チャットのときは、GRAVITY の顔の一覧と使い方を伝える（ふつうの絵文字・顔文字は使わない）",
      wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
      and "## 絵文字（GRAVITY の顔）" in a.decide_calls()[0].messages[0].content
      and "[にこやか]" in a.decide_calls()[0].messages[0].content
      and "ふつうの絵文字" in a.decide_calls()[0].messages[0].content
      and "絵文字の使い方は「## 絵文字」に従う" in a.decide_calls()[0].system)
check("送る前に、ふつうの絵文字と一覧に無い符号を外し、顔は2個まで",
      wait_until(lambda: len(a.chat.posted) == 1, 5.0) and a.chat.posted[0] == "おめでとう！ すごいね[おめでとう][パチパチ]",
      a.chat.posted)
a.close()
check("人が書いた長い括弧・空白入りの括弧は外さない", clean_faces("[今日のテーマ: 好きな食べ物] いいね[にこやか]")
      == "[今日のテーマ: 好きな食べ物] いいね[にこやか]")
a = Agent(mode=MODE_ENGAGE, output_mode="chat", ai_name="アイ", chat_send_mode="auto", chat_emoji=False)
a.say("アイ、合格したよ", speaker="たろう")
check("OFFなら「絵文字・GRAVITY の顔は使わない」", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
      and "絵文字・GRAVITY の顔は使わない" in a.decide_calls()[0].messages[0].content)
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

print("■ 返さなかったら、相手がどう思うかを心の中で考えて、もう一度考える（2026-10-22 本人「無視した場合のこと考えて相手はこう考えるかも"
      "しれないと、心の中で考え、再度返すべきか考える機能欲しい」）")
from agent.config import AgentConfig
check("既定はON", AgentConfig().reconsider_enabled is True)
a = Agent(mode=MODE_ENGAGE, output_mode="chat", ai_name="アイ", chat_send_mode="auto", reconsider_seconds=0.3,
          min_gap_after_speaking=0.0, chat_max_per_minute=10, max_decisions_per_minute=20)   # 回数の上限に当たらないように
a.mock.script_decide = [{"action": "silent", "reason": "割り込むほどではない", "target": None, "inner": "疲れてるのかな"},
                        {"action": "react", "reason": "寂しくさせたくない", "target": "たろう", "inner": "無視されたと思うかも"}]
a.say("今日はほんと疲れたなあ", speaker="たろう")
check("返さないと決めても、すぐに終わりにせず、少しあとでもう一度考える", wait_until(lambda: len(a.decide_calls()) >= 2, 5.0)
      and any("もう一度考えます" in line for line in a.logs), a.logs[-4:])
second = a.decide_calls()[1].messages[0].content if len(a.decide_calls()) >= 2 else ""
check("もう一度考えるときに、さっき返さなかったこと・そのときの心の中・「相手はどう思うかもしれないか」を渡す",
      "## さっき返さなかった発言（もう一度考える）" in second and "割り込むほどではない" in second
      and "疲れてるのかな" in second and "相手はどう思うかもしれないか" in second, second[-700:])
check("考え直して返すなら、返す", wait_until(lambda: len(a.chat.posted) == 1, 5.0), a.chat.posted)
a.mock.script_decide = [{"action": "silent", "reason": "独り言っぽい", "target": None},
                        {"action": "silent", "reason": "まだ独り言っぽい", "target": None}]
a.runtime.config.reconsider_gap_seconds = 0.0
a.say("ふあ〜あ", speaker="はなこ")
check("もう一度考えても返さないなら、そこで終わり（同じ発言は1回だけ考え直す）", wait_until(lambda: len(a.decide_calls()) >= 4, 5.0)
      and (time.sleep(1.0) or len(a.decide_calls()) == 4) and len(a.chat.posted) == 1, len(a.decide_calls()))
a.runtime.config.reconsider_gap_seconds = 60.0
a.mock.script_decide = [{"action": "silent", "reason": "割り込まない", "target": None}]
a.say("お茶飲もう", speaker="じろう")
check("考え直すのは1分に1回まで（AI を呼ぶ回数を増やしすぎない）", wait_until(lambda: len(a.decide_calls()) >= 5, 5.0)
      and (time.sleep(1.0) or len(a.decide_calls()) == 5), len(a.decide_calls()))
a.close()
a = Agent(mode=MODE_ENGAGE, output_mode="chat", ai_name="アイ", chat_send_mode="auto", reconsider_seconds=0.3,
          reconsider_enabled=False)
a.mock.script_decide = [{"action": "silent", "reason": "割り込まない", "target": None}]
a.say("今日はほんと疲れたなあ", speaker="たろう")
check("OFFなら考え直さない", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0) and (time.sleep(1.0) or len(a.decide_calls()) == 1))
a.close()
a = Agent(mode=MODE_ENGAGE, output_mode="chat", ai_name="アイ", chat_send_mode="auto", reconsider_seconds=0.3,
          ignored_people="あらし")
a.mock.script_decide = [{"action": "silent", "reason": "お知らせ", "target": None}]
from dataclasses import replace as _replace
from agent.events import KIND_CHAT_NOTICE
a.runtime.submit(_replace(make_event("はなこが音声ルームに参加しました", speaker="はなこ"), kind=KIND_CHAT_NOTICE))
check("お知らせ（人の発言でないもの）は考え直さない", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
      and (time.sleep(1.0) or len(a.decide_calls()) == 1), len(a.decide_calls()))
a.close()

finish()
