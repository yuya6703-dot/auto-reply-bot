# -*- coding: utf-8 -*-
"""
取り消しの合図（設計書/03 の 5章）。止めたい側が cancel() し、処理する側は合間に cancelled を見る。
"""
import threading


class CancelToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self):
        return self._event.is_set()

    def wait(self, seconds):
        """最大 seconds 待つ。待っている間に取り消されたら True"""
        return self._event.wait(seconds)


# 取り消しが要らない呼び出し用（アラームなど）
class _NeverCancelled(CancelToken):
    def cancel(self):
        pass


NEVER = _NeverCancelled()
