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
    on_auto_reply_toggle = A.App.on_auto_reply_toggle
    _set_manual_send_enabled = A.App._set_manual_send_enabled

    MANUAL_OVER_COLOR = A.App.MANUAL_OVER_COLOR
    MANUAL_NORMAL_BORDER = A.App.MANUAL_NORMAL_BORDER
    get_manual_box_count = A.App.get_manual_box_count
    get_manual_char_limit = A.App.get_manual_char_limit
    save_manual_char_limit = A.App.save_manual_char_limit
    _create_manual_send_box = A.App._create_manual_send_box
    add_manual_send_box = A.App.add_manual_send_box
    remove_manual_send_box = A.App.remove_manual_send_box
    _renumber_manual_boxes = A.App._renumber_manual_boxes
    _refresh_manual_counts = A.App._refresh_manual_counts
    _manual_boxes_over_limit = A.App._manual_boxes_over_limit
    send_manual_box = A.App.send_manual_box
    send_manual_all = A.App.send_manual_all
    _send_manual_entries = A.App._send_manual_entries

    def __init__(self, db, worker):
        super().__init__()
        self.geometry("1000x800")
        self.db = db
        self.worker = worker
        self.logs = []
        self.tab_keywords = ctk.CTkFrame(self)
        self.tab_keywords.pack(fill="both", expand=True)

    def append_log(self, m):
        self.logs.append(m)

    def __getattr__(self, name):
        # 今回の検証に関係しないコールバックは「何もしない関数」で足りる
        # 明示的にクラス属性へ置いた本物のメソッドは、ここへ来る前に見つかる。
        # 到達するのは今回の検証に関係しないコールバックだけ。
        if name.startswith(("on_", "add_", "create_", "rename_", "delete_", "toggle_",
                            "refresh_", "_entry_menu_", "_show_entry_")):
            return lambda *a, **k: None
        raise AttributeError(name)


def fill(entry, text):
    entry["box"].delete("1.0", "end")
    entry["box"].insert("1.0", text)


db = A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db"))
worker = A.AutoReplyWorker(db, lambda m: None)
worker.is_running = True
worker.thread = type("T", (), {"is_alive": staticmethod(lambda: True)})()

app = Harness(db, worker)
app.build_keywords_tab()
app.update()

kids = descendants(app.tab_keywords)
labels = [w.cget("text") for w in kids if isinstance(w, ctk.CTkLabel)]

print("\n[1] キーワード設定タブの構成")
check("キーワード自動返信のスイッチがある", isinstance(app.auto_reply_switch, ctk.CTkSwitch))
check("スイッチはキーワードタブの中にある", app.auto_reply_switch in kids)
check("見出しは「手入力送信」", "手入力送信" in labels, labels)
check("まとめて送信ボタンがある",
      app.manual_send_all_btn.cget("text") == "📨 まとめて送信",
      app.manual_send_all_btn.cget("text"))
check("上限の入力欄がある", isinstance(app.manual_limit_entry, ctk.CTkEntry))
check("上限の既定は250", app.manual_limit_entry.get() == "250", app.manual_limit_entry.get())

print("\n[2] 入力欄が複数ある")
check("既定で3つ", len(app.manual_boxes) == 3, len(app.manual_boxes))
check("送られる順に番号が振られる",
      [e["index"].cget("text") for e in app.manual_boxes] == ["1", "2", "3"],
      [e["index"].cget("text") for e in app.manual_boxes])
check("全てキーワードタブの中にある", all(e["box"] in kids for e in app.manual_boxes))

# ⚠️ テキスト欄はexpandするので、右側の部品を後からpackすると押し出されて
#    幅がほぼ0になる。「部品は存在するのに書けない」状態は構造の検証では
#    捕まらないため、実際の幅を見る。
app.update()
widths = [e["box"].winfo_width() for e in app.manual_boxes]
check("入力欄が潰れていない", all(w > 200 for w in widths), widths)
counts_visible = [e["count"].winfo_width() for e in app.manual_boxes]
check("文字数表示が潰れていない", all(w > 10 for w in counts_visible), counts_visible)

print("\n[3] 欄の追加と削除")
app.add_manual_send_box()
app.update()
check("追加できる", len(app.manual_boxes) == 4, len(app.manual_boxes))
check("番号が振り直される",
      [e["index"].cget("text") for e in app.manual_boxes] == ["1", "2", "3", "4"])
check("欄の数が保存される",
      db.get_setting(A.MANUAL_SEND_BOX_COUNT_SETTING) == "4",
      db.get_setting(A.MANUAL_SEND_BOX_COUNT_SETTING))

app.remove_manual_send_box(app.manual_boxes[-1])
app.update()
check("削除できる", len(app.manual_boxes) == 3, len(app.manual_boxes))

while len(app.manual_boxes) > 1:
    app.remove_manual_send_box(app.manual_boxes[-1])
app.remove_manual_send_box(app.manual_boxes[0])
check("最後の1つは消せない", len(app.manual_boxes) == 1, len(app.manual_boxes))
check("消せない理由を伝える", any("1つ以上必要" in m for m in app.logs), app.logs[-1:])

while len(app.manual_boxes) < 3:
    app.add_manual_send_box()
app.update()

print("\n[4] 文字数の表示と上限の超過")
fill(app.manual_boxes[0], "あ" * 100)
app._refresh_manual_counts()
check("文字数を出す", app.manual_boxes[0]["count"].cget("text") == "100 / 250",
      app.manual_boxes[0]["count"].cget("text"))
check("上限内は灰色", app.manual_boxes[0]["count"].cget("text_color") == "gray")

fill(app.manual_boxes[0], "あ" * 251)
app._refresh_manual_counts()
check("超えたら赤くする",
      app.manual_boxes[0]["count"].cget("text_color") == A.App.MANUAL_OVER_COLOR)
check("欄の枠も赤くする",
      app.manual_boxes[0]["box"].cget("border_color") == A.App.MANUAL_OVER_COLOR)
check("超えている欄の番号を返す", app._manual_boxes_over_limit() == [1],
      app._manual_boxes_over_limit())

print("\n[5] 上限を超えたままでは送らない")
worker._manual_queue.clear()
app.logs.clear()
app.send_manual_all()
check("1件も積まない", worker._manual_queue == [], worker._manual_queue)
check("欄の中身を消さない", len(app.manual_boxes[0]["box"].get("1.0", "end-1c")) == 251)
check("どの欄が超えているか伝える",
      any("1番目の欄が上限" in m for m in app.logs), app.logs)

print("\n[6] まとめて送信は上から順に1通ずつ積む")
worker._manual_queue.clear()
app.logs.clear()
fill(app.manual_boxes[0], "1通目の本文")
fill(app.manual_boxes[1], "   ")          # 空の欄は飛ばされる
fill(app.manual_boxes[2], "3通目の本文")
app.send_manual_all()
check("空の欄を飛ばして順に積む",
      worker._manual_queue == ["1通目の本文", "3通目の本文"], worker._manual_queue)
check("送った欄は空になる",
      app.manual_boxes[0]["box"].get("1.0", "end-1c") == "",
      repr(app.manual_boxes[0]["box"].get("1.0", "end-1c")))
check("文字数表示も戻る", app.manual_boxes[0]["count"].cget("text") == "0 / 250",
      app.manual_boxes[0]["count"].cget("text"))

print("\n[7] Ctrl+Enterはその欄だけ送る")
worker._manual_queue.clear()
fill(app.manual_boxes[1], "この欄だけ")
app.manual_boxes[1]["box"].focus_set()
app.manual_boxes[1]["box"].event_generate("<Control-Return>")
app.update()
check("その欄だけ積まれる", worker._manual_queue == ["この欄だけ"], worker._manual_queue)

print("\n[8] 上限の設定")
app.manual_limit_entry.delete(0, "end")
app.manual_limit_entry.insert(0, "１００")     # 全角でも受け付ける
app.save_manual_char_limit()
check("全角の数字を受け付ける", app.get_manual_char_limit() == 100, app.get_manual_char_limit())
app.manual_limit_entry.delete(0, "end")
app.manual_limit_entry.insert(0, "あいう")
app.save_manual_char_limit()
check("数字でなければ元に戻す", app.get_manual_char_limit() == 100, app.get_manual_char_limit())
check("戻したことを伝える", any("数字で入力" in m for m in app.logs), app.logs[-1:])
app.manual_limit_entry.delete(0, "end")
app.manual_limit_entry.insert(0, "250")
app.save_manual_char_limit()

print("\n[9] スイッチの説明文と保存")
app.auto_reply_var.set(True);  app._refresh_auto_reply_hint()
on_text = app.auto_reply_hint.cget("text")
app.auto_reply_var.set(False); app._refresh_auto_reply_hint()
off_text = app.auto_reply_hint.cget("text")
check("ONとOFFで文言が変わる", on_text != off_text, (on_text, off_text))
check("OFFのとき☑が保たれると伝える", "保たれ" in off_text, off_text)

app.auto_reply_var.set(False); app.on_auto_reply_toggle()
check("OFFにすると有効キーワードが空になる", db.get_active_keywords() == {})
app.auto_reply_var.set(True); app.on_auto_reply_toggle()
check("ONに戻すと有効キーワードが戻る", db.get_active_keywords() != {})

print("\n[10] 送信欄の有効・無効")
app._set_manual_send_enabled(False)
check("停止中は押せない", app.manual_send_all_btn.cget("state") == "disabled")
check("停止中は案内が出る", "監視を開始" in app.manual_send_hint.cget("text"))
app._set_manual_send_enabled(True)
check("監視中は押せる", app.manual_send_all_btn.cget("state") == "normal")
check("監視中は案内を消す", app.manual_send_hint.cget("text") == "")

app.destroy()
print("\n" + "=" * 50)
if FAILS:
    print(f"FAILED {len(FAILS)}件: {FAILS}")
    sys.exit(1)
print("すべて通りました")
