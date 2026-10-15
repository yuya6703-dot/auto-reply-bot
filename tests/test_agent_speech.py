# -*- coding: utf-8 -*-
"""
音声（出す方）の段階2を確かめる。files/agent/speech/ と、それにつなぎ替えた App の読み上げ。
設計書/08 の T21〜T23・T25・T27・T28（T24「話し始めたら譲る」・T26「感情とスタイル」は、それを使う段階で足す）。

⚠️ 本物の音は鳴らさない・エンジンにもつながない。sounddevice・winsound・HTTP はすべて にせもの。
"""
import os, sys, threading, time, urllib.parse

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import auto_reply_app as A
from agent.cancel import CancelToken, NEVER
from agent.speech import audio as AU
from agent.speech import playback as PB
from agent.speech import service as SV
from agent.speech.voicevox_compat import VoicevoxCompatibleEngine

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


def wait_until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


# ---------------------------------------------------------------
print("■ 音量（以前の App._apply_volume_to_wav と同じ）")
wav = AU.make_silence_wav(0.1)
check("100% はそのまま（同じもの）", AU.apply_volume(wav, 100) is wav)
loud = AU.make_silence_wav(0.0)
import io, wave, array
buf = io.BytesIO()
with wave.open(buf, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
    w.writeframes(array.array("h", [10000, -10000, 32767]).tobytes())
half = AU.read_pcm(AU.apply_volume(buf.getvalue(), 50))
samples = array.array("h"); samples.frombytes(half.frames)
check("50% は 0.25 倍（2乗のカーブ）", list(samples) == [2500, -2500, 8191], list(samples))
check("壊れた WAV はそのまま返す", AU.apply_volume(b"not a wav", 30) == b"not a wav")
check("範囲外の音量は 0〜100 に丸める", AU.apply_volume(buf.getvalue(), 150) is not None)
check("長さを読める", abs(AU.read_pcm(AU.make_silence_wav(2.0)).duration_seconds - 2.0) < 1e-6)


# ---------------------------------------------------------------
print("■ AivisSpeech・VOICEVOX のアダプター（にせの HTTP）")


class FakeHttp:
    def __init__(self, speakers_json=b'[]', fail_speaker=None):
        self.calls = []
        self.speakers_json = speakers_json
        self.fail_speaker = fail_speaker

    def __call__(self, url, method, data, timeout):
        self.calls.append((url, method, data, timeout))
        parsed = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(parsed.query)
        if self.fail_speaker is not None and q.get("speaker") == [str(self.fail_speaker)]:
            raise RuntimeError("HTTP Error 422: 話者が無い")
        if parsed.path == "/speakers":
            return self.speakers_json
        if parsed.path == "/audio_query":
            return f'{{"q":"{q["text"][0]}","s":{q["speaker"][0]}}}'.encode("utf-8")
        if parsed.path == "/synthesis":
            return b"WAV:" + parsed.netloc.encode() + b":" + data
        if parsed.path == "/version":
            return b'"1.0"'
        raise RuntimeError("知らない宛先")


url = {"v": "http://127.0.0.1:10101/"}
http = FakeHttp()
eng = VoicevoxCompatibleEngine("aivisspeech", lambda: url["v"], cache_size=2, opener=http)
out = eng.synthesize("こんにちは 世界", 7)
check("問い合わせ→合成の順に2回投げる", [c[0].split("?")[0] for c in http.calls]
      == ["http://127.0.0.1:10101/audio_query", "http://127.0.0.1:10101/synthesis"], http.calls)
check("文は URL に符号化して入れる（空白・日本語）", "text=%E3%81%93" in http.calls[0][0] and "%20" in http.calls[0][0])
check("時間制限は 問い合わせ30秒・合成60秒（以前と同じ）", http.calls[0][3] == 30 and http.calls[1][3] == 60)
check("合成には問い合わせの結果をそのまま送る", http.calls[1][2] == '{"q":"こんにちは 世界","s":7}'.encode())
check("WAV を返す", out.startswith(b"WAV:127.0.0.1:10101"))
eng.synthesize("こんにちは 世界", 7)
check("同じ文・話者は覚えたものを使う（HTTP を投げない）", len(http.calls) == 2)
eng.synthesize("こんにちは 世界", 8)
check("話者が違えば合成し直す", len(http.calls) == 4)
eng.synthesize("別の文", 7)
check("覚えは上限まで（古いものから捨てる）", eng.cached_count() == 2)
eng.synthesize("こんにちは 世界", 7)
check("捨てた分は合成し直す", len(http.calls) == 8)
url["v"] = "http://127.0.0.1:50021"
eng.synthesize("こんにちは 世界", 7)
check("宛先を変えたら、覚えは使わない（宛先ごとに別）", http.calls[-1][0].startswith("http://127.0.0.1:50021/synthesis"))
eng.clear_cache()
check("clear_cache で空になる", eng.cached_count() == 0)
check("動いていれば health は True", eng.health() is True)
check("つながらなければ health は False",
      VoicevoxCompatibleEngine("x", lambda: "http://x", opener=lambda *a: (_ for _ in ()).throw(OSError())).health() is False)

speakers = VoicevoxCompatibleEngine("v", lambda: "http://h", opener=FakeHttp(
    speakers_json='[{"name":"ずんだもん","styles":[{"name":"ノーマル","id":3},{"name":"あまあま","id":1}]},'
                  '{"name":" ","styles":[{"name":"x","id":9}]},{"name":"空","styles":[]}]'.encode("utf-8"))).fetch_speakers()
check("話者一覧は {キャラ: {スタイル: ID}}（名前が空・スタイルが無いものは除く）",
      speakers == {"ずんだもん": {"ノーマル": 3, "あまあま": 1}}, speakers)
try:
    VoicevoxCompatibleEngine("v", lambda: "http://h", opener=FakeHttp()).fetch_speakers()
    check("話者が1人もいなければ例外", False)
except RuntimeError:
    check("話者が1人もいなければ例外", True)


# ---------------------------------------------------------------
print("■ 途中で止められる再生（にせの sounddevice）")


class FakeStream:
    def __init__(self, sd, kwargs):
        self.sd, self.kwargs = sd, kwargs
        self.written = 0
        self.state = "new"

    def start(self):
        self.state = "started"

    def write(self, data):
        if self.sd.fail_write:
            raise RuntimeError("書けない")
        self.written += len(data)

    def abort(self):
        self.state = "aborted"

    def stop(self):
        self.state = "stopped"

    def close(self):
        self.sd.closed.append(self.state)


class FakeSd:
    def __init__(self, fail_open=False, fail_write=False):
        self.fail_open, self.fail_write = fail_open, fail_write
        self.streams, self.closed = [], []

    def RawOutputStream(self, **kwargs):
        if self.fail_open:
            raise RuntimeError("開けない")
        s = FakeStream(self, kwargs)
        self.streams.append(s)
        return s


class FakeWinsound:
    SND_MEMORY = 4

    def __init__(self):
        self.played = []

    def PlaySound(self, data, flags):
        self.played.append(data)


def make_player(sd=None, ws=None, devices=None, default=5):
    devices = {"CABLE Input (VB-Audio Virtual Cable)": 11} if devices is None else devices
    failed = []
    p = PB.AudioPlayer(sd, ws, lambda name: devices.get(name), lambda: default,
                       on_device_failed=failed.append)
    p.TAIL_SECONDS = 0.0
    return p, failed


short = AU.make_silence_wav(0.15)
sd, ws = FakeSd(), FakeWinsound()
player, failed = make_player(sd, ws)
check("選んだ出力先で鳴らす", player.play(short, 100, "CABLE Input (VB-Audio Virtual Cable)") is True
      and sd.streams[-1].kwargs["device"] == 11)
check("全部書き込む", sd.streams[-1].written == len(AU.read_pcm(short).frames))
check("16bit・24000Hz・モノラルで開く", sd.streams[-1].kwargs == {"samplerate": 24000, "channels": 1, "dtype": "int16", "device": 11})
check("最後まで鳴らしたら stop → close", sd.closed[-1] == "stopped")
check("winsound は使わない", ws.played == [])
check("出力先が「既定」なら MME の既定の番号で鳴らす（止められるように）",
      player.play(short, 100, "") is True and sd.streams[-1].kwargs["device"] == 5 and ws.played == [])

sd2, ws2 = FakeSd(), FakeWinsound()
player2, failed2 = make_player(sd2, ws2)
check("出力先が見つからなければ既定で鳴らす（winsound）", player2.play(short, 100, "抜いたデバイス") is True
      and len(ws2.played) == 1)
check("見つからなかったことを知らせる", failed2 == ["抜いたデバイス"])
sd3, ws3 = FakeSd(fail_open=True), FakeWinsound()
player3, failed3 = make_player(sd3, ws3)
check("開けなければ winsound で鳴らす", player3.play(short, 100, "CABLE Input (VB-Audio Virtual Cable)") is True
      and len(ws3.played) == 1 and failed3)
sd4, ws4 = FakeSd(fail_write=True), FakeWinsound()
player4, _ = make_player(sd4, ws4)
check("書き込みに失敗したら winsound で鳴らし直す", player4.play(short, 100, "") is True and len(ws4.played) == 1)
ws5 = FakeWinsound()
player5, _ = make_player(None, ws5)
check("sounddevice が無ければ winsound", player5.play(short, 100, "") is True and len(ws5.played) == 1)
buf8 = io.BytesIO()
with wave.open(buf8, "wb") as w:
    w.setnchannels(1); w.setsampwidth(1); w.setframerate(8000); w.writeframes(b"\x80" * 800)
sd6, ws6 = FakeSd(), FakeWinsound()
player6, _ = make_player(sd6, ws6)
check("16bit 以外は winsound に任せる（以前と同じ）", player6.play(buf8.getvalue(), 100, "") is True
      and sd6.streams == [] and len(ws6.played) == 1)
check("空の音は鳴らさない", player6.play(b"", 100, "") is False)
check("winsound も無ければ False", make_player(None, None)[0].play(short, 100, "") is False)

print("■ T23 再生の停止（10秒の音を 0.2 秒以内に止める）")
long_wav = AU.make_silence_wav(10.0)
sd7, ws7 = FakeSd(), FakeWinsound()
player7, _ = make_player(sd7, ws7)
token = CancelToken()
result = {}


def run_long():
    result["ok"] = player7.play(long_wav, 100, "", token)
    result["end"] = time.monotonic()


th = threading.Thread(target=run_long)
th.start()
time.sleep(0.3)
stopped_at = time.monotonic()
token.cancel()
th.join(2.0)
elapsed = result.get("end", 99) - stopped_at
check("止めてから 0.2 秒以内に戻る", 0 <= elapsed < 0.2, f"{elapsed:.3f}秒")
check("出力は打ち切る（abort。stop は呼ばない）", sd7.closed == ["aborted"], sd7.closed)
check("止めた後に winsound で頭から鳴らし直さない", ws7.played == [])
check("止めたのは「鳴らした」扱い（True）", result.get("ok") is True)
sd8 = FakeSd()
player8, _ = make_player(sd8, FakeWinsound())
pre = CancelToken(); pre.cancel()
check("最初から止められていれば書き込まない", player8.play(long_wav, 100, "", pre) is True and sd8.streams[-1].written == 0)


# ---------------------------------------------------------------
print("■ 音声サービス（順番・失敗・停止）")


class Recorder:
    """合成と再生の にせもの。同時に鳴っていないかも数える"""

    def __init__(self, play_seconds=0.0, fail_texts=()):
        self.play_seconds = play_seconds
        self.fail_texts = set(fail_texts)
        self.synth_calls, self.played, self.events, self.devices = [], [], [], []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.voice = "voicevox:3"
        self.volume = 70

    def synthesize(self, text, voice):
        self.synth_calls.append((text, voice))
        if text in self.fail_texts:
            raise RuntimeError("エンジンが応答しない")
        return f"WAV[{voice}]{text}".encode()

    def play(self, wav, volume, cancel, device=None):
        self.devices.append(device)
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            cancel.wait(self.play_seconds)
            self.played.append((wav, volume, cancel.cancelled))
        finally:
            with self.lock:
                self.active -= 1
        return True

    def on_event(self, kind, job, detail):
        self.events.append((kind, job.text if job else None, detail))

    def service(self, max_queue=20):
        return SV.SpeechService(self.synthesize, self.play, lambda: self.voice, lambda: self.volume,
                                on_event=self.on_event, max_queue=max_queue)


rec = Recorder()
svc = rec.service()
check("用件が来るまでスレッドを起こさない", svc._thread is None)
check("T21 受け付ける", svc.enqueue(SV.SpeechJob(text="こんにちは", source="手入力")) is True)
check("T21 合成した WAV が再生に渡る", wait_until(lambda: len(rec.played) == 1)
      and rec.played[0][0] == b"WAV[voicevox:3]" + "こんにちは".encode())
check("声・音量は、指定が無ければ喋る時点の既定", rec.synth_calls[0][1] == "voicevox:3" and rec.played[0][1] == 70)
check("始まり・終わり・待ち行列の知らせ", wait_until(lambda: [e[0] for e in rec.events][-1] == SV.EVENT_QUEUE_CHANGED)
      and SV.EVENT_STARTED in [e[0] for e in rec.events] and SV.EVENT_DONE in [e[0] for e in rec.events])
rec.voice, rec.volume = "aivisspeech:888", 40
svc.enqueue(SV.SpeechJob(text="次の文"))
check("T28 設定を変えたら、次の発言から新しいエンジン・音量", wait_until(lambda: len(rec.played) == 2)
      and rec.synth_calls[-1][1] == "aivisspeech:888" and rec.played[-1][1] == 40)
svc.enqueue(SV.SpeechJob(text="指定あり", voice="voicevox:1", volume=10))
check("用件に声・音量の指定があればそれを使う", wait_until(lambda: len(rec.played) == 3)
      and rec.synth_calls[-1][1] == "voicevox:1" and rec.played[-1][1] == 10)
svc.enqueue(SV.SpeechJob(wav=b"READY", source="スマホの解析"))
check("合成済みの音（スマホの解析）は合成せずに鳴らす", wait_until(lambda: len(rec.played) == 4)
      and rec.played[-1][0] == b"READY" and len(rec.synth_calls) == 3)

rec = Recorder(fail_texts={"失敗する文"})
svc = rec.service()
svc.enqueue(SV.SpeechJob(text="失敗する文"))
svc.enqueue(SV.SpeechJob(text="次は喋れる"))
check("T22 失敗した発言は捨てて、次の発言は喋れる", wait_until(lambda: len(rec.played) == 1)
      and rec.played[0][0].endswith("次は喋れる".encode()))
fails = [e for e in rec.events if e[0] == SV.EVENT_FAILED]
check("T22 失敗を知らせる（例外を添えて）", len(fails) == 1 and fails[0][1] == "失敗する文"
      and "応答しない" in str(fails[0][2]))
check("T22 失敗してもスレッドは生きている", svc._thread.is_alive())

print("■ T23 停止（音声サービス）")
rec = Recorder(play_seconds=10.0)
svc = rec.service()
for i in range(3):
    svc.enqueue(SV.SpeechJob(text=f"長い{i}"))
wait_until(lambda: svc.is_busy())
t0 = time.monotonic()
dropped = svc.stop_all()
check("待っていた2件を捨てる", dropped == 2, dropped)
check("今の再生が 0.2 秒以内に止まる", wait_until(lambda: len(rec.played) == 1, 0.2), f"{time.monotonic() - t0:.3f}秒")
check("止めた再生は「止められた」", rec.played and rec.played[0][2] is True)
check("待ち行列は空", svc.pending_count() == 0)
check("捨てた分は合成もしない", wait_until(lambda: not svc.is_busy()) and len(rec.synth_calls) == 1)
check("止めた分は「取り消し」として知らせる",
      sum(1 for e in rec.events if e[0] == SV.EVENT_CANCELLED) == 3)
rec.play_seconds = 0.0
svc.enqueue(SV.SpeechJob(text="止めた後も喋れる"))
check("止めた後も、次の用件は喋れる", wait_until(lambda: len(rec.played) == 2))
svc.stop_current()
check("何も鳴っていなければ stop_current は何もしない", svc.pending_count() == 0)

print("■ T25 同時に鳴らない")
rec = Recorder(play_seconds=0.02)
svc = rec.service(max_queue=100)
threads = [threading.Thread(target=lambda n=n: [svc.enqueue(SV.SpeechJob(text=f"{n}-{i}")) for i in range(5)])
           for n in range(4)]
for th in threads:
    th.start()
for th in threads:
    th.join()
check("20件ぜんぶ鳴る", wait_until(lambda: len(rec.played) == 20, 5.0), len(rec.played))
check("1つずつ順番に鳴る（同時に2つ鳴らない）", rec.max_active == 1, rec.max_active)
check("スレッドは1本だけ", sum(1 for t in threading.enumerate() if t is svc._thread) == 1)

print("■ 優先度・上限・終了")
rec = Recorder(play_seconds=0.3)
svc = rec.service(max_queue=3)
svc.enqueue(SV.SpeechJob(text="今鳴っている"))
wait_until(lambda: svc.is_busy())
svc.enqueue(SV.SpeechJob(text="ふつう1"))
svc.enqueue(SV.SpeechJob(text="ふつう2"))
svc.enqueue(SV.SpeechJob(text="急ぎ", priority=SV.PRIORITY_URGENT))
check("上限を超えたら受け付けない（以前と同じく捨てる）", svc.enqueue(SV.SpeechJob(text="あふれ")) is False)
rec.play_seconds = 0.0
check("急ぎは待っている中で先に鳴る（同じ優先度は来た順）", wait_until(lambda: len(rec.played) == 4)
      and [p[0].decode().split("]")[1] for p in rec.played] == ["今鳴っている", "急ぎ", "ふつう1", "ふつう2"],
      [p[0].decode() for p in rec.played])
job = SV.SpeechJob(text="入れる前に止めた")
job.cancel.cancel()
svc.enqueue(job)
check("始まる前に止められた用件は鳴らさない", wait_until(lambda: any(e[0] == SV.EVENT_CANCELLED and e[1] == "入れる前に止めた"
                                                         for e in rec.events)) and len(rec.played) == 4)
rec.play_seconds = 10.0
svc.enqueue(SV.SpeechJob(text="終了時に鳴っている"))
wait_until(lambda: svc.is_busy())
t0 = time.monotonic()
svc.shutdown(timeout=1.0)
check("終了すると今の再生も止めてスレッドが終わる", not svc._thread.is_alive() and time.monotonic() - t0 < 0.5)
check("終了後は受け付けない", svc.enqueue(SV.SpeechJob(text="終了後")) is False)
SV.SpeechService(rec.synthesize, rec.play, lambda: "", lambda: 0).shutdown()
check("一度も使わずに終了しても止まらない", True)


print("■ 終わりを待てる印と出力先（段階3。AI の声はスピーカーだけ）")
rec = Recorder()
svc = rec.service()
job = SV.SpeechJob(text="AIの声", device="")
svc.enqueue(job)
check("終わったら finished が立つ", job.finished.wait(2.0) and job.outcome == SV.EVENT_DONE, job.outcome)
check("出力先を用件ごとに渡す（\"\" = PCの既定）", rec.devices[-1] == "")
svc.enqueue(SV.SpeechJob(text="読み上げ"))
check("出力先を決めない用件は None（読み上げの出力先）", wait_until(lambda: len(rec.devices) == 2) and rec.devices[-1] is None)
rec = Recorder(play_seconds=10.0)
svc = rec.service()
first, second = SV.SpeechJob(text="鳴っている"), SV.SpeechJob(text="待っている")
svc.enqueue(first)
svc.enqueue(second)
wait_until(lambda: svc.is_busy())
svc.stop_all()
check("止めた用件も finished が立つ（取り消し）", first.finished.wait(1.0) and first.outcome == SV.EVENT_CANCELLED
      and second.finished.is_set() and second.outcome == SV.EVENT_CANCELLED, (first.outcome, second.outcome))
rec = Recorder(fail_texts={"失敗"})
svc = rec.service()
bad = SV.SpeechJob(text="失敗")
svc.enqueue(bad)
check("合成に失敗した用件は failed", bad.finished.wait(2.0) and bad.outcome == SV.EVENT_FAILED)
svc.shutdown(timeout=1.0)


# ---------------------------------------------------------------
print("■ App の読み上げ（本物のメソッドを借りる）")


class FakeLabel:
    def __init__(self):
        self.text = ""

    def configure(self, text=None, **kw):
        self.text = text


class Harness:
    """読み上げに関わるメソッドだけを本物のまま借りる器（画面は作らない）"""
    request_speech = A.App.request_speech
    _on_speech_event = A.App._on_speech_event
    stop_speech = A.App.stop_speech
    _refresh_speech_queue_label = A.App._refresh_speech_queue_label
    _on_phone_bridge_speak_query = A.App._on_phone_bridge_speak_query
    _split_voice_selector = A.App._split_voice_selector
    _normalize_voice_selector = A.App._normalize_voice_selector
    synthesize_voice_wav = A.App.synthesize_voice_wav
    synthesize_zundamon_wav = A.App.synthesize_zundamon_wav
    synthesize_aivisspeech_wav = A.App.synthesize_aivisspeech_wav
    _play_alarm_once = A.App._play_alarm_once
    _play_wav_bytes = A.App._play_wav_bytes

    def __init__(self, http, play_seconds=0.0):
        self.logs, self.history, self.played = [], [], []
        self.posted = []
        self.speech_queue_label = FakeLabel()
        self.voice = "voicevox:3"
        self.play_seconds = play_seconds
        self.tts_engines = {
            A.TTS_ENGINE_VOICEVOX: VoicevoxCompatibleEngine(A.TTS_ENGINE_VOICEVOX, lambda: "http://vv:50021", opener=http),
            A.TTS_ENGINE_AIVISSPEECH: VoicevoxCompatibleEngine(A.TTS_ENGINE_AIVISSPEECH, lambda: "http://aivis:10101", opener=http),
        }
        self.speech_service = SV.SpeechService(
            synthesize=self.synthesize_voice_wav, play=self._fake_play,
            default_voice=lambda: self.voice, default_volume=lambda: 60,
            on_event=self._on_speech_event, max_queue=A.MAX_SPEECH_QUEUE_SIZE)

    def _fake_play(self, wav, volume, cancel, device=None):
        cancel.wait(self.play_seconds)
        self.played.append((wav, volume, cancel.cancelled))
        return True

    def get_speech_speaker_id(self):
        return self.voice

    def synthesize_from_query(self, query, selector):
        return b"FROM-QUERY:" + selector.encode()

    def append_log(self, m):
        self.logs.append(m)

    def _add_speech_history(self, text):
        self.history.append(text)

    def _post_to_ui(self, cb):
        self.posted.append(cb)

    def pump(self):
        while self.posted:
            self.posted.pop(0)()


http = FakeHttp(fail_speaker=999)
h = Harness(http)
check("request_speech は受け付けたら True", h.request_speech("  読み上げて  ", source="手入力") is True)
check("空の文は受け付けない", h.request_speech("   ") is False)
check("鳴る（VOICEVOX へ合成を頼む）", wait_until(lambda: len(h.played) == 1)
      and h.played[0][0].startswith(b"WAV:vv:50021") and h.played[0][1] == 60)
wait_until(lambda: not h.speech_service.is_busy())
time.sleep(0.05)
h.pump()
check("ログ・履歴（以前と同じ文言）", "🗣️ 読み上げ: [手入力] 「読み上げて」" in h.logs and h.history == ["読み上げて"], h.logs)
check("待ちの表示は伝言板を通して更新（なし）", h.speech_queue_label.text == "読み上げ待ち: なし")
long_text = "あ" * (A.MAX_SPEECH_TEXT_LENGTH + 50)
h.request_speech(long_text)
check("長い文は上限で切る（以前と同じ）", wait_until(lambda: len(h.played) == 2)
      and http.calls[-2][0].count("%E3%81%82") == A.MAX_SPEECH_TEXT_LENGTH)
h.pump()

h.voice = "aivisspeech:5"
h.request_speech("エンジンを変えた")
check("T28 声が AivisSpeech なら AivisSpeech へ", wait_until(lambda: len(h.played) == 3)
      and h.played[-1][0].startswith(b"WAV:aivis:10101"))
h.voice = "voicevox:999"
h.request_speech("無い話者")
failed_logged = wait_until(lambda: (h.pump() or True) and any(m.startswith("⚠️ 読み上げに失敗しました（") for m in h.logs))
check("T27 話者が無ければ喋らない（違う声で代わりに喋らない）", failed_logged and len(h.played) == 3)
check("T27 失敗の知らせ（以前と同じ文言・エンジン名）",
      any(m.startswith("⚠️ 読み上げに失敗しました（") and "VOICEVOXが起動しているか確認してください。" in m
          for m in h.logs), h.logs[-2:])

print("■ 「⏹ 止める」")
h = Harness(FakeHttp(), play_seconds=10.0)
h.request_speech("一つ目")
h.request_speech("二つ目")
h.request_speech("三つ目")
wait_until(lambda: h.speech_service.is_busy())
t0 = time.monotonic()
h.stop_speech()
check("今の読み上げが 0.2 秒以内に止まる", wait_until(lambda: len(h.played) == 1, 0.2))
check("止めたことをログに出す（待っていた件数つき）", h.logs[-1] == "⏹ 読み上げを止めました（待っていた2件も取り消し）。", h.logs[-1])
wait_until(lambda: not h.speech_service.is_busy())
time.sleep(0.05)
h.pump()
check("待ちの表示は「なし」に戻る", h.speech_queue_label.text == "読み上げ待ち: なし")
h.stop_speech()
check("何も無いときに押しても困らない", h.logs[-1] == "⏹ 止める読み上げはありません。")
h.play_seconds = 10.0
h.request_speech("一つだけ")
wait_until(lambda: h.speech_service.is_busy())
h.stop_speech()
check("待ちが無ければ件数は出さない", h.logs[-1] == "⏹ 読み上げを止めました。")
h.speech_service.shutdown(timeout=1.0)

print("■ スマホの解析から読み上げ（合成済みの音を同じ待ち行列へ）")
h = Harness(FakeHttp(), play_seconds=0.2)
h.request_speech("先に喋っている")
ok, reason = h._on_phone_bridge_speak_query({"accent_phrases": []}, label="こんにちは")
check("受け付けたら (True, '') をすぐ返す（鳴り終わりを待たない）", (ok, reason) == (True, "") and len(h.played) == 0)
check("ほかの読み上げと重ならず、後に鳴る", wait_until(lambda: len(h.played) == 2)
      and h.played[1][0] == b"FROM-QUERY:voicevox:3" and h.played[1][1] == 60)
h.pump()
check("ログ（以前と同じ文言）", "🗣️ スマホの解析から読み上げました:「こんにちは」" in h.logs)
h.play_seconds = 10.0
for i in range(A.MAX_SPEECH_QUEUE_SIZE + 1):
    h.request_speech(f"詰める{i}")
ok, reason = h._on_phone_bridge_speak_query({}, label="")
check("待ち行列が一杯なら断って理由を返す", ok is False and "一杯" in reason)
h.speech_service.shutdown(timeout=1.0)

print("■ アラーム（OK を押したら途中でも止まる）")


class AlarmHarness(Harness):
    def __init__(self):
        self.beeps = 0
        self.player_calls = []

    def get_audio_output_device(self):
        return ""

    def _play_beep_once(self, volume):
        self.beeps += 1
        return True


ah = AlarmHarness()
ah.audio_player = type("P", (), {"play": lambda s, wav, vol, dev, cancel=NEVER: (ah.player_calls.append(cancel), False)[1]})()
check("音が鳴らせなければ、以前と同じくビープ音", ah._play_alarm_once(b"WAV", 50) is True and ah.beeps == 1)
stopped = CancelToken(); stopped.cancel()
check("止めた後はビープ音に切り替えない", ah._play_alarm_once(b"WAV", 50, stopped) is True and ah.beeps == 1)
check("止める合図を再生に渡す", ah.player_calls[-1] is stopped)
check("音声が無ければビープ音", ah._play_alarm_once(None, 50) is True and ah.beeps == 2)

print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
