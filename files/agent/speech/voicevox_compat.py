# -*- coding: utf-8 -*-
"""
AivisSpeech・VOICEVOX のアダプター（設計書/05 の 4.2）。

【事実】どちらも同じ HTTP の手順（/speakers → /audio_query → /synthesis）で合成できる（既存コードで動いていた）。
そこで1つのクラスを、宛先違いで2つ使う。宛先は呼ぶたびに getter から読む（画面で書き換えた宛先にすぐ従うため）。

⚠️ 動きは段階2より前の App のメソッド（_voicevox_request・synthesize_zundamon_wav・fetch_voicevox_speakers と、
   AivisSpeech 版の3つ）と同じにしてある。時間制限（問い合わせ30秒・合成60秒・一覧15秒）、
   合成結果の覚え（宛先・話者・文が同じなら使い回す。上限つき）も同じ。
"""
import json
import threading
import urllib.parse
import urllib.request


class TTSError(Exception):
    """音声合成ができなかった（エンジンが起動していない・話者が無い など）"""


class VoicevoxCompatibleEngine:
    QUERY_TIMEOUT = 30
    SYNTHESIS_TIMEOUT = 60
    SPEAKERS_TIMEOUT = 15

    def __init__(self, name, base_url_getter, cache_size=40, opener=None):
        self.name = name                         # "voicevox" / "aivisspeech"
        self._base_url = base_url_getter         # 例 lambda: "http://127.0.0.1:10101"
        self._cache_size = cache_size
        self._cache = {}
        self._cache_lock = threading.Lock()
        # HTTP を投げる関数（テストで差し替える）: (url, method, data, timeout) -> bytes
        self._open = opener or self._urlopen

    @staticmethod
    def _urlopen(url, method, data, timeout):
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.read()

    def base_url(self):
        return (self._base_url() or "").rstrip("/")

    def request(self, path, method="GET", data=None, timeout=30):
        """エンジンへそのまま投げる（アクセント解析など、合成以外の用途にも使う）"""
        return self._open(f"{self.base_url()}{path}", method, data, timeout)

    def health(self, timeout=2):
        try:
            self.request("/version", timeout=timeout)
            return True
        except Exception:
            return False

    def fetch_speakers(self):
        """全キャラのスタイル一覧を {キャラ名: {スタイル名: 話者ID}} で返す。接続できなければ例外"""
        raw = self.request("/speakers", timeout=self.SPEAKERS_TIMEOUT)
        speakers = json.loads(raw.decode("utf-8"))
        result = {}
        for speaker in speakers:
            name = (speaker.get("name") or "").strip()
            styles = {s["name"]: s["id"] for s in speaker.get("styles", []) if "id" in s}
            if name and styles:
                result[name] = styles
        if not result:
            raise RuntimeError("エンジンから音声が1つも見つかりませんでした。")
        return result

    def synthesize(self, text, speaker_id):
        """WAV(bytes) を返す。同じ宛先・話者・文は覚えたものを返す"""
        cache_key = (self.base_url(), speaker_id, text)
        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        query_json = self.request(f"/audio_query?text={urllib.parse.quote(text)}&speaker={speaker_id}",
                                  method="POST", data=b"", timeout=self.QUERY_TIMEOUT)
        wav_data = self.request(f"/synthesis?speaker={speaker_id}", method="POST", data=query_json,
                                timeout=self.SYNTHESIS_TIMEOUT)

        with self._cache_lock:
            # 古いものから捨てる（dict は入れた順を保つので、先頭が最古）
            while len(self._cache) >= self._cache_size:
                del self._cache[next(iter(self._cache))]
            self._cache[cache_key] = wav_data
        return wav_data

    def clear_cache(self):
        with self._cache_lock:
            self._cache.clear()

    def cached_count(self):
        with self._cache_lock:
            return len(self._cache)
