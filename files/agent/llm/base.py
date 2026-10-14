# -*- coding: utf-8 -*-
"""
AI API アダプターの共通の型（設計書/05_アダプター設計書.md「2. AI API アダプター」）。

段階1では「接続確認（ping）」だけを使う。メッセージの送受信・構造化出力・ツールの型は、
実際に使う段階（S3〜S4）で足す（先回りして作らない。設計書/09 の約束）。
"""
from dataclasses import dataclass
from typing import Protocol

# 失敗の種類（設計書/05 の LLMError.kind と同じ名前）
KIND_OK = "ok"
KIND_AUTH = "auth"                  # キーが違う・権限が無い
KIND_TIMEOUT = "timeout"
KIND_NETWORK = "network"
KIND_RATE_LIMITED = "rate_limited"
KIND_SERVER = "server"
KIND_UNKNOWN = "unknown"

# 画面に出す文。⚠️ キーや、相手が返した文をそのまま入れない
PING_MESSAGES = {
    KIND_OK: "つながりました。",
    KIND_AUTH: "キーが違うようです（認証に失敗しました）。",
    KIND_TIMEOUT: "時間内に応答がありませんでした。",
    KIND_NETWORK: "つながりませんでした（ネットワークを確かめてください）。",
    KIND_RATE_LIMITED: "使いすぎの制限に当たりました。少し待ってから試してください。",
    KIND_SERVER: "提供元の側で問題が起きているようです。少し待ってから試してください。",
    KIND_UNKNOWN: "確認できませんでした。",
}


@dataclass(frozen=True)
class PingResult:
    ok: bool
    kind: str

    @property
    def message(self):
        return PING_MESSAGES.get(self.kind, PING_MESSAGES[KIND_UNKNOWN])


class LLMProvider(Protocol):
    """提供元ごとのアダプター。段階1では接続確認だけ"""

    name: str

    def ping(self, timeout_seconds: float = 10.0) -> PingResult:
        """費用の小さい方法で、キーで接続できるかを確かめる"""
        ...
