# -*- coding: utf-8 -*-
"""
エージェントの設定（設計書/04 の 2.2・7.2、06 の 10章）。

保存は既存の settings 表（app_data.db）。キー名は "agent." で始める（設計書/07 の 1章）。
⚠️ ここに機密（APIキーなど）を入れない。キーは api_keys.py が暗号文で持つ。
既定値は設計書の「既定の案」。実際の場で調整する（要検証）。
"""
import json
import re
from dataclasses import dataclass, field, fields

SETTING_PREFIX = "agent."

# 応答のしかた（2026-10-15 本人「チャットモードと音声応答モードを切り替えられるように」）
OUTPUT_VOICE = "voice"        # 声で答える（PCのスピーカーだけ。ルームへは流さない）
OUTPUT_CHAT = "chat"          # GRAVITYのチャットに書き込む（既存の手入力送信の待ち行列を通す。送るのは監視ワーカーだけ）
# 声で答えて、読み上げの出力先（VB-CABLE などからルームへ）に流す（2026-10-16 本人「連携してる読み上げツール…で話す仕組みにしたい」）。
# ⚠️ ルームの全員に聞こえる。本人が選んだときだけ（選ぶときに確かめる）
OUTPUT_VOICE_ROOM = "voice_room"
OUTPUT_MODES = (OUTPUT_VOICE, OUTPUT_VOICE_ROOM, OUTPUT_CHAT)
CHAT_APPROVE = "approve"      # 下書きを見せて、本人が「送る」を押したら送る（既定）
CHAT_AUTO = "auto"            # 確かめずに送る（本人が選んだときだけ）
CHAT_SEND_MODES = (CHAT_APPROVE, CHAT_AUTO)
NAME_SEPARATORS = re.compile(r"[、,，/／]")
NAMES_MAX_CHARS = 60
IGNORED_MAX_CHARS = 300
WAIT_TEXT_MAX_CHARS = 40
# GRAVITYのアカウントごとの設定（呼ばれ方・オーナーの名前）。{アカウント名: {"ai_name": ..., "owner_names": ...}}
ACCOUNT_PROFILES_SETTING = SETTING_PREFIX + "account_profiles"
PROFILE_KEYS = ("ai_name", "owner_names")


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
    ignored_people: str = ""               # 反応しない人の表示名（「、」で区切って複数）。荒らしなどに付き合わない（2026-10-16）
    settle_seconds: float = 2.5            # 最後の出来事からこれだけ静かになったら、まとめて判断する
    inbox_max: int = 100                   # 受付箱の上限
    min_gap_after_speaking: float = 8.0    # R6: 自分が喋り終わってから、これだけは自分から話さない
    max_utterances_per_minute: int = 2     # R7
    max_utterances_per_hour: int = 30      # R7
    max_decisions_per_minute: int = 6      # R10: 判断の呼び出しの頻度
    daily_call_limit: int = 300            # R8: AI を呼ぶ回数の1日の上限（会話の判断・文作り）
    # 裏の仕事（声を文字にする・整理・1日のまとめ・自己分析の読み込み）の1日の上限。会話の分とは別に数える
    # （2026-10-16: 文字起こしが続くと、会話の返事に使う分が早く尽きていた）。費用の上限は全部まとめて1つ
    background_daily_call_limit: int = 300
    daily_cost_limit_usd: float = 1.0      # R8: 費用の見積もりの1日の上限（米ドル）。8割で知らせる
    monthly_cost_limit_usd: float = 10.0   # R8: 1か月の上限
    model: str = ""                        # 使うモデル（空なら提供元の既定）
    output_mode: str = OUTPUT_VOICE        # 応答のしかた（声 / チャット）
    chat_send_mode: str = CHAT_APPROVE     # チャットに送る前に確かめるか
    chat_max_per_minute: int = 1           # R7（チャット）: 声より厳しく（設計書/06 の 9章）
    chat_max_per_hour: int = 20
    chat_approval_seconds: float = 60.0    # 下書きを見せておく時間。過ぎたら捨てる
    # 特定の人にチャットで返すときは、文の頭に「@名前 」を付ける（2026-10-16 本人「特定の誰かにチャットで返信する場合メンションするように」）
    chat_mention: bool = True
    # チャットで気持ちを絵文字で表す（2026-10-16 本人「チャットで感情を出す時、絵文字で表現する仕組みあったらいいかも」）。
    # 付けるかどうか・どれにするかは AI に任せる（コードで足すと、控えた判断を上書きしてしまう）
    chat_emoji: bool = True
    # 呼ばれたときは、判断と文を1回で頼む（AIを呼ぶのが2回→1回。2026-10-16 本人「応答遅いの気になる」→「それもやろう」）。
    # 呼ばれていないときは今まで通り判断だけ先に頼む（黙るなら文を作らない＝費用がかからない）
    combined_when_addressed: bool = True
    # 話しかけられたら続けて話す（2026-10-16 本人「間を空けなくても連続して会話できるように…たくさん話したい人からしたら寂しい」）。
    # 呼ばれて返すとき・話している相手に返すときだけ、ふだんの上限（チャットは1分1通）より多く返す。連投に見えないよう最低3秒あける
    conversation_enabled: bool = True
    conversation_max_per_minute: int = 4
    conversation_max_per_hour: int = 60
    conversation_min_gap_seconds: float = 3.0
    conversation_partner_seconds: float = 90.0    # 返事をした相手は、このあいだ「話している相手」（名前を呼ばれなくても返す）
    # 考え中のつなぎ言葉（2026-10-16 本人「考えてる最中にあーとか、えーととかをいうとか、うーんとかもね」）。
    # 声で答えるときに、呼ばれて返事を作るのに時間がかかったら、先に短く言う。チャットでは言わない
    thinking_fillers: bool = True
    filler_after_seconds: float = 2.0
    # 返さなかったら、相手がどう思うかを心の中で考えて、少しあとでもう一度考える（2026-10-22 本人「無視した場合のこと考えて
    # 相手はこう考えるかもしれないと、心の中で考え、再度返すべきか考える機能欲しい」）。同じ発言は1回だけ・1分に1回まで
    reconsider_enabled: bool = True
    reconsider_seconds: float = 15.0
    reconsider_gap_seconds: float = 60.0
    # オーナーにチャットで「タスクして」と頼まれたら、「📋 タスクをこなす」をして、終わったらルームに戻る（2026-10-24 本人「作る」）
    owner_tasks_enabled: bool = True
    filler_words: str = "えーと、うーん、あー、んーと"
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
    # 長期記憶ファイル（GRAVITYのアカウントごと＋相手ごとに、会話の全文と要約を読めるファイルに残す。既定OFF。2026-10-16）
    journal_enabled: bool = False
    digest_enabled: bool = False                  # 1日のまとめを作る（ファイルがONのとき。AIを1日1回呼ぶ。既定OFF）
    # オーナーの自己分析を読む・気づいたことを書き足す（既定OFF。フォルダは本人が選ぶ。リポジトリに書かない）
    owner_profile_enabled: bool = False
    owner_profile_dir: str = ""
    recall_past_lines: int = 6                    # 話しかけてきた人との前のやりとりを、ファイルから何行まで渡すか（ファイルがONのとき）
    returning_after_days: float = 3.0             # これだけ間が空いて来た人は「久しぶり」（会話を覚えるがONのとき）
    # 頼まれたら調べる（Wikipedia・天気。既定OFF。2026-10-16 本人「調べるからちょっと待っててね…チャットの中の話ね」）
    lookup_enabled: bool = False
    lookup_wait_text: str = "ちょっと調べるね、待ってて！"   # 調べる前に出す一言（空なら出さない）。⚠️ 下書きを見せる設定でも確かめずに送る（本人の決定）
    lookup_max_per_hour: int = 10
    lookup_timeout_seconds: float = 8.0
    # ウェブ検索・ニュース（Tavily。キーを保存したときだけ）は1日の上限も持つ。無料は毎月1,000回 → 1日30回なら月に収まる
    web_search_max_per_day: int = 30
    # 声を聞く（PC の音声入力。iPad など。既定OFF。2026-10-16 本人「iPad mini 6から音を拾う仕組み」→「1から6まで」の6）
    hearing_enabled: bool = False
    hearing_device: str = ""                      # 音声入力の名前（MME）
    hearing_threshold: float = 0.02               # これより大きい音を「話している」とみる（0〜1）
    hearing_max_minutes_per_hour: float = 10.0    # 1時間に文字にする量の上限（BGM で上限まで使い切らないように）
    hearing_hints: str = ""                       # 聞き取りのヒント（よく出る名前・言葉。「、」で区切る）。文字にするときに渡す
    # オーナーのマイク（任意）。ここで聞いた声は「オーナーの声」（声でもオーナーの合図が効く。2026-10-16）
    hearing_owner_device: str = ""
    # GRAVITYのアカウントごとの設定（2026-10-16 本人「全部やろうか」）。空の項目は共通の設定を使う
    account_profiles: dict = field(default_factory=dict)
    active_account: str = ""                      # 今チャットしている GRAVITY のアカウント（エージェントが入れる）
    active_account_named: bool = False            # そのアカウントの名前が分かっているか（「本体のGRAVITY」などの仮の呼び名でない）
    self_voice: str = ""                          # 今の AI の声（キャラ名・スタイル。エージェントが入れる。自分の声を知る）
    hearing_active: bool = False                  # 今ルームの声を聞いているか（画面が入れる。AI が「聞こえていない声」を聞こえたと言わないように）
    # 「声で答える（ルームへ）」なのに AI のマイクがミュートのときは、チャットで返す（2026-10-16 本人「マイクをミュートにしていることをAIが把握できるように」）
    mute_fallback_chat: bool = True
    react_max_chars: int = 40              # C2: 短い反応の上限（声）
    engage_max_chars: int = 120            # C2: 参加の上限（声）
    chat_react_max_chars: int = 60         # C2: チャットの短い反応の上限（チャットは読むので声より長くてよい）
    # C2: チャットの参加の上限。GRAVITY の入力欄はふつうの文字で150字まで（超えた分は切られる。2026-10-24 実測）、メンションは文の後ろに「@名前 」で
    #     付くので、その分を残す（2026-10-24 本人「まかせる」で200→120。これまでのAIの発言の最長は95字）
    chat_engage_max_chars: int = 120
    hold_max_seconds: float = 30.0         # 保留した出来事は、これより古くなったら記録だけにする
    addressed_hold_max_seconds: float = 90.0   # 呼ばれた出来事は、回数の上限が空くまで長めに待つ（1分の上限を待てるように）
    ignore_words: list = field(default_factory=list)   # R9: これだけの出来事は判断しない
    banned_words: list = field(default_factory=list)   # C3: これを含む文は喋らない
    decide_timeout_seconds: float = 20.0
    degraded_after_failures: int = 3       # 続けてこの回数失敗したら AI を呼ばない状態へ
    degraded_check_seconds: float = 60.0   # AI を呼ばない状態で、回復を確かめる間隔

    # 画面で変える項目
    EDITABLE = ("ai_name", "self_names", "owner_names", "ignored_people", "daily_call_limit", "daily_cost_limit_usd",
                "monthly_cost_limit_usd", "model", "output_mode", "chat_send_mode", "initiative_enabled",
                "conversation_enabled", "chat_mention", "chat_emoji", "thinking_fillers", "mute_fallback_chat",
                "reconsider_enabled", "owner_tasks_enabled",
                "memory_enabled", "impressions_enabled", "relationships_enabled", "journal_enabled",
                "lookup_enabled", "lookup_wait_text", "digest_enabled", "hearing_enabled", "hearing_device",
                "hearing_threshold", "hearing_hints", "hearing_owner_device", "owner_profile_enabled",
                "owner_profile_dir")

    def profile_value(self, key):
        """今のアカウントの設定（無い・空なら共通の設定）"""
        profile = self.account_profiles.get(self.active_account) if self.active_account else None
        value = (profile or {}).get(key) or ""
        return value or getattr(self, key)

    @property
    def ai_names(self):
        """呼ばれ方のリスト（最初のものが、AIが自分を名乗るときの名前）。アカウントごとの設定があればそちら"""
        return split_names(self.profile_value("ai_name"))

    @property
    def display_name(self):
        names = self.ai_names
        return names[0] if names else ""

    @property
    def self_name_list(self):
        """自分のアカウント名（設定の名前＋今チャットしているアカウントの名前が分かっていればそれも）"""
        names = split_names(self.self_names)
        if self.active_account_named and self.active_account and self.active_account not in names:
            names.append(self.active_account)
        return names

    @property
    def ignored_name_list(self):
        return split_names(self.ignored_people)

    @property
    def owner_name_list(self):
        return split_names(self.profile_value("owner_names"))

    @property
    def call_names(self):
        """呼ばれたかを見る名前（呼ばれ方＋アカウント名。メンションはアカウント名で来る）"""
        names = list(self.ai_names)
        for name in self.self_name_list:
            if name not in names:
                names.append(name)
        return names

    def limits_for(self, strong):
        """(1分の上限, 1時間の上限, 前の発言から空ける秒数)。呼ばれた・話している相手なら会話の上限（ふだんより多い）"""
        per_minute, per_hour = self.utterance_limits
        if strong and self.conversation_enabled:
            # 間を空けるのはチャットだけ（連投に見えないように）。声は喋っている時間がそのまま間になる
            gap = self.conversation_min_gap_seconds if self.output_mode == OUTPUT_CHAT else 0.0
            return (max(per_minute, self.conversation_max_per_minute), max(per_hour, self.conversation_max_per_hour), gap)
        return per_minute, per_hour, 0.0

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
        config.ignored_people = config.ignored_people.strip()[:IGNORED_MAX_CHARS]
        config.hearing_hints = config.hearing_hints.strip()[:IGNORED_MAX_CHARS]
        config.lookup_wait_text = " ".join(config.lookup_wait_text.split())[:WAIT_TEXT_MAX_CHARS]
        config.account_profiles = load_account_profiles(get_setting)
        return config

    def save(self, save_setting):
        for name in self.EDITABLE:
            value = getattr(self, name)
            save_setting(SETTING_PREFIX + name, ("1" if value else "0") if isinstance(value, bool) else str(value))


def load_account_profiles(get_setting):
    """アカウントごとの設定を読む。壊れていたら空（共通の設定だけを使う）"""
    try:
        data = json.loads(get_setting(ACCOUNT_PROFILES_SETTING, "") or "{}")
    except (TypeError, ValueError):
        return {}
    profiles = {}
    for account, profile in (data.items() if isinstance(data, dict) else []):
        if isinstance(profile, dict) and account:
            values = {k: str(profile.get(k) or "").strip()[:NAMES_MAX_CHARS] for k in PROFILE_KEYS}
            if any(values.values()):
                profiles[str(account)] = values
    return profiles


def save_account_profiles(save_setting, profiles):
    save_setting(ACCOUNT_PROFILES_SETTING, json.dumps(profiles, ensure_ascii=False))
