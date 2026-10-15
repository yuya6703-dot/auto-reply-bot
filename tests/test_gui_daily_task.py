# -*- coding: utf-8 -*-
"""
GRAVITYのタスク・ルーレットの画面部品（メインタブのボタン、設定タブの区画）が、
本物のコードのまま組み立って動くかを確かめる。実機は使わない（画面が一瞬出る）。

⚠️ ウィジェットを書き写して組み立ててはいけない（test_gui_widgets.py と同じ理由）。
   App の実装をそのまま借りて呼ぶこと。
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


class FakeWorker:
    """is_running / is_alive / start_job / stop だけを持つ、実機につながない代役"""

    def __init__(self, running=False):
        self.is_running = running
        self.alive = running
        self.started = []
        self.stopped = False
        self.forgotten = 0

    def is_alive(self):
        return self.alive

    def start_job(self, job):
        self.started.append(job)
        self.is_running = self.alive = True
        return True

    def stop(self):
        self.stopped = True
        self.is_running = False

    def start(self, *coords):
        # 監視の開始（範囲の座標。範囲を選ばずに開始したときは全部 None）
        self.started.append(("monitor",) + coords)
        self.is_running = self.alive = True
        return True

    def forget_today(self):
        self.forgotten += 1


class Harness(ctk.CTk):
    """UIの組み立てだけを見るための器。検証したいメソッドは本物を借りる"""

    build_main_tab = A.App.build_main_tab
    build_daily_task_section = A.App.build_daily_task_section
    save_daily_task_friend = A.App.save_daily_task_friend
    save_daily_task_text = A.App.save_daily_task_text
    on_daily_task_notify_toggle = A.App.on_daily_task_notify_toggle
    forget_daily_task_today = A.App.forget_daily_task_today
    start_gravity_job = A.App.start_gravity_job
    stop_gravity_job = A.App.stop_gravity_job
    _set_gravity_job_buttons = A.App._set_gravity_job_buttons
    _watch_gravity_job = A.App._watch_gravity_job
    start_monitoring = A.App.start_monitoring
    _begin_monitoring = A.App._begin_monitoring

    def __init__(self, db):
        super().__init__()
        self.geometry("900x700")
        self.db = db
        self.logs = []
        self.last_coords = None
        self.worker = FakeWorker()
        self.task_worker = FakeWorker()
        self.tab_main = ctk.CTkFrame(self)
        self.tab_main.pack(fill="both", expand=True)
        self.settings = ctk.CTkFrame(self)
        self.settings.pack(fill="both", expand=True)

    def append_log(self, m):
        self.logs.append(m)

    # build_main_tab が組み立て時に参照するだけのもの。今回の検証には関係しない
    def stop_monitoring(self): pass
    def copy_all_log(self): pass
    def copy_log_selection(self): pass
    def select_all_log(self): pass
    def clear_log_display(self): pass
    def _show_log_context_menu(self, event): pass
    def _show_entry_context_menu(self, event): pass
    def on_emulator_auto_scroll_toggle(self): pass
    # start_monitoring が範囲選択に進んだら呼ばれる。ここまで来たら「止められなかった」
    def withdraw(self): self.logs.append("WITHDRAW")
    # _begin_monitoring が開始後に呼ぶもの。今回の検証には関係しない
    def _set_manual_send_enabled(self, enabled): pass
    def _watch_worker_state(self): pass


def state(button):
    return button.cget("state")


db = A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db"))
db.save_setting("daily_task_friend_name", "テストの相手さんです")
h = Harness(db)
h.build_main_tab()
h.build_daily_task_section(h.settings)
h.update()

print("■ メインタブのボタン")
check("「タスクをこなす」", h.daily_task_btn.cget("text") == "📋 タスクをこなす")
check("「ルーレットを回す」は別のボタン", h.roulette_btn.cget("text") == "🎡 ルーレットを回す（無料の1回）")
check("中止は最初は押せない", state(h.gravity_job_stop_btn) == "disabled")

print("■ 監視中はタスクを始めない（同じ画面を操作して混ざるため）")
h.worker.is_running = True
h.start_gravity_job(A.GravityTaskWorker.JOB_TASKS)
check("始めていない", h.task_worker.started == [], h.task_worker.started)
check("理由をログに出す", any("監視中は実行できません" in m for m in h.logs), h.logs[-1:])
h.worker.is_running = False

print("■ タスクを始めると、終わるまでボタンが押せない")
h.start_gravity_job(A.GravityTaskWorker.JOB_TASKS)
check("タスクとして始めた", h.task_worker.started == [A.GravityTaskWorker.JOB_TASKS], h.task_worker.started)
check("タスクのボタンは押せない", state(h.daily_task_btn) == "disabled")
check("ルーレットのボタンも押せない", state(h.roulette_btn) == "disabled")
check("中止は押せる", state(h.gravity_job_stop_btn) == "normal")

print("■ タスクの実行中は監視を始めない")
h.start_monitoring()
check("範囲選択に進まない", "WITHDRAW" not in h.logs)
check("理由をログに出す", any("監視を始められません" in m for m in h.logs), h.logs[-1:])

print("■ 中止 → スレッドが終わったらボタンが戻る")
h.stop_gravity_job()
check("中止を伝えた", h.task_worker.stopped)
check("中止は二度押せない", state(h.gravity_job_stop_btn) == "disabled")
h.task_worker.alive = True
h._watch_gravity_job()
check("後片付け中はまだ戻さない", state(h.daily_task_btn) == "disabled")
h.task_worker.alive = False
h._watch_gravity_job()
check("終わったら戻る", state(h.daily_task_btn) == "normal" and state(h.roulette_btn) == "normal")

print("■ ルーレットは別の仕事として始まる")
h.task_worker = FakeWorker()
h.start_gravity_job(A.GravityTaskWorker.JOB_ROULETTE)
check("ルーレットとして始めた", h.task_worker.started == [A.GravityTaskWorker.JOB_ROULETTE], h.task_worker.started)
h.task_worker.is_running = h.task_worker.alive = False
h._watch_gravity_job()

print("■ 「チャット欄で自動開始」は範囲を選ばずに監視を始める（2026-10-15）")
check("ボタンがある", h.start_auto_btn.cget("text") == "▶ チャット欄で自動開始")
h.worker = FakeWorker()
h.logs.clear()
h.start_monitoring(auto=True)
check("範囲の座標なし（全部 None）で始める", h.worker.started == [("monitor", None, None, None, None)], h.worker.started)
check("範囲選択の画面に進まない", "WITHDRAW" not in h.logs, h.logs)
check("開始のボタンは押せなくなる", state(h.start_auto_btn) == "disabled" and state(h.start_btn) == "disabled")
h.worker = FakeWorker()

print("■ 設定タブの区画")
check("送り先は保存した値が入っている", h.daily_task_friend_entry.get() == "テストの相手さんです")
check("文面の既定は「タスク」", h.daily_task_text_entry.get() == A.DEFAULT_DAILY_TASK_TEXT == "タスク")
check("お知らせの音は既定でON", h.daily_task_notify_var.get() is True)

h.daily_task_friend_entry.delete(0, "end")
h.daily_task_friend_entry.insert(0, "  別の人  ")
h.save_daily_task_friend()
check("送り先を保存（前後の空白は除く）", db.get_setting("daily_task_friend_name") == "別の人")

warnings = []
A.messagebox.showwarning = lambda *a, **k: warnings.append(a)
h.daily_task_text_entry.delete(0, "end")
h.save_daily_task_text()
check("空の文面は保存しない", db.get_setting("daily_task_text", "未保存") == "未保存" and warnings, warnings)
h.daily_task_text_entry.insert(0, "おはよう")
h.save_daily_task_text()
check("文面を保存", db.get_setting("daily_task_text") == "おはよう")

h.daily_task_notify_var.set(False)
h.on_daily_task_notify_toggle()
check("お知らせの音をOFFにできる", db.get_setting("daily_task_notify_sound") == "0")

print("■ 今日の「済み」の記録を消すボタン")
check("ボタンがある", h.daily_task_forget_btn.cget("text") == "🔄 今日の「済み」の記録を消す")
h.task_worker = FakeWorker(running=True)
h.forget_daily_task_today()
check("実行中は消さない", h.task_worker.forgotten == 0 and any("実行中は" in m for m in h.logs), h.logs[-1:])
h.task_worker = FakeWorker()
h.forget_daily_task_today()
check("止まっているときは消す", h.task_worker.forgotten == 1 and any("記録を消しました" in m for m in h.logs),
      h.logs[-1:])

print("■ アプリのアイコン（窓・ダイアログ）")
icon = A.find_app_icon()
check("アイコンのファイルが見つかる", icon is not None and icon.endswith(A.APP_ICON_FILE), icon)
# ⚠️ CustomTkinterのダイアログは、作った0.2秒後に目印を見ずに既定のアイコンで上書きする（5.2.2）。
# Windowsでは .ico で付けたアイコンを wm_iconbitmap() で読み返せない（None になる）ので、
# iconbitmap が呼ばれた順を記録し、上書きの時間を過ぎた後で「最後に付いたもの」を見る。
import time


class RecordedToplevel(ctk.CTkToplevel):
    """
    iconbitmap が呼ばれた順を、窓を作った瞬間から記録するダイアログ。
    ⚠️ 作った後でメソッドを差し替えてはいけない。CTkToplevel は作る途中（タイトルバーの色を変えるところ）で
       自分で update() を呼ぶので、作るのに0.2秒以上かかると、0.2秒後の上書きが作る途中で先に走ってしまう。
       後から差し替えた記録には何も残らず、ときどき失敗していた（2026-10-15。記録が [] のまま）
    """

    def __init__(self, *args, **kwargs):
        self.icon_calls = []
        super().__init__(*args, **kwargs)

    def iconbitmap(self, bitmap=None, default=None):
        self.icon_calls.append(bitmap)
        return super().iconbitmap(bitmap, default)

def pump_until(condition, timeout=5.0):
    """
    条件がそろうまで画面の処理を回す。
    ⚠️ 決まった秒数だけ回すと、1回の update() が長引いたときに0.2秒後の上書きより先に終わり、
    たまたま失敗する（実際に1度起きた）。上書きと付け直しが起きたのを見てから止める。
    """
    end = time.time() + timeout
    while time.time() < end and not condition():
        h.update()
        time.sleep(0.02)

plain = RecordedToplevel(h)
plain_calls = plain.icon_calls
dialog = RecordedToplevel(h)
dialog_calls = dialog.icon_calls
A.App._apply_window_icon(dialog)
# 対策したダイアログは「付ける → 既定のアイコンに上書きされる → 付け直す」の3回呼ばれるはず
# （作るのが遅いと「上書き → 付ける → 付け直す」の順になる。どちらでも、最後はアプリのアイコン）
pump_until(lambda: plain_calls and len(dialog_calls) >= 3)
# 付け直した後に、さらに上書きされないことも見る
settle = time.time() + 0.5
pump_until(lambda: time.time() >= settle)
check("何もしないダイアログは、既定のアイコンに上書きされる（この対策が要る理由）",
      bool(plain_calls) and "CustomTkinter" in str(plain_calls[-1]), plain_calls)
check("アイコンを付けたダイアログは、上書きの後もアプリのアイコンのまま",
      bool(dialog_calls) and dialog_calls[-1] == icon, dialog_calls)
plain.destroy()
dialog.destroy()

h.destroy()
print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
