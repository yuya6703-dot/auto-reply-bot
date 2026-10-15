# -*- coding: utf-8 -*-
"""
AI の利用量（設計書/08 の 6章）。AI を呼ぶたびに agent_data.db の usage_records に残し、1日の回数を数える。

費用の見積もりは「値段の表 × トークン数」。値段は提供元・モデルごとに手で入れる（自動では取れない）。
段階3は模擬だけなので値段は0。費用の上限は、実際の提供元が決まる段階4で足す（設計書/09 の S4）。
⚠️ 見積もりであって請求額ではない。
"""
import time

# 100万トークンあたりの値段（円）。{(提供元, モデル): (入力, 出力)}。段階4で提供元が決まったら足す
PRICES_PER_MILLION_YEN = {}


def estimate_cost(provider, model, input_tokens, output_tokens):
    price = PRICES_PER_MILLION_YEN.get((provider, model))
    if not price:
        return 0.0
    return ((input_tokens or 0) * price[0] + (output_tokens or 0) * price[1]) / 1_000_000


def local_day_start(now):
    """その日（このPCの時刻）の0時の UNIX 秒"""
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


class UsageTracker:
    def __init__(self, store, clock=time.time):
        self._store = store
        self._clock = clock

    def record(self, provider_name, purpose, turn_id, response=None, error=None):
        if response is not None:
            usage = response.usage
            cost = estimate_cost(response.provider, response.model, usage.input_tokens, usage.output_tokens)
            self._store.add_usage(response.provider, response.model, purpose, usage.input_tokens,
                                  usage.output_tokens, usage.cached_input_tokens, cost, True, None, turn_id)
        else:
            kind = getattr(error, "kind", "unknown")
            self._store.add_usage(provider_name, None, purpose, None, None, None, 0.0, False, kind, turn_id)

    def today(self):
        """(今日 AI を呼んだ回数, 今日の費用の見積もり)"""
        return self._store.usage_since(local_day_start(self._clock()))
