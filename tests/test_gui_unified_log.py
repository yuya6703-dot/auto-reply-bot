# -*- coding: utf-8 -*-
"""
ログを1つにまとめる（2026-10-23 本人「ログの統合して欲しい」→「1つにまとめる」）。
メインタブのログ欄に、監視・送信のログと AI の判断のログを来た順に出し、「すべて／監視・送信／AI」で絞る。
AI のログも保存する（画面の文字は伏せる。受け取った発言をそのまま書いた行は保存しない）。
⚠️ 本物のコード（App のメソッド）をそのまま借りて組み立てる。画面が一瞬出る。テストの名前・内容は作り物。
"""
import os
import sqlite3
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import customtkinter as ctk  # noqa: E402
import auto_reply_app as A  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


class Harness(ctk.CTk):
    append_log = A.App.append_log
    _append_agent_log = A.App._append_agent_log
    _add_to_unified = A.App._add_to_unified
    _log_filter_kind = A.App._log_filter_kind
    _insert_log_line = A.App._insert_log_line
    on_log_filter_changed = A.App.on_log_filter_changed
    clear_log_display = A.App.clear_log_display
    _log_inner_widget = A.App._log_inner_widget
    _on_main_thread = staticmethod(A.App._on_main_thread)
    AGENT_LOG_MAX_LINES = A.App.AGENT_LOG_MAX_LINES

    def __init__(self, db):
        super().__init__()
        self.db = db
        self._ui_queue = None
        self.auto_scroll_var = ctk.BooleanVar(value=True)
        self.unified_log = A.UnifiedLog()
        self.log_filter_var = ctk.StringVar(value="すべて")
        self.log_textbox = ctk.CTkTextbox(self, state="disabled")
        self.log_textbox.pack()
        self.agent_log_textbox = ctk.CTkTextbox(self, state="disabled")
        self.agent_log_textbox.pack()


def shown(box):
    return [line for line in box.get("1.0", "end").splitlines() if line.strip()]


db = A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db"))
h = Harness(db)
h.withdraw()

print("■ メインタブのログ欄に、監視・送信と AI の判断のログを来た順に出す")
h.append_log("▶ 監視を開始しました")
h.update()
h._append_agent_log("💬 参加:「こんばんは、たろうさん」")
h._append_agent_log("📥 [GRAVITY] たろう: やっほー")
h.append_log("✉️ 送信しました")
h.update()
lines = shown(h.log_textbox)
check("4行とも、来た順に出る", len(lines) == 4 and lines[0] == "▶ 監視を開始しました" and lines[3] == "✉️ 送信しました", lines)
check("AI の行は「🤖 時刻」で始まる（見分けられる）", lines[1].startswith("🤖 ") and "💬 参加:「こんばんは、たろうさん」" in lines[1], lines[1])
check("AIタブの判断のログにも、今まで通り出る", len(shown(h.agent_log_textbox)) == 2)

print("■ 種類で絞る")
h.log_filter_var.set("AI")
h.on_log_filter_changed()
check("AI だけ", shown(h.log_textbox) == lines[1:3], shown(h.log_textbox))
h.append_log("👀 画面の文字を読み取りました")
h.update()
check("AI だけを見ている間は、監視・送信の新しい行は出さない（ため置き場には入る）",
      shown(h.log_textbox) == lines[1:3] and "👀 画面の文字を読み取りました" in h.unified_log.lines())
h._append_agent_log("🤫 沈黙: 割り込まない")
check("AI の新しい行は出る", shown(h.log_textbox)[-1].endswith("🤫 沈黙: 割り込まない"))
h.log_filter_var.set("監視・送信")
h.on_log_filter_changed()
check("監視・送信だけ", shown(h.log_textbox) == ["▶ 監視を開始しました", "✉️ 送信しました", "👀 画面の文字を読み取りました"],
      shown(h.log_textbox))
h.log_filter_var.set("すべて")
h.on_log_filter_changed()
check("すべてに戻すと、全部が来た順に", len(shown(h.log_textbox)) == 6 and shown(h.log_textbox)[-1].endswith("割り込まない"))

print("■ AI のログも保存する（画面の文字は伏せる・受け取った発言の行は保存しない）")
with sqlite3.connect(db.db_name) as c:
    saved = [m for (m,) in c.execute("SELECT message FROM logs ORDER BY id")]
check("AI の行を保存する（🤖 で始める）", "🤖 🤫 沈黙: 割り込まない" in saved, saved)
check("「」の中（ほかの人の名前・発言）は伏せる", "🤖 💬 参加:「＊＊＊」" in saved and not any("たろうさん" in m for m in saved), saved)
check("受け取った発言をそのまま書いた行（📥）は保存しない", not any("やっほー" in m or "📥" in m for m in saved), saved)

print("■ 表示を消す")
h.clear_log_display()
h.on_log_filter_changed()
check("消したら、絞り込みを変えても前の行は出ない", shown(h.log_textbox) == [], shown(h.log_textbox))

h.destroy()
print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
