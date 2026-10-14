# -*- coding: utf-8 -*-
"""
音声サービス（設計書/03 の 4.2・5章、段階2）。喋る用件を順番に「合成 → 再生」し、止められるようにする。

段階2より前の「読み上げの待ち行列（最大20件）と専用スレッド」を置き換えたもの。
⚠️ 既存と同じにしていること
   - 1件の失敗（エンジンが起動していない等）でスレッドを止めない。次の用件へ進む
   - 待ち行列が一杯なら、その用件は捨てる（連打や誤送信で延々と喋り続けないように）
   - スレッドは最初の用件が来たときに1本だけ起こす（複数のスレッドから同時に呼ばれても2本にならない）
   - 声と音量は「合成・再生する時点」の設定を読む（呼び出し側の default_voice / default_volume）
足したこと: 今の再生を止める・待ち行列を空にする・優先度（小さいほど先。同じなら来た順）
"""
import itertools
import queue
import threading
from dataclasses import dataclass, field
from typing import Optional

from ..cancel import CancelToken

PRIORITY_URGENT = 0       # 予約（緊急の知らせなど）
PRIORITY_NORMAL = 50      # 読み上げ（手入力・クリップボード・スマホ）・AI の発言

EVENT_STARTED = "started"
EVENT_DONE = "done"
EVENT_CANCELLED = "cancelled"
EVENT_FAILED = "failed"
EVENT_QUEUE_CHANGED = "queue_changed"


@dataclass
class SpeechJob:
    text: Optional[str] = None       # 合成する文（wav が無いとき）
    wav: Optional[bytes] = None      # 合成済みの音（スマホでアクセントを直した文など）
    source: str = ""                 # どこから来たか（ログ用）
    voice: Optional[str] = None      # 話者の選び方（"engine:話者ID"）。None なら合成する時点の既定
    volume: Optional[int] = None     # 0〜100。None なら再生する時点の既定
    priority: int = PRIORITY_NORMAL
    job_id: int = 0
    cancel: CancelToken = field(default_factory=CancelToken)


class SpeechService:
    def __init__(self, synthesize, play, default_voice, default_volume, on_event=None, max_queue=20):
        """
        synthesize(text, voice) -> wav(bytes)。失敗は例外
        play(wav, volume, cancel) -> bool
        default_voice() / default_volume(): 用件に指定が無いときに使う（ワーカーのスレッドから呼ばれる）
        on_event(kind, job, detail): 状態の知らせ（ワーカーのスレッドから呼ばれる。画面に触るなら伝言板を通すこと）
        """
        self._synthesize = synthesize
        self._play = play
        self._default_voice = default_voice
        self._default_volume = default_volume
        self._on_event = on_event or (lambda kind, job, detail: None)
        self._max_queue = max_queue
        self._queue = queue.PriorityQueue()
        self._counter = itertools.count(1)
        self._lock = threading.Lock()
        self._thread = None
        self._current = None
        self._closed = False

    # --- 呼ぶ側 ---
    def enqueue(self, job):
        """用件を入れる。受け付けたら True。一杯・終了後なら False"""
        with self._lock:
            if self._closed or self._queue.qsize() >= self._max_queue:
                return False
            job.job_id = next(self._counter)
            self._queue.put((job.priority, job.job_id, job))
            self._ensure_worker()
        self._emit(EVENT_QUEUE_CHANGED, job)
        return True

    def pending_count(self):
        return self._queue.qsize()

    def is_busy(self):
        return self._current is not None

    def stop_current(self):
        """今の再生（または合成中の用件）を止める。待っている用件はそのまま"""
        current = self._current
        if current is not None:
            current.cancel.cancel()

    def clear_queue(self):
        """待っている用件を捨てる。捨てた数を返す"""
        dropped = 0
        while True:
            try:
                _, _, job = self._queue.get_nowait()
            except queue.Empty:
                break
            job.cancel.cancel()
            self._queue.task_done()
            dropped += 1
            self._emit(EVENT_CANCELLED, job, "待ち行列から捨てた")
        if dropped:
            self._emit(EVENT_QUEUE_CHANGED, None)
        return dropped

    def stop_all(self):
        """待ち行列を空にして、今の再生も止める（「音声を止める」ボタン）"""
        dropped = self.clear_queue()
        self.stop_current()
        return dropped

    def shutdown(self, timeout=2.0):
        """終了時の後片付け。新しい用件を受け付けず、今のものを止めてスレッドの終わりを待つ"""
        with self._lock:
            self._closed = True
        self.stop_all()
        self._queue.put((-1, 0, None))       # ワーカーを起こして終わらせる合図
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    # --- ワーカー ---
    def _ensure_worker(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _emit(self, kind, job, detail=None):
        try:
            self._on_event(kind, job, detail)
        except Exception:
            pass     # 知らせの失敗でワーカーを止めない

    def _run(self):
        while True:
            _, _, job = self._queue.get()
            if job is None:
                self._queue.task_done()
                return
            self._current = job
            try:
                if job.cancel.cancelled:
                    self._emit(EVENT_CANCELLED, job, "始める前に止められた")
                    continue
                self._emit(EVENT_STARTED, job)
                wav = job.wav
                if wav is None:
                    voice = job.voice or self._default_voice()
                    job.voice = voice
                    wav = self._synthesize(job.text, voice)
                if job.cancel.cancelled:
                    self._emit(EVENT_CANCELLED, job, "合成の後に止められた")
                    continue
                volume = self._default_volume() if job.volume is None else job.volume
                self._play(wav, volume, job.cancel)
                self._emit(EVENT_CANCELLED if job.cancel.cancelled else EVENT_DONE, job)
            except Exception as e:
                # ⚠️ ここで例外が漏れるとワーカーごと止まり、以後まったく喋らなくなる（既存と同じ考え）
                self._emit(EVENT_FAILED, job, e)
            finally:
                self._current = None
                try:
                    self._queue.task_done()
                except ValueError:
                    pass
                self._emit(EVENT_QUEUE_CHANGED, job)
