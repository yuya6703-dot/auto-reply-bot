# -*- coding: utf-8 -*-
"""
AI API アダプターの共通の型（設計書/05_アダプター設計書.md「2. AI API アダプター」）。

段階1では「接続確認（ping）」だけを使った。段階3で、判断と文章生成のための送受信の型（LLMRequest・LLMResponse）と
失敗の種類（LLMError）を足した。ツールの型は、ツールを使う段階で足す（先回りして作らない。設計書/09 の約束）。
"""
from dataclasses import dataclass, field
from typing import Optional, Protocol

# 失敗の種類（設計書/05 の LLMError.kind と同じ名前）
KIND_OK = "ok"
KIND_AUTH = "auth"                  # キーが違う・権限が無い
KIND_TIMEOUT = "timeout"
KIND_NETWORK = "network"
KIND_RATE_LIMITED = "rate_limited"
KIND_SERVER = "server"
KIND_BAD_REQUEST = "bad_request"
KIND_BILLING = "billing"            # 前払いの残高が無い・支払いの設定（やり直しても通らない）
KIND_CANCELLED = "cancelled"
KIND_UNKNOWN = "unknown"

# 再試行してよい種類（設計書/03 の 6章。再試行はこの層で1回まで）
RETRYABLE_KINDS = frozenset({KIND_TIMEOUT, KIND_NETWORK, KIND_RATE_LIMITED, KIND_SERVER})

# 画面に出す文。⚠️ キーや、相手が返した文をそのまま入れない
PING_MESSAGES = {
    KIND_OK: "つながりました。",
    KIND_AUTH: "キーが違うようです（認証に失敗しました）。",
    KIND_TIMEOUT: "時間内に応答がありませんでした。",
    KIND_NETWORK: "つながりませんでした（ネットワークを確かめてください）。",
    KIND_RATE_LIMITED: "使いすぎの制限に当たりました。少し待ってから試してください。",
    KIND_SERVER: "提供元の側で問題が起きているようです。少し待ってから試してください。",
    KIND_BILLING: "支払いの設定（前払いの残高など）を確かめてください。",
    KIND_UNKNOWN: "確認できませんでした。",
}

# 返事が止まった理由
STOP_END = "end"
STOP_MAX_TOKENS = "max_tokens"
STOP_REFUSAL = "refusal"            # 安全上の理由で答えなかった（再試行しない）
STOP_OTHER = "other"

PURPOSE_DECIDE = "decide"
PURPOSE_GENERATE = "generate"
PURPOSE_SUMMARIZE = "summarize"
PURPOSE_DIGEST = "digest"          # 1日のまとめ（2026-10-16）
PURPOSE_PING = "ping"


@dataclass(frozen=True)
class PingResult:
    ok: bool
    kind: str

    @property
    def message(self):
        return PING_MESSAGES.get(self.kind, PING_MESSAGES[KIND_UNKNOWN])


@dataclass
class LLMMessage:
    role: str                              # "user" / "assistant"
    content: str


@dataclass
class LLMRequest:
    purpose: str                           # decide / generate / summarize / ping（費用の集計に使う）
    system: str
    messages: list
    response_schema: Optional[dict] = None   # 構造化出力（JSON Schema）
    max_output_tokens: int = 1024
    timeout_seconds: float = 20.0
    extras: dict = field(default_factory=dict)   # 提供元固有の指定
    # 模擬の AI とテストが見る手がかり（今回の出来事・行動・相手など）。
    # ⚠️ 本物の提供元のアダプターは使わない・送らない。AI に渡すのは system と messages だけ
    hints: dict = field(default_factory=dict)


@dataclass
class LLMUsage:
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None


@dataclass
class LLMResponse:
    text: Optional[str]
    structured: Optional[dict]             # response_schema に合わせて読んだもの（読めなければ None）
    stop: str
    usage: LLMUsage
    provider: str
    model: str
    latency_ms: int = 0


class LLMError(Exception):
    """AI の呼び出しの失敗。⚠️ 文にキーや相手の返した文を入れない（ログに出るため）"""

    def __init__(self, kind, detail="", retry_after=None):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.retry_after = retry_after

    @property
    def retryable(self):
        return self.kind in RETRYABLE_KINDS


class LLMProvider(Protocol):
    """提供元ごとのアダプター"""

    name: str

    def ping(self, timeout_seconds: float = 10.0) -> PingResult:
        """費用の小さい方法で、キーで接続できるかを確かめる"""
        ...

    def complete(self, request: LLMRequest, cancel) -> LLMResponse:
        """送って返事を受け取る。失敗は LLMError。cancel が立ったら結果を捨ててよい"""
        ...
