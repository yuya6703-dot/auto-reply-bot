# -*- coding: utf-8 -*-
"""
声を聞く（2026-10-16 本人「Windowsに接続したiPad mini 6から音を拾う仕組みがあったら（AIの名前）もはっきりと音を聞き取れる」
→「1から6まで」の6）。

PC の音声入力（iPad をつないだライン入力・USB の音声入力・仮想ケーブル など）から音を取り、話し声のかたまりを見つけて渡す。
文字にするのはエージェント（runtime.hear。AI の提供元に音を送る。Gemini は音声を入力にできる）。

- 区切り方: 30ミリ秒ごとの音の大きさ（RMS）が しきい値 を超えたら話し始め、0.8秒 下回り続けたら終わり。
  0.5秒より短いもの（咳・物音）は捨て、15秒で切る（長く続く音楽で1回の量が増えすぎないように）
- 音は PC に保存しない（メモリの中だけ。文字にしたら捨てる）
- ⚠️ 誰が話したかは分からない（声の出来事の speaker は None）
- ⚠️ ルームで BGM が流れていると音楽も拾う → 文字にするときに「話し声だけ」と頼み、1時間に文字にする量に上限を付ける（runtime）
- ⚠️ ここは tkinter・auto_reply_app を import しない（設計書/04 の D3）。sounddevice は使うときだけ import する
"""
import io
import math
import queue
import re
import unicodedata
import threading
import time
import wave
from array import array
from collections import deque

FRAME_SECONDS = 0.03
START_FRAMES = 3                 # しきい値を超えるフレームがこれだけ続いたら話し始め（ぷつっという物音で始めない）
END_SECONDS = 0.8
MIN_SECONDS = 0.5
MAX_SECONDS = 15.0
PRE_ROLL_SECONDS = 0.3           # 話し始めの少し前から入れる（頭が切れないように）
# 続いている音（BGM など）を下地として覚え、それより十分大きいときだけ声とみる（2026-10-16 本人「人が出している声をしっかり認識する仕組み」）
FLOOR_RATIO = 2.0                # 下地のこの倍より大きい音を声とみる
FLOOR_WINDOW_SECONDS = 4.5       # 下地は、直近4.5秒の音の大きさの…
FLOOR_PERCENTILE = 0.2           # …小さい方から2割のところ（話し声には息つぎの間があるので、下地は声に引っぱられにくい）


# 笑い声・相づち（2026-10-16 本人「笑い声を会話の割り込みとして捉えないようにする仕組み」）。
# 文字にしたものがこれだけなら、割り込み・話しかけとして扱わない
_LAUGH = re.compile(
    r"^(?:(?:(?:ぎゃ|あ|う|え|い|が|わ|だ|に|ア|ウ|エ|イ|ガ|ワ|ダ)[っッ]?)?[はハふフひヒへヘほホ][っッー〜]*|w|ｗ|"
    # 「草」「くさ」「草生える」も笑い（同日 本人「笑う時くさとか草生えるっていう人もいるからそれも含めて」）
    r"大草原|草生え(?:る|た|すぎ)?|草はえ(?:る|た)?|くさ(?:はえる|生える)?|クサ|草|笑い声|爆笑|笑|"
    r"わら|わろた|ワロタ|わろす|ワロス|ウケる|うける|ウケた|うけた|くすくす|クスクス)+$", re.IGNORECASE)
BACKCHANNELS = ("うん", "うんうん", "ん", "んー", "へー", "へぇ", "ほー", "ほう", "えー", "おー", "あー", "そうなんだ", "なるほど",
                "たしかに", "確かに", "わかる", "ねー", "そうそう", "そっか", "まじか", "まじ", "いいね", "すご", "すごい", "ふーん",
                "へえ", "ほえー", "おお", "うわー")
_STRIP = re.compile(r"[\s、。！!？?…・()（）「」]+")


def _plain(text):
    return _STRIP.sub("", unicodedata.normalize("NFKC", text or ""))


def is_laughter(text):
    """笑い声だけか（あはは・www・（笑） など）"""
    t = _plain(text)
    return bool(t) and bool(_LAUGH.match(t))


def is_backchannel(text):
    """笑い声か、短い相づちだけか（AI が喋っている途中なら、割り込みにしない）"""
    t = _plain(text)
    if not t or is_laughter(t):
        return True
    return t in BACKCHANNELS or any(t == b * 2 or t == b * 3 for b in BACKCHANNELS)


def frame_level(pcm):
    """int16 のモノラルの PCM（bytes）の大きさ 0〜1（RMS）"""
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0


def to_wav(pcm, rate):
    """int16 モノラルの PCM を WAV にする（AI の提供元へ送る形）"""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm)
    return buffer.getvalue()


class VoiceSegmenter:
    """音のフレームを順に受け取り、話し声のかたまりを返す（機材に触らない。テストしやすいように分けた）"""

    def __init__(self, rate, threshold=0.02, adaptive=True):
        self.rate = int(rate)
        self.threshold = threshold
        self.adaptive = adaptive
        self.floor = 0.0             # 続いている音の大きさ（BGM など）
        self._recent_levels = deque(maxlen=max(1, int(FLOOR_WINDOW_SECONDS / FRAME_SECONDS)))
        self.frame_bytes = int(self.rate * FRAME_SECONDS) * 2
        self._pre = []               # 話し始める前の少しの音
        self._voice = []             # 今のかたまり
        self._loud_run = 0
        self._quiet_run = 0
        self._active_frames = 0      # 話し始めてからのフレーム数（話し始めの前の音は数えない）
        self.active = False
        self.level = 0.0

    @property
    def effective_threshold(self):
        """今の「声とみる大きさ」（しきい値と、下地の FLOOR_RATIO 倍の大きい方）"""
        return max(self.threshold, self.floor * FLOOR_RATIO) if self.adaptive else self.threshold

    def _learn_floor(self, level):
        self._recent_levels.append(level)
        ordered = sorted(self._recent_levels)
        self.floor = ordered[int(len(ordered) * FLOOR_PERCENTILE)]

    def feed(self, pcm):
        """フレーム（だいたい30ミリ秒）を足す。かたまりが終わったら [(pcm, 秒)] を返す"""
        level = frame_level(pcm)
        self.level = level
        if self.adaptive:
            self._learn_floor(level)      # 続いている音（BGM など）を下地として覚える
        loud = level >= self.effective_threshold
        done = []
        if not self.active:
            self._pre.append(pcm)
            keep = max(1, int(PRE_ROLL_SECONDS / FRAME_SECONDS))
            if len(self._pre) > keep + START_FRAMES:
                self._pre.pop(0)
            self._loud_run = self._loud_run + 1 if loud else 0
            if self._loud_run >= START_FRAMES:
                self.active = True
                self._voice = list(self._pre)
                self._pre = []
                self._quiet_run = 0
                self._active_frames = START_FRAMES
            return done
        self._voice.append(pcm)
        self._active_frames += 1
        self._quiet_run = 0 if loud else self._quiet_run + 1
        seconds = len(self._voice) * FRAME_SECONDS
        if self._quiet_run * FRAME_SECONDS >= END_SECONDS or seconds >= MAX_SECONDS:
            voice, self._voice = self._voice, []
            self.active = False
            self._loud_run = 0
            spoken = (self._active_frames - self._quiet_run) * FRAME_SECONDS     # 話し始めてから、終わりの静けさまで
            if spoken >= MIN_SECONDS:
                done.append((b"".join(voice), round(seconds, 2)))
        return done


# PCのスピーカーの音（今の既定の出力）をループバックで取る（2026-10-16 本人が選んだ「PCのスピーカーの音をそのまま取る」）。
# MuMu がルームの声を既定の出力（スピーカー）に出しているときに使う。読み上げ・AI の声は VB-CABLE へ出すので、ここには入らない。
# ⚠️ MuMu のスピーカーを仮想ケーブルにしているときは、ここには何も来ない（下の assess_hearing_input）。
# ⚠️ Windows のループバックは、その出力で何も鳴っていないと音のかたまりを1つも送ってこない（無音のデータも来ない）
LOOPBACK_DEFAULT = "🔊 PCのスピーカーの音（今の既定の出力）"


def loopback_available():
    import importlib.util
    return importlib.util.find_spec("pyaudiowpatch") is not None


def list_input_devices():
    """
    音声入力の名前の一覧。いちばん上に「PCのスピーカーの音（ループバック）」、続けて MME の入力
    （⚠️ 出す側で DirectSound は音が消えることがあった。聞く側も MME にそろえる）。機材が読めなければ空
    """
    names = [LOOPBACK_DEFAULT] if loopback_available() else []
    return names + _mme_input_devices()


def _mme_input_devices():
    try:
        import sounddevice as sd
        devices, apis = sd.query_devices(), sd.query_hostapis()
    except Exception:
        return []
    names = []
    for d in devices:
        if d.get("max_input_channels", 0) > 0 and apis[d["hostapi"]]["name"] == "MME" and d["name"] not in names:
            names.append(d["name"])
    return names


# --- 聞く入力で、ルームの音（MuMu のスピーカーの音）が取れるか（2026-10-19 本人「音声認識できなくねーか」） ---
# ⚠️ 流し方で、正しい入力が逆になる。名前で決め打ちせず、MuMu の設定を読んで確かめる:
#   - MuMu のスピーカー → CABLE Input（本人の今の形）: CABLE Output にルームの音が来る（読み上げも同じケーブルに乗る）
#   - MuMu のスピーカー → 既定の出力（2026-10-16 の形）: CABLE Output には読み上げしか来ない。ループバックで聞く
# 2026-10-19 実物: MuMu のスピーカーは CABLE Input、既定の出力はモニターのスピーカー。ループバックには何も来ず、
#   保存されていた CABLE Output が正しかった（前に足した「CABLE Output は読み上げしか聞こえない」の注意は、この形では間違い）
_DEFAULT_WORDS = ("default", "既定", "默认", "默認")
_CABLE = re.compile(r"^(?P<name>\S.*?) (?P<side>Input|Output)\b")


def mumu_speakers(manager_path):
    """
    MuMu の各インスタンスの「スピーカー」（ルームの音を出す先）。MuMuManager.exe の場所から
    <MuMu>/vms/*/configs/customer_config.json の setting.volume_setting.loudspeaker を読む（読むだけ）。
    既定の出力なら ""。読めなければ空のリスト（MuMu でない・設定の形が違う）
    """
    import glob
    import json
    import os
    if not manager_path:
        return []
    root = os.path.dirname(os.path.dirname(os.path.abspath(manager_path)))
    speakers = []
    for path in sorted(glob.glob(os.path.join(root, "vms", "*", "configs", "customer_config.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                volume = json.load(f).get("setting", {}).get("volume_setting", {})
        except (OSError, ValueError, AttributeError):
            continue
        if not isinstance(volume, dict) or "loudspeaker" not in volume:
            continue
        name = str(volume.get("loudspeaker") or "").strip()
        speakers.append("" if any(w in name.lower() for w in _DEFAULT_WORDS) else name)
    return speakers


def default_output_name():
    """今の既定の出力（スピーカー）の名前（ループバックで聞くのはここ）。分からなければ空"""
    try:
        import pyaudiowpatch as pyaudio
    except Exception:
        return ""
    audio = pyaudio.PyAudio()
    try:
        wasapi = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
        return str(audio.get_device_info_by_index(wasapi["defaultOutputDevice"])["name"])
    except Exception:
        return ""
    finally:
        audio.terminate()


def _cable(device):
    """仮想ケーブルの名前と向き。「CABLE Output (VB-Audio Virtual 」→ ("CABLE", "Output")。仮想ケーブルでなければ (None, None)。
    ⚠️ MME の名前は31文字で切れるので、頭の「名前 Input/Output」だけで比べる"""
    m = _CABLE.match(device or "")
    if not m or ("VB-Audio" not in device and not m.group("name").upper().startswith("CABLE")):
        return None, None
    return m.group("name"), m.group("side")


def assess_hearing_input(device, speakers, tts_output="", default_output=""):
    """
    選んだ聞く入力で、ルームの音（MuMu のスピーカーの音）が取れるか。戻り値 (ok, 説明)。
    ok: True＝取れる / False＝取れない / None＝分からない（MuMu の設定が読めない・iPad などの入力）。
    speakers は mumu_speakers の戻り値、tts_output は読み上げの出力先、default_output は今の既定の出力（ループバックのとき）
    """
    if not device:
        return None, ""
    if device == LOOPBACK_DEFAULT:
        if not speakers:
            return None, ""
        if any(not s or (default_output and (s.startswith(default_output) or default_output.startswith(s)))
               for s in speakers):
            return True, "MuMu は既定の出力に音を出しているので、ここでルームの声が聞けます。"
        pair, side = _cable(speakers[0])
        hint = (f"「{pair} Output」を選んでください。" if side == "Input"
                else "MuMu のスピーカーを既定の出力にしてください。")
        return False, (f"MuMu はルームの音を「{speakers[0]}」に出しているので、今の既定の出力"
                       f"（{default_output or '不明'}）を聞いても聞こえません。{hint}")
    name, side = _cable(device)
    if not name or side != "Output":
        return None, ""
    own = _cable(tts_output) == (name, "Input")
    if any(_cable(s) == (name, "Input") for s in speakers):
        return True, (f"MuMu はルームの音を「{name} Input」に出しているので、ここでルームの声が聞けます"
                      + ("（読み上げも同じケーブルに乗りますが、自分の読み上げは聞き分けて使いません）。" if own else "。"))
    if speakers:
        where = speakers[0] or "既定の出力"
        return False, (f"MuMu はルームの音を「{where}」に出しているので、この入力（{name} Output）には"
                       + ("このアプリの読み上げしか来ません。" if own else "ルームの声が来ません。")
                       + ("ルームの声は「🔊 PCのスピーカーの音」で聞けます。" if not speakers[0] else ""))
    if own:
        return None, (f"この入力（{name} Output）には、{name} Input に流れた音（このアプリの読み上げなど）が来ます。"
                      f"MuMu のスピーカーを「{name} Input」にしていなければ、ルームの声は聞こえません。")
    return None, ""


class _LoopbackStream:
    """PyAudioWPatch の流れを、sounddevice の流れと同じに止められるようにまとめたもの"""

    def __init__(self, audio, stream):
        self._audio, self._stream = audio, stream

    def stop(self):
        try:
            self._stream.stop_stream()
        except Exception:
            pass

    def close(self):
        try:
            self._stream.close()
        finally:
            self._audio.terminate()


def _open_loopback(push):
    """
    今の既定の出力（スピーカー）のループバックを開く。何チャンネルでも1チャンネル（モノラル）にして push へ渡す。
    戻り値: (止められる流れ, サンプルレート)
    """
    import pyaudiowpatch as pyaudio
    audio = pyaudio.PyAudio()
    try:
        wasapi = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
        speakers = audio.get_device_info_by_index(wasapi["defaultOutputDevice"])
        loop = next((d for d in audio.get_loopback_device_info_generator() if speakers["name"] in d["name"]), None)
        if loop is None:
            raise ValueError(f"「{speakers['name']}」のループバックが見つかりません")
        rate, channels = int(loop["defaultSampleRate"]), max(1, int(loop["maxInputChannels"]))

        def callback(data, frames, info, status):
            push(to_mono(data, channels))
            return (None, pyaudio.paContinue)
        stream = audio.open(format=pyaudio.paInt16, channels=channels, rate=rate, input=True,
                            input_device_index=loop["index"], frames_per_buffer=int(rate * FRAME_SECONDS),
                            stream_callback=callback)
        stream.start_stream()
        return _LoopbackStream(audio, stream), rate
    except Exception:
        audio.terminate()
        raise


def to_mono(pcm, channels):
    """int16 の何チャンネルかの PCM（交互に並ぶ）を、平均して1チャンネルにする"""
    if channels <= 1:
        return pcm
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % (2 * channels)])
    return array("h", (sum(samples[i:i + channels]) // channels for i in range(0, len(samples), channels))).tobytes()


class VoiceListener:
    """
    音声入力を開いて聞き続ける（自分のスレッド）。かたまりができたら on_segment(wav, 秒) を呼ぶ（そのスレッドから。
    呼ばれた側が文字にするあいだ、次の音はたまっていく）。level は画面の音量の表示用
    """

    def __init__(self, device_name, threshold, on_segment, on_error=lambda message: None, stream_factory=None,
                 on_activity=None):
        self.device_name = device_name
        self.threshold = threshold
        self._on_segment = on_segment
        self._on_activity = on_activity          # (話しているか) -> None。話し始め・終わりで呼ぶ（AI が割り込まないように）
        self._on_error = on_error
        self._stream_factory = stream_factory      # テストでは にせもの
        self._frames = queue.Queue(maxsize=2000)
        self._stop = threading.Event()
        self._thread = None
        self._stream = None
        self.segmenter = None
        self.rate = 0

    @property
    def level(self):
        return self.segmenter.level if self.segmenter is not None else 0.0

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def set_threshold(self, value):
        self.threshold = value
        if self.segmenter is not None:
            self.segmenter.threshold = value

    def start(self):
        """(始めたか, わけ)"""
        try:
            self._stream, self.rate = self._open()
        except Exception as e:
            return False, f"音声入力を開けませんでした（{type(e).__name__}: {str(e)[:80]}）"
        self.segmenter = VoiceSegmenter(self.rate, self.threshold)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="voice-listener", daemon=True)
        self._thread.start()
        return True, ""

    def stop(self):
        self._stop.set()
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(2.0)
        self._thread = None

    def _open(self):
        if self._stream_factory is not None:
            return self._stream_factory(self._push)
        if self.device_name == LOOPBACK_DEFAULT:
            return _open_loopback(self._push)
        import sounddevice as sd
        index = None
        for i, d in enumerate(sd.query_devices()):
            if d["name"] == self.device_name and d.get("max_input_channels", 0) > 0 \
                    and sd.query_hostapis(d["hostapi"])["name"] == "MME":
                index = i
                break
        if index is None:
            raise ValueError(f"「{self.device_name}」が見つかりません")
        rate = int(sd.query_devices(index)["default_samplerate"]) or 44100
        stream = sd.RawInputStream(device=index, samplerate=rate, channels=1, dtype="int16",
                                   blocksize=int(rate * FRAME_SECONDS),
                                   callback=lambda data, frames, t, status: self._push(bytes(data)))
        stream.start()
        return stream, rate

    def _push(self, pcm):
        try:
            self._frames.put_nowait(pcm)
        except queue.Full:
            pass                      # 文字にするのが追いつかないときは、古い音を捨てる（遅れて聞くより取りこぼす方がまし）

    def _run(self):
        while not self._stop.is_set():
            try:
                pcm = self._frames.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                was_active = self.segmenter.active
                segments = self.segmenter.feed(pcm)
                if self._on_activity is not None and self.segmenter.active != was_active:
                    self._on_activity(self.segmenter.active)
                for voice, seconds in segments:
                    if self._stop.is_set():
                        break
                    self._on_segment(to_wav(voice, self.rate), seconds)
            except Exception as e:
                self._on_error(f"{type(e).__name__}: {e}")
                time.sleep(0.5)
