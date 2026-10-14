# -*- coding: utf-8 -*-
"""
設定タブの「🤖 AI API」区画（入力欄・👁・保存・削除・接続確認）が、本物のコードのまま組み立って動くかを確かめる。
画面が一瞬出る。設計書/05「3. AI API キーの入力と保存」。

⚠️ ウィジェットを書き写して組み立ててはいけない（test_gui_widgets.py と同じ理由）。App の実装をそのまま借りる。
⚠️ キーはテスト用の作り物。
"""
import os, sys, tempfile, time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import customtkinter as ctk
import auto_reply_app as A
from agent import api_keys as K
from agent import llm as L
from agent.llm.base import KIND_AUTH
from agent.llm.mock import MockProvider

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


class Harness(ctk.CTk):
    """AI API の区画だけを組み立てる器。検証したいメソッドは本物を借りる"""

    AI_API_KEY_MASK = A.App.AI_API_KEY_MASK
    build_ai_api_section = A.App.build_ai_api_section
    _selected_ai_provider = A.App._selected_ai_provider
    _set_ai_key_reveal = A.App._set_ai_key_reveal
    _refresh_ai_api_status = A.App._refresh_ai_api_status
    on_ai_provider_selected = A.App.on_ai_provider_selected
    save_ai_api_key = A.App.save_ai_api_key
    delete_ai_api_key = A.App.delete_ai_api_key
    test_ai_api_connection = A.App.test_ai_api_connection
    _on_ai_api_test_done = A.App._on_ai_api_test_done

    def __init__(self, db):
        super().__init__()
        self.geometry("900x400")
        self.db = db
        self.api_keys = K.ApiKeyStore(db, env={})
        # ⚠️ 伏せ字にする前の文をそのまま記録する。ボットのコードがキーをログへ渡していないことを確かめるため
        self.raw_logs = []
        self.posted = []
        self.frame = ctk.CTkFrame(self)
        self.frame.pack(fill="both", expand=True)

    def append_log(self, message):
        self.raw_logs.append(message)

    def _post_to_ui(self, callback):
        self.posted.append(callback)      # ワーカーから届いた用件。テストが取り出して実行する

    def _show_entry_context_menu(self, event):
        pass


def run_posted(h, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end and not h.posted:
        time.sleep(0.02)
    while h.posted:
        h.posted.pop(0)()
    h.update()


dialogs = []
A.messagebox.showwarning = lambda *a, **k: dialogs.append(("warning",) + a)
A.messagebox.showinfo = lambda *a, **k: dialogs.append(("info",) + a)
A.messagebox.showerror = lambda *a, **k: dialogs.append(("error",) + a)
answers = []
A.messagebox.askyesno = lambda *a, **k: (dialogs.append(("ask",) + a), answers.pop(0))[1]

FAKE_KEY = "fake-gui-key-abcdef0123456789"
path = os.path.join(tempfile.mkdtemp(), "t.db")
db = A.DatabaseManager(path)
h = Harness(db)
h.build_ai_api_section(h.frame)
h.update()

print("■ 区画の組み立て")
check("提供元は「未定」と「テスト用（模擬）」", h.ai_provider_menu.cget("values") == [p.label for p in L.PROVIDERS.values()],
      h.ai_provider_menu.cget("values"))
check("既定は「未定」", h._selected_ai_provider().provider_id == "unassigned")
check("キーの欄は「●」で隠れる", h.ai_api_key_entry.cget("show") == "●")
check("未定では接続確認を押せない", h.ai_api_test_btn.cget("state") == "disabled")
check("状態は「未保存」と、接続確認ができない理由", "未保存" in h.ai_api_status_label.cget("text")
      and "提供元が決まると" in h.ai_api_status_label.cget("text"), h.ai_api_status_label.cget("text"))

print("■ 👁 は押している間だけ見せる")
h._set_ai_key_reveal(True)
check("押すと見える", h.ai_api_key_entry.cget("show") == "")
h._set_ai_key_reveal(False)
check("離すと隠れる", h.ai_api_key_entry.cget("show") == "●")

print("■ 保存（未定のまま、手元のキーを保存しておける）")
h.ai_api_key_entry.insert(0, FAKE_KEY)
h.save_ai_api_key()
check("保存したら欄を空にする", h.ai_api_key_entry.get() == "")
check("状態は「保存済み」", "保存済み" in h.ai_api_status_label.cget("text"), h.ai_api_status_label.cget("text"))
check("DB には暗号文だけ", db.get_setting("ai_api_key.unassigned", "").startswith(K.DPAPI_PREFIX)
      and FAKE_KEY not in db.get_setting("ai_api_key.unassigned", ""))
check("ログに保存したことを出す（キーは出さない）", any("暗号化して保存しました" in m for m in h.raw_logs)
      and all(FAKE_KEY not in m for m in h.raw_logs), h.raw_logs)
check("状態の表示にキーの一部も出さない", FAKE_KEY[-4:] not in h.ai_api_status_label.cget("text"))

print("■ 形の悪いキーは保存しない")
dialogs.clear()
h.ai_api_key_entry.insert(0, "abc def")
h.save_ai_api_key()
check("知らせる", dialogs and dialogs[-1][0] == "warning", dialogs)
check("保存済みのキーは変わらない", h.api_keys.load("unassigned") == FAKE_KEY)
h.ai_api_key_entry.delete(0, "end")

print("■ 提供元を切り替えると、その提供元の状態になる")
h.ai_provider_var.set("テスト用（模擬）")
h.on_ai_provider_selected("テスト用（模擬）")
check("選んだ提供元を覚える", db.get_setting("ai_api_provider") == "mock")
check("模擬には保存していないので「未保存」", "未保存" in h.ai_api_status_label.cget("text"))
check("模擬は接続確認を押せる", h.ai_api_test_btn.cget("state") == "normal")

print("■ 接続確認（模擬）")
dialogs.clear()
h.test_ai_api_connection()
check("キーが無ければ知らせて、確認しない", dialogs and dialogs[-1][0] == "info" and not h.posted, dialogs)
h.ai_api_key_entry.insert(0, FAKE_KEY)
h.test_ai_api_connection()
check("確認中は押せない", h.ai_api_test_btn.cget("state") == "disabled")
run_posted(h)
check("「つながりました」を表示", "つながりました" in h.ai_api_status_label.cget("text"), h.ai_api_status_label.cget("text"))
check("終わったら押せる", h.ai_api_test_btn.cget("state") == "normal")
original = L.PROVIDERS["mock"]
L.PROVIDERS["mock"] = L.ProviderInfo("mock", original.label, None,
                                     lambda key: MockProvider(key, behavior=KIND_AUTH), original.note)
h.test_ai_api_connection()
run_posted(h)
check("認証の失敗を表示", "キーが違うようです" in h.ai_api_status_label.cget("text"), h.ai_api_status_label.cget("text"))
L.PROVIDERS["mock"] = original
check("接続確認でもキーをログに出さない", all(FAKE_KEY not in m for m in h.raw_logs), h.raw_logs[-2:])
h.ai_api_key_entry.delete(0, "end")

print("■ 削除")
h.ai_provider_var.set(L.PROVIDERS["unassigned"].label)
h.on_ai_provider_selected(L.PROVIDERS["unassigned"].label)
answers.append(False)
h.delete_ai_api_key()
check("「いいえ」なら消さない", h.api_keys.load("unassigned") == FAKE_KEY)
answers.append(True)
h.delete_ai_api_key()
check("「はい」なら消す", h.api_keys.load("unassigned") is None and "未保存" in h.ai_api_status_label.cget("text"))
dialogs.clear()
h.delete_ai_api_key()
check("保存が無ければ、そう知らせる", dialogs and dialogs[-1][0] == "info", dialogs)

print("■ 最後に: ログのどこにもキーが無い")
check("ログ全体", all(FAKE_KEY not in m for m in h.raw_logs), h.raw_logs)

h.destroy()
print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
