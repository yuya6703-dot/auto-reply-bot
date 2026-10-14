# -*- coding: utf-8 -*-
"""
テスト用（模擬）の提供元。通信しない。保存と接続確認の流れを試すため・テストのため。
"""
from .base import KIND_OK, PingResult


class MockProvider:
    name = "mock"

    def __init__(self, api_key, behavior=KIND_OK):
        # behavior: 接続確認で返す結果の種類（テストで失敗の表示を確かめるときに変える）
        self._has_key = bool(api_key)
        self.behavior = behavior

    def ping(self, timeout_seconds=10.0):
        return PingResult(ok=self.behavior == KIND_OK, kind=self.behavior)
