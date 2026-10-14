# -*- coding: utf-8 -*-
"""
キーワード設定タブの「対象」の欄が、本物のコードのまま組み立って動くかを確かめる（画面が一瞬出る）。

⚠️ ウィジェットを書き写して組み立ててはいけない（test_gui_widgets.py と同じ理由）。App の実装をそのまま借りる。
"""
import os, sys, tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import customtkinter as ctk
import auto_reply_app as A

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


class Harness(ctk.CTk):
    """キーワード設定タブの組み立てと、ペアの保存・選択だけを見る器"""

    build_keywords_tab = A.App.build_keywords_tab
    _refresh_auto_reply_hint = A.App._refresh_auto_reply_hint
    get_manual_box_count = A.App.get_manual_box_count
    get_manual_char_limit = A.App.get_manual_char_limit
    _create_manual_send_box = A.App._create_manual_send_box
    _renumber_manual_boxes = A.App._renumber_manual_boxes
    _refresh_manual_counts = A.App._refresh_manual_counts
    _manual_boxes_over_limit = A.App._manual_boxes_over_limit
    _set_manual_send_enabled = A.App._set_manual_send_enabled
    MANUAL_OVER_COLOR = A.App.MANUAL_OVER_COLOR
    MANUAL_NORMAL_BORDER = A.App.MANUAL_NORMAL_BORDER
    # 検証したいもの
    refresh_keyword_listbox = A.App.refresh_keyword_listbox
    _selected_keyword_row = A.App._selected_keyword_row
    on_keyword_select = A.App.on_keyword_select
    _selected_keyword_target = A.App._selected_keyword_target
    _set_trigger_entry = A.App._set_trigger_entry
    on_keyword_target_selected = A.App.on_keyword_target_selected
    add_or_update_keyword = A.App.add_or_update_keyword

    def __init__(self, db):
        super().__init__()
        self.geometry("1000x800")
        self.db = db
        self.worker = A.AutoReplyWorker(db, lambda m: None)
        self.logs = []
        self.tab_keywords = ctk.CTkFrame(self)
        self.tab_keywords.pack(fill="both", expand=True)

    def append_log(self, m):
        self.logs.append(m)

    def __getattr__(self, name):
        # 今回の検証に関係しないコールバックは「何もしない関数」で足りる
        if name.startswith(("on_", "add_", "create_", "rename_", "delete_", "toggle_", "refresh_",
                            "send_", "remove_", "save_", "_entry_menu_", "_show_entry_")):
            return lambda *a, **k: None
        raise AttributeError(name)


db = A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db"))
h = Harness(db)
h.build_keywords_tab()
h.current_keyword_set_id = db.get_keyword_sets()[0]["id"]
h.keyword_set_var.set("デフォルト")
h.refresh_keyword_listbox()
h.update()

print("■ 「対象」の欄")
check("既定は「すべての文字（今まで通り）」", h.keyword_target_var.get() == "すべての文字（今まで通り）")
check("選べるもの", h.keyword_target_menu.cget("values") == list(A.KEYWORD_TARGET_LABELS.values()),
      h.keyword_target_menu.cget("values"))

print("■ お知らせの種類を選ぶと、検知ワードの欄に見出しが入って打てなくなる")
h.keyword_target_var.set("［参加したとき］")
h.on_keyword_target_selected("［参加したとき］")
check("見出しが入る", h.trigger_entry.get() == "［参加したとき］", h.trigger_entry.get())
check("打てない", h.trigger_entry.cget("state") == "disabled")
h.reply_entry.insert(0, "{名前}さん、いらっしゃい！")
h.add_or_update_keyword()
rows = {r["trigger"]: r for r in db.get_keywords_in_set(h.current_keyword_set_id)}
check("［参加したとき］として保存", rows.get("［参加したとき］", {}).get("target") == "join", rows)
check("保存したら欄を戻す（打てる・今まで通り）", h.trigger_entry.get() == "" and h.trigger_entry.cget("state") == "normal"
      and h.keyword_target_var.get() == "すべての文字（今まで通り）")

print("■ 文字で反応する対象に戻すと、見出しを消して打てるようにする")
h.keyword_target_var.set("［参加したとき］")
h.on_keyword_target_selected("［参加したとき］")
h.keyword_target_var.set("人の発言の本文だけ")
h.on_keyword_target_selected("人の発言の本文だけ")
check("見出しが消える", h.trigger_entry.get() == "")
check("打てる", h.trigger_entry.cget("state") == "normal")
h.trigger_entry.insert(0, "かわいい")
h.reply_entry.insert(0, "ありがとう")
h.add_or_update_keyword()
rows = {r["trigger"]: r for r in db.get_keywords_in_set(h.current_keyword_set_id)}
check("「人の発言の本文だけ」で保存", rows.get("かわいい", {}).get("target") == "message", rows)

print("■ 一覧の表示と、選んだときの欄")
items = list(h.keyword_listbox.get(0, "end"))
check("発言のペアに〔発言〕の印", any("〔発言〕かわいい" in t for t in items), items)
check("今まで通りのペアには印を付けない", any(t.startswith("☑ が音声ルームに参加しました") for t in items), items)
index = next(i for i, t in enumerate(items) if "［参加したとき］" in t)
h.keyword_listbox.selection_clear(0, "end")
h.keyword_listbox.selection_set(index)
h.on_keyword_select(None)
check("選ぶと対象も戻る", h.keyword_target_var.get() == "［参加したとき］")
check("お知らせの種類のペアは、検知ワードを打てない", h.trigger_entry.cget("state") == "disabled")
check("返信ワードも戻る", h.reply_entry.get() == "{名前}さん、いらっしゃい！")

print("■ 見出しを、文字で反応する対象の検知ワードとしては保存しない")
warned = []
A.messagebox.showwarning = lambda *a, **k: warned.append(a)
h.keyword_target_var.set("すべての文字（今まで通り）")
h._set_trigger_entry("［マイクをもらったとき］", editable=True)
h.reply_entry.delete(0, "end")
h.reply_entry.insert(0, "x")
h.add_or_update_keyword()
check("知らせて保存しない", warned and "［マイクをもらったとき］" not in
      {r["trigger"] for r in db.get_keywords_in_set(h.current_keyword_set_id)}, warned)

h.destroy()
print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
