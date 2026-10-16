# -*- coding: utf-8 -*-
"""
長期記憶ファイル（2026-10-16 本人「アカウント別にチャットした会話の内容を長期記憶ファイルに保存して欲しい」）。

本人の決定: 自分のアカウントごと＋相手ごと / 会話の全文と要約の両方 / 読めるファイル（メモ帳で開ける）。
アカウントは GRAVITY のアカウント（本人「アカウントはアカウントでもグラビティに限ったものだからね」）。書くのも GRAVITY のチャットだけ。

    AIの記憶/
      <GRAVITYのアカウント名>/
        会話の記録/2026-10-16.md   … その日の全文（ルーム全体。出来事が届いた順）
        相手/<相手の名前>.md        … メモ（本人が書く）＋覚えていること（要約。整理のたびに書き直す）＋その人の発言とAIの返事
        この場とAI自身.md           … この場の記憶・AIが言ったこと（要約）
        まとめ/2026-10-16.md        … 1日のまとめ（AIが会話の記録から作る。スイッチがONのとき）

AI も読む（2026-10-16 本人「全部やろうか」）: 話しかけてきた人のファイルの
  - 「## メモ（自分で書く）」… 本人が書いたこと。確かなこととして使う（人間でいう、人から教わった知識）
  - 「## 会話の記録」の、今の会話より前の数行 … 前回の続きを話せるように（人間でいう、出来事の記憶＝エピソード記憶）

⚠️ 他の人の発言の全文を長く残す。本人がスイッチをONにしたときだけ書く・読む（既定OFF）。このPCの中だけ。
   リポジトリに入れない（.gitignore）。自動では消さない（本人が読む・消すためのファイル）。
⚠️ 書くのはエージェントのスレッド。名前を覚えたときの移し替えだけ監視のスレッドから来るので、鍵をかけて同時に触らない。
⚠️ 見出しは「行まるごと」で探す。チャットの発言に「## 会話の記録」と書かれても、記録の行（「- 12:00 名前: …」）の途中なので見出しにはならない。
"""
import os
import re
import shutil
import threading
import time
from collections import OrderedDict

from ..events import KIND_CHAT_MESSAGE, KIND_CHAT_NOTICE, SOURCE_GRAVITY, SOURCE_VOICE, clean_name
from .recall import same_person

FOLDER_NAME = "AIの記憶"
UNKNOWN_ACCOUNT = "アカウント不明"
MEMO_HEAD = "## メモ（自分で書く）"
MEMO_NOTE = "（ここに書いたことは、AIが確かなこととして会話に使います。AIはここを書き換えません。1行に1つ）"
SUMMARY_HEAD = "## 覚えていること"
LOG_HEAD = "## 会話の記録"
SUMMARY_NOTE = "（AIの要約。整理のたびに書き直します。印象は推定で、事実ではありません）"
EMPTY = "- （まだありません）"
ROOM_FILE = "この場とAI自身.md"
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_ENTRY = re.compile(r"^- (\d{2}):(\d{2}) (.+)$")
_DAY = re.compile(r"^### (\d{4}-\d{2}-\d{2})\s*$")
_AI_LINE = re.compile(r"^.*?（AI・(声|チャット)）: ")
MAX_NAME = 40
MAX_REMEMBERED_EVENTS = 2000
MAX_MEMO_LINES = 8
MAX_MEMO_LINE_CHARS = 100
MAX_PAST_LINE_CHARS = 120
READ_WHOLE_BYTES = 512 * 1024       # これより大きいファイルは、頭と後ろだけ読む（メモは頭、前のやりとりは後ろにある）
READ_HEAD_BYTES = 16 * 1024
READ_TAIL_BYTES = 128 * 1024


def safe_name(name, fallback="名前不明"):
    """ファイル・フォルダの名前に使える形にする（Windows で使えない文字を「_」に。末尾の点・空白は除く）"""
    name = _BAD_CHARS.sub("_", (name or "").strip())[:MAX_NAME].rstrip(". ")
    return name or fallback


def _heading(text, head):
    """見出しの行の位置（行まるごと一致するものだけ）。無ければ -1"""
    m = re.search(rf"^{re.escape(head)}[ \t]*$", text, re.M)
    return m.start() if m else -1


def _memo_block():
    return f"{MEMO_HEAD}\n{MEMO_NOTE}\n\n"


class ConversationJournal:
    def __init__(self, root_dir, enabled_getter, clock=time.time):
        self.root = root_dir
        self._enabled = enabled_getter      # () -> bool（本人がONにしているか）
        self._clock = clock
        self._lock = threading.RLock()
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
    def _append(self, path, line, header=None, day_heading=False, at=None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if new and header:
                f.write(header)
            if day_heading:
                day = time.strftime("%Y-%m-%d", time.localtime(self._clock() if at is None else at))
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
                heads = [line[4:].strip() for line in f if _DAY.match(line)]
            return heads[-1] if heads else None
        except OSError:
            return None

    def _partner_header(self, account, name):
        return (f"# {name} との会話\n\n（GRAVITYのアカウント: {account or UNKNOWN_ACCOUNT}）\n\n"
                f"{_memo_block()}{SUMMARY_HEAD}\n{SUMMARY_NOTE}\n\n{EMPTY}\n\n{LOG_HEAD}\n")

    def record_events(self, events):
        """GRAVITY のチャットの新しい行を書く（その日の全文と、相手ごと）。起動前からあった行は書かない"""
        if not self.enabled:
            return
        with self._lock:
            for e in events:
                if e.source not in (SOURCE_GRAVITY, SOURCE_VOICE) or e.backlog or e.event_id in self._written:
                    continue
                self._written[e.event_id] = True
                while len(self._written) > MAX_REMEMBERED_EVENTS:
                    self._written.popitem(last=False)
                account = e.meta.get("account") or ""
                stamp = time.strftime("%H:%M", time.localtime(e.observed_at))
                text = (e.text or "").replace("\n", " / ")
                if e.kind == KIND_CHAT_NOTICE:
                    line = f"- {stamp} （お知らせ）{text}"
                elif e.source == SOURCE_VOICE:
                    line = f"- {stamp} （声）{clean_name(e.speaker) or 'だれか'}: {text}"    # 声を聞く（誰かは分からない）
                else:
                    mark = "（自分）" if e.is_self else ""
                    line = f"- {stamp} {clean_name(e.speaker) or '名前不明'}{mark}: {text}"
                day = time.strftime("%Y-%m-%d", time.localtime(e.observed_at))
                day_file = os.path.join(self.account_dir(account), "会話の記録", day + ".md")
                self._append(day_file, line, header=f"# 会話の記録（{account or UNKNOWN_ACCOUNT}） {day}\n\n")
                if e.kind == KIND_CHAT_MESSAGE and not e.is_self and e.speaker:
                    name = clean_name(e.speaker)
                    path = self.partner_path(account, name)
                    self._append(path, line, header=self._partner_header(account, name), day_heading=True,
                                 at=e.observed_at)

    def record_reply(self, account, target, text, channel, ai_name=""):
        """
        AI の発言を書く。声で答えたときはチャット欄に出ないので、その日の全文にも書く
        （チャットに書いたときは、送った文がチャット欄に出たところで自分の発言として書かれる）
        """
        if not self.enabled:
            return
        with self._lock:
            stamp = time.strftime("%H:%M", time.localtime(self._clock()))
            how = "チャット" if channel == "chat" else "声"
            line = f"- {stamp} {ai_name or 'AI'}（AI・{how}）: {(text or '').replace(chr(10), ' / ')}"
            if channel != "chat":
                day = time.strftime("%Y-%m-%d", time.localtime(self._clock()))
                day_file = os.path.join(self.account_dir(account), "会話の記録", day + ".md")
                self._append(day_file, line, header=f"# 会話の記録（{account or UNKNOWN_ACCOUNT}） {day}\n\n")
            if target:
                name = clean_name(target)
                path = self.partner_path(account, name)
                self._append(path, line, header=self._partner_header(account, name), day_heading=True)

    def write_summaries(self, account, summary):
        """
        要約（MemoryKeeper.summary_for_files）を、相手のファイルの「覚えていること」と「この場とAI自身.md」に書き直す。
        メモ（本人が書く）と会話の記録の部分には触らない
        """
        if not self.enabled or not summary:
            return
        with self._lock:
            for name, lines in (summary.get("people") or {}).items():
                path = self.partner_path(account, name)
                if not os.path.exists(path):
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8", newline="\n") as f:
                        f.write(self._partner_header(account, name))
                self._replace_summary(path, lines)
            room_path = os.path.join(self.account_dir(account), ROOM_FILE)
            os.makedirs(os.path.dirname(room_path), exist_ok=True)
            with open(room_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(f"# この場とAI自身（{account or UNKNOWN_ACCOUNT}）\n\n{SUMMARY_NOTE}\n\n")
                f.write("\n".join(summary.get("room") or [EMPTY]) + "\n")

    @staticmethod
    def _replace_summary(path, lines):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        body = "\n".join(lines or [EMPTY])
        block = f"{SUMMARY_HEAD}\n{SUMMARY_NOTE}\n\n{body}\n\n"
        start, end = _heading(text, SUMMARY_HEAD), _heading(text, LOG_HEAD)
        if start == -1 or end == -1 or end < start:
            text = text.rstrip("\n") + "\n\n" + block + LOG_HEAD + "\n"      # 形が崩れていたら、後ろに足す
        else:
            if _heading(text, MEMO_HEAD) == -1:          # メモの欄が無い（前の形の）ファイルには、メモの欄を足す
                text = text[:start] + _memo_block() + text[start:]
                start, end = _heading(text, SUMMARY_HEAD), _heading(text, LOG_HEAD)
            text = text[:start] + block + text[end:]
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    # --- 読む（AI が会話に使う） ---
    def recall(self, account, names, before, max_lines=6):
        """
        話しかけてきた人のファイルから {"notes": メモの行, "past": 前のやりとりの行} を返す（無ければ空のもの）。
        前のやりとりは before（今の会話の窓の始まり）より前の行だけ、相手ごとに max_lines 行まで
        """
        if not self.enabled:
            return {}
        notes, past = [], []
        with self._lock:
            for name in names:
                name = clean_name(name)
                path = self.partner_path(account, name)
                if not name or not os.path.exists(path):
                    continue
                text = self._read_for_recall(path)
                notes += [f"[{name}] {line}" for line in self._memo_lines(text)]
                entries = self._past_entries(text, before)[-max(0, max_lines):] if max_lines else []
                if entries:
                    past.append(f"（{name} とのやりとり）")
                    past += entries
        out = {}
        if notes:
            out["notes"] = notes
        if past:
            out["past"] = past
        return out

    @staticmethod
    def _read_for_recall(path):
        """大きいファイルは頭（メモ）と後ろ（新しい記録）だけ読む"""
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size <= READ_WHOLE_BYTES:
                return f.read().decode("utf-8", errors="ignore")
            head = f.read(READ_HEAD_BYTES).decode("utf-8", errors="ignore")
            f.seek(size - READ_TAIL_BYTES)
            tail = f.read().decode("utf-8", errors="ignore")
        tail = tail.split("\n", 1)[-1]                 # 途中から読んだ行は捨てる
        return head + "\n" + LOG_HEAD + "\n" + tail

    @staticmethod
    def _memo_lines(text):
        start = _heading(text, MEMO_HEAD)
        if start == -1:
            return []
        lines = []
        for line in text[start:].splitlines()[1:]:
            line = line.strip()
            if line.startswith("## "):
                break
            if not line or line == MEMO_NOTE or line == EMPTY:
                continue
            line = line[2:].strip() if line.startswith(("- ", "・")) else line
            if line:
                lines.append(line[:MAX_MEMO_LINE_CHARS])
            if len(lines) >= MAX_MEMO_LINES:
                break
        return lines

    @staticmethod
    def _past_entries(text, before):
        """会話の記録の行のうち、before より前のもの（古い順）。AI の行は「あなた（声）」にする"""
        start = _heading(text, LOG_HEAD)
        if start == -1:
            return []
        day, entries = None, []
        for line in text[start:].splitlines()[1:]:
            m = _DAY.match(line)
            if m:
                day = m.group(1)
                continue
            m = _ENTRY.match(line)
            if not m or day is None:
                continue
            try:
                at = time.mktime(time.strptime(f"{day} {m.group(1)}:{m.group(2)}", "%Y-%m-%d %H:%M"))
            except ValueError:
                continue
            if at + 60 > before:            # 今の会話の窓に入っている分は渡さない（同じ行を2度渡さない）
                continue
            body = _AI_LINE.sub(lambda a: f"あなた（{a.group(1)}）: ", m.group(3))
            when = time.strftime("%m/%d %H:%M", time.localtime(at)).lstrip("0")
            entries.append(f"[{when}] {body}"[:MAX_PAST_LINE_CHARS])
        return entries

    # --- 心の中（2026-10-16） ---
    def record_thought(self, account, text):
        """AI の心の中（口に出さなかったこと）を「心の中/日付.md」に書く"""
        if not self.enabled or not text:
            return
        with self._lock:
            now = self._clock()
            day = time.strftime("%Y-%m-%d", time.localtime(now))
            path = os.path.join(self.account_dir(account), "心の中", day + ".md")
            self._append(path, f"- {time.strftime('%H:%M', time.localtime(now))} {text}",
                         header=f"# 心の中（{account or UNKNOWN_ACCOUNT}） {day}\n\n（AIが口に出さずに思ったこと）\n\n")

    # --- 1日のまとめ（2026-10-16） ---
    def day_file(self, account, day):
        return os.path.join(self.account_dir(account), "会話の記録", day + ".md")

    def digest_file(self, account, day):
        return os.path.join(self.account_dir(account), "まとめ", day + ".md")

    def day_lines(self, account, day, max_chars=8000):
        """その日の会話の記録の行（新しい方から max_chars まで）"""
        path = self.day_file(account, day)
        if not os.path.exists(path):
            return []
        with self._lock, open(path, encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f if line.startswith("- ")]
        kept, total = [], 0
        for line in reversed(lines):
            total += len(line) + 1
            if total > max_chars:
                break
            kept.append(line[2:])
        return list(reversed(kept))

    def days_without_digest(self, account, before_day, max_days=7):
        """before_day より前で、記録はあるがまとめが無い日（古い順。直近 max_days 日まで）"""
        folder = os.path.join(self.account_dir(account), "会話の記録")
        if not os.path.isdir(folder):
            return []
        days = sorted(f[:-3] for f in os.listdir(folder) if f.endswith(".md") and f[:-3] < before_day)[-max_days:]
        return [d for d in days if not os.path.exists(self.digest_file(account, d))]

    def write_digest(self, account, day, text):
        path = self.digest_file(account, day)
        with self._lock:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(f"# {day} のまとめ（{account or UNKNOWN_ACCOUNT}）\n\n"
                        "（AIが会話の記録から作ったまとめです。印象は推定で、事実ではありません）\n\n"
                        f"{text.strip()}\n")
        return path

    # --- 移す ---
    def move_account(self, old, new):
        """
        old のアカウントのフォルダを new へ移す（仮の呼び名「本体のGRAVITY」で書いたあとで、本当の名前が分かったとき）。
        new のフォルダがもうあれば、ファイルごとにまとめる（同じファイルは、old の記録を後ろに足す）
        """
        with self._lock:
            src, dst = self.account_dir(old), self.account_dir(new)
            if src == dst or not os.path.isdir(src):
                return
            if not os.path.exists(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.rename(src, dst)
            else:
                for folder, _dirs, files in os.walk(src):
                    rel = os.path.relpath(folder, src)
                    target_dir = os.path.normpath(os.path.join(dst, rel))
                    os.makedirs(target_dir, exist_ok=True)
                    for file in files:
                        source, target = os.path.join(folder, file), os.path.join(target_dir, file)
                        if not os.path.exists(target):
                            shutil.move(source, target)
                        elif file != ROOM_FILE:         # この場とAI自身は次の整理で書き直されるので、new の方を残す
                            self._merge_file(source, target, old)
                shutil.rmtree(src, ignore_errors=True)
            self._last_day.clear()

    @staticmethod
    def _merge_file(source, target, old):
        with open(source, encoding="utf-8") as f:
            text = f.read()
        start = _heading(text, LOG_HEAD)
        body = text[start:].split("\n", 1)[-1] if start != -1 else text.split("\n\n", 1)[-1]
        with open(target, "a", encoding="utf-8", newline="\n") as f:
            f.write(f"\n（ここから、名前が分かる前に「{old}」として書いた記録）\n{body.strip()}\n")
