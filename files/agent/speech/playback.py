# -*- coding: utf-8 -*-
"""
途中で止められる再生（設計書/05 の 5章、段階2）。

段階2より前は「全部書き込んで、音の長さだけ sleep する」作りで、途中で止める手段が無かった。
ここでは短く区切って書き込み、待つ間も 0.05 秒ごとに取り消しの合図を見て、合図があれば出力を打ち切る（abort）。

⚠️ 既存と同じにしていること
   - 出力先は MME の中から名前で探す（呼び出し側の resolve_device）。DirectSound は音が届かない（開発ログ 2026-08-13）
   - 書き込みは再生の終わりを待たずに返るので、音の長さ＋0.2 秒待ってから閉じる（早く閉じると途中で切れる）
   - 選んだ出力先で鳴らせなければ、既定のデバイスで鳴らす（呼び出し側に1度だけ知らせる）
   - 16bit 以外の WAV は winsound に任せる
⚠️ 変えたこと: 出力先が「既定のデバイス」のときも、まず MME の既定の出力で鳴らす（止められるように）。
   鳴らせなければ、これまでどおり winsound で鳴らす（winsound の再生は途中で止められない）。
"""
import time

from ..cancel import NEVER
from .audio import apply_volume, read_pcm

PLAYED = "played"
CANCELLED = "cancelled"
UNAVAILABLE = "unavailable"


class AudioPlayer:
    CHUNK_SECONDS = 0.1     # 1回に書き込む長さ（止める合図に気付くまでの最大の遅れの目安）
    WAIT_STEP = 0.05        # 書き終わった後、鳴り終わるまで合図を見る間隔
    TAIL_SECONDS = 0.2      # 音の長さに足して待つ時間（既存と同じ）

    def __init__(self, sounddevice_module, winsound_module, resolve_device, default_device,
                 on_device_failed=None, clock=time.monotonic):
        self._sd = sounddevice_module             # None なら使わない
        self._ws = winsound_module                # None なら使わない
        self._resolve_device = resolve_device     # 出力先の名前 -> 番号（無ければ None）
        self._default_device = default_device     # () -> 既定の出力の番号（無ければ None）
        self._on_device_failed = on_device_failed or (lambda name: None)
        self._clock = clock

    def play(self, wav_data, volume_percent, device_name="", cancel=NEVER):
        """鳴らす（止められたら途中で終わる）。鳴らした・止めたなら True、鳴らせなかったら False"""
        if not wav_data:
            return False
        adjusted = apply_volume(wav_data, volume_percent)

        if device_name:
            index = self._resolve_device(device_name) if self._sd is not None else None
            result = self._play_stream(adjusted, index, cancel) if index is not None else UNAVAILABLE
            if result != UNAVAILABLE:
                return True
            # 選んだ出力先で鳴らせなかった。黙って無音にせず既定へ（デバイスを抜いた・名前が変わった等）
            self._on_device_failed(device_name)
        elif self._sd is not None:
            index = self._default_device()
            if index is not None and self._play_stream(adjusted, index, cancel) != UNAVAILABLE:
                return True

        if cancel.cancelled:
            return True     # ⚠️ 止められたのに winsound で頭から鳴らし直さない
        return self._play_winsound(adjusted)

    def _play_stream(self, wav_data, index, cancel):
        pcm = read_pcm(wav_data)
        if pcm is None or pcm.sampwidth != 2 or not pcm.frames:
            return UNAVAILABLE       # 16bit 以外は winsound 側に任せる（既存と同じ）
        try:
            stream = self._sd.RawOutputStream(samplerate=pcm.framerate, channels=pcm.channels,
                                              dtype="int16", device=index)
        except Exception:
            return UNAVAILABLE
        aborted = False
        try:
            stream.start()
            chunk = max(1, int(pcm.framerate * self.CHUNK_SECONDS)) * 2 * pcm.channels
            started = self._clock()
            for offset in range(0, len(pcm.frames), chunk):
                if cancel.cancelled:
                    stream.abort()
                    aborted = True
                    return CANCELLED
                stream.write(pcm.frames[offset:offset + chunk])
            end = started + pcm.duration_seconds + self.TAIL_SECONDS
            while True:
                remaining = end - self._clock()
                if remaining <= 0:
                    return PLAYED
                if cancel.wait(min(self.WAIT_STEP, remaining)):
                    stream.abort()
                    aborted = True
                    return CANCELLED
        except Exception:
            return UNAVAILABLE
        finally:
            try:
                if not aborted:
                    stream.stop()
                stream.close()
            except Exception:
                pass

    def _play_winsound(self, wav_data):
        if self._ws is None:
            return False
        try:
            self._ws.PlaySound(wav_data, self._ws.SND_MEMORY)
            return True
        except Exception:
            return False
