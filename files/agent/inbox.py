# -*- coding: utf-8 -*-
"""
受付箱（設計書/03 の 3.2）。出来事を受け取り、同じものを除き、区切りまで待ってまとめて渡す。

- 同じ出来事（event_id か key が同じ）は2度受け付けない（R4。覚えるのは直近の一定数）
- 最後の出来事から settle_seconds 静かになったら、まとめて1つの「まとまり」にする（複数のコメントに1回だけ判断する）
- 強い合図（AI の名前を呼ばれた）なら、待たずに渡す
- 上限を超えたら受け付けない（溢れた分は捨てる）
どのスレッドから submit してもよい。next_batch はエージェント本体のスレッドだけが呼ぶ。
"""
import threading
import time
from collections import OrderedDict


class Inbox:
    REMEMBER = 2000      # 重複の判定に覚えておく数

    def __init__(self, max_size=100, settle_seconds=2.5, strong_signal=None, clock=time.monotonic):
        self._max = max_size
        self.settle_seconds = settle_seconds
        self._strong = strong_signal or (lambda event: False)
        self._clock = clock
        self._cond = threading.Condition()
        self._pending = []
        self._last_at = None
        self._strong_pending = False
        self._seen = OrderedDict()
        self._closed = False
        self._wake = False
        self.seq = 0           # 受け付けた数の通し番号
        self.fresh_seq = 0     # そのうち、他の人の新しい出来事だけの通し番号（判断の間に状況が変わったかを見る。C1）

    def submit(self, event):
        """受け付けたら True。閉じている・同じ出来事・満杯なら False"""
        with self._cond:
            if self._closed:
                return False
            if event.event_id in self._seen or (event.key and ("key", event.key) in self._seen):
                return False
            if len(self._pending) >= self._max:
                return False
            self._remember(event.event_id)
            if event.key:
                self._remember(("key", event.key))
            self._pending.append(event)
            self._last_at = self._clock()
            self.seq += 1
            if not event.is_self and not event.backlog:
                self.fresh_seq += 1
            if self._strong(event):
                self._strong_pending = True
            self._cond.notify_all()
            return True

    def _remember(self, mark):
        self._seen[mark] = True
        while len(self._seen) > self.REMEMBER:
            self._seen.popitem(last=False)

    def next_batch(self, timeout):
        """まとまりを返す。timeout 秒たっても区切りが来なければ空のリスト。閉じたら空"""
        deadline = self._clock() + max(0.0, timeout)
        with self._cond:
            while True:
                if self._closed:
                    return []
                if self._wake:
                    self._wake = False
                    return []
                now = self._clock()
                if self._pending and (self._strong_pending or now - self._last_at >= self.settle_seconds):
                    batch, self._pending = self._pending, []
                    self._strong_pending = False
                    return batch
                waits = [deadline - now]
                if self._pending:
                    waits.append(self._last_at + self.settle_seconds - now)
                wait = min(waits)
                if wait <= 0 and not self._pending:
                    return []
                if wait <= 0:
                    # 締め切りが来たが、区切りはまだ（集めている途中）。呼び出し側に一度戻す
                    return []
                self._cond.wait(wait)

    def wake(self):
        """next_batch で待っているエージェントを起こす（状態が変わったとき）"""
        with self._cond:
            self._wake = True
            self._cond.notify_all()

    def pending_count(self):
        with self._cond:
            return len(self._pending)

    def clear(self):
        with self._cond:
            dropped = len(self._pending)
            self._pending = []
            self._strong_pending = False
            return dropped

    def close(self):
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def reopen(self):
        with self._cond:
            self._closed = False
            self._wake = False
