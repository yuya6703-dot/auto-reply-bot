# -*- coding: utf-8 -*-
"""
エージェントの設定（設計書/04 の 2.2・7.2、06 の 10章）。

保存は既存の settings 表（app_data.db）。キー名は "agent." で始める（設計書/07 の 1章）。
⚠️ ここに機密（APIキーなど）を入れない。キーは api_keys.py が暗号文で持つ。
既定値は設計書の「既定の案」。実際の場で調整する（要検証）。
"""
import re
from dataclasses import dataclass, field, fields

SETTING_PREFIX = "agent."

# 応答のしかた（2026-10-15 本人「チャットモードと音声応答モードを切り替えられるように」）
OUTPUT_VOICE = "voice"        # 声で答える（PCのスピーカーだけ。ルームへは流さない）
OUTPUT_CHAT = "chat"          # GRAVITYのチャットに書き込む（既存の手入力送信の待ち行列を通す。送るのは監視ワーカーだけ）
OUTPUT_MODES = (OUTPUT_VOICE, OUTPUT_CHAT)
CHAT_APPROVE = "approve"      # 下書きを見せて、本人が「送る」を押したら送る（既定）
CHAT_AUTO = "auto"            # 確かめずに送る（本人が選んだときだけ）
CHAT_SEND_MODES = (CHAT_APPROVE, CHAT_AUTO)
NAME_SEPARATORS = re.compile(r"[、,，/／]")
NAMES_MAX_CHARS = 60


def split_names(raw):
    """「アイ、@アイ」のように区切って書いた名前を、重複なしのリストにする（書いた順）"""
    names = []
    for name in NAME_SEPARATORS.split(raw or ""):
        name = name.strip()
        if name and name not in names:
            names.append(name)
    return names


@dataclass
class AgentConfig:
    ai_name: str = ""                      # 呼ばれ方（「、」で区切って複数。含まれていたら R6 を越えて判断する。強い合図）
    self_names: str = ""                   # GRAVITYでのこのアカウントの表示名（「、」で区切って複数）。この名前の発言は自分の発言
    owner_names: str = ""                  # オーナー（このAIを動かしている本人）の表示名。親しく話してよい相手
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
    output_mode: str = OUTPUT_VOICE        # 応答のしかた（声 / チャット）
    chat_send_mode: str = CHAT_APPROVE     # チャットに送る前に確かめるか
    chat_max_per_minute: int = 1           # R7（チャット）: 声より厳しく（設計書/06 の 9章）
    chat_max_per_hour: int = 20
    chat_approval_seconds: float = 60.0    # 下書きを見せておく時間。過ぎたら捨てる
    # 呼ばれたときは、判断と文を1回で頼む（AIを呼ぶのが2回→1回。2026-10-16 本人「応答遅いの気になる」→「それもやろう」）。
    # 呼ばれていないときは今まで通り判断だけ先に頼む（黙るなら文を作らない＝費用がかからない）
    combined_when_addressed: bool = True
    # 静かなときに自分から話すか考える（既定OFF。外に見える動きなので本人がONにしたときだけ）
    initiative_enabled: bool = False
    initiative_quiet_seconds: float = 300.0       # これだけ誰も書かなかったら
    initiative_min_gap_seconds: float = 900.0     # 自分から考えるのは、これだけ空けて（15分に1回まで）
    initiative_activity_seconds: float = 1800.0   # 直近にやりとりがあった場だけ（誰もいない場で独り言を言わない）
    # 記憶（設計書/07。⚠️ 他の人のことを覚える。どれも本人がONにしたときだけ。既定OFF）
    memory_enabled: bool = False                  # 会話を覚える（人・この場・自分が言ったこと）
    impressions_enabled: bool = False             # 人の印象を推定する（話し方・好み。推定として。口に出さない）
    relationships_enabled: bool = False           # 関係の値（なじみ・温かさ）を持つ
    summarize_interval_seconds: float = 600.0     # 覚えることを整理する間隔（10分）
    summarize_quiet_seconds: float = 120.0        # 会話がこれだけ静かになったら、10分たっていなくても整理する
    summarize_min_lines: int = 6                  # 他の人の発言がこれだけたまってから整理する
    # 長期記憶ファイル（自分のアカウントごと＋相手ごとに、会話の全文と要約を読めるファイルに残す。既定OFF。2026-10-16）
    journal_enabled: bool = False
    react_max_chars: int = 40              # C2: 短い反応の上限（声）
    engage_max_chars: int = 120            # C2: 参加の上限（声）
    chat_react_max_chars: int = 60         # C2: チャットの短い反応の上限（チャットは読むので声より長くてよい）
    chat_engage_max_chars: int = 200       # C2: チャットの参加の上限（GRAVITYの1通は250字まで）
    hold_max_seconds: float = 30.0         # 保留した出来事は、これより古くなったら記録だけにする
    addressed_hold_max_seconds: float = 90.0   # 呼ばれた出来事は、回数の上限が空くまで長めに待つ（1分の上限を待てるように）
    ignore_words: list = field(default_factory=list)   # R9: これだけの出来事は判断しない
    banned_words: list = field(default_factory=list)   # C3: これを含む文は喋らない
    decide_timeout_seconds: float = 20.0
    degraded_after_failures: int = 3       # 続けてこの回数失敗したら AI を呼ばない状態へ
    degraded_check_seconds: float = 60.0   # AI を呼ばない状態で、回復を確かめる間隔

    # 画面で変える項目
    EDITABLE = ("ai_name", "self_names", "owner_names", "daily_call_limit", "daily_cost_limit_usd",
                "monthly_cost_limit_usd", "model", "output_mode", "chat_send_mode", "initiative_enabled",
                "memory_enabled", "impressions_enabled", "relationships_enabled", "journal_enabled")

    @property
    def ai_names(self):
        """呼ばれ方のリスト（最初のものが、AIが自分を名乗るときの名前）"""
        return split_names(self.ai_name)

    @property
    def display_name(self):
        names = self.ai_names
        return names[0] if names else ""

    @property
    def self_name_list(self):
        return split_names(self.self_names)

    @property
    def owner_name_list(self):
        return split_names(self.owner_names)

    @property
    def call_names(self):
        """呼ばれたかを見る名前（呼ばれ方＋アカウント名。メンションはアカウント名で来る）"""
        names = list(self.ai_names)
        for name in self.self_name_list:
            if name not in names:
                names.append(name)
        return names

    @property
    def utterance_limits(self):
        """(1分の上限, 1時間の上限)。応答のしかたで変わる（チャットは声より厳しい）"""
        if self.output_mode == OUTPUT_CHAT:
            return self.chat_max_per_minute, self.chat_max_per_hour
        return self.max_utterances_per_minute, self.max_utterances_per_hour

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
                if isinstance(current, bool):       # ⚠️ bool("0") は True になるので文字で見る
                    value = str(raw).strip().lower() in ("1", "true", "on", "yes")
                else:
                    value = type(current)(raw) if not isinstance(current, str) else str(raw)
            except (TypeError, ValueError):
                continue
            setattr(config, f.name, value)
        config.daily_call_limit = max(0, config.daily_call_limit)
        config.daily_cost_limit_usd = max(0.0, config.daily_cost_limit_usd)
        config.monthly_cost_limit_usd = max(0.0, config.monthly_cost_limit_usd)
        config.ai_name = config.ai_name.strip()[:NAMES_MAX_CHARS]
        if config.output_mode not in OUTPUT_MODES:
            config.output_mode = OUTPUT_VOICE
        if config.chat_send_mode not in CHAT_SEND_MODES:
            config.chat_send_mode = CHAT_APPROVE
        config.self_names = config.self_names.strip()[:NAMES_MAX_CHARS]
        config.owner_names = config.owner_names.strip()[:NAMES_MAX_CHARS]
        return config

    def save(self, save_setting):
        for name in self.EDITABLE:
            value = getattr(self, name)
            save_setting(SETTING_PREFIX + name, ("1" if value else "0") if isinstance(value, bool) else str(value))
