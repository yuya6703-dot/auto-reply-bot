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

    def is_alive(self):
        return self.alive

    def start_job(self, job):
        self.started.append(job)
        self.is_running = self.alive = True
        return True

    def stop(self):
        self.stopped = True
        self.is_running = False


class Harness(ctk.CTk):
    """UIの組み立てだけを見るための器。検証したいメソッドは本物を借りる"""

    build_main_tab = A.App.build_main_tab
    build_daily_task_section = A.App.build_daily_task_section
    save_daily_task_friend = A.App.save_daily_task_friend
    save_daily_task_text = A.App.save_daily_task_text
    on_daily_task_notify_toggle = A.App.on_daily_task_notify_toggle
    start_gravity_job = A.App.start_gravity_job
    stop_gravity_job = A.App.stop_gravity_job
    _set_gravity_job_buttons = A.App._set_gravity_job_buttons
    _watch_gravity_job = A.App._watch_gravity_job
    start_monitoring = A.App.start_monitoring

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

h.destroy()
print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
