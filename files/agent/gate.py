# -*- coding: utf-8 -*-
"""
規則の関所（設計書/04 の 2.2）。AI を呼ぶ前に、規則で決まるものはここで決める（AI を呼ばずに済ませる）。

上から順に見て、当たったらそこで決める。R1（停止中）と R4（同じ出来事）は受付箱の入口で落とすので、ここには来ない。
"""
import re
from dataclasses import dataclass, field
from typing import Optional

PASS = "pass"          # AI に判断させる
OBSERVE = "observe"    # 記録だけ（AI を呼ばない）
HOLD = "hold"          # 今は判断しない。少し後で見直す

RULE_TEXTS = {
    "R2": "AIを呼ばない状態",
    "R3": "自分の発言・起動前からあった行だけ",
    "R5": "誰かが話している",
    "R6": "直前に自分が喋った",
    "R7": "発言の回数の上限",
    "R8": "AIを呼ぶ回数・費用の上限",
    "R9": "中身が無い・無視する言葉",
    "R10": "判断の頻度の上限",
}

# 記号・空白だけ（R9）。文字・数字が1つも無いもの
_NO_WORD = re.compile(r"^[\W_]*$", re.UNICODE)


@dataclass
class GateSnapshot:
    """関所が見る「今の様子」。エージェント本体が作って渡す"""
    now: float
    degraded: bool = False
    listening: bool = False
    speaking: bool = False
    last_utterance_end: Optional[float] = None
    utterance_times: list = field(default_factory=list)   # 自分が喋り始めた時刻
    decision_times: list = field(default_factory=list)    # AI に判断させた時刻
    calls_today: int = 0
    cost_today: float = 0.0
    cost_month: float = 0.0


@dataclass(frozen=True)
class GateResult:
    outcome: str
    rule_id: Optional[str] = None
    wait_seconds: Optional[float] = None    # HOLD のとき、いつ見直すか（None は合図が来るまで）
    strong: bool = False                    # 名前を呼ばれた（R6 を越えた）

    @property
    def reason(self):
        return RULE_TEXTS.get(self.rule_id, "")


def is_strong_signal(event, ai_name):
    """AI の名前が呼ばれた（自分の発言・起動前からあった行は数えない）"""
    return bool(ai_name) and not event.is_self and not event.backlog and ai_name in (event.text or "")


def is_meaningless(event, ignore_words):
    text = (event.text or "").strip()
    return not text or bool(_NO_WORD.match(text)) or text in ignore_words


class Gate:
    def __init__(self, config):
        self.config = config

    def check(self, events, snap):
        c = self.config
        fresh = [e for e in events if not e.is_self and not e.backlog]
        if snap.degraded:
            return GateResult(OBSERVE, "R2")
        if not fresh:
            return GateResult(OBSERVE, "R3")
        strong = any(is_strong_signal(e, c.ai_name) for e in fresh)
        if snap.listening:
            return GateResult(HOLD, "R5", None, strong)
        if not strong:
            if snap.speaking:
                return GateResult(HOLD, "R6", c.min_gap_after_speaking, strong)
            if snap.last_utterance_end is not None:
                remaining = snap.last_utterance_end + c.min_gap_after_speaking - snap.now
                if remaining > 0:
                    return GateResult(HOLD, "R6", remaining, strong)
        last_minute = [t for t in snap.utterance_times if snap.now - t < 60]
        last_hour = [t for t in snap.utterance_times if snap.now - t < 3600]
        if len(last_minute) >= c.max_utterances_per_minute or len(last_hour) >= c.max_utterances_per_hour:
            return GateResult(OBSERVE, "R7", None, strong)
        if (snap.calls_today >= c.daily_call_limit or snap.cost_today >= c.daily_cost_limit_usd
                or snap.cost_month >= c.monthly_cost_limit_usd):
            return GateResult(OBSERVE, "R8", None, strong)
        if all(is_meaningless(e, c.ignore_words) for e in fresh):
            return GateResult(OBSERVE, "R9", None, strong)
        recent = sorted(t for t in snap.decision_times if snap.now - t < 60)
        if len(recent) >= c.max_decisions_per_minute:
            return GateResult(HOLD, "R10", max(0.1, recent[0] + 60 - snap.now), strong)
        return GateResult(PASS, None, None, strong)

    def utterance_allowed(self, snap):
        """C5: 判断の間に発言の上限を超えていないか（喋る直前にもう一度見る）"""
        c = self.config
        last_minute = [t for t in snap.utterance_times if snap.now - t < 60]
        last_hour = [t for t in snap.utterance_times if snap.now - t < 3600]
        return len(last_minute) < c.max_utterances_per_minute and len(last_hour) < c.max_utterances_per_hour
