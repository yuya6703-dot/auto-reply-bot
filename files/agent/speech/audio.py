# -*- coding: utf-8 -*-
"""
WAV（16bit PCM）の小さな道具。音量を変える・中身を読む。
⚠️ 中身は auto_reply_app.App._apply_volume_to_wav と同じ（段階2で移した）。動きを変えないこと。
"""
import array
import io
import wave
from dataclasses import dataclass


def apply_volume(wav_data, volume_percent):
    """
    WAVデータ(bytes)の音量を変更したWAVデータを返す。
    16bitモノラル/ステレオのWAVに対応。それ以外の形式やエラー時は元データをそのまま返す。
    """
    volume_percent = max(0, min(100, int(volume_percent)))
    if volume_percent == 100:
        return wav_data
    try:
        with wave.open(io.BytesIO(wav_data), "rb") as src:
            params = src.getparams()
            frames = src.readframes(src.getnframes())
        if params.sampwidth != 2:
            return wav_data  # 16bit以外は加工せずそのまま鳴らす

        gain = (volume_percent / 100.0) ** 2
        samples = array.array("h")
        samples.frombytes(frames)
        for i, value in enumerate(samples):
            samples[i] = int(max(-32768, min(32767, value * gain)))

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as dst:
            dst.setnchannels(params.nchannels)
            dst.setsampwidth(params.sampwidth)
            dst.setframerate(params.framerate)
            dst.writeframes(samples.tobytes())
        return buffer.getvalue()
    except Exception:
        return wav_data


@dataclass(frozen=True)
class PcmInfo:
    channels: int
    sampwidth: int
    framerate: int
    frame_count: int
    frames: bytes

    @property
    def duration_seconds(self):
        return self.frame_count / float(self.framerate) if self.framerate else 0.0


def read_pcm(wav_data):
    """WAV の中身を読む。読めなければ None"""
    try:
        with wave.open(io.BytesIO(wav_data), "rb") as w:
            count = w.getnframes()
            return PcmInfo(w.getnchannels(), w.getsampwidth(), w.getframerate(), count, w.readframes(count))
    except Exception:
        return None


def make_silence_wav(seconds, framerate=24000, channels=1):
    """テスト用の無音の WAV"""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(b"\x00\x00" * channels * int(framerate * seconds))
    return buffer.getvalue()
