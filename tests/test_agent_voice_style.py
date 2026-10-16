# -*- coding: utf-8 -*-
"""
AI が話し方を決めて、読み上げツール（VOICEVOX / AivisSpeech）で話す（2026-10-16 本人「連携してる読み上げツールを
AIAPIが話し方を調整した上で読み上げツールで話す仕組みにしたい」「声の抑揚とかもAIが調整できるようにしてね」）。

通信しない（エンジンは にせもの）。音は鳴らさない。テストの名前・内容は作り物（リポジトリは公開）。
"""
import json, threading

from agent_harness import Agent, check, finish, wait_until
from agent.context import GENERATION_SCHEMA, COMBINED_SCHEMA
from agent.generation import parse_utterance
from agent.llm.mock import MODE_ENGAGE
from agent.speech.service import SpeechJob, SpeechService
from agent.speech.voicevox_compat import VoicevoxCompatibleEngine
from agent.voice_style import choose_style, speech_adjust

STYLES = ["ノーマル", "あまあま", "ツンツン", "セクシー", "ささやき", "喜び（強）"]

print("■ 声の様子を選ぶ")
check("AI が選んだ様子をそのまま", choose_style(STYLES, "ツンツン", "joy") == "ツンツン")
check("少し違う名前は近いものを（喜び → 喜び（強））", choose_style(STYLES, "喜び") == "喜び（強）")
check("選ばなければ感情から近いもの（うれしい → あまあま）", choose_style(["ノーマル", "あまあま"], None, "joy") == "あまあま")
check("怒っている → ツンツン", choose_style(STYLES, None, "angry") == "ツンツン")
check("合うものが無ければ None（いつもの声）", choose_style(["ノーマル"], "号泣", "sad") is None
      and choose_style([], "ノーマル") is None)

print("■ 速さ・抑揚・高さ・間・大きさ・緩急")
check("ふつうの値は入れない（変えないなら None）", speech_adjust(speed=1.0, intonation=1.0, pitch=0.0) is None
      and speech_adjust() is None)
adj = speech_adjust(speed=1.1, intonation=1.3, pitch=0.05, pause=1.2, volume=0.9, tempo=1.1, unknown=5)
check("エンジンの項目の名前にする", adj == {"speedScale": 1.1, "intonationScale": 1.3, "pitchScale": 0.05,
                                           "pauseLengthScale": 1.2, "volumeScale": 0.9, "tempoDynamicsScale": 1.1}, adj)
adj = speech_adjust(speed=3, intonation=0, pitch=1, pause=9, volume=5, tempo="x")
check("決めた範囲より外には出さない（極端な声にしない）", adj == {"speedScale": 1.25, "intonationScale": 0.7,
                                                         "pitchScale": 0.08, "pauseLengthScale": 1.4,
                                                         "volumeScale": 1.15}, adj)

print("■ AI の返事を読む")
u = parse_utterance({"text": "やったね！", "emotion": "joy", "style": " あまあま ", "speed": 1.2, "intonation": 2.0,
                     "pitch": -1, "pause": None, "volume": "大きく"}, "t")
check("声の出し方を読む（範囲に収める・読めないものは無し）", (u.style, u.speed, u.intonation, u.pitch, u.pause, u.volume)
      == ("あまあま", 1.2, 1.4, -0.08, None, None), (u.style, u.speed, u.intonation, u.pitch, u.pause, u.volume))
u = parse_utterance({"text": "ふつう", "emotion": "calm"}, "t")
check("書いていなければ、いつもの声", u.style is None and u.speed is None)
check("返事の形に声の出し方（null も可）", all(k in GENERATION_SCHEMA["properties"] and k in COMBINED_SCHEMA["properties"]
                                             for k in ("style", "speed", "intonation", "pitch", "pause", "volume", "tempo"))
      and GENERATION_SCHEMA["required"] == ["text", "emotion"])


class FakeHttp:
    def __init__(self):
        self.calls = []

    def __call__(self, url, method, data, timeout):
        self.calls.append((url, data))
        if "/audio_query" in url:
            return json.dumps({"speedScale": 1.0, "intonationScale": 1.0, "pitchScale": 0.0,
                               "volumeScale": 1.0, "accent_phrases": []}).encode()
        return b"WAV:" + data


print("■ 読み上げツールに渡す")
http = FakeHttp()
eng = VoicevoxCompatibleEngine("voicevox", lambda: "http://127.0.0.1:50021", opener=http)
eng.synthesize("こんにちは", 3, {"speedScale": 1.2, "pauseLengthScale": 1.3, "tempoDynamicsScale": 1.1})
sent = json.loads(http.calls[1][1])
check("問い合わせの結果に話し方を書き込んで合成する", sent["speedScale"] == 1.2 and sent["intonationScale"] == 1.0)
check("エンジンが知らない項目は入れない（古い版・VOICEVOX に無い緩急）", "pauseLengthScale" not in sent
      and "tempoDynamicsScale" not in sent)
eng.synthesize("こんにちは", 3)
check("話し方が違えば、覚えた音は使わない（合成し直す）", len(http.calls) == 4 and json.loads(http.calls[3][1])["speedScale"] == 1.0)
eng.synthesize("こんにちは", 3, {"speedScale": 1.2, "pauseLengthScale": 1.3, "tempoDynamicsScale": 1.1})
check("同じ話し方なら覚えた音を使う", len(http.calls) == 4)

got = []
done = threading.Event()
service = SpeechService(synthesize=lambda text, voice, adjust=None: got.append((text, voice, adjust)) or b"WAV",
                        play=lambda wav, volume, cancel, device: done.set() or True,
                        default_voice=lambda: "voicevox:3", default_volume=lambda: 50)
service.enqueue(SpeechJob(text="はい", voice="voicevox:8", adjust={"speedScale": 1.1}))
check("音声サービスは話し方を合成へ渡す", done.wait(3.0) and got == [("はい", "voicevox:8", {"speedScale": 1.1})], got)
service.enqueue(SpeechJob(text="読み上げ"))
check("読み上げ（話し方の無い用件）は今まで通り", wait_until(lambda: len(got) == 2, 3.0) and got[1] == ("読み上げ", "voicevox:3", None))
service.shutdown(timeout=1.0)

print("■ エージェントの中で: 声で答えるときに話し方を選ばせる")
a = Agent(mode=MODE_ENGAGE, start=False, output_mode="voice_room")
a.runtime.deps.voice_styles = lambda: ["ノーマル", "あまあま", "ツンツン"]
a.runtime.start()
a.mock.script_generate = [{"text": "いいね！", "emotion": "joy", "style": "あまあま", "speed": 1.1, "intonation": 1.2}]
a.say("聞いて、合格した！", speaker="たろう")
check("喋る", wait_until(lambda: len(a.speaker.spoken) >= 1, 5.0))
content = a.generate_calls()[-1].messages[0].content
check("使える声の様子と、速さ・抑揚・高さ・間・大きさ・緩急を選ばせる", "style は声の様子。次から1つ: ノーマル / あまあま / ツンツン"
      in content and all(w in content for w in ("speed", "intonation", "pitch", "pause", "volume", "tempo")), content[-400:])
check("選んだ話し方を判断のログに", any("（あまあま・速さ1.1・抑揚1.2）" in line for line in a.logs), a.logs[-3:])
a.close()

a = Agent(mode=MODE_ENGAGE, start=False, output_mode="chat")
a.runtime.deps.voice_styles = lambda: ["ノーマル"]
a.runtime.start()
a.say("聞いて", speaker="たろう")
check("チャットで答えるときは、声の出し方を聞かない", wait_until(lambda: len(a.generate_calls()) >= 1, 5.0)
      and "## 声の出し方" not in a.generate_calls()[-1].messages[0].content)
a.close()

finish()
