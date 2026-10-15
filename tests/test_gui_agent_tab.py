# -*- coding: utf-8 -*-
"""
AIタブ（段階3）が本物のコードのまま組み立って動くかを確かめる（設計書/08 の T44）。画面が一瞬出る。音は鳴らさない。

⚠️ ウィジェットを書き写して組み立ててはいけない（test_gui_widgets.py と同じ理由）。App の実装をそのまま借りる。
⚠️ agent_data.db は一時フォルダに作る（本物の記録に触らない）。
"""
import os, sys, tempfile, time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import customtkinter as ctk
import auto_reply_app as A
from agent import api_keys as K
from agent.speech import service as SV

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


TMP = tempfile.mkdtemp()
A.AGENT_DB_FILE = os.path.join(TMP, "agent_data.db")


class Harness(ctk.CTk):
    """AIタブだけを組み立てる器。検証したいメソッドは本物を借りる"""

    AGENT_LOG_MAX_LINES = A.App.AGENT_LOG_MAX_LINES
    build_agent_tab = A.App.build_agent_tab
    _ensure_agent_runtime = A.App._ensure_agent_runtime
    _agent_provider = A.App._agent_provider
    _selected_agent_mock_mode = A.App._selected_agent_mock_mode
    on_agent_mock_mode_selected = A.App.on_agent_mock_mode_selected
    _agent_speak = A.App._agent_speak
    _append_agent_log = A.App._append_agent_log
    clear_agent_log = A.App.clear_agent_log
    _refresh_agent_provider_label = A.App._refresh_agent_provider_label
    _refresh_agent_state = A.App._refresh_agent_state
    _refresh_agent_usage = A.App._refresh_agent_usage
    start_agent = A.App.start_agent
    stop_agent = A.App.stop_agent
    emergency_stop_agent = A.App.emergency_stop_agent
    resume_agent = A.App.resume_agent
    save_agent_settings = A.App.save_agent_settings
    submit_agent_manual_event = A.App.submit_agent_manual_event
    stop_speech = A.App.stop_speech

    def __init__(self, db):
        super().__init__()
        self.geometry("900x700")
        self.db = db
        self.api_keys = K.ApiKeyStore(db, env={})
        self.logs, self.posted, self.played = [], [], []
        self.speech_service = SV.SpeechService(
            synthesize=lambda text, voice: f"WAV:{text}".encode(), play=self._fake_play,
            default_voice=lambda: "voicevox:3", default_volume=lambda: 50)
        self.tab_agent = ctk.CTkFrame(self)
        self.tab_agent.pack(fill="both", expand=True)

    def _fake_play(self, wav, volume, cancel, device):
        self.played.append((wav.decode(), device))
        return True

    def append_log(self, message):
        self.logs.append(message)

    def _post_to_ui(self, callback):
        self.posted.append(callback)

    def _show_entry_context_menu(self, event):
        pass


def pump(h, until=None, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        while h.posted:
            h.posted.pop(0)()
        h.update()
        if until is None or until():
            return True
        time.sleep(0.02)
    return False


def agent_log(h):
    return h.agent_log_textbox.get("1.0", "end")


dialogs = []
A.messagebox.showinfo = lambda *a, **k: dialogs.append(("info",) + a)
A.messagebox.showwarning = lambda *a, **k: dialogs.append(("warning",) + a)
A.messagebox.showerror = lambda *a, **k: dialogs.append(("error",) + a)

db = A.DatabaseManager(os.path.join(TMP, "app.db"))
h = Harness(db)
h.build_agent_tab()
pump(h)

print("■ 組み立て")
check("状態は停止中", h.agent_state_label.cget("text") == "状態: 停止中")
check("提供元が未定なら、選び方を案内する", "設定タブ" in h.agent_provider_label.cget("text"))
check("停止・再開は押せない", h.agent_stop_btn.cget("state") == "disabled" and h.agent_resume_btn.cget("state") == "disabled")
check("使うまで agent_data.db を作らない", not os.path.exists(A.AGENT_DB_FILE))

print("■ 提供元が未定なら始めない")
h.start_agent()
check("理由を知らせて始めない", dialogs and "提供元" in dialogs[-1][2] and not h.agent_runtime.running)

print("■ 模擬で始めて、出来事を入れる")
db.save_setting("ai_api_provider", "mock")
h._refresh_agent_provider_label()
check("使うAI: テスト用（模擬）", h.agent_provider_label.cget("text") == "使うAI: テスト用（模擬）")
h.agent_mock_mode_var.set("いつも参加")
h.on_agent_mock_mode_selected("いつも参加")
h.start_agent()
pump(h, lambda: h.agent_runtime.running)
check("始まる", h.agent_runtime.running and h.agent_state_label.cget("text") == "状態: 待機中",
      h.agent_state_label.cget("text"))
check("開始は押せない・停止は押せる", h.agent_start_btn.cget("state") == "disabled" and h.agent_stop_btn.cget("state") == "normal")
check("模擬AIの返事を選んだとおりに", h._agent_mock.mode == "engage")
check("メインのログにも開始を出す", any("AIを始めました" in m for m in h.logs))
h.agent_event_text_entry.insert(0, "今日なにしてた？")
h.submit_agent_manual_event()
check("入れた出来事をログに出し、欄を空にする", "📥 テスト: 今日なにしてた？" in agent_log(h)
      and h.agent_event_text_entry.get() == "")
check("AI が喋る（音声サービスへ）", pump(h, lambda: len(h.played) == 1), h.played)
check("⚠️ AI の声は PC の既定の出力（\"\"）。読み上げの出力先には流さない", h.played and h.played[0][1] == "")
check("判断のログに発言が出る", pump(h, lambda: "🗣️ 参加:「テストさん、" in agent_log(h)), agent_log(h)[-200:])
check("今日の回数を出す（判断1＋生成1）", pump(h, lambda: h.agent_usage_label.cget("text").startswith("今日AIを呼んだ回数: 2 /")),
      h.agent_usage_label.cget("text"))
check("agent_data.db は指定した場所にだけ作る", os.path.exists(A.AGENT_DB_FILE))

print("■ お知らせの出来事")
h.agent_event_kind_var.set("お知らせ")
h.agent_event_text_entry.insert(0, "〇〇さんが音声ルームに参加しました")
h.submit_agent_manual_event()
check("お知らせは名前なしで入る", "📥 お知らせ: 〇〇さんが音声ルームに参加しました" in agent_log(h))
check("直前に喋ったので規則で保留（R6）", pump(h, lambda: "R6" in agent_log(h)), agent_log(h)[-200:])
h.agent_event_kind_var.set("発言")

print("■ 緊急停止と再開")
h.emergency_stop_agent()
pump(h)
check("緊急停止中と出る", h.agent_state_label.cget("text").startswith("状態: 緊急停止中"))
check("再開だけ押せる", h.agent_resume_btn.cget("state") == "normal" and h.agent_start_btn.cget("state") == "disabled")
h.agent_event_text_entry.insert(0, "まだ聞こえる？")
h.submit_agent_manual_event()
check("緊急停止中は受け付けない", "受け付けられませんでした" in agent_log(h))
h.resume_agent()
pump(h)
check("再開すると待機中", h.agent_state_label.cget("text") == "状態: 待機中")

print("■ 設定")
h.agent_name_entry.delete(0, "end"); h.agent_name_entry.insert(0, "アイ")
h.agent_limit_entry.delete(0, "end"); h.agent_limit_entry.insert(0, "たくさん")
h.save_agent_settings()
check("回数が数でなければ保存しない", dialogs[-1][0] == "warning" and db.get_setting("agent.ai_name") is None)
h.agent_limit_entry.delete(0, "end"); h.agent_limit_entry.insert(0, "5")
h.save_agent_settings()
check("保存する（settings 表の agent.〜）", db.get_setting("agent.ai_name") == "アイ" and db.get_setting("agent.daily_call_limit") == "5")
check("動いているエージェントにもすぐ効く", h.agent_runtime.config.ai_name == "アイ" and h.agent_runtime.config.daily_call_limit == 5)
check("上限の表示も変わる", h.agent_usage_label.cget("text").endswith("/ 5回"), h.agent_usage_label.cget("text"))

print("■ 停止")
h.stop_agent()
check("止まる", h.agent_runtime.join(2.0))
pump(h)
check("停止中に戻る", h.agent_state_label.cget("text") == "状態: 停止中" and h.agent_start_btn.cget("state") == "normal")
h.agent_event_text_entry.insert(0, "止まった？")
h.submit_agent_manual_event()
check("止まっていたら開始を促す", dialogs[-1][0] == "info" and "開始" in dialogs[-1][2])

h.speech_service.shutdown(timeout=0.5)
h.agent_store.close()
h.destroy()

print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
