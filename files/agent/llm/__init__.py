# -*- coding: utf-8 -*-
"""
AI API の提供元の一覧。

2026-10-15 本人の決定: 提供元は「まだ決めない」。段階1では、キーを保存しておける「未定」と、
流れを試せる「テスト用（模擬）」だけを並べる。提供元が決まったら、ここに1行と llm/<提供元>.py を足す
（手順は 設計書/05 の 2.4）。
"""
from dataclasses import dataclass
from typing import Callable, Optional

from .base import PingResult, LLMProvider   # noqa: F401（外から使う）
from .mock import MockProvider


@dataclass(frozen=True)
class ProviderInfo:
    provider_id: str                       # 保存のキー名に使う（英小文字・数字・_）
    label: str                             # 画面に出す名前
    env_var: Optional[str]                 # 提供元の標準の環境変数（あれば保存したキーより優先）
    factory: Optional[Callable[[str], LLMProvider]]   # None = まだ接続確認できない
    note: str                              # 画面に添える説明


UNASSIGNED_PROVIDER_ID = "unassigned"
MOCK_PROVIDER_ID = "mock"

PROVIDERS = {
    UNASSIGNED_PROVIDER_ID: ProviderInfo(
        UNASSIGNED_PROVIDER_ID, "未定（あとで提供元を決める）", None, None,
        "提供元が決まると、接続確認ができるようになります。"),
    MOCK_PROVIDER_ID: ProviderInfo(
        MOCK_PROVIDER_ID, "テスト用（模擬）", None, MockProvider,
        "通信しません。保存と接続確認の流れを試すためのものです。"),
}
DEFAULT_PROVIDER_ID = UNASSIGNED_PROVIDER_ID


def provider_by_label(label):
    """画面の表示名から提供元を返す。わからなければ既定（未定）"""
    return next((p for p in PROVIDERS.values() if p.label == label), PROVIDERS[DEFAULT_PROVIDER_ID])


def provider_by_id(provider_id):
    return PROVIDERS.get(provider_id) or PROVIDERS[DEFAULT_PROVIDER_ID]
