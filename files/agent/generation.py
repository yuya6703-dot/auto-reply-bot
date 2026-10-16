# -*- coding: utf-8 -*-
"""
文章生成と、出す前の確認（設計書/04 の 2.4・4章）。

出す前の確認で落ちたら、切ったり直したりせずに沈黙する（途中で切った文は喋らない）。
"""
import difflib
import re
from dataclasses import dataclass

from .context import EMOTIONS
from .decision import SPEAKING_ACTIONS, parse_decision, request_structured

PRIORITY_AI = 50      # 音声サービスの優先度（読み上げと同じ。来た順に喋る）

# 出す前の確認で落ちた理由
CHECK_TOO_LONG = "C2"
CHECK_FORBIDDEN = "C3"
CHECK_REPEAT = "C4"
CHECK_LIMIT = "C5"
CHECK_STALE = "C1"
CHECK_TEXTS = {
    CHECK_STALE: "判断の間に新しい出来事が来た",
    CHECK_TOO_LONG: "長すぎる",
    CHECK_FORBIDDEN: "言わない言葉・個人情報らしいもの・URL",
    CHECK_REPEAT: "直前の自分の発言とほぼ同じ",
    CHECK_LIMIT: "発言の回数の上限",
}

_URL = re.compile(r"(https?://|www\.)", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\d{2,4}[-‐ー−]\d{2,4}[-‐ー−]\d{3,4}|\d{10,11}")
_POSTAL = re.compile(r"〒?\d{3}[-‐ー−]\d{4}")
_REPEAT_RATIO = 0.9


@dataclass
class Utterance:
    text: str
    emotion: str
    turn_id: str
    priority: int = PRIORITY_AI


MAX_CHAT_LINES = 3      # チャットは改行2つ（3行）まで


def tidy_text(raw, keep_newlines=False):
    """声は改行・続く空白を1つの空白に。チャットは改行を2つ（3行）まで残し、行の中の空白だけ詰める"""
    if not keep_newlines:
        return " ".join(raw.split())
    lines = [" ".join(line.split()) for line in raw.replace("\r", "").split("\n")]
    lines = [line for line in lines if line]
    if len(lines) > MAX_CHAT_LINES:
        lines = lines[:MAX_CHAT_LINES - 1] + [" ".join(lines[MAX_CHAT_LINES - 1:])]
    return "\n".join(lines)


def parse_utterance(data, turn_id, keep_newlines=False):
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        raise ValueError("text が無い")
    text = tidy_text(data["text"], keep_newlines)
    if not text:
        raise ValueError("text が空")
    emotion = data.get("emotion")
    return Utterance(text=text, emotion=emotion if emotion in EMOTIONS else "neutral", turn_id=turn_id)


def request_utterance(provider, request, turn_id, cancel, on_call, keep_newlines=False):
    """文を作ってもらう。型に合わなければ1回だけ作り直し。失敗は DecisionFailed / LLMError"""
    return request_structured(provider, request, cancel, on_call,
                              lambda r: parse_utterance(r.structured, turn_id, keep_newlines))


def request_decision_with_text(provider, request, turn_id, cancel, on_call, keep_newlines=False):
    """
    判断と文を1回で頼む（context.build_combined_request）。(Decision, Utterance または None) を返す。
    文が無い・形が合わないときは None（呼ぶ側が文だけをもう一度頼む）。判断の形が合わなければ1回だけ作り直し（DecisionFailed / LLMError）
    """
    holder = {}

    def parse(response):
        decision = parse_decision(response.structured, turn_id, response.model)
        holder["data"] = response.structured
        return decision

    decision = request_structured(provider, request, cancel, on_call, parse)
    utterance = None
    if decision.action in SPEAKING_ACTIONS:
        try:
            utterance = parse_utterance(holder.get("data"), turn_id, keep_newlines)
        except ValueError:
            utterance = None
    return decision, utterance


def precheck(text, max_chars, banned_words=(), recent_own=()):
    """出す前の確認（C2〜C4）。通れば None、落ちたら理由の番号"""
    if len(text) > max_chars:
        return CHECK_TOO_LONG
    if any(w and w in text for w in banned_words):
        return CHECK_FORBIDDEN
    if _URL.search(text) or _EMAIL.search(text) or _PHONE.search(text) or _POSTAL.search(text):
        return CHECK_FORBIDDEN
    for previous in recent_own[-1:]:
        if difflib.SequenceMatcher(None, previous, text).ratio() >= _REPEAT_RATIO:
            return CHECK_REPEAT
    return None
