# -*- coding: utf-8 -*-
"""
AI の利用量と費用の見積もり（設計書/08 の 6章）。AI を呼ぶたびに agent_data.db の usage_records に残す。

費用の見積もりは「値段の表 × トークン数」。値段は提供元・モデルごとに手で入れる（自動では取れない）。
⚠️ 見積もりであって請求額ではない（画面にもそう書く）。値段が変わったらここを直す。
"""
import time
from datetime import date

# 100万トークンあたりの値段（米ドル）。{(提供元, モデル): [(この日から, 入力, キャッシュ済みの入力, 出力), ...]}
# 【事実: https://ai.google.dev/gemini-api/docs/pricing（2026-10-15 に確認）。有料枠の値段。出力は考えた分を含む】
PRICES_PER_MILLION_USD = {
    ("gemini", "gemini-3.5-flash-lite"): [(date(2000, 1, 1), 0.30, 0.03, 2.50)],
    ("gemini", "gemini-3.1-flash-lite"): [(date(2000, 1, 1), 0.25, 0.025, 1.50)],
    ("gemini", "gemini-3.8-flash"): [(date(2000, 1, 1), 0.75, 0.075, 3.75),
                                     (date(2027, 1, 1), 1.50, 0.15, 7.50)],
}


def _price(provider, model, on):
    table = PRICES_PER_MILLION_USD.get((provider, model))
    if not table:
        return None
    current = None
    for since, *price in table:
        if on >= since:
            current = price
    return current


def estimate_cost(provider, model, input_tokens, output_tokens, cached_tokens=0, on=None):
    """米ドルの見積もり。値段がわからないモデルは0（画面に「値段の表に無い」と出す）"""
    price = _price(provider, model, on or date.today())
    if not price:
        return 0.0
    input_price, cached_price, output_price = price
    cached = min(cached_tokens or 0, input_tokens or 0)
    fresh = (input_tokens or 0) - cached
    return (fresh * input_price + cached * cached_price + (output_tokens or 0) * output_price) / 1_000_000


def has_price(provider, model):
    return (provider, model) in PRICES_PER_MILLION_USD


def local_day_start(now):
    """その日（このPCの時刻）の0時の UNIX 秒"""
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def local_month_start(now):
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))


class UsageTracker:
    def __init__(self, store, clock=time.time):
        self._store = store
        self._clock = clock

    def record(self, provider_name, purpose, turn_id, response=None, error=None):
        if response is not None:
            usage = response.usage
            cost = estimate_cost(response.provider, response.model, usage.input_tokens, usage.output_tokens,
                                 usage.cached_input_tokens)
            self._store.add_usage(response.provider, response.model, purpose, usage.input_tokens,
                                  usage.output_tokens, usage.cached_input_tokens, cost, True, None, turn_id)
        else:
            kind = getattr(error, "kind", "unknown")
            self._store.add_usage(provider_name, None, purpose, None, None, None, 0.0, False, kind, turn_id)

    def today(self, purposes=None, exclude=None):
        """(今日 AI を呼んだ回数, 今日の費用の見積もり（米ドル）)。purposes / exclude で用途を絞る"""
        return self._store.usage_since(local_day_start(self._clock()), purposes, exclude)

    def this_month(self):
        return self._store.usage_since(local_month_start(self._clock()))
