# -*- coding: utf-8 -*-
"""
発言の判断（設計書/04 の 2.3）。AI に「どう動くか」だけを構造化出力で返させる（文は作らせない）。

- 型に合わない返事は1回だけ作り直しを頼み、だめなら沈黙（T8）
- 提供元が答えなかった（refusal）は再試行しない。沈黙（T9）
- 時間切れ・混雑などは1回だけ再試行（SDK の自動再試行と二重にしない。設計書/03 の 6章）
"""
from dataclasses import dataclass, replace
from typing import Optional

from .llm.base import STOP_REFUSAL, LLMError, LLMMessage
from .tools.lookup import TOOLS

SILENT = "silent"
OBSERVE = "observe"
REACT = "react"
ENGAGE = "engage"
USE_TOOL = "use_tool"
HOLD = "hold"
ACTIONS = (SILENT, OBSERVE, REACT, ENGAGE, USE_TOOL, HOLD)
SPEAKING_ACTIONS = (REACT, ENGAGE)

ACTION_LABELS = {SILENT: "沈黙", OBSERVE: "記録だけ", REACT: "短く反応", ENGAGE: "参加",
                 USE_TOOL: "ツール", HOLD: "保留"}

DECIDED_BY_RULE = "rule"
DECIDED_BY_LLM = "llm"

FAIL_REFUSED = "refused"
FAIL_SCHEMA = "schema_mismatch"

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "reason": {"type": "string", "description": "短い理由（30字以内）"},
        "urgency": {"type": "number", "minimum": 0, "maximum": 1},
        "addressed_to_ai": {"type": "boolean"},
        "target": {"type": ["string", "null"]},
        "topic": {"type": "string"},
        "mood": {"type": "string"},
        "hold_seconds": {"type": ["number", "null"]},
        # 調べる（use_tool）とき。⚠️ null を混ぜた enum は書かない（本番で通った「null を許す型」だけ）。値は parse_decision が確かめる
        "tool": {"type": ["string", "null"], "description": "use_tool のとき: wikipedia / weather"},
        "tool_query": {"type": ["string", "null"], "description": "use_tool のとき: 調べる言葉・地名"},
        # 心の中（2026-10-16 本人「考えながら話をする仕組み…いわゆる心の中」）。口に出さない
        "inner": {"type": ["string", "null"], "description": "心の中で思ったこと（口に出さない。60字以内）"},
    },
    "required": ["action", "reason"],
}

RETRY_INSTRUCTION = ("前の返事は決められた形（JSON）になっていませんでした。"
                     "決められた項目を含む JSON だけを返してください。")


@dataclass
class Decision:
    action: str
    reason: str
    decided_by: str
    turn_id: str
    urgency: float = 0.0
    target: Optional[str] = None
    hold_seconds: Optional[float] = None
    rule_id: Optional[str] = None
    model: Optional[str] = None
    topic: str = ""
    mood: str = ""
    tool: Optional[str] = None            # use_tool のとき: wikipedia / weather
    tool_query: Optional[str] = None      # use_tool のとき: 調べる言葉・地名
    inner: Optional[str] = None           # 心の中で思ったこと（口に出さない）


class DecisionFailed(Exception):
    def __init__(self, kind, detail=""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind


def parse_decision(data, turn_id, model=None):
    """AI の返事を Decision にする。型に合わなければ ValueError"""
    if not isinstance(data, dict):
        raise ValueError("JSON の形ではない")
    action = data.get("action")
    if action not in ACTIONS:
        raise ValueError(f"知らない行動: {action!r}")
    reason = data.get("reason")
    if not isinstance(reason, str):
        raise ValueError("reason が無い")
    try:
        urgency = float(data.get("urgency") or 0.0)
    except (TypeError, ValueError):
        raise ValueError("urgency が数ではない")
    hold = data.get("hold_seconds")
    if hold is not None:
        try:
            hold = min(60.0, max(1.0, float(hold)))
        except (TypeError, ValueError):
            raise ValueError("hold_seconds が数ではない")
    target = data.get("target")
    target = target.strip()[:40] if isinstance(target, str) and target.strip() else None
    tool = data.get("tool") if data.get("tool") in TOOLS else None
    query = data.get("tool_query")
    query = " ".join(query.split())[:60] if isinstance(query, str) and query.strip() else None
    return Decision(action=action, reason=reason.strip()[:60], decided_by=DECIDED_BY_LLM, turn_id=turn_id,
                    urgency=min(1.0, max(0.0, urgency)), target=target, hold_seconds=hold, model=model,
                    topic=str(data.get("topic") or "")[:40], mood=str(data.get("mood") or "")[:20],
                    tool=tool, tool_query=query,
                    inner=" ".join(data["inner"].split())[:80] if isinstance(data.get("inner"), str) and data["inner"].strip()
                    else None)


def call_llm(provider, request, cancel, on_call):
    """
    1回呼ぶ。時間切れ・混雑などは1回だけ再試行する。
    on_call(response_or_None, error_or_None) は呼ぶたびに知らせる（利用量の記録に使う）
    """
    for attempt in range(2):
        try:
            response = provider.complete(request, cancel)
        except LLMError as e:
            on_call(None, e)
            if e.retryable and attempt == 0 and not cancel.cancelled:
                if e.retry_after:
                    cancel.wait(min(10.0, e.retry_after))
                continue
            raise
        on_call(response, None)
        return response


def request_structured(provider, request, cancel, on_call, parse):
    """
    構造化出力を頼み、parse(response) で読む（型に合わなければ parse が ValueError）。
    合わなければ1回だけ作り直しを頼む。失敗は DecisionFailed / LLMError
    """
    response = call_llm(provider, request, cancel, on_call)
    for attempt in range(2):
        if response.stop == STOP_REFUSAL:
            raise DecisionFailed(FAIL_REFUSED)
        try:
            return parse(response)
        except ValueError as e:
            if attempt == 1 or cancel.cancelled:
                raise DecisionFailed(FAIL_SCHEMA, str(e))
        response = call_llm(provider, _retry_request(request, response), cancel, on_call)


def request_decision(provider, request, turn_id, cancel, on_call):
    """判断を頼む（設計書/04 の 2.3）"""
    return request_structured(provider, request, cancel, on_call,
                              lambda r: parse_decision(r.structured, turn_id, r.model))


def _retry_request(request, bad_response):
    """作り直しの依頼（前の返事を見せて、形だけ直してもらう）"""
    messages = list(request.messages)
    messages.append(LLMMessage("assistant", (bad_response.text or "")[:500]))
    messages.append(LLMMessage("user", RETRY_INSTRUCTION))
    return replace(request, messages=messages)
