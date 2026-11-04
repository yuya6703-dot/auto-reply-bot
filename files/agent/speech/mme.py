# -*- coding: utf-8 -*-
"""
MME（winmm）の機材を、今の並びで扱う（2026-11-03 スマホから送った文の読み上げが、ルームで聞こえない）。

何が起きていたか:
- sounddevice（PortAudio）は、機材の一覧を import したときに1回だけ作り、その後は作り直さない（🔄 も同じ一覧を読み直すだけ）
- PortAudio の MME は、一覧を作ったときの winmm の番号で機材を開く
- Windows（winmm）は、今の既定の機材を 0番に置き、残りを決まった順に並べる。既定が変わると番号が入れ替わる
→ 既定の再生デバイスが CABLE Input に変わっていた間、「CABLE Input」の番号はモニターのスピーカーを指し、
  例外も出ずにそちらへ鳴っていた（ルームには届かない。スマホには「✓ 読み上げます。」と出る）

ここでやること:
- 鳴らす（WaveOutStream）: 鳴らす直前に waveOutGetDevCaps で今の名前を読み、その番号で waveOutOpen する。
  MME のままなので、これまでの実測（DirectSound は音が消える・WASAPI は 24000Hz を断る。App の AUDIO_HOST_API）はそのまま当てはまる
- 聞く・マイクの転送（sounddevice のまま）: 一覧が今の並びと違えば作り直す（PortAudioGuard）。
  ⚠️ 作り直すと開いている流れが全部閉じられるので、ほかの流れが開いている間は作り直さず、開かずに断る（別の機材が開くよりよい）

⚠️ ここは tkinter・auto_reply_app・sounddevice を import しない（sounddevice は呼ぶ側から受け取る）
"""
import ctypes
import threading
import time

try:
    _winmm = ctypes.WinDLL("winmm")
    _kernel32 = ctypes.WinDLL("kernel32")
except (AttributeError, OSError):         # Windows 以外
    _winmm = _kernel32 = None

WAVE_MAPPER = 0xFFFFFFFF          # 「既定の機材」。開いた時点の既定へ鳴る
WAVE_FORMAT_PCM = 1
CALLBACK_EVENT = 0x00050000
WHDR_DONE = 0x00000001
MMSYSERR_NOERROR = 0
_ERRORS = {2: "その番号の機材が無い", 4: "ほかで使われている", 6: "ドライバーが無い", 7: "メモリーが足りない",
           32: "この形式では鳴らせない"}

STALE_MESSAGE = ("Windowsの音の機材の並びが変わったため、今は開けません。\n"
                 "声を聞く・マイクの転送を止めてからやり直すか、アプリを再起動してください。")
BROKEN_MESSAGE = ("Windowsの音の機材の一覧を読み直せませんでした。\n"
                  "アプリを起動し直してください。")
LIST_HINT = "声を聞く・マイクの転送をしている間は、後からつないだ機材は一覧に出ません（止めてから🔄を押してください）。"

_WORD, _DWORD, _UINT = ctypes.c_uint16, ctypes.c_uint32, ctypes.c_uint


class _WAVEOUTCAPSW(ctypes.Structure):
    _fields_ = [("wMid", _WORD), ("wPid", _WORD), ("vDriverVersion", _UINT), ("szPname", ctypes.c_wchar * 32),
                ("dwFormats", _DWORD), ("wChannels", _WORD), ("wReserved1", _WORD), ("dwSupport", _DWORD)]


class _WAVEINCAPSW(ctypes.Structure):
    _fields_ = [("wMid", _WORD), ("wPid", _WORD), ("vDriverVersion", _UINT), ("szPname", ctypes.c_wchar * 32),
                ("dwFormats", _DWORD), ("wChannels", _WORD), ("wReserved1", _WORD)]


class _WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", _WORD), ("nChannels", _WORD), ("nSamplesPerSec", _DWORD), ("nAvgBytesPerSec", _DWORD),
                ("nBlockAlign", _WORD), ("wBitsPerSample", _WORD), ("cbSize", _WORD)]


class _WAVEHDR(ctypes.Structure):
    pass


_WAVEHDR._fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", _DWORD), ("dwBytesRecorded", _DWORD),
                     ("dwUser", ctypes.c_size_t), ("dwFlags", _DWORD), ("dwLoops", _DWORD),
                     ("lpNext", ctypes.POINTER(_WAVEHDR)), ("reserved", ctypes.c_size_t)]


def _declare():
    """引数の型を決めておく（64bit で handle・ポインターが切れないように）"""
    handle = ctypes.c_void_p
    for name in ("waveOutGetNumDevs", "waveInGetNumDevs"):
        getattr(_winmm, name).argtypes = []
    _winmm.waveOutGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(_WAVEOUTCAPSW), _UINT]
    _winmm.waveInGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(_WAVEINCAPSW), _UINT]
    _winmm.waveOutOpen.argtypes = [ctypes.POINTER(handle), _UINT, ctypes.POINTER(_WAVEFORMATEX), ctypes.c_size_t,
                                   ctypes.c_size_t, _DWORD]
    for name in ("waveOutPrepareHeader", "waveOutWrite", "waveOutUnprepareHeader"):
        getattr(_winmm, name).argtypes = [handle, ctypes.POINTER(_WAVEHDR), _UINT]
    for name in ("waveOutReset", "waveOutClose"):
        getattr(_winmm, name).argtypes = [handle]
    for name in ("waveOutGetNumDevs", "waveInGetNumDevs", "waveOutGetDevCapsW", "waveInGetDevCapsW", "waveOutOpen",
                 "waveOutPrepareHeader", "waveOutWrite", "waveOutUnprepareHeader", "waveOutReset", "waveOutClose"):
        getattr(_winmm, name).restype = _UINT
    _kernel32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
    _kernel32.CreateEventW.restype = handle
    _kernel32.WaitForSingleObject.argtypes = [handle, _DWORD]
    _kernel32.WaitForSingleObject.restype = _DWORD
    _kernel32.CloseHandle.argtypes = [handle]
    _kernel32.CloseHandle.restype = ctypes.c_int


if _winmm is not None:
    _declare()


def available():
    """winmm を使えるか（Windows なら使える）"""
    return _winmm is not None


def _clean(name):
    """
    PortAudio と同じ形の名前にする。MME は名前を UTF-16 の31単位で切るので、絵文字などの途中で切れると片割れ（サロゲート）が残る。
    PortAudio は WideCharToMultiByte で UTF-8 にして片割れを U+FFFD にするが、ctypes はそのまま返す
    （そのままだと一覧と比べてずっと「並びが違う」になり、DB にも保存できない）
    """
    return name.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def output_names():
    """今の再生の機材の名前を winmm の番号の順に（読めない番号は None）。winmm が無ければ None"""
    if _winmm is None:
        return None
    names = []
    for i in range(_winmm.waveOutGetNumDevs()):
        caps = _WAVEOUTCAPSW()
        ok = _winmm.waveOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == MMSYSERR_NOERROR
        names.append(_clean(caps.szPname) if ok else None)
    return names


def input_names():
    """今の録音の機材の名前を winmm の番号の順に（読めない番号は None）。winmm が無ければ None"""
    if _winmm is None:
        return None
    names = []
    for i in range(_winmm.waveInGetNumDevs()):
        caps = _WAVEINCAPSW()
        ok = _winmm.waveInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == MMSYSERR_NOERROR
        names.append(_clean(caps.szPname) if ok else None)
    return names


def find(names, wanted):
    """
    名前から番号を引く。まず完全一致、無ければ「保存した名前が、今の名前で始まる」もの
    （MME は名前を31文字で切るので、前の版が保存した長い名前も拾う。App._resolve_device_index と同じ決まり）
    """
    wanted = (wanted or "").strip()
    if not wanted or not names:
        return None
    stripped = [(name or "").strip() for name in names]
    if wanted in stripped:
        return stripped.index(wanted)
    for i, name in enumerate(stripped):
        if name and wanted.startswith(name):
            return i
    return None


class _OutputId(int):
    """find_output が返す番号。開いた後に同じ機材か確かめるため、引いたときの名前も持つ"""

    def __new__(cls, value, name):
        self = super().__new__(cls, value)
        self.name = name
        return self


def _caps_name(device):
    """waveOutGetDevCaps の名前（番号・WAVE_MAPPER・開いている handle のどれでも引ける）。読めなければ None"""
    caps = _WAVEOUTCAPSW()
    if _winmm.waveOutGetDevCapsW(device, ctypes.byref(caps), ctypes.sizeof(caps)) != MMSYSERR_NOERROR:
        return None
    return _clean(caps.szPname)


def _is_mapper(device_name):
    """
    「Microsoft サウンド マッパー - Output」か。前の版の一覧（sounddevice）にはあったので、選んでいた人がいる。
    winmm の番号の一覧には無い（既定の機材のこと）→ WAVE_MAPPER で鳴らす（見つからない扱いにすると、止められない winsound で鳴る）
    """
    mapper = (_caps_name(WAVE_MAPPER) or "").strip()
    return bool(mapper) and (device_name or "").strip().startswith(mapper)


def find_output(device_name):
    """再生の機材の今の番号（無ければ None）。⚠️ 鳴らす直前に呼ぶ（既定の機材が変わると番号が入れ替わる）"""
    names = output_names()
    index = find(names, device_name)
    if index is not None:
        return _OutputId(index, names[index])
    if names and _is_mapper(device_name):
        return WAVE_MAPPER
    return None


def default_output():
    """既定の再生の機材（WAVE_MAPPER。開いた時点の既定へ鳴る）。機材が1つも無ければ None"""
    return WAVE_MAPPER if output_names() else None


def _check(code, what):
    if code != MMSYSERR_NOERROR:
        raise OSError(f"{what} に失敗しました（{_ERRORS.get(code, code)}）")


class WaveOutStream:
    """
    waveOut で鳴らす流れ。AudioPlayer が sounddevice.RawOutputStream に使っていた分（start・write・abort・stop・close）と、
    鳴り終わっていない数（pending）を持つ。
    write は待たずに返る（winmm が順に鳴らす。sounddevice の write も鳴り終わりを待たずに返っていた）。
    ⚠️ 閉じるまで、書いた音の入れ物を手放さない（winmm が後から読みに来る）
    """
    STOP_TIMEOUT = 2.0        # stop で鳴り終わりを待つ上限（秒）
    OPEN_TRIES = 3            # 開いた機材が引いたときの名前と違ったら、引き直して開き直す回数

    def __init__(self, samplerate, channels, dtype="int16", device=WAVE_MAPPER):
        if _winmm is None:
            raise OSError("winmm が使えません")
        if dtype != "int16":
            raise ValueError(f"{dtype} は鳴らせません（int16 だけ）")
        self._headers, self._queued, self._buffers = [], [], []    # 用意した分（閉じるときに戻す）・渡せた分（鳴り終わりを待つ）
        self._closed = False
        block = channels * 2
        fmt = _WAVEFORMATEX(WAVE_FORMAT_PCM, channels, samplerate, samplerate * block, block, 16, 0)
        self._event = _kernel32.CreateEventW(None, False, False, None)
        if not self._event:
            raise OSError("CreateEventW に失敗しました")
        self._handle = ctypes.c_void_p()
        try:
            self._open(device, fmt)
        except Exception:
            _kernel32.CloseHandle(self._event)
            raise

    def _open(self, device, fmt):
        """
        開いて、開いた機材が名前を引いた機材か確かめる（番号は名前を引いてから開くまでの間にも入れ替わりうる）。
        違えば閉じて、名前から引き直して開き直す
        """
        for _ in range(self.OPEN_TRIES):
            code = _winmm.waveOutOpen(ctypes.byref(self._handle), int(device), ctypes.byref(fmt), self._event, 0,
                                      CALLBACK_EVENT)
            if code != MMSYSERR_NOERROR:
                raise OSError(f"waveOutOpen に失敗しました（{_ERRORS.get(code, code)}）")
            wanted = getattr(device, "name", None)          # WAVE_MAPPER（既定）は確かめない
            opened = _caps_name(self._handle.value) if wanted is not None else None
            if wanted is None or opened is None or opened == wanted:
                return
            _winmm.waveOutClose(self._handle)
            device = find_output(wanted)
            if device is None:
                raise OSError(f"「{wanted.strip()}」が見つかりません")
        raise OSError("機材の並びが変わり続けたため開けませんでした")

    def start(self):
        """waveOut は書いたら鳴り始める（sounddevice と同じ呼び方にするためだけにある）"""

    def write(self, data):
        data = bytes(data)
        if not data:
            return
        buffer = ctypes.create_string_buffer(data, len(data))
        header = _WAVEHDR(lpData=ctypes.cast(buffer, ctypes.c_void_p), dwBufferLength=len(data))
        _check(_winmm.waveOutPrepareHeader(self._handle, ctypes.byref(header), ctypes.sizeof(header)),
               "waveOutPrepareHeader")
        self._buffers.append(buffer)
        self._headers.append(header)
        _check(_winmm.waveOutWrite(self._handle, ctypes.byref(header), ctypes.sizeof(header)), "waveOutWrite")
        self._queued.append(header)                 # ⚠️ 渡せなかった分は鳴り終わらないので、待つのは渡せた分だけ

    def pending(self):
        """渡した音のうち、まだ鳴り終わっていない数"""
        return sum(1 for header in self._queued if not header.dwFlags & WHDR_DONE)

    def abort(self):
        """待っている分も捨てて、すぐ止める"""
        _winmm.waveOutReset(self._handle)

    def stop(self):
        """渡した分が鳴り終わるまで待つ（上限 STOP_TIMEOUT 秒。sounddevice の stop と同じ）"""
        deadline = time.monotonic() + self.STOP_TIMEOUT
        while self.pending():
            if time.monotonic() >= deadline:
                return
            _kernel32.WaitForSingleObject(self._event, 20)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            _winmm.waveOutReset(self._handle)       # ⚠️ 鳴らし途中の分が残っていると閉じられない
            for header in self._headers:
                _winmm.waveOutUnprepareHeader(self._handle, ctypes.byref(header), ctypes.sizeof(header))
            _winmm.waveOutClose(self._handle)
        finally:
            _kernel32.CloseHandle(self._event)
            self._headers, self._queued, self._buffers = [], [], []


class WaveOut:
    """AudioPlayer に sounddevice の代わりに渡すもの（RawOutputStream だけ使う）"""
    RawOutputStream = WaveOutStream


def _same_order(portaudio_names, winmm_names):
    """
    PortAudio の MME の一覧（片方の向き）が winmm の今の並びと同じか。
    PortAudio は先頭に「Microsoft サウンド マッパー」を置き、続けて winmm の番号の順に並べる（読めない番号は飛ばす）。
    2026-11-04 実物: 入力・出力とも、先頭を除くと winmm の並びと一致した
    """
    now = [name for name in winmm_names if name is not None]
    extra = len(portaudio_names) - len(now)
    return extra in (0, 1) and portaudio_names[extra:] == now


INPUT, OUTPUT = "input", "output"
BOTH = (INPUT, OUTPUT)


class PortAudioGuard:
    """
    sounddevice（PortAudio）の機材の一覧が、今の MME の並びと同じかを向き（入力・出力）ごとに見て、違えば作り直す。
    ⚠️ 作り直す（Pa_Terminate → Pa_Initialize）と、開いている流れは全部閉じられる。
       流れを開く側は hold（閉じたら release）で数えておき、1つでも開いている間は作り直さない。
       そのときも、使う向きの並びが今のままなら開ける（入力の番号は出力の並びに左右されない。2026-11-04 の見直しで見つけた:
       両方の向きをまとめて見ると、転送中に再生の並びだけ変わったとき、声を聞く・マイクの確認まで断っていた）
    ⚠️ 作り直している最中に一覧を読む・流れを開くと PortAudio が壊れる。一覧を読むときは lock を持つ
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.on_refresh = None          # 作り直したら呼ぶ（ログ用。どのスレッドからも呼ばれる）
        self._held = 0

    @property
    def held(self):
        return self._held

    def stale(self, sd):
        """
        一覧が今の並びと違う向きの集合（INPUT・OUTPUT）。比べられなければ空（これまでどおり使う）。
        ⚠️ 前の作り直しで PortAudio が止まったまま（Pa_Initialize に失敗）なら両方（一覧を読むと例外になり、空と見誤らないように）
        """
        if getattr(sd, "_initialized", 1) < 1:
            return set(BOTH)
        inputs_now, outputs_now = input_names(), output_names()
        if inputs_now is None or outputs_now is None:
            return set()
        try:
            apis = sd.query_hostapis()
            inputs, outputs = [], []
            for device in sd.query_devices():
                if apis[device["hostapi"]]["name"] != "MME":
                    continue
                if device.get("max_input_channels", 0) > 0:
                    inputs.append(device.get("name"))
                if device.get("max_output_channels", 0) > 0:
                    outputs.append(device.get("name"))
        except Exception:
            return set()
        stale = set()
        if not _same_order(inputs, inputs_now):
            stale.add(INPUT)
        if not _same_order(outputs, outputs_now):
            stale.add(OUTPUT)
        return stale

    def is_current(self, sd):
        """sounddevice の一覧が、両方の向きとも今の MME の並びと同じか"""
        return not self.stale(sd)

    def _refresh_if_stale(self, sd, need):
        stale = self.stale(sd)
        if not stale:
            return True
        if self._held:
            return not stale & set(need)     # 使う向きが今のままなら、作り直さなくても正しい機材が開く
        try:
            if getattr(sd, "_initialized", 1) >= 1:
                sd._terminate()
            sd._initialize()                 # 前に失敗して止まったままなら、立ち上げ直すだけ
        except Exception:
            return False
        if self.on_refresh is not None:
            try:
                self.on_refresh()
            except Exception:
                pass
        return True

    def refresh(self, sd, need=BOTH):
        """
        一覧を読む前に（🔄 など）。古ければ、開いている流れが無いときだけ作り直す。
        need の向きの一覧を信じてよければ True（False なら古いまま。選んでいた機材を消さないこと）
        """
        with self.lock:
            return self._refresh_if_stale(sd, need)

    def hold(self, sd, need=BOTH):
        """
        sounddevice で流れを開く前に呼ぶ。need は開く向き。開いてよければ True（数える。閉じたら release を呼ぶ）。
        その向きの一覧が古いのに、ほかの流れが開いていて作り直せなければ False（数えない。開かないこと: 別の機材が開く）
        """
        with self.lock:
            if not self._refresh_if_stale(sd, need):
                return False
            self._held += 1
            return True

    def release(self):
        with self.lock:
            self._held = max(0, self._held - 1)

    def refusal(self, sd, listing=False):
        """hold・refresh が断ったわけ（画面・ログに出す文）。listing なら 🔄 で一覧を読み直せなかったとき"""
        if getattr(sd, "_initialized", 1) < 1:
            return BROKEN_MESSAGE
        return LIST_HINT if listing else STALE_MESSAGE


PORTAUDIO = PortAudioGuard()
