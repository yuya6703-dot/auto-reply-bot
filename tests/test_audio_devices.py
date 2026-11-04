# -*- coding: utf-8 -*-
"""
音の機材の番号（2026-11-03 スマホから送った文の読み上げが、ルームで聞こえない）。

起きていたこと: sounddevice（PortAudio）は機材の一覧を起動したときに1回だけ作り、そのときの winmm の番号で開く。
Windows は既定の機材を 0番に並べ替えるので、起動した後に既定の再生デバイスが CABLE Input に変わると、
「CABLE Input」の番号がモニターのスピーカーを指し、例外も出ずにそちらへ鳴っていた。

確かめること: 既定の機材が変わっても、読み上げ・マイクの転送・マイクの確認・声を聞く が選んだ機材を開くこと。
一覧を作り直せないとき（ほかの流れが開いている）は、別の機材を開かずに断ること。

⚠️ 本物の音は鳴らさない・機材に触らない。winmm・sounddevice・winsound はすべて にせもの
"""
import ctypes, os, sys, threading, time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import auto_reply_app as A
import agent.hearing as H
from agent.cancel import CancelToken
from agent.speech import audio as AU
from agent.speech import mme as M

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


CABLE_IN = "CABLE Input (VB-Audio Virtual C"        # MME の名前は31文字で切れる
CABLE_OUT = "CABLE Output (VB-Audio Virtual "       # 切れた後ろに空白が残る（実物と同じ）
MONITOR = "スピーカー (モニター)"
HEADPHONES = "ヘッドホン (USB Audio)"
MIC = "マイク (USB Audio)"
LINE_IN = "ライン入力 (iPad)"


class FakeSystem:
    """Windows の音の機材。winmm は、今の既定の機材を 0番に置き、残りを決まった順に並べる（実物と同じ）"""

    def __init__(self):
        self.devices = {"render": [CABLE_IN, MONITOR, HEADPHONES], "capture": [CABLE_OUT, MIC, LINE_IN]}
        self.default = {"render": MONITOR, "capture": MIC}
        self.opened = []        # (どこから, 開いた機材)
        self.played = []        # (鳴った機材, バイト数)

    def order(self, kind):
        default = self.default[kind]
        return [default] + [name for name in self.devices[kind] if name != default]


class FakeWinmm:
    """
    winmm の にせもの。番号は、呼ばれた時点の並びで決まる。開いた handle からも名前を引ける（実物と同じ）。
    before_open: 最初に開くとき、番号を機材に当てはめる前に1回だけ呼ぶ（名前を引いてから開くまでの間に既定が変わる、を作る）
    fail_write_at: その回目（0から）の waveOutWrite を失敗させる / stall: 渡した音がいつまでも鳴り終わらない
    """
    HANDLE_BASE = 0x10000
    MAPPER = "Microsoft サウンド マッパー"

    def __init__(self, system, fail_open=()):
        self.system, self.fail_open = system, set(fail_open)
        self.handles, self.resets, self.closed = {}, 0, 0
        self.before_open, self.fail_write_at, self.stall = None, None, False
        self.writes, self.queued = 0, []

    def waveOutGetNumDevs(self):
        return len(self.system.order("render"))

    def waveInGetNumDevs(self):
        return len(self.system.order("capture"))

    def waveOutGetDevCapsW(self, i, caps, size):
        if i in self.handles:
            caps._obj.szPname = self.handles[i]
            return 0
        if i == M.WAVE_MAPPER:
            caps._obj.szPname = self.MAPPER
            return 0
        return self._caps("render", i, caps)

    def waveInGetDevCapsW(self, i, caps, size):
        return self._caps("capture", i, caps)

    def _caps(self, kind, i, caps):
        names = self.system.order(kind)
        if i >= len(names):
            return 2
        caps._obj.szPname = names[i]
        return 0

    def waveOutOpen(self, handle, device, fmt, callback, instance, flags):
        if self.before_open is not None:
            hook, self.before_open = self.before_open, None
            hook()
        names = self.system.order("render")
        if device == M.WAVE_MAPPER:
            name = self.system.default["render"]
        elif device < len(names):
            name = names[device]
        else:
            return 2
        if name in self.fail_open:
            return 4
        handle._obj.value = self.HANDLE_BASE + len(self.handles)
        self.handles[handle._obj.value] = name
        self.system.opened.append(("winmm", name, fmt._obj.nSamplesPerSec, fmt._obj.nChannels))
        return 0

    def waveOutPrepareHeader(self, handle, header, size):
        header._obj.dwFlags |= 2
        return 0

    def waveOutWrite(self, handle, header, size):
        index, self.writes = self.writes, self.writes + 1
        if index == self.fail_write_at:
            return 6                                  # MMSYSERR_NODRIVER（機材が抜けた）
        self.system.played.append((self.handles[handle.value], header._obj.dwBufferLength))
        self.queued.append(header._obj)
        if not self.stall:
            header._obj.dwFlags |= M.WHDR_DONE
        return 0

    def waveOutUnprepareHeader(self, handle, header, size):
        header._obj.dwFlags &= ~2
        return 0

    def waveOutReset(self, handle):
        self.resets += 1
        for header in self.queued:                    # 実物も、待っている分を鳴り終わった扱いで返す
            header.dwFlags |= M.WHDR_DONE
        return 0

    def waveOutClose(self, handle):
        self.closed += 1
        return 0


class FakeKernel32:
    def CreateEventW(self, *args):
        return 1

    def WaitForSingleObject(self, handle, milliseconds):
        return 0

    def CloseHandle(self, handle):
        return 1


class FakeStream:
    def __init__(self, pa, name, kwargs):
        self.pa, self.name, self.kwargs = pa, name, kwargs
        self.open, self.killed = True, False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def start(self):
        callback = self.kwargs.get("callback")
        if callback is not None:
            callback(b"\x00\x00" * 4, 4, None, None)

    def read(self, frames):
        time.sleep(0.002)
        return b"\x00\x00" * frames * self.kwargs.get("channels", 1), False

    def write(self, data):
        self.pa.system.played.append((self.name, len(data)))

    def stop(self):
        pass

    def abort(self):
        pass

    def close(self):
        self.open = False


def pa_name(name):
    """PortAudio の名前の形（WideCharToMultiByte で UTF-8 にするので、片割れのサロゲートは U+FFFD になる）"""
    return name.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


class FakePortAudio:
    """
    sounddevice の にせもの。⚠️ 実物と同じく、機材の一覧は _initialize のときの並びのまま。
    開くときは、そのとき覚えた winmm の番号で開く（並びが変わると、同じ番号で別の機材が開く）。
    止まっている（_initialized が 0）間は、一覧を読むと例外（実物と同じ）。fail_initialize の回数だけ立ち上げに失敗する
    """
    MAPPER_IN, MAPPER_OUT = "Microsoft サウンド マッパー - Input", "Microsoft サウンド マッパー - Output"

    def __init__(self, system):
        self.system, self.count, self.refreshed, self.streams = system, 0, 0, []
        self.fail_initialize = 0
        self._initialize()

    @property
    def _initialized(self):
        return self.count

    def _alive(self):
        if self.count < 1:
            raise RuntimeError("PortAudio not initialized")

    def _initialize(self):
        if self.fail_initialize:
            self.fail_initialize -= 1
            raise RuntimeError("Error initializing PortAudio")
        if self.count == 0:
            self.inputs = [pa_name(name) for name in self.system.order("capture")]
            self.outputs = [pa_name(name) for name in self.system.order("render")]
        self.count += 1

    def _terminate(self):
        self._alive()
        self.count -= 1
        if self.count == 0:
            self.refreshed += 1
            for stream in self.streams:          # 実物も、開いている流れを全部閉じる
                if stream.open:
                    stream.open, stream.killed = False, True

    def _devices(self):
        def device(name, inputs, outputs):
            return {"name": name, "hostapi": 0, "max_input_channels": inputs, "max_output_channels": outputs,
                    "default_samplerate": 44100.0}
        return ([device(self.MAPPER_IN, 2, 0)] + [device(name, 2, 0) for name in self.inputs]
                + [device(self.MAPPER_OUT, 0, 2)] + [device(name, 0, 2) for name in self.outputs])

    def query_hostapis(self, index=None):
        self._alive()
        api = {"name": "MME", "default_input_device": 1, "default_output_device": len(self.inputs) + 2}
        return api if index is not None else [api]

    def query_devices(self, device=None, kind=None):
        self._alive()
        devices = self._devices()
        if device is None and kind is None:
            return devices
        if device is None:
            device = self.query_hostapis(0)["default_input_device" if kind == "input" else "default_output_device"]
        return devices[device]

    def _open(self, kind, device):
        self._alive()
        if device is None:
            device = self.query_hostapis(0)["default_input_device" if kind == "input" else "default_output_device"]
        name = self._devices()[device]["name"]
        now = self.system.order("capture" if kind == "input" else "render")
        if name in (self.MAPPER_IN, self.MAPPER_OUT):
            return now[0]
        stored = (self.inputs if kind == "input" else self.outputs).index(name)   # 一覧を作ったときの番号
        if stored >= len(now):
            raise RuntimeError("Invalid device")
        return now[stored]                                                       # ⚠️ 今その番号にある機材

    def RawInputStream(self, device=None, **kwargs):
        stream = FakeStream(self, self._open("input", device), kwargs)
        self.streams.append(stream)
        self.system.opened.append(("pa-in", stream.name))
        return stream

    def RawOutputStream(self, device=None, **kwargs):
        stream = FakeStream(self, self._open("output", device), kwargs)
        self.streams.append(stream)
        self.system.opened.append(("pa-out", stream.name))
        return stream


class FakeWinsound:
    SND_MEMORY = 4

    def __init__(self):
        self.played = []

    def PlaySound(self, data, flags):
        self.played.append(data)


class FakeDb:
    def __init__(self, settings):
        self.settings = dict(settings)

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def save_setting(self, key, value):
        self.settings[key] = value


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeMenu:
    def __init__(self):
        self.values = None

    def configure(self, values=None, **kwargs):
        self.values = values


class AppHarness:
    """音の機材に関わるメソッドだけを本物のまま借りる器（画面は作らない）"""
    AUDIO_HOST_API = A.App.AUDIO_HOST_API
    AUDIO_OUTPUT_DEFAULT_LABEL = A.App.AUDIO_OUTPUT_DEFAULT_LABEL
    AUDIO_INPUT_DEFAULT_LABEL = A.App.AUDIO_INPUT_DEFAULT_LABEL
    _make_audio_player = A.App._make_audio_player
    _resolve_device_index = A.App._resolve_device_index
    _resolve_output_device_index = A.App._resolve_output_device_index
    _resolve_input_device_index = A.App._resolve_input_device_index
    _default_output_device_index = A.App._default_output_device_index
    _warn_output_device_once = A.App._warn_output_device_once
    list_output_devices = A.App.list_output_devices
    list_input_devices = A.App.list_input_devices
    refresh_input_devices = A.App.refresh_input_devices
    get_audio_output_device = A.App.get_audio_output_device
    get_audio_input_device = A.App.get_audio_input_device
    measure_input_level = A.App.measure_input_level
    _input_stream_format = A.App._input_stream_format
    start_input_passthrough = A.App.start_input_passthrough
    stop_input_passthrough = A.App.stop_input_passthrough
    is_input_passthrough_running = A.App.is_input_passthrough_running

    def __init__(self, output="", input=""):
        self.db = FakeDb({"audio_output_device": output, "audio_input_device": input})
        self.logs = []
        self.audio_input_menu, self.audio_input_var = FakeMenu(), FakeVar(input or A.App.AUDIO_INPUT_DEFAULT_LABEL)

    def _post_to_ui(self, callback):
        callback()

    def append_log(self, message):
        self.logs.append(message)

    def _sync_passthrough_ui(self):
        pass


REAL = (A.sounddevice, A.winsound, sys.modules.get("sounddevice"), M._winmm, M._kernel32, M.PORTAUDIO)


def setup(fail_open=(), extra_render=()):
    """機材・winmm・PortAudio の にせものを組み直す。PortAudio の一覧は、ここ（アプリを起動したとき）の並びで作られる"""
    system = FakeSystem()
    system.devices["render"].extend(extra_render)
    pa = FakePortAudio(system)
    A.sounddevice = pa
    sys.modules["sounddevice"] = pa            # 声を聞く（agent/hearing.py）は使うときに import する
    A.winsound = FakeWinsound()
    M._winmm, M._kernel32 = FakeWinmm(system, fail_open), FakeKernel32()
    M.PORTAUDIO = M.PortAudioGuard()
    return system, pa


def played_to(system):
    return sorted({name for name, _size in system.played})


def opened(system, where):
    return [entry[1] for entry in system.opened if entry[0] == where]


def pa_index(pa, name, kind):
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    return next(i for i, d in enumerate(pa.query_devices()) if d["name"] == name and d[key] > 0)


WAV = AU.make_silence_wav(0.2)
FRAMES = len(AU.read_pcm(WAV).frames)


def make_player(app):
    player = app._make_audio_player()
    player.TAIL_SECONDS = 0.0
    return player


# ---------------------------------------------------------------
print("■ 再現: にせの PortAudio が、実物と同じずれ方をする（2026-11-03）")
system, pa = setup()
before = pa.RawOutputStream(device=pa_index(pa, CABLE_IN, "output")).name
system.default["render"] = CABLE_IN
after = pa.RawOutputStream(device=pa_index(pa, CABLE_IN, "output")).name
check("起動したときの並びなら、「CABLE Input」の番号で CABLE Input が開く", before == CABLE_IN, before)
check("既定の再生デバイスが CABLE Input に変わると、同じ番号でモニターのスピーカーが開く（例外は出ない）",
      after == MONITOR, after)

print("■ winmm の名前から番号を引く")
names = [MONITOR, CABLE_IN, None, HEADPHONES]
check("完全一致", M.find(names, CABLE_IN) == 1)
check("前の版が保存した長い名前（31文字で切れる前）も拾う", M.find(names, "CABLE Input (VB-Audio Virtual Cable)") == 1)
check("前後の空白は比べない", M.find([CABLE_OUT], "CABLE Output (VB-Audio Virtual") == 0)
check("読めない番号は飛ばして、番号はずらさない", M.find(names, HEADPHONES) == 3)
check("無ければ None", M.find(names, "抜いた機材") is None and M.find(names, "") is None and M.find(None, CABLE_IN) is None)
check("構造体の大きさが Windows の定義と同じ",
      ctypes.sizeof(M._WAVEOUTCAPSW) == 84 and ctypes.sizeof(M._WAVEINCAPSW) == 80
      and ctypes.sizeof(M._WAVEHDR) == (48 if ctypes.sizeof(ctypes.c_void_p) == 8 else 32)
      and ctypes.sizeof(M._WAVEFORMATEX) >= 18, (ctypes.sizeof(M._WAVEOUTCAPSW), ctypes.sizeof(M._WAVEHDR)))

print("■ PortAudio の一覧が今の並びと同じか")
check("先頭のサウンド マッパーを除いて同じなら同じ", M._same_order(["マッパー", MONITOR, CABLE_IN], [MONITOR, CABLE_IN]))
check("並びが入れ替わっていたら違う", not M._same_order(["マッパー", MONITOR, CABLE_IN], [CABLE_IN, MONITOR]))
check("機材が増えていたら違う", not M._same_order(["マッパー", MONITOR], [MONITOR, CABLE_IN]))
check("読めない番号は PortAudio も飛ばす", M._same_order(["マッパー", MONITOR], [MONITOR, None]))
check("機材が1つも無い", M._same_order([], []))

# ---------------------------------------------------------------
print("■ 読み上げ: 起動した後に既定の再生デバイスが変わっても、選んだ出力先に鳴る")
system, pa = setup()
app = AppHarness(output=CABLE_IN)
player = make_player(app)
system.default["render"] = CABLE_IN              # 2026-11-03 の形
check("鳴らせた", player.play(WAV, 100, app.get_audio_output_device()) is True)
check("CABLE Input に鳴る（モニターのスピーカーに鳴らない）", played_to(system) == [CABLE_IN], played_to(system))
check("全部書き込む", sum(size for name, size in system.played if name == CABLE_IN) == FRAMES)
check("winsound（既定のデバイス）で鳴らし直さない", A.winsound.played == [])
check("出力デバイスの注意を出さない", app.logs == [], app.logs)
system.played.clear()
system.default["render"] = HEADPHONES            # また変わる
player.play(WAV, 100, app.get_audio_output_device())
check("もう一度変わっても CABLE Input に鳴る", played_to(system) == [CABLE_IN], played_to(system))
system.played.clear()
player.play(WAV, 100, "CABLE Input (VB-Audio Virtual Cable)")
check("前の版が保存した長い名前でも CABLE Input に鳴る", played_to(system) == [CABLE_IN], played_to(system))
if any(entry[0] == "winmm" for entry in system.opened):
    check("16bit・24000Hz・モノラルのまま開く（MME。音声エンジンの出力そのまま）",
          all(entry[2:] == (24000, 1) for entry in system.opened if entry[0] == "winmm"), system.opened)
system.played.clear()
check("出力先が「既定」なら、今の既定に鳴る", player.play(WAV, 100, "") is True
      and played_to(system) == [HEADPHONES], played_to(system))

print("■ 読み上げ: 鳴らせないとき（これまでと同じく、既定のデバイスで鳴らして1度だけ知らせる）")
system, pa = setup()
app = AppHarness(output="抜いた機材")
player = make_player(app)
check("見つからなければ winsound で鳴らす", player.play(WAV, 100, app.get_audio_output_device()) is True
      and len(A.winsound.played) == 1 and system.played == [])
check("見つからなかったことを知らせる", any("抜いた機材" in m for m in app.logs), app.logs)
system, pa = setup(fail_open={CABLE_IN})
app = AppHarness(output=CABLE_IN)
player = make_player(app)
check("開けなければ winsound で鳴らす", player.play(WAV, 100, app.get_audio_output_device()) is True
      and len(A.winsound.played) == 1 and system.played == [])
check("開けなかったことを知らせる", any(CABLE_IN in m for m in app.logs), app.logs)

print("■ 読み上げ: 途中で止める")
system, pa = setup()
app = AppHarness(output=CABLE_IN)
player = make_player(app)
token, result = CancelToken(), {}


def run_long():
    result["ok"] = player.play(AU.make_silence_wav(10.0), 100, app.get_audio_output_device(), token)
    result["end"] = time.monotonic()


thread = threading.Thread(target=run_long)
thread.start()
time.sleep(0.3)
stopped_at = time.monotonic()
token.cancel()
thread.join(2.0)
check("止めてから 0.2 秒以内に戻る", 0 <= result.get("end", 99) - stopped_at < 0.2, result)
check("止めたのは「鳴らした」扱い（True）", result.get("ok") is True)
check("待っている分も捨てる（waveOutReset）", M._winmm.resets >= 1 and M._winmm.closed == 1)
check("止めた後に winsound で頭から鳴らし直さない", A.winsound.played == [])

print("■ 読み上げ: 名前を引いてから開くまでの間に並びが変わっても、開き直して選んだ出力先に鳴る")
system, pa = setup()
app = AppHarness(output=CABLE_IN)
player = make_player(app)
M._winmm.before_open = lambda: system.default.__setitem__("render", CABLE_IN)
check("鳴らせた", player.play(WAV, 100, app.get_audio_output_device()) is True)
check("CABLE Input に鳴る", played_to(system) == [CABLE_IN], played_to(system))
check("1度目に開いたのは別の機材で、確かめて開き直した", [e[1] for e in system.opened if e[0] == "winmm"] == [MONITOR, CABLE_IN],
      system.opened)
check("開き直す前の機材は閉じた", M._winmm.closed == 2, M._winmm.closed)
check("知らせない・winsound で鳴らさない", app.logs == [] and A.winsound.played == [], (app.logs, A.winsound.played))

print("■ 前の版で「サウンド マッパー」を選んでいた設定は、今の既定の機材に鳴る（止められる鳴らし方で）")
system, pa = setup()
app = AppHarness(output=FakePortAudio.MAPPER_OUT)
player = make_player(app)
check("鳴らせた", player.play(WAV, 100, app.get_audio_output_device()) is True)
check("今の既定の機材に鳴る", played_to(system) == [MONITOR], played_to(system))
check("winsound（止められない）で鳴らさない・知らせない", A.winsound.played == [] and app.logs == [], app.logs)

print("■ 渡せなかった音の鳴り終わりは待たない（すぐ既定のデバイスで鳴らす）")
system, pa = setup()
M._winmm.fail_write_at = 1
app = AppHarness(output=CABLE_IN)
player = make_player(app)
started = time.monotonic()
ok = player.play(WAV, 100, app.get_audio_output_device())
elapsed = time.monotonic() - started
check("既定のデバイス（winsound）で鳴らす", ok is True and len(A.winsound.played) == 1)
check("待たずに切り替える（2秒待たない）", elapsed < 0.5, f"{elapsed:.2f}秒")
check("鳴らせなかったことを知らせる", any(CABLE_IN in m for m in app.logs), app.logs)

print("■ 鳴り終わらないまま止まったら、黙って「鳴らした」にしない（知らせて既定のデバイスで鳴らす）")
system, pa = setup()
M._winmm.stall = True
app = AppHarness(output=CABLE_IN)
player = make_player(app)
player.DRAIN_SECONDS = 0.3
check("既定のデバイス（winsound）で鳴らす", player.play(WAV, 100, app.get_audio_output_device()) is True
      and len(A.winsound.played) == 1)
check("鳴らせなかったことを知らせる", any(CABLE_IN in m for m in app.logs), app.logs)
check("待っている分を捨てて閉じる", M._winmm.resets >= 1 and M._winmm.closed == 1, (M._winmm.resets, M._winmm.closed))
system, pa = setup()
M._winmm.stall = True
app = AppHarness(output=CABLE_IN)
player = make_player(app)
player.DRAIN_SECONDS = 5.0
token = CancelToken()
threading.Timer(0.4, token.cancel).start()
started = time.monotonic()
ok = player.play(WAV, 100, app.get_audio_output_device(), token)
elapsed = time.monotonic() - started
check("鳴り終わりを待つ間も止められる（0.2秒以内）", ok is True and 0.35 < elapsed < 0.6, f"{elapsed:.2f}秒")
check("止めたら winsound で鳴らし直さない", A.winsound.played == [])

print("■ 出力先の一覧: 起動した後につないだ機材も 🔄 で出る")
system, pa = setup()
app = AppHarness()
system.devices["render"].append("イヤホン (Bluetooth)")
names = app.list_output_devices()
check("今つながっている機材が並ぶ", "イヤホン (Bluetooth)" in names and CABLE_IN in names, names)
check("先頭は既定を表す項目", names[0] == A.App.AUDIO_OUTPUT_DEFAULT_LABEL)

# ---------------------------------------------------------------
print("■ マイクの転送: 起動した後に既定の再生デバイスが変わっても、選んだ出力先へ流す")
system, pa = setup()
app = AppHarness(output=CABLE_IN, input=MIC)
system.default["render"] = CABLE_IN
ok, why = app.start_input_passthrough()
wait_until(lambda: opened(system, "pa-out"))
app.stop_input_passthrough()
check("始められた", ok is True, why)
check("CABLE Input へ流す（モニターのスピーカーへ流さない）", opened(system, "pa-out") == [CABLE_IN], opened(system, "pa-out"))
check("選んだマイクから取る", opened(system, "pa-in") == [MIC], opened(system, "pa-in"))
check("止めたら、開いている数を戻す", M.PORTAUDIO.held == 0, M.PORTAUDIO.held)

print("■ ほかの流れが開いている間に並びが変わったら、一覧を作り直さず、別の機材を開かずに断る")
system, pa = setup()
app = AppHarness(output=CABLE_IN, input=MIC)
listener = H.VoiceListener(CABLE_OUT, 0.05, lambda wav, seconds: None)
listener_ok, _ = listener.start()                # 声を聞く（sounddevice の流れを開いたまま）
system.default["render"] = CABLE_IN
ok, why = app.start_input_passthrough()
check("声を聞くは開けた", listener_ok is True)
check("マイクの転送は断る（わけを言う）", ok is False and "並びが変わった" in why, (ok, why))
check("別の機材を開かない", opened(system, "pa-out") == [], opened(system, "pa-out"))
check("聞いている流れを閉じない（一覧を作り直さない）", pa.refreshed == 0 and not any(s.killed for s in pa.streams))
listener.stop()
check("声を聞くを止めたら、開いている数を戻す", M.PORTAUDIO.held == 0, M.PORTAUDIO.held)
ok, why = app.start_input_passthrough()
wait_until(lambda: opened(system, "pa-out"))
app.stop_input_passthrough()
check("止めた後なら、一覧を作り直して CABLE Input へ流せる", ok is True and opened(system, "pa-out") == [CABLE_IN],
      (ok, why, opened(system, "pa-out")))

print("■ マイクの確認: 起動した後に既定の録音デバイスが変わっても、選んだマイクで録る")
system, pa = setup()
app = AppHarness(input=MIC)
system.default["capture"] = CABLE_OUT
level, why = app.measure_input_level(seconds=0.02)
check("録れた", level is not None, why)
check("選んだマイクで録る（CABLE Output で録らない）", opened(system, "pa-in") == [MIC], opened(system, "pa-in"))
check("録り終えたら、開いている数を戻す", M.PORTAUDIO.held == 0, M.PORTAUDIO.held)

print("■ 声を聞く: 起動した後に既定の録音デバイスが変わっても、選んだ入力を聞く")
system, pa = setup()
system.default["capture"] = CABLE_OUT
listener = H.VoiceListener(MIC, 0.05, lambda wav, seconds: None)
ok, why = listener.start()
listener.stop()
check("聞き始められた", ok is True, why)
check("選んだ入力を開く", opened(system, "pa-in") == [MIC], opened(system, "pa-in"))
check("止めたら、開いている数を戻す", M.PORTAUDIO.held == 0, M.PORTAUDIO.held)
system, pa = setup()
first = H.VoiceListener(CABLE_OUT, 0.05, lambda wav, seconds: None)
first.start()
system.default["capture"] = CABLE_OUT
second = H.VoiceListener(MIC, 0.05, lambda wav, seconds: None)    # オーナーのマイク
ok, why = second.start()
check("1つ目が開いたまま並びが変わったら、2つ目は断る", ok is False and "並びが変わった" in why, (ok, why))
check("2つ目で別の入力を開かない", opened(system, "pa-in") == [CABLE_OUT], opened(system, "pa-in"))
check("1つ目を閉じない", not any(s.killed for s in pa.streams))
first.stop()
check("開いている数が戻る（断った方は数えない）", M.PORTAUDIO.held == 0, M.PORTAUDIO.held)

print("■ ほかの流れが開いていても、使う向きの並びが今のままなら開ける（再生の並びだけ変わったとき）")
system, pa = setup()
app = AppHarness(output=CABLE_IN, input=MIC)
ok, why = app.start_input_passthrough()          # 転送中（入力・出力とも開いている）
wait_until(lambda: opened(system, "pa-out"))
system.default["render"] = CABLE_IN              # 再生の並びだけ変わる（2026-11-03 の形）
listener = H.VoiceListener(CABLE_OUT, 0.05, lambda wav, seconds: None)
listener_ok, listener_why = listener.start()
level, level_why = app.measure_input_level(seconds=0.02)
listener.stop()
app.stop_input_passthrough()
check("転送は始められた", ok is True, why)
check("声を聞くは開ける（入力の並びは今のまま）", listener_ok is True, listener_why)
check("マイクの確認も開ける", level is not None, level_why)
check("入力は選んだ機材を開く", opened(system, "pa-in") == [MIC, CABLE_OUT, MIC], opened(system, "pa-in"))
check("一覧を作り直さない（転送を閉じない）", pa.refreshed == 0 and not any(s.killed for s in pa.streams))
check("開いている数が戻る", M.PORTAUDIO.held == 0, M.PORTAUDIO.held)

print("■ 作り直しで PortAudio を立ち上げ直せなかったら、次の機会にやり直す（選んでいたマイクは消さない）")
system, pa = setup()
app = AppHarness(input=MIC)
system.default["capture"] = CABLE_OUT
pa.fail_initialize = 1
level, why = app.measure_input_level(seconds=0.02)
check("1回目は断る（読み直せなかったと言う）", level is None and "読み直せません" in why, why)
level, why = app.measure_input_level(seconds=0.02)
check("2回目は立ち上げ直して、選んだマイクで録る", level is not None and opened(system, "pa-in") == [MIC],
      (why, opened(system, "pa-in")))
check("開いている数が戻る", M.PORTAUDIO.held == 0, M.PORTAUDIO.held)
system, pa = setup()
app = AppHarness(input=MIC)
system.default["capture"] = CABLE_OUT
pa.fail_initialize = 2                            # 立ち上げ直しが続けて失敗する（🔄 1回につき1回やり直す）
app.refresh_input_devices()
app.refresh_input_devices()
check("🔄 で一覧を読めなくても、選んでいたマイクを消さない（続けて失敗しても）",
      app.audio_input_var.get() == MIC and app.db.settings["audio_input_device"] == MIC, app.db.settings)
check("読み直せなかったことを知らせる", sum("読み直せません" in m for m in app.logs) == 2, app.logs)
app.refresh_input_devices()
check("次の 🔄 で立ち上げ直せれば、一覧が戻る", MIC in (app.audio_input_menu.values or []), app.audio_input_menu.values)

print("■ 🔄 の知らせは、一覧を作った後の状態で決める（立ち上げ直しが1回だけ失敗したとき）")
system, pa = setup()
app = AppHarness(input=MIC)
system.default["capture"] = CABLE_OUT
system.devices["capture"].remove(MIC)             # 選んでいたマイクを抜いた
pa.fail_initialize = 1
app.refresh_input_devices()
check("1回目: 読み直せなかったと知らせ、選んでいたマイクは消さない",
      any("読み直せません" in m for m in app.logs) and app.db.settings["audio_input_device"] == MIC, app.logs)
check("何も開いていないのに「止めてから🔄」とは言わない", not any("止めてから🔄" in m for m in app.logs), app.logs)
app.logs.clear()
app.refresh_input_devices()
check("2回目: 立ち上げ直して、抜いたマイクは既定に戻す（これまでどおり）",
      app.db.settings["audio_input_device"] == "" and MIC not in (app.audio_input_menu.values or []), (app.db.settings, app.logs))

print("■ 声を聞いている間の 🔄 は、古い一覧のままだと知らせる（選んでいたマイクは消さない）")
system, pa = setup()
app = AppHarness(input=MIC)
listener = H.VoiceListener(CABLE_OUT, 0.05, lambda wav, seconds: None)
listener.start()
system.devices["capture"].append("マイク (Webカメラ)")
app.refresh_input_devices()
check("止めてから 🔄 を押すように知らせる", any("止めてから🔄" in m for m in app.logs), app.logs)
check("選んでいたマイクはそのまま", app.audio_input_var.get() == MIC and app.db.settings["audio_input_device"] == MIC)
listener.stop()
app.refresh_input_devices()
check("止めた後の 🔄 では出る", "マイク (Webカメラ)" in (app.audio_input_menu.values or []), app.audio_input_menu.values)

print("■ 名前が絵文字の途中で切れていても、PortAudio と同じ形で比べる")
CUT = "ヘッドホン (BT \ud83c"                       # 31文字目で切れて、サロゲートの片割れが残った名前
system, pa = setup(extra_render=[CUT])
app = AppHarness(output=pa_name(CUT))            # 前の版は PortAudio の名前（U+FFFD）を保存していた


def utf8_ok(text):
    try:
        text.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


check("今の並びと同じと分かる（作り直さない）", M.PORTAUDIO.is_current(pa) and pa.refreshed == 0)
check("出力先の一覧の名前は保存できる形", all(utf8_ok(name) for name in app.list_output_devices()))
player = make_player(app)
check("前の版が保存した名前で、その機材に鳴る", player.play(WAV, 100, app.get_audio_output_device()) is True
      and played_to(system) == [CUT] and A.winsound.played == [], (played_to(system), app.logs))

print("■ 入力の一覧: 起動した後につないだ機材も 🔄 で出る")
system, pa = setup()
app = AppHarness()
system.devices["capture"].append("マイク (Webカメラ)")
check("マイクの一覧に出る", "マイク (Webカメラ)" in app.list_input_devices(), app.list_input_devices())
check("声を聞くの一覧に出る", "マイク (Webカメラ)" in H.list_input_devices(), H.list_input_devices())

print("■ 並びが変わっていなければ、一覧を作り直さない")
system, pa = setup()
app = AppHarness(output=CABLE_IN, input=MIC)
app.list_input_devices()
app.measure_input_level(seconds=0.02)
H.list_input_devices()
check("作り直さない", pa.refreshed == 0, pa.refreshed)

print("■ winmm が無い環境では、これまでどおり")
system, pa = setup()
M._winmm = M._kernel32 = None
check("比べられないので作り直さない", M.PORTAUDIO.refresh(pa) is True and pa.refreshed == 0)
check("一覧は sounddevice から", CABLE_IN in AppHarness().list_output_devices())
app = AppHarness(output=CABLE_IN)
player = make_player(app)
check("読み上げは sounddevice で鳴らす", player.play(WAV, 100, app.get_audio_output_device()) is True
      and opened(system, "pa-out") == [CABLE_IN], opened(system, "pa-out"))

A.sounddevice, A.winsound, real_sd, M._winmm, M._kernel32, M.PORTAUDIO = REAL
if real_sd is not None:
    sys.modules["sounddevice"] = real_sd

print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
