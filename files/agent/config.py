# -*- coding: utf-8 -*-
"""
エージェントの設定（設計書/04 の 2.2・7.2、06 の 10章）。

保存は既存の settings 表（app_data.db）。キー名は "agent." で始める（設計書/07 の 1章）。
⚠️ ここに機密（APIキーなど）を入れない。キーは api_keys.py が暗号文で持つ。
既定値は設計書の「既定の案」。実際の場で調整する（要検証）。
"""
from dataclasses import dataclass, field, fields

SETTING_PREFIX = "agent."


@dataclass
class AgentConfig:
    ai_name: str = ""                      # 呼ばれる名前（含まれていたら R6 を越えて判断する。強い合図）
    settle_seconds: float = 2.5            # 最後の出来事からこれだけ静かになったら、まとめて判断する
    inbox_max: int = 100                   # 受付箱の上限
    min_gap_after_speaking: float = 8.0    # R6: 自分が喋り終わってから、これだけは自分から話さない
    max_utterances_per_minute: int = 2     # R7
    max_utterances_per_hour: int = 30      # R7
    max_decisions_per_minute: int = 6      # R10: 判断の呼び出しの頻度
    daily_call_limit: int = 300            # R8: AI を呼ぶ回数の1日の上限
    daily_cost_limit_usd: float = 1.0      # R8: 費用の見積もりの1日の上限（米ドル）。8割で知らせる
    monthly_cost_limit_usd: float = 10.0   # R8: 1か月の上限
    model: str = ""                        # 使うモデル（空なら提供元の既定）
    react_max_chars: int = 40              # C2: 短い反応の上限
    engage_max_chars: int = 120            # C2: 参加の上限
    hold_max_seconds: float = 30.0         # 保留した出来事は、これより古くなったら記録だけにする
    ignore_words: list = field(default_factory=list)   # R9: これだけの出来事は判断しない
    banned_words: list = field(default_factory=list)   # C3: これを含む文は喋らない
    decide_timeout_seconds: float = 20.0
    degraded_after_failures: int = 3       # 続けてこの回数失敗したら AI を呼ばない状態へ
    degraded_check_seconds: float = 60.0   # AI を呼ばない状態で、回復を確かめる間隔

    # 画面で変える項目
    EDITABLE = ("ai_name", "daily_call_limit", "daily_cost_limit_usd", "monthly_cost_limit_usd", "model")

    @classmethod
    def load(cls, get_setting):
        """get_setting(key, default) -> str。読めない値は既定のまま"""
        config = cls()
        for f in fields(cls):
            if f.name not in cls.EDITABLE:
                continue
            raw = get_setting(SETTING_PREFIX + f.name, None)
            if raw is None or raw == "":
                continue
            current = getattr(config, f.name)
            try:
                value = type(current)(raw) if not isinstance(current, str) else str(raw)
            except (TypeError, ValueError):
                continue
            setattr(config, f.name, value)
        config.daily_call_limit = max(0, config.daily_call_limit)
        config.daily_cost_limit_usd = max(0.0, config.daily_cost_limit_usd)
        config.monthly_cost_limit_usd = max(0.0, config.monthly_cost_limit_usd)
        config.ai_name = config.ai_name.strip()[:20]
        return config

    def save(self, save_setting):
        for name in self.EDITABLE:
            save_setting(SETTING_PREFIX + name, str(getattr(self, name)))
