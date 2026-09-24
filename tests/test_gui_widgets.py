# -*- coding: utf-8 -*-
"""
キーワード設定タブが本物のコードのまま組み立つかを確かめる。

⚠️ ウィジェットを書き写して組み立ててはいけない。それでは本体を変えても
   テストが通り続ける。App の実装をそのまま借りて呼ぶこと。
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

def descendants(widget):
    out = []
    for child in widget.winfo_children():
        out.append(child)
        out.extend(descendants(child))
    return out


class Harness(ctk.CTk):
    """UIの組み立てだけを見るための器。検証したいメソッドは本物を借りる"""

    # ここが本体。書き写さず、Appの実装をそのまま使う
    build_keywords_tab = A.App.build_keywords_tab
    _refresh_auto_reply_hint = A.App._refresh_auto_reply_hint
    _set_manual_send_enabled = A.App._set_manual_send_enabled
    on_auto_reply_toggle = A.App.on_auto_reply_toggle

    def __init__(self, db):
        super().__init__()
        self.geometry("900x700")
        self.db = db
        self.logs = []
        self.tab_keywords = ctk.CTkFrame(self)
        self.tab_keywords.pack(fill="both", expand=True)

    def append_log(self, m):
        self.logs.append(m)

    def __getattr__(self, name):
        # 今回の検証に関係しないコールバックは「何もしない関数」で足りる
        if name.startswith(("on_", "create_", "rename_", "delete_", "add_", "send_",
                            "toggle_", "refresh_", "_entry_menu_", "_show_entry_")):
            return lambda *a, **k: None
        raise AttributeError(name)


db = A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db"))
app = Harness(db)
app.build_keywords_tab()
app.update()

kids = descendants(app.tab_keywords)
labels = [w.cget("text") for w in kids if isinstance(w, ctk.CTkLabel)]

print("\n[1] キーワード設定タブに両方が置かれている")
check("キーワード自動返信のスイッチがある", isinstance(app.auto_reply_switch, ctk.CTkSwitch))
check("手入力送信の入力欄がある", isinstance(app.manual_send_box, ctk.CTkTextbox))
check("送信ボタンがある", isinstance(app.manual_send_btn, ctk.CTkButton))
check("スイッチはキーワードタブの中にある", app.auto_reply_switch in kids)
check("入力欄はキーワードタブの中にある", app.manual_send_box in kids)
check("見出しは「手入力送信」", "手入力送信" in labels, labels)
check("古い「手入力して送る」が残っていない", "手入力して送る" not in labels, labels)

print("\n[2] スイッチの説明文が切り替わる")
app.auto_reply_var.set(True);  app._refresh_auto_reply_hint()
on_text = app.auto_reply_hint.cget("text")
app.auto_reply_var.set(False); app._refresh_auto_reply_hint()
off_text = app.auto_reply_hint.cget("text")
check("ONとOFFで文言が変わる", on_text != off_text, (on_text, off_text))
check("OFFのとき☑が保たれると伝える", "保たれ" in off_text, off_text)

print("\n[3] スイッチを操作すると設定が保存される")
app.auto_reply_var.set(False); app.on_auto_reply_toggle()
check("OFFが保存される", db.get_setting(A.KEYWORD_AUTO_REPLY_SETTING) == "0")
check("OFFにすると有効キーワードが空になる", db.get_active_keywords() == {})
app.auto_reply_var.set(True); app.on_auto_reply_toggle()
check("ONが保存される", db.get_setting(A.KEYWORD_AUTO_REPLY_SETTING) == "1")
check("ONに戻すと有効キーワードが戻る", db.get_active_keywords() != {})

print("\n[4] 送信欄の有効・無効")
app._set_manual_send_enabled(False)
check("停止中は押せない", app.manual_send_btn.cget("state") == "disabled")
check("停止中は案内が出る", "監視を開始" in app.manual_send_hint.cget("text"))
app._set_manual_send_enabled(True)
check("監視中は押せる", app.manual_send_btn.cget("state") == "normal")
check("監視中は案内を消す", app.manual_send_hint.cget("text") == "")

print("\n[5] 複数行とCtrl+Enter")
app.manual_send_box.insert("1.0", "1行目\n2行目")
check("改行を保って読み出せる",
      app.manual_send_box.get("1.0", "end-1c") == "1行目\n2行目",
      repr(app.manual_send_box.get("1.0", "end-1c")))

fired = []
app.send_manual_text = lambda: fired.append(1)
app.manual_send_box.focus_set()
app.manual_send_box.event_generate("<Control-Return>")
app.update()
check("Ctrl+Enterで送信が呼ばれる", fired == [1], fired)

app.destroy()
print("\n" + "=" * 50)
if FAILS:
    print(f"FAILED {len(FAILS)}件: {FAILS}")
    sys.exit(1)
print("すべて通りました")
