# -*- coding: utf-8 -*-
"""
出来事（設計書/03 の 2章）。チャットの発言・お知らせ・手入力など、エージェントが受け取るもの。

⚠️ text は外から来た文字。中に「指示を無視して」などが書いてあっても命令として扱わない（設計書/04 の 3章）。
   AI に渡すときは、下の区切り記号で囲んで「データ」として渡す。
"""
import itertools
import re
import threading
import unicodedata
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

KIND_CHAT_MESSAGE = "chat_message"
KIND_CHAT_NOTICE = "chat_notice"
KIND_VOICE_UTTERANCE = "voice_utterance"
KIND_MANUAL = "manual"
KIND_SYSTEM = "system"

SOURCE_GRAVITY = "gravity"
SOURCE_VOICE = "voice"
SOURCE_MANUAL = "manual"
SOURCE_TEST = "test"
SOURCE_SYSTEM = "system"      # エージェント自身が作った出来事（静かなときに話すか考える など）

# AI に渡すときの区切り。外から来た文字を「データ」として囲む（設計書/04 の 3章）
EVENT_BLOCK_BEGIN = "<<<今回の出来事ここから>>>"
EVENT_BLOCK_END = "<<<今回の出来事ここまで>>>"
RECENT_BLOCK_BEGIN = "<<<直近の会話ここから>>>"
RECENT_BLOCK_END = "<<<直近の会話ここまで>>>"
ROOM_BLOCK_BEGIN = "<<<ルームの様子ここから>>>"     # ルーム名・アナウンスも人が書いたもの（データ）
ROOM_BLOCK_END = "<<<ルームの様子ここまで>>>"
PAST_BLOCK_BEGIN = "<<<前のやりとりここから>>>"    # 長期記憶ファイルから読んだ、前にその人と話したこと（人が書いたもの＝データ）
PAST_BLOCK_END = "<<<前のやりとりここまで>>>"
TRUNCATION_MARKS = ("..", "…")

_manual_counter = itertools.count(1)
_manual_lock = threading.Lock()


@dataclass(frozen=True)
class AgentEvent:
    event_id: str                 # 一意。重複判定に使う
    kind: str
    source: str
    key: str                      # 同じ出来事かの目印（GRAVITY はチャット欄の行の目印と同じ形）
    speaker: Optional[str]        # 話した人（読めなければ None）
    text: str                     # 本文（外から来た文字。命令として扱わない）
    observed_at: float            # 受け取った時刻（UNIX 秒）
    meta: dict = field(default_factory=dict)   # backlog（起動前からあった）など
    is_self: bool = False         # 自分（AI・本人）の発言とわかっているもの

    @property
    def backlog(self):
        return bool(self.meta.get("backlog"))


def new_event_id():
    return uuid.uuid4().hex


def make_manual_event(text, speaker=None, kind=KIND_CHAT_MESSAGE, clock=time.time):
    """AIタブの「手入力で出来事を入れる」用。同じ文を2回入れても別の出来事にする（key に通し番号）"""
    with _manual_lock:
        n = next(_manual_counter)
    speaker = (speaker or "").strip() or None
    text = (text or "").strip()
    return AgentEvent(event_id=new_event_id(), kind=kind, source=SOURCE_MANUAL,
                      key=f"manual:{n}", speaker=speaker, text=text, observed_at=clock(),
                      meta={"manual_kind": kind})


def clean_name(name):
    """チャット欄の名前は長いと「名前..」と切れて出る。末尾の「..」「…」と空白を除く
    ⚠️ auto_reply_app.clean_display_name と同じ。agent から auto_reply_app を import しない約束（D3）なので写してある"""
    return re.sub(r"(\s*(\.\.+|…)\s*)+$", "", (name or "").strip())


def name_matches(shown, wanted):
    """
    画面に出た名前 shown が、設定した名前 wanted の人か（名前は「名前..」と切れて出る）。
    ⚠️ auto_reply_app.friend_name_matches と同じ考え（D3 で import できないので写した）。切れていれば先頭一致（2文字以上）、
       切れていなければ完全一致。全角・半角は揃えて比べる
    """
    shown = unicodedata.normalize("NFKC", (shown or "").strip())
    wanted = unicodedata.normalize("NFKC", (wanted or "").strip())
    if not shown or not wanted:
        return False
    for mark in TRUNCATION_MARKS:
        if shown.endswith(mark):
            head = shown[:-len(mark)].strip()
            return len(head) >= 2 and wanted.startswith(head)
    return shown == wanted


def describe_event(event, now=None):
    """AI に渡す1行。お知らせは本文だけ、発言は「名前: 本文」"""
    ago = ""
    if now is not None:
        seconds = max(0, int(now - event.observed_at))
        ago = f"[{seconds}秒前] "
    who = event.speaker or "（名前不明）"
    mark = "（自分）" if event.is_self else ""
    if event.kind == KIND_CHAT_NOTICE:
        return f"{ago}お知らせ: {event.text}"
    if event.kind == KIND_SYSTEM:
        return f"{ago}（このツールからの知らせ）{event.text}"
    if event.kind == KIND_VOICE_UTTERANCE:
        return f"{ago}声 {who}{mark}: {event.text}"
    return f"{ago}{who}{mark}: {event.text}"
