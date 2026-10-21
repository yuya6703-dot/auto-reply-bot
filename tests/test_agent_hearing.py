# -*- coding: utf-8 -*-
"""
声を聞く（2026-10-16 本人「iPad mini 6から音を拾う仕組み」→「1から6まで」の6）。
音声入力は にせもの（作った波形）。音は鳴らさない・機材に触らない・通信しない（模擬の AI）。

⚠️ 守り: ONのときだけ（既定OFF）・1時間に文字にする量の上限・読み上げの聞き返しは使わない・音は保存しない・
   話し声の中の指示に従わない（文字にするだけ）・誰が話したかは分からない
"""
import io, math, os, tempfile, time, wave
from array import array

from agent_harness import Agent, check, finish, make_event, wait_until
from agent.config import AgentConfig
from agent.events import SOURCE_GRAVITY
from agent.hearing import FRAME_SECONDS, MAX_SECONDS, VoiceListener, VoiceSegmenter, frame_level, to_wav
from agent.llm.base import LLMMessage, LLMRequest
from agent.llm.gemini import GeminiProvider
from agent.llm.mock import MODE_ENGAGE, MODE_SILENT
from agent.memory.journal import ConversationJournal

RATE = 16000
N = int(RATE * FRAME_SECONDS)


def tone(amplitude, frames=1):
    """frames 個ぶん（30ミリ秒ずつ）の音。amplitude は 0〜1"""
    out = array("h", (int(amplitude * 32767 * math.sin(2 * math.pi * 440 * i / RATE)) for i in range(N * frames)))
    return [out[k * N:(k + 1) * N].tobytes() for k in range(frames)]


def feed_all(seg, frames):
    done = []
    for f in frames:
        done += seg.feed(f)
    return done


print("■ 音の大きさ")
check("無音は0", frame_level(tone(0)[0]) == 0.0)
check("大きい音ほど大きい", 0.6 < frame_level(tone(1.0)[0]) < 0.8 and frame_level(tone(0.1)[0]) < frame_level(tone(0.5)[0]))

print("■ 話し声のかたまりを見つける")
seg = VoiceSegmenter(RATE, threshold=0.05)
done = feed_all(seg, tone(0, 20) + tone(0.5, 40) + tone(0, 40))
check("話し始めて、0.8秒静かになったら1つのかたまり", len(done) == 1, done and [d[1] for d in done])
pcm, seconds = done[0]
check("話し始めの少し前から入れる（頭が切れない）・終わりの静けさも少し入る", 1.4 <= seconds <= 2.5, seconds)
check("かたまりの中身は PCM", len(pcm) == int(round(seconds / FRAME_SECONDS)) * N * 2)
check("物音（0.15秒）は捨てる", feed_all(VoiceSegmenter(RATE, 0.05), tone(0, 20) + tone(0.5, 5) + tone(0, 40)) == [])
check("しきい値より小さい音は声にしない", feed_all(VoiceSegmenter(RATE, 0.3), tone(0, 10) + tone(0.1, 60) + tone(0, 40)) == [])
long_done = feed_all(VoiceSegmenter(RATE, 0.05, adaptive=False), tone(0.5, int(20 / FRAME_SECONDS)) + tone(0, 40))
check("長く続く声は15秒で切る（1回に送る量を増やしすぎない）", len(long_done) == 2 and long_done[0][1] <= MAX_SECONDS + 0.01,
      [d[1] for d in long_done])

print("■ 続いている音（BGM）を下地として覚える（2026-10-16 本人「人が出している声をしっかり認識する仕組み」）")
seg = VoiceSegmenter(RATE, 0.02)
bgm = tone(0.1, int(6 / FRAME_SECONDS))
check("ずっと流れている BGM は声にしない", feed_all(seg, bgm) == [] and not seg.active, seg.floor)
check("下地を覚えて、声とみる大きさが上がる", seg.effective_threshold >= 0.13, (seg.floor, seg.effective_threshold))


def speech_over_bgm(seconds):
    """BGM の上で話す（話し声には息つぎの間がある）"""
    frames = []
    for i in range(int(seconds / FRAME_SECONDS)):
        frames += tone(0.5 if (i // 10) % 3 != 2 else 0.1)
    return frames


done = feed_all(seg, speech_over_bgm(2.0) + bgm[:60])
check("BGM の上で話した声は拾う", len(done) == 1 and 1.5 <= done[0][1] <= 3.5, [d[1] for d in done])
check("話し終わったら、また BGM は声にしない", feed_all(seg, bgm) == [])
quiet = VoiceSegmenter(RATE, 0.02)
feed_all(quiet, bgm)
feed_all(quiet, tone(0, 200))
check("BGM が止まって静かになったら、下地も下がる（小さな声も拾える）", quiet.effective_threshold < 0.03, quiet.effective_threshold)
w = wave.open(io.BytesIO(to_wav(pcm, RATE)))
check("AI へ送る形（WAV・モノラル・16bit）", w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() == RATE)

print("■ PCのスピーカーの音（ループバック。2026-10-16 本人が選んだ取り方）")
from agent.hearing import LOOPBACK_DEFAULT, list_input_devices, loopback_available, to_mono
stereo = array("h", [100, 300, -200, -400, 32000, 32000]).tobytes()
check("2チャンネルを平均して1チャンネルにする", array("h", to_mono(stereo, 2)).tolist() == [200, -300, 32000])
check("1チャンネルはそのまま", to_mono(stereo, 1) == stereo)
check("部品（PyAudioWPatch）があれば、入力のいちばん上に「PCのスピーカーの音」", not loopback_available()
      or list_input_devices()[0] == LOOPBACK_DEFAULT)

print("■ 聞く入力でルームの音が取れるか（MuMu のスピーカーの設定を読む。2026-10-19 本人「音声認識できなくねーか」）")
import json
import os
import tempfile
from agent.hearing import assess_hearing_input, mumu_speakers
root = os.path.join(tempfile.mkdtemp(), "MuMuPlayer")
manager = os.path.join(root, "nx_main", "MuMuManager.exe")


def put_config(vm, data):
    os.makedirs(os.path.join(root, "vms", vm, "configs"), exist_ok=True)
    with open(os.path.join(root, "vms", vm, "configs", "customer_config.json"), "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


check("MuMu が無い・場所が空なら、分からない（空）", mumu_speakers("") == [] and mumu_speakers(manager) == [])
put_config("A-0", {"setting": {"volume_setting": {"loudspeaker": "CABLE Input (VB-Audio Virtual Cable)"}}})
put_config("B-1", {"setting": {"volume_setting": {"loudspeaker": ""}}})
put_config("C-2", "{壊れた設定")
put_config("D-3", {"setting": {}})
check("インスタンスごとのスピーカーを読む（既定の出力は空。壊れた・形の違う設定は飛ばす）",
      mumu_speakers(manager) == ["CABLE Input (VB-Audio Virtual Cable)", ""], mumu_speakers(manager))
CABLE_OUT, CABLE_IN = "CABLE Output (VB-Audio Virtual ", "CABLE Input (VB-Audio Virtual C"     # MME の名前は31文字で切れる
SPEAKER_CABLE = ["CABLE Input (VB-Audio Virtual Cable)"]
ok, why = assess_hearing_input(CABLE_OUT, SPEAKER_CABLE, tts_output=CABLE_IN)
check("MuMu のスピーカーが CABLE Input なら、CABLE Output にルームの声が来る（本人の今の流し方）", ok is True and "読み上げ" in why, why)
ok, why = assess_hearing_input(CABLE_OUT, [""], tts_output=CABLE_IN)
check("MuMu のスピーカーが既定の出力なら、CABLE Output には読み上げしか来ない（ループバックを案内）",
      ok is False and "このアプリの読み上げしか来ません" in why and LOOPBACK_DEFAULT[:12] in why, why)
ok, why = assess_hearing_input(LOOPBACK_DEFAULT, SPEAKER_CABLE, default_output="1 - LCD-MF225X (AMD High Definition Audio Device)")
check("MuMu のスピーカーが CABLE Input なら、既定の出力のループバックには来ない（CABLE Output を案内）",
      ok is False and "「CABLE Output」を選んでください" in why, why)
check("MuMu のスピーカーが既定の出力なら、ループバックで聞ける", assess_hearing_input(LOOPBACK_DEFAULT, [""])[0] is True)
check("MuMu のスピーカーが既定の出力と同じ機器なら、ループバックで聞ける",
      assess_hearing_input(LOOPBACK_DEFAULT, ["Speakers (Anker SoundCore)"], default_output="Speakers (Anker SoundCore)")[0] is True)
check("iPad などのライン入力・マイクは、分からない（何も言わない）",
      assess_hearing_input("Microphone (Senary Audio)", SPEAKER_CABLE, tts_output=CABLE_IN) == (None, "")
      and assess_hearing_input("Line Input (USB Audio)", [""]) == (None, ""))
ok, why = assess_hearing_input(CABLE_OUT, [], tts_output=CABLE_IN)
check("MuMu の設定が読めないときは決めつけない（読み上げと同じケーブルなら、気を付けることだけ伝える）",
      ok is None and "MuMu のスピーカーを「CABLE Input」にしていなければ" in why, why)
print("■ オーナーのマイクに、ルームの音やAIの声が流れる入力を選ばせない（2026-10-22 本人「声聞こえてないのに声聞こえてるとか嘘ついてる」）")
# 実物: オーナーのマイクとルームの音が同じ CABLE Output。ルームの音も AI 自身の声もオーナーの声として渡り、同じ音を2回ずつ文字にしていた
from agent.hearing import owner_mic_problem
check("ルームの音と同じ入力はだめ", "ルームの音と同じ入力" in owner_mic_problem(CABLE_OUT, CABLE_OUT, CABLE_IN))
check("読み上げ（AI の声）が流れる仮想ケーブルの出口はだめ",
      "AI自身の声" in owner_mic_problem(CABLE_OUT, LOOPBACK_DEFAULT, CABLE_IN))
check("ふつうのマイクはよい", owner_mic_problem("Microphone (Senary Audio)", CABLE_OUT, CABLE_IN) == ""
      and owner_mic_problem("", CABLE_OUT, CABLE_IN) == "")
check("別の仮想ケーブル（CABLE-A）は、その入口と組にする",
      assess_hearing_input("CABLE-A Output (VB-Audio Cable A)", ["CABLE-A Input (VB-Audio Cable A)"])[0] is True
      and assess_hearing_input("CABLE-A Output (VB-Audio Cable A)", SPEAKER_CABLE)[0] is False)

print("■ 聞き続ける（にせの音声入力）")
got = []
holder = {}


class FakeStream:
    def stop(self):
        holder["stopped"] = True

    def close(self):
        pass


def factory(push):
    holder["push"] = push
    return FakeStream(), RATE


activity = []
listener = VoiceListener("テストの入力", 0.05, lambda wav, s: got.append((wav[:4], s)), stream_factory=factory,
                         on_activity=activity.append)
ok, why = listener.start()
check("始められる", ok and listener.running, why)
for f in tone(0, 10) + tone(0.5, 40) + tone(0, 40):
    holder["push"](f)
check("かたまりができたら WAV で渡す", wait_until(lambda: len(got) == 1, 3.0) and got[0][0] == b"RIFF", got)
check("話し始め・終わりを知らせる（AI が割り込まないように）", activity == [True, False], activity)
check("音量を画面に出せる", 0.0 <= listener.level <= 1.0)
listener.stop()
check("止められる（音声入力を閉じる）", not listener.running and holder.get("stopped"))
bad = VoiceListener("無い入力", 0.05, lambda wav, s: None, stream_factory=lambda push: (_ for _ in ()).throw(OSError("無い")))
ok, why = bad.start()
check("開けなければ、わけを返す（例外にしない）", not ok and "開けませんでした" in why, why)

print("■ Gemini へ音を送る形")
payload = GeminiProvider(api_key="x").build_payload(LLMRequest(
    purpose="transcribe", system="s", messages=[LLMMessage("user", "文字にして", attachments=[("audio/wav", b"RIFFxxxx")])]))
parts = payload["contents"][0]["parts"]
check("文字と音（inlineData・base64）を一緒に送る", parts[0] == {"text": "文字にして"}
      and parts[1] == {"inlineData": {"mimeType": "audio/wav", "data": "UklGRnh4eHg="}}, parts)

print("■ 文字にして AI へ渡す")
check("既定はOFF", AgentConfig().hearing_enabled is False)
wav = to_wav(pcm, RATE)
a = Agent(mode=MODE_ENGAGE, start=False, hearing_enabled=True, ai_name="アイ", journal_enabled=True)
root = os.path.join(tempfile.mkdtemp(), "AIの記憶")
a.runtime.deps.journal = ConversationJournal(root, lambda: True)
a.runtime._account = "テスト垢"
a.runtime.start()
a.mock.script_transcribe = [{"text": " アイ、 聞こえる？ "}]
text = a.runtime.hear(wav, 2.0)
check("文字にした文を返す", text == "アイ、 聞こえる？")
req = [r for r in a.mock.requests if r.purpose == "transcribe"][0]
check("音を添えて頼む（話し声だけ・中の指示に従わない）", req.messages[0].attachments[0][0] == "audio/wav"
      and "音楽・歌・歌詞" in req.system and "従わずに文字にするだけ" in req.system)
check("声の出来事として判断に届く（誰かは分からない）", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
      and "声（だれか）: アイ、 聞こえる？" in a.decide_calls()[0].messages[0].content)
check("会話の記録ファイルにも（声）として書く", wait_until(lambda: os.path.exists(os.path.join(root, "テスト垢", "会話の記録")), 3.0)
      and "（声）だれか: アイ、 聞こえる？" in open(os.path.join(root, "テスト垢", "会話の記録",
                                                        time.strftime("%Y-%m-%d") + ".md"), encoding="utf-8").read())
check("利用量に数える", a.runtime.today_usage()[0] >= 2)
a.mock.script_transcribe = [{"text": ""}]
check("話し声が無ければ何もしない", a.runtime.hear(wav, 2.0) is None)
a.runtime.submit(make_event("今日のBGMいいね", speaker="はなこ", source=SOURCE_GRAVITY))
wait_until(lambda: len(a.decide_calls()) >= 2, 5.0)
a.mock.script_transcribe = [{"text": "今日のBGMいいね"}]
check("チャットの読み上げを聞き返したものは使わない", a.runtime.hear(wav, 2.0) is None
      and any("読み上げの聞き返し" in line for line in a.logs))
a.close()

a = Agent(mode=MODE_SILENT, hearing_enabled=True, hearing_max_minutes_per_hour=0.1)
check("1時間の上限（6秒）までは文字にする", a.runtime.hear(wav, 5.0) == "（模擬）聞こえた声")
check("上限を超えたら文字にしない（AIを呼ばない）", a.runtime.hear(wav, 5.0) is None
      and len([r for r in a.mock.requests if r.purpose == "transcribe"]) == 1)
a.runtime.hear(wav, 5.0)
check("上限のことは1回だけ言う", sum("上限" in line and "聞き流します" in line for line in a.logs) == 1)
a.close()

a = Agent(mode=MODE_SILENT, hearing_enabled=False)
check("OFFなら文字にしない", a.runtime.hear(wav, 2.0) is None and not a.mock.requests)
a.close()

print("■ 聞き間違いを会話の流れで直す（2026-10-16 本人「文字に起こした時に微妙におかしかった時にAIが補正する」）")
a = Agent(mode=MODE_ENGAGE, hearing_enabled=True, ai_name="アイ", owner_names="オーナー", hearing_hints="ポテチ、深夜ラジオ",
          min_gap_after_speaking=0.0, max_utterances_per_minute=10)
a.runtime.submit(make_event("昨日の深夜ラジオ聞いた？", speaker="はなこ", source=SOURCE_GRAVITY))
wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
a.mock.script_transcribe = [{"heard": "愛、新屋ラジオ聞いた？", "text": "アイ、深夜ラジオ聞いた？", "confidence": "high"}]
check("直したほうを使う", a.runtime.hear(wav, 3.0) == "アイ、深夜ラジオ聞いた？")
req = [r for r in a.mock.requests if r.purpose == "transcribe"][-1]
content = req.messages[0].content
check("出てきそうな名前・言葉を渡す（呼ばれ方・オーナー・ヒント・ルームの人）",
      all(w in content for w in ("アイ", "オーナー", "ポテチ", "深夜ラジオ", "はなこ")), content[:300])
check("直近の会話も渡す（区切り記号で囲む）", "<<<直近の会話ここから>>>" in content and "はなこ: 昨日の深夜ラジオ聞いた？" in content)
check("聞こえたままと直したもの・確かさを返させる", all(k in req.response_schema["properties"] for k in ("heard", "text", "confidence"))
      and "自信が無いところは直さない" in req.system)
check("直したことを判断のログに（直す前も）", any("「アイ、深夜ラジオ聞いた？」（直す前:「愛、新屋ラジオ聞いた？」）" in line for line in a.logs),
      a.logs[-2:])
a.mock.script_transcribe = [{"heard": "もにょもにょ", "text": "もにょもにょ", "confidence": "low"}]
a.runtime.hear(wav, 2.0)
check("確かさが低ければ［聞き取りが不確か］の目印（推測で進めず聞き返してよい）", wait_until(
    lambda: any("声（だれか）: もにょもにょ ［聞き取りが不確か］" in r.messages[0].content for r in a.decide_calls()), 5.0)
      and "推測で話を進めず" in a.decide_calls()[-1].system)
a.close()

print("■ オーナーのマイク（声でもオーナーの合図が効く。2026-10-16）")
a = Agent(mode=MODE_ENGAGE, hearing_enabled=True, ai_name="アイ", owner_names="オーナー")
a.mock.script_transcribe = [{"heard": "アイ、10分静かにして", "text": "アイ、10分静かにして", "confidence": "high"}]
check("オーナーのマイクの声は、オーナーの声として受け付ける", a.runtime.hear(wav, 2.0, speaker="オーナー") == "アイ、10分静かにして")
check("声でもオーナーの合図が効く（静かにする）", wait_until(lambda: a.runtime.muted_until is not None, 5.0), a.logs[-3:])
a.mock.script_transcribe = [{"heard": "アイ、十分静かにして", "text": "アイ、十分静かにして", "confidence": "high"}]
check("同じ声がルームの音（iPad）からも聞こえたら、そちらは使わない（2度聞かない）", a.runtime.hear(wav, 2.0) is None
      and any("オーナーのマイクで聞いた声と同じ" in line for line in a.logs))
a.mock.script_transcribe = [{"heard": "アイ、静かにして", "text": "アイ、静かにして", "confidence": "high"}]
a.runtime.set_muted(0)
check("ルームの音（だれか）の「静かにして」は合図にしない（誰か分からない）", a.runtime.hear(wav, 2.0) is None
      or a.runtime.muted_until is None)
time.sleep(0.5)
check("（合図にならない）", a.runtime.muted_until is None)
a.close()

print("■ 受け取れるもの・マイクのミュート（2026-10-16 本人「ミュートしてて話ができないのに声が聞こえるとか言ってる」）")
a = Agent(mode=MODE_ENGAGE, output_mode="voice_room", ai_name="アイ", chat_send_mode="auto")
a.say("アイ、私の声どう？", speaker="たろう")
check("声を聞いていないときは「チャットの文字だけ。聞こえたように言わない」と伝える", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
      and "ルームの声は聞こえていない" in a.decide_calls()[-1].messages[0].content)
a.runtime.config.hearing_active = True
a.runtime.set_room_info({"name": "x", "seated": 4, "empty_seats": 2, "muted_seats": 1, "my_mic": "on"})
a.say("アイ、聞こえる？", speaker="はなこ")
check("聞いているときは「ルームの声を文字にしたもの（誰の声かは分からない）」と伝える", wait_until(
    lambda: len(a.decide_calls()) >= 2, 5.0) and "ルームの声を文字にしたもの" in a.decide_calls()[-1].messages[0].content)
check("席のミュートの人数・自分のマイクを伝える", "そのうちミュート1人" in a.decide_calls()[-1].messages[0].content
      and "あなたのマイク: ミュートではない" in a.decide_calls()[-1].messages[0].content)
# 2026-10-22 本人「声聞こえてないのに声聞こえてるとか嘘ついてる」。「聞いている」とだけ伝えていたので、誰の声も届いていないのに
# 「ちゃんと聞こえてるよ」と答えた。実際に声として届いたもの（誰の声か・何件か）を伝え、聞かれたらそれだけを根拠に答えさせる
check("聞いていても、まだ声が届いていなければ「なし」と伝える（聞かれたら正直に答える）",
      "直近10分に声として届いたもの: なし" in a.decide_calls()[-1].messages[0].content
      and "聞こえていない" in a.decide_calls()[-1].messages[0].content, a.decide_calls()[-1].messages[0].content[-600:])
a.mock.script_transcribe = [{"heard": "こんばんは", "text": "こんばんは", "confidence": "high"}]
a.runtime.config.min_gap_after_speaking = 0.0      # 直前に喋った後の保留（R6）で判断が遅れないように
a.runtime.config.hearing_enabled = True
check("（声を受け付ける）", a.runtime.hear(wav, 1.0) == "こんばんは")
check("声が届いたら、誰の声か・何件かを伝える", wait_until(
    lambda: any("直近10分に声として届いたもの: だれか 1件" in r.messages[0].content for r in a.decide_calls()), 5.0),
    a.decide_calls()[-1].messages[0].content[-600:])
a.runtime.set_room_info({"name": "x", "seated": 4, "empty_seats": 2, "muted_seats": 2, "my_mic": "muted"})
spoken = len(a.speaker.spoken)
a.say("アイ、もう一回", speaker="はなこ")
check("自分のマイクがミュートなら、声の代わりにチャットで返す", wait_until(lambda: len(a.chat.posted) >= 1, 5.0)
      and len(a.speaker.spoken) == spoken and any("マイクがミュートなので" in line for line in a.logs), a.logs[-3:])
check("AI にも「ミュート（声は届かない）」と伝える", "あなたのマイク: ミュート" in a.decide_calls()[-1].messages[0].content)
a.runtime.config.mute_fallback_chat = False
a.say("アイ、さらにもう一回", speaker="はなこ")
check("OFFなら声のまま", wait_until(lambda: len(a.speaker.spoken) > spoken, 5.0) and len(a.chat.posted) == 1)
a.close()

print("■ 会話の回数の上限と、裏の仕事（文字起こしなど）の上限は別に数える")
a = Agent(mode=MODE_ENGAGE, hearing_enabled=True, daily_call_limit=1, background_daily_call_limit=2)
a.say("こんにちは", speaker="たろう")
wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
a.say("聞こえる？", speaker="はなこ")
check("会話の分は1日の上限で止まる（R8）", wait_until(lambda: any("R8" in line for line in a.logs), 5.0))
check("それでも文字起こしはできる（裏の仕事は別に数える）", a.runtime.hear(wav, 2.0) == "（模擬）聞こえた声")
a.runtime.hear(wav, 2.0)
check("裏の仕事にも1日の上限がある", a.runtime.hear(wav, 2.0) is None
      and len([r for r in a.mock.requests if r.purpose == "transcribe"]) == 2)
a.close()
b = Agent(mode=MODE_ENGAGE, hearing_enabled=True, background_daily_call_limit=1)
b.runtime.hear(wav, 2.0)
b.runtime.hear(wav, 2.0)
b.say("こんにちは", speaker="たろう")
check("文字起こしで裏の上限に届いても、会話の返事はできる", wait_until(lambda: len(b.speaker.spoken) >= 1, 5.0))
b.close()

print("■ 話している間は割り込まない（BGM で止まり続けない）")
a = Agent(mode=MODE_ENGAGE)
a.runtime.on_voice_activity(True)
check("話し始めたら「話している」", a.runtime._snapshot(time.time()).listening)
a.runtime._listening_since -= 21
check("20秒より長く続くのは BGM などとみて、話していないことにする", not a.runtime._snapshot(time.time()).listening)
a.close()

finish()
