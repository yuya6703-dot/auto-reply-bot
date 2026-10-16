# -*- coding: utf-8 -*-
"""
規則の関所（設計書/04 の 2.2）。AI を呼ぶ前に、規則で決まるものはここで決める（AI を呼ばずに済ませる）。

上から順に見て、当たったらそこで決める。R1（停止中）と R4（同じ出来事）は受付箱の入口で落とすので、ここには来ない。
"""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from .events import name_matches

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
    "R11": "反応しない人の発言だけ",
    "R12": "オーナーに静かにと言われている",
}

# 記号・空白だけ（R9）。文字・数字が1つも無いもの
_NO_WORD = re.compile(r"^[\W_]*$", re.UNICODE)
# チャット欄のメンションは長い名前が「@名前..」と切れて出る（2026-10-16 実物で確認）
_CUT_MENTION = re.compile(r"@([^\s@]+?)(?:\.\.+|…)")


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
    muted: bool = False                     # オーナーの合図で静かにしている（R12）
    partners: tuple = ()                    # 今話している相手（名前を呼ばれなくても呼ばれたのと同じに扱う）


@dataclass(frozen=True)
class GateResult:
    outcome: str
    rule_id: Optional[str] = None
    wait_seconds: Optional[float] = None    # HOLD のとき、いつ見直すか（None は合図が来るまで）
    strong: bool = False                    # 名前を呼ばれた（R6 を越えた）

    @property
    def reason(self):
        return RULE_TEXTS.get(self.rule_id, "")


def _norm(text):
    return unicodedata.normalize("NFKC", text or "").strip()


def mentions_name(text, names):
    """
    名前のどれかで呼ばれているか。名前そのものが入っているか、切れたメンション「@名前..」の先頭が名前と同じか。
    ⚠️ 切れた残りが1文字だと別の人の名前とも合うので、2文字以上のときだけ（friend_name_matches と同じ考え）
    """
    text = _norm(text)
    names = [n for n in (_norm(n) for n in names) if n]
    if any(name in text for name in names):
        return True
    for match in _CUT_MENTION.finditer(text):
        head = match.group(1)
        if len(head) >= 2 and any(name.lstrip("@").startswith(head) for name in names):
            return True
    return False


def is_strong_signal(event, ai_names):
    """AI が呼ばれた（自分の発言・起動前からあった行は数えない）"""
    if isinstance(ai_names, str):
        ai_names = [ai_names] if ai_names else []
    return not event.is_self and not event.backlog and mentions_name(event.text, ai_names)


def is_ignored_name(name, config):
    """反応しない人か（オーナーが AIタブで決めた名前。切れて出ても見分ける）"""
    return bool(name) and any(name_matches(name, wanted) for wanted in config.ignored_name_list)


def is_ignored(event, config):
    return not event.is_self and is_ignored_name(event.speaker, config)


def is_partner(event, partners):
    """今話している相手の発言か（AI が返事をした相手。少しのあいだ、名前を呼ばれなくても呼ばれたのと同じ）"""
    return bool(partners) and not event.is_self and bool(event.speaker) \
        and any(name_matches(event.speaker, p) for p in partners)


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
        if snap.muted:
            return GateResult(OBSERVE, "R12")
        fresh = [e for e in fresh if not is_ignored(e, c)]
        if not fresh:
            return GateResult(OBSERVE, "R11")
        strong = any(is_strong_signal(e, c.call_names) or is_partner(e, snap.partners) for e in fresh)
        if snap.listening:
            return GateResult(HOLD, "R5", None, strong)
        if not strong:
            if snap.speaking:
                return GateResult(HOLD, "R6", c.min_gap_after_speaking, strong)
            if snap.last_utterance_end is not None:
                remaining = snap.last_utterance_end + c.min_gap_after_speaking - snap.now
                if remaining > 0:
                    return GateResult(HOLD, "R6", remaining, strong)
        if not self._within_limits(snap, strong):
            # 呼ばれたときは捨てずに、1分の上限が空くまで待ってから返事する（1時間の上限なら記録だけ）。
            # 2026-10-16 実物: 返事の55秒後にまた呼ばれ、1分1通の上限で記録だけになり、返事をしないままだった
            wait = self._wait_for_limit(snap, strong)
            if strong and wait is not None:
                return GateResult(HOLD, "R7", wait, strong)
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

    def _within_limits(self, snap, strong=False):
        """
        発言の回数の上限（応答のしかたで変わる。チャットは1分に1通・1時間に20通）。
        呼ばれた・話している相手なら会話の上限（1分に4回・1時間に60回。前の発言から3秒あける）
        """
        per_minute, per_hour, gap = self.config.limits_for(strong)
        last_minute = [t for t in snap.utterance_times if snap.now - t < 60]
        last_hour = [t for t in snap.utterance_times if snap.now - t < 3600]
        recent = max(snap.utterance_times, default=None)
        if gap and recent is not None and snap.now - recent < gap:
            return False
        return len(last_minute) < per_minute and len(last_hour) < per_hour

    def _wait_for_limit(self, snap, strong=False):
        """上限が空くまでの秒数。1時間の上限に当たっていれば None（待っても空かない）"""
        per_minute, per_hour, gap = self.config.limits_for(strong)
        if len([t for t in snap.utterance_times if snap.now - t < 3600]) >= per_hour:
            return None
        waits = [0.1]
        recent = max(snap.utterance_times, default=None)
        if gap and recent is not None:
            waits.append(recent + gap - snap.now + 0.1)
        minute = sorted(t for t in snap.utterance_times if snap.now - t < 60)
        if len(minute) >= per_minute:
            waits.append(minute[len(minute) - per_minute] + 60 - snap.now + 0.5)
        return max(waits)

    def utterance_allowed(self, snap, strong=False):
        """C5: 判断の間に発言の上限を超えていないか（喋る直前にもう一度見る）"""
        return self._within_limits(snap, strong)
