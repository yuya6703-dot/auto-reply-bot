# -*- coding: utf-8 -*-
"""
長期記憶ファイル（2026-10-16 本人「アカウント別にチャットした会話の内容を長期記憶ファイルに保存して欲しい」）。

本人の決定: 自分のアカウントごと＋相手ごと / 会話の全文と要約の両方 / 読めるファイル（メモ帳で開ける）。

    AIの記憶/
      <自分のアカウント名>/
        会話の記録/2026-10-16.md   … その日の全文（ルーム全体。出来事が届いた順）
        相手/<相手の名前>.md        … 覚えていること（要約。整理のたびに書き直す）＋その人の発言とAIの返事
        この場とAI自身.md           … この場の記憶・AIが言ったこと（要約）

⚠️ 他の人の発言の全文を長く残す。本人がスイッチをONにしたときだけ書く（既定OFF）。このPCの中だけ。リポジトリに入れない（.gitignore）。
   自動では消さない（本人が読む・消すためのファイル）。
⚠️ 書くのはエージェントのスレッドだけ（同時に書かない）。名前はファイル名に使えない文字を「_」にする。
"""
import os
import re
import time
from collections import OrderedDict

from ..events import KIND_CHAT_MESSAGE, KIND_CHAT_NOTICE, SOURCE_GRAVITY, clean_name
from .recall import same_person

FOLDER_NAME = "AIの記憶"
UNKNOWN_ACCOUNT = "アカウント不明"
SUMMARY_HEAD = "## 覚えていること"
LOG_HEAD = "## 会話の記録"
SUMMARY_NOTE = "（AIの要約。整理のたびに書き直します。印象は推定で、事実ではありません）"
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_NAME = 40
MAX_REMEMBERED_EVENTS = 2000


def safe_name(name, fallback="名前不明"):
    """ファイル・フォルダの名前に使える形にする（Windows で使えない文字を「_」に。末尾の点・空白は除く）"""
    name = _BAD_CHARS.sub("_", (name or "").strip())[:MAX_NAME].rstrip(". ")
    return name or fallback


class ConversationJournal:
    def __init__(self, root_dir, enabled_getter, clock=time.time):
        self.root = root_dir
        self._enabled = enabled_getter      # () -> bool（本人がONにしているか）
        self._clock = clock
        self._last_day = {}                 # ファイルごとに、最後に書いた日の見出し
        # 書いた出来事。⚠️ 保留（HOLD）から戻った出来事は、もう一度 _process に来る。同じ行を2度書かない
        self._written = OrderedDict()

    @property
    def enabled(self):
        try:
            return bool(self._enabled())
        except Exception:
            return False

    # --- 場所 ---
    def account_dir(self, account):
        return os.path.join(self.root, safe_name(account, UNKNOWN_ACCOUNT))

    def partner_path(self, account, name):
        """相手のファイル。名前が切れて出ても、前に作った同じ人のファイルを使う"""
        folder = os.path.join(self.account_dir(account), "相手")
        name = clean_name(name) or "名前不明"
        if os.path.isdir(folder):
            for file in os.listdir(folder):
                stem = file[:-3] if file.endswith(".md") else file
                if same_person(name, stem):
                    return os.path.join(folder, file)
        return os.path.join(folder, safe_name(name) + ".md")

    # --- 書く ---
    def _append(self, path, line, header=None, day_heading=False):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if new and header:
                f.write(header)
            if day_heading:
                day = time.strftime("%Y-%m-%d", time.localtime(self._clock()))
                if self._last_day.get(path) is None and not new:
                    self._last_day[path] = self._last_heading(path)
                if self._last_day.get(path) != day:
                    f.write(f"\n### {day}\n")
                    self._last_day[path] = day
            f.write(line + "\n")

    @staticmethod
    def _last_heading(path):
        try:
            with open(path, encoding="utf-8") as f:
                heads = [line[4:].strip() for line in f if line.startswith("### ")]
            return heads[-1] if heads else None
        except OSError:
            return None

    def _partner_header(self, account, name):
        return (f"# {name} との会話\n\n（自分のアカウント: {account or UNKNOWN_ACCOUNT}）\n\n"
                f"{SUMMARY_HEAD}\n{SUMMARY_NOTE}\n\n- （まだありません）\n\n{LOG_HEAD}\n")

    def record_events(self, events):
        """GRAVITY のチャットの新しい行を書く（その日の全文と、相手ごと）。起動前からあった行は書かない"""
        if not self.enabled:
            return
        for e in events:
            if e.source != SOURCE_GRAVITY or e.backlog or e.event_id in self._written:
                continue
            self._written[e.event_id] = True
            while len(self._written) > MAX_REMEMBERED_EVENTS:
                self._written.popitem(last=False)
            account = e.meta.get("account") or ""
            stamp = time.strftime("%H:%M", time.localtime(e.observed_at))
            text = (e.text or "").replace("\n", " / ")
            if e.kind == KIND_CHAT_NOTICE:
                line = f"- {stamp} （お知らせ）{text}"
            else:
                mark = "（自分）" if e.is_self else ""
                line = f"- {stamp} {clean_name(e.speaker) or '名前不明'}{mark}: {text}"
            day_file = os.path.join(self.account_dir(account), "会話の記録",
                                    time.strftime("%Y-%m-%d", time.localtime(e.observed_at)) + ".md")
            self._append(day_file, line, header=f"# 会話の記録（{account or UNKNOWN_ACCOUNT}）"
                                                f" {time.strftime('%Y-%m-%d', time.localtime(e.observed_at))}\n\n")
            if e.kind == KIND_CHAT_MESSAGE and not e.is_self and e.speaker:
                name = clean_name(e.speaker)
                path = self.partner_path(account, name)
                self._append(path, line, header=self._partner_header(account, name), day_heading=True)

    def record_reply(self, account, target, text, channel, ai_name=""):
        """
        AI の発言を書く。声で答えたときはチャット欄に出ないので、その日の全文にも書く
        （チャットに書いたときは、送った文がチャット欄に出たところで自分の発言として書かれる）
        """
        if not self.enabled:
            return
        stamp = time.strftime("%H:%M", time.localtime(self._clock()))
        how = "声" if channel == "voice" else "チャット"
        line = f"- {stamp} {ai_name or 'AI'}（AI・{how}）: {(text or '').replace(chr(10), ' / ')}"
        if channel == "voice":
            day_file = os.path.join(self.account_dir(account), "会話の記録",
                                    time.strftime("%Y-%m-%d", time.localtime(self._clock())) + ".md")
            self._append(day_file, line, header=f"# 会話の記録（{account or UNKNOWN_ACCOUNT}）"
                                                f" {time.strftime('%Y-%m-%d', time.localtime(self._clock()))}\n\n")
        if target:
            name = clean_name(target)
            path = self.partner_path(account, name)
            self._append(path, line, header=self._partner_header(account, name), day_heading=True)

    def write_summaries(self, account, summary):
        """
        要約（MemoryKeeper.summary_for_files）を、相手のファイルの「覚えていること」と「この場とAI自身.md」に書き直す。
        会話の記録の部分には触らない
        """
        if not self.enabled or not summary:
            return
        for name, lines in (summary.get("people") or {}).items():
            path = self.partner_path(account, name)
            if not os.path.exists(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(self._partner_header(account, name))
            self._replace_summary(path, lines)
        room_path = os.path.join(self.account_dir(account), "この場とAI自身.md")
        os.makedirs(os.path.dirname(room_path), exist_ok=True)
        with open(room_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# この場とAI自身（{account or UNKNOWN_ACCOUNT}）\n\n{SUMMARY_NOTE}\n\n")
            f.write("\n".join(summary.get("room") or ["- （まだありません）"]) + "\n")

    @staticmethod
    def _replace_summary(path, lines):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        body = "\n".join(lines or ["- （まだありません）"])
        block = f"{SUMMARY_HEAD}\n{SUMMARY_NOTE}\n\n{body}\n\n"
        start, end = text.find(SUMMARY_HEAD), text.find(LOG_HEAD)
        if start == -1 or end == -1 or end < start:
            text = text.rstrip("\n") + "\n\n" + block + LOG_HEAD + "\n"      # 形が崩れていたら、後ろに足す
        else:
            text = text[:start] + block + text[end:]
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
