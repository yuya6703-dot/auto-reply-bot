# -*- coding: utf-8 -*-
"""
エージェント本体（設計書/03 の 3.3・4.1・5章）。状態を持ち、受付箱 → 規則の関所 → 判断 → 文章生成 → 出す前の確認 → 音声
の順に進める。専用のスレッドを1本だけ使う（判断は1本で順番に。複数のコメントに同時に反応しない）。

- 沈黙・記録だけのときは、文章生成も音声合成も再生もしない（記録だけ残す）
- 「止める」: 新しい出来事を受け付けない。AI の結果は捨てる。喋っている文は最後まで
- 「緊急停止」: すぐ止める（AI の結果を捨て、音声も止める）。手で再開するまで何もしない
- 想定外の例外が起きても、そのまとまりを捨てて待ちに戻る（スレッドは止めない）
⚠️ 画面（tkinter）に触らない。知らせは on_log / on_notice / on_state で返す（呼ばれるのはこのスレッド）。
"""
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from typing import Callable

from .audit import AuditLog
from .cancel import CancelToken
from .context import ConversationWindow, build_decide_request, build_generate_request, max_chars_for, rules_note
from .decision import (DECIDED_BY_LLM, DECIDED_BY_RULE, ENGAGE, FAIL_REFUSED, HOLD, OBSERVE, SILENT, USE_TOOL,
                       Decision, DecisionFailed, request_decision)
from .gate import HOLD as GATE_HOLD
from .gate import OBSERVE as GATE_OBSERVE
from .gate import Gate, GateSnapshot, is_strong_signal
from .generation import CHECK_LIMIT, CHECK_STALE, CHECK_TEXTS, precheck, request_utterance
from .inbox import Inbox
from .llm.base import KIND_AUTH, KIND_BAD_REQUEST, PURPOSE_DECIDE, PURPOSE_GENERATE, LLMError
from .persona import DEFAULT_PERSONA_ID, Persona
from .usage import UsageTracker

STATE_STOPPED = "stopped"
STATE_IDLE = "idle"
STATE_GATHERING = "gathering"
STATE_LISTENING = "listening"
STATE_DECIDING = "deciding"
STATE_GENERATING = "generating"
STATE_SPEAKING = "speaking"
STATE_DEGRADED = "degraded"
STATE_EMERGENCY = "emergency_stopped"

STATE_LABELS = {
    STATE_STOPPED: "停止中",
    STATE_IDLE: "待機中",
    STATE_GATHERING: "出来事を集めている",
    STATE_LISTENING: "誰かが話している（聞いている）",
    STATE_DECIDING: "判断している",
    STATE_GENERATING: "喋る文を作っている",
    STATE_SPEAKING: "喋っている",
    STATE_DEGRADED: "AIを呼ばない状態（失敗が続いた）",
    STATE_EMERGENCY: "緊急停止中（再開を押すまで何もしない）",
}

# 喋った結果（speak の戻り値）
SPOKEN = "spoken"
SPEECH_CANCELLED = "cancelled"
SPEECH_FAILED = "failed"

RESTORE_SECONDS = 30 * 60        # 起動時に直近の窓へ戻す範囲（設計書/07 の 3章）
LLM_HOLD_DEFAULT = 5.0


@dataclass
class AgentDeps:
    provider_factory: Callable          # () -> LLMProvider（使えなければ None）
    speak: Callable                     # (Utterance, CancelToken) -> SPOKEN / SPEECH_CANCELLED / SPEECH_FAILED。鳴り終わるまで戻らない
    stop_speech: Callable               # () -> None。緊急停止で、待っている読み上げも含めて止める
    store: object                       # memory.store.AgentStore（開いたもの）
    on_log: Callable = lambda line: None        # 判断のログ（AIタブ）
    on_notice: Callable = None                  # 本人に知らせたいこと（メインのログにも）
    on_state: Callable = lambda state: None     # 状態が変わった
    on_error: Callable = lambda detail: None    # 想定外の例外（error_log.txt へ）
    clock: Callable = time.time


class AgentRuntime:
    def __init__(self, deps, config):
        self.deps = deps
        self.config = config
        self._clock = deps.clock
        self.log = AuditLog(deps.on_log, deps.on_notice)
        self.gate = Gate(config)
        self.inbox = Inbox(config.inbox_max, config.settle_seconds,
                           strong_signal=lambda e: is_strong_signal(e, self.config.ai_name))
        self.window = ConversationWindow(clock=self._clock)
        self.usage = UsageTracker(deps.store, clock=self._clock)
        self.persona = deps.store.load_persona(DEFAULT_PERSONA_ID) or Persona()

        self._lock = threading.RLock()
        self._thread = None
        self._provider = None
        self._running = False
        self._stop_flag = threading.Event()
        self._resume = threading.Event()
        self._emergency = False
        self._state = STATE_STOPPED
        self._reported_state = STATE_STOPPED

        self._listening = False
        self._speaking = False
        self._last_utterance_end = None
        self._utterance_times = []
        self._decision_times = []
        self._held = []
        self._hold_until = None
        self._llm_held_ids = set()
        self._failures = 0
        self._degraded = False
        self._next_recovery_check = 0.0
        self._limit_notified_day = None
        self._current_cancel = None
        self._speech_cancel = None

    # ================= 操作（画面のスレッドから） =================
    @property
    def state(self):
        with self._lock:
            if self._emergency:
                return STATE_EMERGENCY
            if not self._running:
                return STATE_STOPPED
            if self._state in (STATE_IDLE, STATE_GATHERING):
                if self._listening:
                    return STATE_LISTENING
                if self._degraded:
                    return STATE_DEGRADED
            return self._state

    @property
    def running(self):
        return self._running

    def start(self):
        """(始めたか, 言うこと)"""
        with self._lock:
            if self._emergency:
                return False, "緊急停止中です。「再開」を押してから始めてください。"
            if self._running:
                return False, "もう動いています。"
            provider = self.deps.provider_factory()
            if provider is None:
                return False, ("使う AI が決まっていません。設定タブの「🤖 AI API」で提供元を選んでください"
                               "（今選べるのは「テスト用（模擬）」だけです）。")
            self._provider = provider
            self._stop_flag.clear()
            self._resume.clear()
            self._failures = 0
            self._degraded = False
            self._held = []
            self._llm_held_ids = set()
            self.inbox.reopen()
            self.inbox.clear()
            self._running = True
            self._state = STATE_IDLE
            self._restore_window()
            self._thread = threading.Thread(target=self._run, name="agent-runtime", daemon=True)
            self._thread.start()
        self._report_state()
        self.log.notice(f"🤖 AIを始めました（{getattr(provider, 'name', '?')}）。")
        return True, ""

    def stop(self):
        """新しい出来事を受け付けない。AI の結果は捨てる。喋っている文は最後まで"""
        with self._lock:
            if not self._running:
                return
            self._stop_flag.set()
            self._resume.set()
            self.inbox.close()
            if self._current_cancel is not None:
                self._current_cancel.cancel()
        self.log.notice("🤖 AIを止めました。")

    def join(self, timeout=None):
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def emergency_stop(self):
        """すぐ止める。手で再開するまで何もしない（どの状態からでも）"""
        with self._lock:
            self._emergency = True
            self._resume.clear()
            self.inbox.close()
            self.inbox.clear()
            self._held = []
            if self._current_cancel is not None:
                self._current_cancel.cancel()
            if self._speech_cancel is not None:
                self._speech_cancel.cancel()
        try:
            self.deps.stop_speech()
        except Exception:
            pass
        self._report_state()
        self.log.notice("🛑 緊急停止しました。「再開」を押すまで何もしません。")

    def resume(self):
        with self._lock:
            if not self._emergency:
                return
            self._emergency = False
            if self._running:
                self.inbox.reopen()
                self._state = STATE_IDLE
            self._resume.set()
        self._report_state()
        self.log.notice("↩ 緊急停止から戻しました。" if self._running else "↩ 緊急停止を解きました（AIは止まったままです）。")

    def submit(self, event):
        """出来事を受付箱へ。受け付けたら True（止まっている・緊急停止中・同じ出来事・満杯なら False）"""
        with self._lock:
            if not self._running or self._emergency or self._stop_flag.is_set():
                return False
            ok = self.inbox.submit(event)
            if ok and self._state == STATE_IDLE:
                self._state = STATE_GATHERING
        if ok:
            self._report_state()
        return ok

    def on_voice_activity(self, speaking):
        """誰かが話し始めた/終わった（声を聞く段階で使う）。話している間は話し始めない（R5）"""
        with self._lock:
            self._listening = bool(speaking)
        if not speaking:
            self.inbox.wake()
        self._report_state()

    def today_usage(self):
        return self.usage.today()

    # ================= スレッドの中 =================
    def _set_state(self, state):
        with self._lock:
            self._state = state
        self._report_state()

    def _report_state(self):
        state = self.state
        if state != self._reported_state:
            self._reported_state = state
            try:
                self.deps.on_state(state)
            except Exception:
                pass

    def _restore_window(self):
        """再起動したら、直近30分の出来事を窓に戻す（反応はしない。T38）"""
        try:
            events = self.deps.store.recent_events(self._clock() - RESTORE_SECONDS)
        except Exception:
            events = []
        if events:
            self.window.add_events(events)

    def _run(self):
        try:
            while not self._stop_flag.is_set():
                if self._emergency:
                    self._resume.wait(0.5)
                    continue
                batch = self.inbox.next_batch(self._wait_timeout())
                if self._stop_flag.is_set():
                    break
                if self._emergency:
                    continue
                self._maybe_recover()
                events = self._take_events(batch)
                if not events:
                    self._set_state(STATE_GATHERING if self.inbox.pending_count() else STATE_IDLE)
                    continue
                try:
                    self._process(events)
                except Exception:
                    self.deps.on_error(traceback.format_exc())
                    self.log.write("⚠️ 想定外のエラーが起きました。今回の出来事は見送ります（詳細は error_log.txt）。")
                finally:
                    with self._lock:
                        self._current_cancel = None
                        self._speech_cancel = None
                        self._speaking = False
                    if not self._stop_flag.is_set() and not self._emergency:
                        self._set_state(STATE_GATHERING if self.inbox.pending_count() else STATE_IDLE)
        finally:
            with self._lock:
                self._running = False
                self._state = STATE_STOPPED
            self._report_state()

    def _wait_timeout(self):
        now = self._clock()
        waits = [1.0]
        if self._held:
            waits.append(0.5 if self._hold_until is None else self._hold_until - now)
        if self._degraded:
            waits.append(self._next_recovery_check - now)
        return max(0.05, min(waits))

    def _take_events(self, batch):
        """新しいまとまりと、保留していた出来事を合わせる"""
        now = self._clock()
        with self._lock:
            held = self._held
            release = bool(batch) or (held and (
                (self._hold_until is not None and now >= self._hold_until)
                or (self._hold_until is None and not self._listening)))
            if not release:
                return []
            self._held, self._hold_until = [], None
        expired = [e for e in held if now - e.observed_at > self.config.hold_max_seconds]
        if expired:
            turn_id = self._new_turn(expired, now, store_events=False)
            self._record(Decision(OBSERVE, "保留したまま古くなった", DECIDED_BY_RULE, turn_id))
            self.log.write(f"📝 保留していた{len(expired)}件は古くなったので、記録だけにしました。")
        return [e for e in held if e not in expired] + list(batch)

    def _new_turn(self, events, now, store_events=True):
        turn_id = uuid.uuid4().hex
        if store_events:
            self.deps.store.add_events(events, turn_id)
        self.deps.store.add_turn(turn_id, [e.event_id for e in events], now)
        return turn_id

    def _record(self, decision, outcome=None):
        self.deps.store.add_decision(decision)
        self.deps.store.close_turn(decision.turn_id, outcome or decision.action)
        self.window.add_action(decision.action)

    def _snapshot(self, now):
        calls, _cost = self.usage.today()
        with self._lock:
            return GateSnapshot(now=now, degraded=self._degraded, listening=self._listening,
                                speaking=self._speaking, last_utterance_end=self._last_utterance_end,
                                utterance_times=list(self._utterance_times),
                                decision_times=list(self._decision_times), calls_today=calls)

    def _hold(self, events, wait_seconds):
        with self._lock:
            self._held = list(events) + self._held
            self._hold_until = None if wait_seconds is None else self._clock() + wait_seconds

    def _process(self, events):
        now = self._clock()
        turn_id = self._new_turn(events, now)
        self.window.add_events(events)      # 保留から戻った出来事は、窓が同じものを2度入れない

        # --- 規則の関所（AI を呼ばない） ---
        snap = self._snapshot(now)
        result = self.gate.check(events, snap)
        if result.outcome == GATE_HOLD:
            self._hold(events, result.wait_seconds)
            self._record(Decision(HOLD, result.reason, DECIDED_BY_RULE, turn_id, rule_id=result.rule_id))
            when = f"{result.wait_seconds:.0f}秒後に見直す" if result.wait_seconds else "終わったら見直す"
            self.log.write(f"⏸ 保留（{result.rule_id} {result.reason}）— {when}")
            return
        if result.outcome == GATE_OBSERVE:
            self._record(Decision(OBSERVE, result.reason, DECIDED_BY_RULE, turn_id, rule_id=result.rule_id))
            self.log.write(f"🤫 記録だけ（{result.rule_id} {result.reason}）")
            if result.rule_id == "R8":
                self._notify_limit_once(now)
            return

        # --- AI の判断 ---
        self._set_state(STATE_DECIDING)
        cancel = CancelToken()
        with self._lock:
            self._current_cancel = cancel
            self._decision_times = [t for t in self._decision_times if now - t < 60] + [now]
        fresh_seq = self.inbox.fresh_seq
        left_minute = max(0, self.config.max_utterances_per_minute
                          - len([t for t in snap.utterance_times if now - t < 60]))
        note = rules_note(left_minute, max(0, self.config.daily_call_limit - snap.calls_today - 1))
        request = build_decide_request(events, self.window, self.persona, self.config, note, now,
                                       timeout=self.config.decide_timeout_seconds)
        try:
            decision = request_decision(self._provider, request, turn_id, cancel,
                                        self._usage_recorder(turn_id, PURPOSE_DECIDE))
        except DecisionFailed as e:
            reason = "AIが答えなかった" if e.kind == FAIL_REFUSED else "AIの返事の形が合わなかった"
            self._record(Decision(SILENT, reason, DECIDED_BY_LLM, turn_id))
            self.log.write(f"🤫 沈黙（{reason}）")
            return
        except LLMError as e:
            self._on_llm_failure(e, turn_id)
            return
        self._failures = 0
        if cancel.cancelled:
            return          # 止めた・緊急停止した。結果は捨てる
        self._record(decision)

        if decision.action in (SILENT, OBSERVE, USE_TOOL):
            reason = decision.reason + ("（ツールはまだ使えない）" if decision.action == USE_TOOL else "")
            mark = "📝 記録だけ" if decision.action == OBSERVE else "🤫 沈黙"
            self.log.write(f"{mark}: {reason}")
            return
        if decision.action == HOLD:
            ids = {e.event_id for e in events}
            if ids & self._llm_held_ids:
                self.log.write(f"🤫 沈黙: {decision.reason}（保留は1回まで）")
                return
            self._llm_held_ids |= ids
            wait = decision.hold_seconds or LLM_HOLD_DEFAULT
            self._hold(events, wait)
            self.log.write(f"⏸ 保留: {decision.reason} — {wait:.0f}秒後に見直す")
            return

        # --- 文章生成 ---
        self._set_state(STATE_GENERATING)
        request = build_generate_request(decision, events, self.window, self.persona, self.config,
                                         self._clock(), timeout=self.config.decide_timeout_seconds)
        try:
            utterance = request_utterance(self._provider, request, turn_id, cancel,
                                          self._usage_recorder(turn_id, PURPOSE_GENERATE))
        except (DecisionFailed, LLMError) as e:
            if isinstance(e, LLMError):
                self._on_llm_failure(e, turn_id, during="文を作る")
            else:
                self.log.write("🤫 沈黙（AIが文を作れなかった）")
            return
        if cancel.cancelled:
            return

        # --- 出す前の確認 ---
        check = self._precheck(utterance, decision, fresh_seq)
        if check:
            self.deps.store.add_utterance(turn_id, utterance.text, utterance.emotion, self.persona.voice,
                                          f"dropped:{check}", None, None)
            self.log.write(f"🚫 喋らない（{check} {CHECK_TEXTS[check]}）:「{utterance.text}」")
            return

        # --- 喋る ---
        self._speak(utterance, decision, turn_id)

    def _precheck(self, utterance, decision, fresh_seq):
        if self.inbox.fresh_seq != fresh_seq or self._listening:
            return CHECK_STALE
        own = [u.text for u in self.window.own_utterances()]
        check = precheck(utterance.text, max_chars_for(decision.action, self.config),
                         self.config.banned_words, own)
        if check:
            return check
        if not self.gate.utterance_allowed(self._snapshot(self._clock())):
            return CHECK_LIMIT
        return None

    def _speak(self, utterance, decision, turn_id):
        speech_cancel = CancelToken()
        started = self._clock()
        with self._lock:
            if self._emergency:
                return
            self._speech_cancel = speech_cancel
            self._speaking = True
            self._utterance_times = [t for t in self._utterance_times if started - t < 3600] + [started]
        self._set_state(STATE_SPEAKING)
        label = "🗣️ 参加" if decision.action == ENGAGE else "💬 短く反応"
        self.log.write(f"{label}:「{utterance.text}」")
        try:
            outcome = self.deps.speak(utterance, speech_cancel)
        except Exception:
            outcome = SPEECH_FAILED
        ended = self._clock()
        with self._lock:
            self._speaking = False
            self._last_utterance_end = ended
        self.window.add_own(utterance.text, started)
        self.deps.store.add_utterance(turn_id, utterance.text, utterance.emotion, self.persona.voice,
                                      outcome, started, ended)
        if outcome == SPEECH_CANCELLED:
            self.log.write("⏹ 途中で止めました。")
        elif outcome == SPEECH_FAILED:
            self.log.write("⚠️ 声にできませんでした（音声エンジンを確かめてください）。")

    def _usage_recorder(self, turn_id, purpose):
        """AI を呼ぶたびに利用量を残す（失敗した呼び出しも1回と数える）"""
        provider_name = getattr(self._provider, "name", "?")
        return lambda response, error: self.usage.record(provider_name, purpose, turn_id, response, error)

    def _on_llm_failure(self, error, turn_id, during="判断"):
        kind = error.kind
        self._record(Decision(SILENT, f"AIの呼び出しに失敗（{kind}）", DECIDED_BY_LLM, turn_id))
        if kind in (KIND_AUTH, KIND_BAD_REQUEST):
            self._enter_degraded()
            hint = "設定タブの「🤖 AI API」でAPIキーを確かめてください" if kind == KIND_AUTH else "設定を確かめてください"
            self.log.notice(f"⚠️ AIの{during}に失敗しました（{kind}）。{hint}。AIを呼ばない状態にします。")
            return
        self._failures += 1
        self.log.write(f"⚠️ AIの{during}に失敗しました（{kind}）。今回は沈黙します。")
        if self._failures >= self.config.degraded_after_failures and not self._degraded:
            self._enter_degraded()
            self.log.notice(f"⚠️ AIの呼び出しが{self._failures}回続けて失敗しました。"
                            f"{self.config.degraded_check_seconds:.0f}秒ごとに確かめて、戻ったら再開します。")

    def _enter_degraded(self):
        with self._lock:
            self._degraded = True
            self._next_recovery_check = self._clock() + self.config.degraded_check_seconds
        self._report_state()

    def _maybe_recover(self):
        if not self._degraded or self._clock() < self._next_recovery_check:
            return
        try:
            ok = self._provider.ping(timeout_seconds=10.0).ok
        except Exception:
            ok = False
        with self._lock:
            if ok:
                self._degraded = False
                self._failures = 0
            else:
                self._next_recovery_check = self._clock() + self.config.degraded_check_seconds
        if ok:
            self._report_state()
            self.log.notice("✅ AIが使えるようになりました。")

    def _notify_limit_once(self, now):
        day = time.strftime("%Y%m%d", time.localtime(now))
        if self._limit_notified_day != day:
            self._limit_notified_day = day
            self.log.notice(f"⚠️ 今日AIを呼べる回数（{self.config.daily_call_limit}回）に達しました。"
                            "明日まで、記録だけにします。")
