# -*- coding: utf-8 -*-
"""
エージェントのテストで共通に使う器（test_agent_decision.py・test_agent_guards.py・test_agent_lifecycle.py）。

本物の AgentRuntime を、模擬の AI・にせの声・一時フォルダの agent_data.db で動かす。音は鳴らさない。
⚠️ テストの出来事に実在の人の名前を書かない（リポジトリは公開）。
"""
import os, sys, tempfile, threading, time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
from agent.config import AgentConfig
from agent.events import AgentEvent, KIND_CHAT_MESSAGE, SOURCE_TEST, make_manual_event, new_event_id
from agent.llm.base import PURPOSE_DECIDE, PURPOSE_GENERATE
from agent.llm.mock import MockProvider
from agent.memory.store import AgentStore
from agent.runtime import CHAT_DISCARDED, POSTED, SPEECH_CANCELLED, SPOKEN, AgentDeps, AgentRuntime

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


def finish():
    print()
    if FAILS:
        print(f"失敗 {len(FAILS)} 件: {FAILS}")
        sys.exit(1)
    print("すべて成功")


def wait_until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def make_event(text, speaker="テスト", event_id=None, key=None, is_self=False, backlog=False, at=None,
               source=SOURCE_TEST, account=None):
    meta = {"backlog": True} if backlog else {}
    if account is not None:
        meta["account"] = account
    return AgentEvent(event_id=event_id or new_event_id(), kind=KIND_CHAT_MESSAGE, source=source,
                      key=key or new_event_id(), speaker=speaker, text=text,
                      observed_at=time.time() if at is None else at, meta=meta, is_self=is_self)


class FakeSpeaker:
    """AgentDeps.speak のにせもの。喋った文を覚え、play_seconds だけ（止められるまで）待つ"""

    def __init__(self, play_seconds=0.0):
        self.play_seconds = play_seconds
        self.spoken = []
        self.cancelled = []
        self.stop_all_calls = 0
        self.speaking = threading.Event()

    def speak(self, utterance, cancel):
        self.speaking.set()
        try:
            if cancel.wait(self.play_seconds):
                self.cancelled.append(utterance.text)
                return SPEECH_CANCELLED
            self.spoken.append(utterance.text)
            return SPOKEN
        finally:
            self.speaking.clear()

    def stop_all(self):
        self.stop_all_calls += 1


class FakeChat:
    """AgentDeps.post_chat のにせもの。answer で返事を決める（POSTED / CHAT_DISCARDED / CHAT_FAILED / "wait"）"""

    def __init__(self, answer=POSTED):
        self.answer = answer
        self.posted = []
        self.asked = []
        self.waiting = threading.Event()

    def post(self, utterance, cancel):
        self.asked.append(utterance.text)
        if self.answer == "wait":           # 確認の画面で本人が迷っている（緊急停止で止まる）
            self.waiting.set()
            cancel.wait(10.0)
            return SPEECH_CANCELLED if cancel.cancelled else CHAT_DISCARDED
        if self.answer == POSTED:
            self.posted.append(utterance.text)
        return self.answer


class Agent:
    """runtime・mock・speaker・store・ログをまとめたもの"""

    def __init__(self, path=None, mode="script", start=True, play_seconds=0.0, **config):
        self.dir = os.path.dirname(path) if path else tempfile.mkdtemp()
        self.path = path or os.path.join(self.dir, "agent_data.db")
        self.store = AgentStore(self.path)
        self.open_status = self.store.open()
        self.mock = MockProvider(mode=mode)
        self.speaker = FakeSpeaker(play_seconds)
        self.chat = FakeChat()
        self.logs, self.notices, self.states, self.errors = [], [], [], []
        defaults = dict(settle_seconds=0.15, ai_name="アイ")
        defaults.update(config)
        self.config = AgentConfig(**defaults)
        self.runtime = AgentRuntime(AgentDeps(
            provider_factory=lambda: self.mock, speak=self.speaker.speak, stop_speech=self.speaker.stop_all,
            post_chat=self.chat.post,
            store=self.store, on_log=self.logs.append, on_notice=self.notices.append,
            on_state=self.states.append, on_error=self.errors.append), self.config)
        if start:
            ok, message = self.runtime.start()
            assert ok, message

    # --- 出来事 ---
    def say(self, text, speaker="テスト", **kw):
        return self.runtime.submit(make_manual_event(text, speaker=speaker, **kw))

    def event(self, text, **kw):
        return make_event(text, **kw)

    # --- 見る ---
    def decide_calls(self):
        return [r for r in self.mock.requests if r.purpose == PURPOSE_DECIDE]

    def generate_calls(self):
        return [r for r in self.mock.requests if r.purpose == PURPOSE_GENERATE]

    def decisions(self):
        """古い順の (action, reason, decided_by, rule_id)"""
        rows = self.store.recent_decisions(200)
        return [(a, r, by, rule) for _turn, a, r, by, rule, _at in reversed(rows)]

    def wait_decisions(self, n, timeout=3.0):
        return wait_until(lambda: len(self.decisions()) >= n, timeout)

    def wait_idle(self, timeout=3.0):
        """出来事が片付いて、判断も喋るのも終わるまで"""
        from agent.runtime import STATE_IDLE, STATE_DEGRADED
        return wait_until(lambda: self.runtime.inbox.pending_count() == 0
                          and self.runtime.state in (STATE_IDLE, STATE_DEGRADED)
                          and not self.runtime._held, timeout)

    def utterance_rows(self):
        with self.store._lock:
            return self.store._conn.execute("SELECT text, status FROM utterances ORDER BY id").fetchall()

    def close(self):
        self.runtime.stop()
        self.runtime.join(2.0)
        self.store.close()
