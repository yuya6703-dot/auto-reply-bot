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
A.AGENT_JOURNAL_DIR = os.path.join(TMP, "AIの記憶")


class FakeWorker:
    """監視ワーカーの代わり（橋を受け取る・AIの文を積む）"""
    is_running = False

    def __init__(self):
        self.bridge = None
        self.agent_texts = []
        self.agent_account_user = None
        self.sent = []

    def was_sent_exactly(self, text):
        return text in self.sent

    def set_agent_bridge(self, bridge):
        self.bridge = bridge

    def enqueue_agent_text(self, text):
        self.agent_texts.append(text)
        return True, ""

    def discard_agent_texts(self):
        dropped, self.agent_texts = len(self.agent_texts), []
        return dropped


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
    PERSONA_LIMITS = A.App.PERSONA_LIMITS
    PERSONA_MAX_LINES = A.App.PERSONA_MAX_LINES
    PERSONA_LINE_CHARS = A.App.PERSONA_LINE_CHARS
    build_agent_persona_section = A.App.build_agent_persona_section
    _fill_agent_persona = A.App._fill_agent_persona
    _read_agent_persona = A.App._read_agent_persona
    save_agent_persona = A.App.save_agent_persona
    reset_agent_persona = A.App.reset_agent_persona
    AGENT_GRAVITY_SETTING = A.App.AGENT_GRAVITY_SETTING
    AGENT_GRAVITY_CONSENT_SETTING = A.App.AGENT_GRAVITY_CONSENT_SETTING
    _agent_gravity_active = A.App._agent_gravity_active
    _confirm_agent_gravity_consent = A.App._confirm_agent_gravity_consent
    on_agent_gravity_toggled = A.App.on_agent_gravity_toggled
    _on_gravity_events = A.App._on_gravity_events
    _on_gravity_room = A.App._on_gravity_room
    AGENT_MEMORY_SWITCHES = A.App.AGENT_MEMORY_SWITCHES
    build_agent_memory_section = A.App.build_agent_memory_section
    on_agent_memory_toggled = A.App.on_agent_memory_toggled
    _agent_memory_store = A.App._agent_memory_store
    refresh_agent_memory_list = A.App.refresh_agent_memory_list
    delete_selected_agent_memory = A.App.delete_selected_agent_memory
    delete_all_agent_memory = A.App.delete_all_agent_memory
    reset_agent_relationships = A.App.reset_agent_relationships
    open_agent_journal_folder = A.App.open_agent_journal_folder
    AGENT_ACCOUNT_NAMES_SETTING = A.App.AGENT_ACCOUNT_NAMES_SETTING
    ACCOUNT_NAME_VOTES = A.App.ACCOUNT_NAME_VOTES
    _load_task_account_names = A.App._load_task_account_names
    _current_account_user = A.App._current_account_user
    _gravity_account_name = A.App._gravity_account_name
    _agent_my_names = A.App._agent_my_names
    _learn_gravity_account_name = A.App._learn_gravity_account_name
    on_agent_initiative_toggled = A.App.on_agent_initiative_toggled
    AGENT_OUTPUT_LABELS = A.App.AGENT_OUTPUT_LABELS
    AGENT_CHAT_SEND_LABELS = A.App.AGENT_CHAT_SEND_LABELS
    _set_agent_config_value = A.App._set_agent_config_value
    on_agent_output_selected = A.App.on_agent_output_selected
    on_agent_chat_send_selected = A.App.on_agent_chat_send_selected
    _agent_post_chat = A.App._agent_post_chat
    _show_agent_chat_draft = A.App._show_agent_chat_draft
    _apply_window_icon = staticmethod(A.App._apply_window_icon)

    def get_manual_char_limit(self):
        return 30

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
        self.worker = FakeWorker()

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
answers = []
A.messagebox.askyesno = lambda *a, **k: (dialogs.append(("ask",) + a), answers.pop(0))[1]

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
h.agent_name_entry.delete(0, "end"); h.agent_name_entry.insert(0, "テストちゃん、@テスト👼")
h.agent_self_names_entry.insert(0, "テスト👼")
h.save_agent_settings()
check("呼ばれ方を複数・自分のアカウント名を保存する", db.get_setting("agent.ai_name") == "テストちゃん、@テスト👼"
      and db.get_setting("agent.self_names") == "テスト👼")
check("自分のアカウント名は、監視スレッドが読む値にもすぐ入る（橋が使う）", h.agent_bridge.self_names() == ["テスト👼"])
check("動いているエージェントの呼ばれ方も変わる", h.agent_runtime.config.ai_names == ["テストちゃん", "@テスト👼"])
h.agent_self_names_entry.delete(0, "end"); h.agent_self_names_entry.insert(0, "あ" * 61)
h.save_agent_settings()
check("長すぎれば保存しない", dialogs[-1][0] == "warning" and db.get_setting("agent.self_names") == "テスト👼")
h.agent_self_names_entry.delete(0, "end"); h.agent_self_names_entry.insert(0, "テスト👼")
h.agent_name_entry.delete(0, "end"); h.agent_name_entry.insert(0, "アイ")
h.save_agent_settings()
check("上限の表示も変わる", "/ 5回" in h.agent_usage_label.cget("text"), h.agent_usage_label.cget("text"))
h.agent_owner_entry.insert(0, "オーナー太郎")
h.save_agent_settings()
check("オーナーの名前を保存し、動いているエージェントにもすぐ効く", db.get_setting("agent.owner_names") == "オーナー太郎"
      and h.agent_runtime.config.owner_name_list == ["オーナー太郎"])

print("■ モデルと費用の上限")
h.agent_cost_day_entry.delete(0, "end"); h.agent_cost_day_entry.insert(0, "-1")
h.save_agent_settings()
check("費用の上限が負なら保存しない", dialogs[-1][0] == "warning" and db.get_setting("agent.daily_cost_limit_usd") == "1.0")
h.agent_cost_day_entry.delete(0, "end"); h.agent_cost_day_entry.insert(0, "0.5")
h.agent_cost_month_entry.delete(0, "end"); h.agent_cost_month_entry.insert(0, "3")
h.agent_model_var.set(dict(A.GEMINI_MODELS)["gemini-3.1-flash-lite"])
h.save_agent_settings()
check("費用の上限とモデルを保存する", db.get_setting("agent.daily_cost_limit_usd") == "0.5"
      and db.get_setting("agent.monthly_cost_limit_usd") == "3.0" and db.get_setting("agent.model") == "gemini-3.1-flash-lite")
check("費用の見積もりを出す（請求額ではないと書く）", "今日 $0.0000 / $0.50" in h.agent_usage_label.cget("text")
      and "請求額ではありません" in h.agent_usage_label.cget("text"), h.agent_usage_label.cget("text"))

print("■ 人格")
check("欄には既定の人格", "静かで落ち着いている" in h.agent_persona_widgets["summary"].get("1.0", "end"))
h.agent_persona_widgets["name"].insert(0, "ミント")
h.agent_persona_widgets["summary"].delete("1.0", "end")
h.agent_persona_widgets["summary"].insert("1.0", "あ" * 301)
h.save_agent_persona()
check("長すぎれば保存しない（文字数を言う）", dialogs[-1][0] == "warning" and "300文字" in dialogs[-1][2])
h.agent_persona_widgets["summary"].delete("1.0", "end")
h.agent_persona_widgets["summary"].insert("1.0", "明るくて元気。")
h.agent_persona_widgets["example_lines"].delete("1.0", "end")
h.agent_persona_widgets["example_lines"].insert("1.0", "\n".join(f"例{i}" for i in range(6)))
h.save_agent_persona()
check("口調の例は5行まで", dialogs[-1][0] == "warning" and "5行" in dialogs[-1][2])
h.agent_persona_widgets["example_lines"].delete("1.0", "end")
h.agent_persona_widgets["example_lines"].insert("1.0", "やっほー！\n\nいいじゃん！")
h.save_agent_persona()
saved = h.agent_store.load_persona("default")
check("保存する（agent_data.db）。空の行は除く", saved.name == "ミント" and saved.summary == "明るくて元気。"
      and saved.example_lines == ["やっほー！", "いいじゃん！"], saved)
check("動いているエージェントにもすぐ効く", h.agent_runtime.persona.name == "ミント")
answers.append(False)
h.reset_agent_persona()
check("既定に戻すのは確かめてから（いいえなら何もしない）", h.agent_persona_widgets["name"].get() == "ミント")
answers.append(True)
h.reset_agent_persona()
check("はいなら欄が既定に戻る（保存はしない）", h.agent_persona_widgets["name"].get() == ""
      and h.agent_store.load_persona("default").name == "ミント")

print("■ GRAVITYのチャットを渡す（段階5）")
check("既定はOFF・橋は監視ワーカーに渡してある", h.agent_gravity_var.get() is False and h.worker.bridge is h.agent_bridge)
check("OFFなら渡さない（動いていても）", h.agent_runtime.running and not h._agent_gravity_active())
asks = len([d for d in dialogs if d[0] == "ask"])
h.agent_gravity_var.set(True)
h.on_agent_gravity_toggled()
check("模擬なら外へ送らないので聞かない", len([d for d in dialogs if d[0] == "ask"]) == asks)
check("ONにすると渡す（保存もする）", h._agent_gravity_active() and db.get_setting("agent.gravity_bridge") == "1")
from agent_harness import make_event
before = len(h.agent_runtime.window.recent_events())
h._on_gravity_events([make_event("前からの発言", speaker="伏せ字3", backlog=True),
                      make_event("新しい発言", speaker="伏せ字7")])
check("AIタブのログ: 前からあった件数と、新しい行", pump(h, lambda: "📥 [GRAVITY] 伏せ字7: 新しい発言" in agent_log(h))
      and "📜 画面にあった1件を" in agent_log(h), agent_log(h)[-300:])
h.emergency_stop_agent()
check("緊急停止中は渡さない", not h._agent_gravity_active())
h.resume_agent()
pump(h)

print("■ 応答のしかた（声 / チャット。段階5b）")
check("既定は声", h.agent_output_var.get() == h.AGENT_OUTPUT_LABELS["voice"]
      and h.agent_chat_send_var.get() == h.AGENT_CHAT_SEND_LABELS["approve"])
answers.append(False)
h.agent_output_var.set(h.AGENT_OUTPUT_LABELS["chat"])
h.on_agent_output_selected(h.AGENT_OUTPUT_LABELS["chat"])
check("チャットにするときは確かめる（全員に見えると書く）", dialogs[-1][0] == "ask" and "ルームの全員に見えます" in dialogs[-1][2])
check("「いいえ」なら声のまま", h.agent_output_var.get() == h.AGENT_OUTPUT_LABELS["voice"]
      and db.get_setting("agent.output_mode") != "chat", db.get_setting("agent.output_mode"))
answers.append(True)
h.agent_output_var.set(h.AGENT_OUTPUT_LABELS["chat"])
h.on_agent_output_selected(h.AGENT_OUTPUT_LABELS["chat"])
check("「はい」ならチャットにする（動いているエージェントにもすぐ効く）", db.get_setting("agent.output_mode") == "chat"
      and h.agent_runtime.config.output_mode == "chat")
answers.append(False)
h.agent_chat_send_var.set(h.AGENT_CHAT_SEND_LABELS["auto"])
h.on_agent_chat_send_selected(h.AGENT_CHAT_SEND_LABELS["auto"])
check("「確認せずに送る」も確かめる。「いいえ」なら毎回確認のまま", h.agent_chat_send_var.get() == h.AGENT_CHAT_SEND_LABELS["approve"]
      and db.get_setting("agent.chat_send_mode") != "auto", db.get_setting("agent.chat_send_mode"))

print("■ 下書きを見せてから送る")
import threading
from agent.cancel import CancelToken
from agent.generation import Utterance


def post_in_thread(text, cancel=None):
    """エージェントのスレッドの代わり。結果は box[0] に入る"""
    box = []
    th = threading.Thread(target=lambda: box.append(h._agent_post_chat(Utterance(text, "calm", "t"), cancel or CancelToken())))
    th.start()
    return th, box


def draft_button(label):
    stack = [h._agent_draft_dialog]
    while stack:
        widget = stack.pop()
        if isinstance(widget, ctk.CTkButton) and widget.cget("text") == label:
            return widget
        stack.extend(widget.winfo_children())
    return None


h.worker.is_running = False
th, box = post_in_thread("監視していない")
th.join(2.0)
check("監視していなければ、下書きを見せずに「送れない」", box == ["chat_failed"] and getattr(h, "_agent_draft_dialog", None) is None)
h.worker.is_running = True
th, box = post_in_thread("こんばんは")
check("下書きを見せる", pump(h, lambda: getattr(h, "_agent_draft_dialog", None) is not None))
draft = [w for w in h._agent_draft_dialog.winfo_children() if isinstance(w, ctk.CTkTextbox)][0]
check("下書きに AI の文", draft.get("1.0", "end").strip() == "こんばんは")
draft.delete("1.0", "end"); draft.insert("1.0", "あ" * 31)
draft_button("📨 送る").invoke()
check("1通の上限を超えるように直したら送らない（窓は閉じない）", dialogs[-1][0] == "warning" and "30文字" in dialogs[-1][2]
      and h._agent_draft_dialog is not None)
draft.delete("1.0", "end"); draft.insert("1.0", "こんばんは！\n\nよろしく")
draft_button("📨 送る").invoke()
th.join(2.0)
check("送ると、直した文（改行は残す。空の行は詰める）を送信待ちへ", box == ["posted"] and h.worker.agent_texts == ["こんばんは！\nよろしく"],
      (box, h.worker.agent_texts))
th, box = post_in_thread("捨てられる文")
pump(h, lambda: getattr(h, "_agent_draft_dialog", None) is not None)
draft_button("🗑 捨てる").invoke()
th.join(2.0)
check("捨てたら送らない", box == ["discarded"] and h.worker.agent_texts == ["こんばんは！\nよろしく"])
h.agent_runtime.config.chat_approval_seconds = 1
th, box = post_in_thread("放っておかれる文")
check("時間が過ぎたら捨てる", pump(h, lambda: bool(box), timeout=5.0) and box == ["discarded"]
      and "時間が過ぎたので捨てました" in agent_log(h))
h.agent_runtime.config.chat_approval_seconds = 60
token = CancelToken()
th, box = post_in_thread("緊急停止される文", token)
pump(h, lambda: getattr(h, "_agent_draft_dialog", None) is not None)
token.cancel()
t0 = time.time()
check("緊急停止（取り消し）で下書きをすぐ閉じる（1秒の見回りを待たない）",
      pump(h, lambda: bool(box) and h._agent_draft_dialog is None, timeout=3.0) and box == ["cancelled"]
      and time.time() - t0 < 0.8, (box, h._agent_draft_dialog, round(time.time() - t0, 2)))
answers.append(True)
h.agent_chat_send_var.set(h.AGENT_CHAT_SEND_LABELS["auto"])
h.on_agent_chat_send_selected(h.AGENT_CHAT_SEND_LABELS["auto"])
th, box = post_in_thread("確認せずに送る文")
th.join(2.0)
check("確認せずに送るなら、下書きを見せずに送信待ちへ", box == ["posted"] and h.worker.agent_texts[-1] == "確認せずに送る文")
h.emergency_stop_agent()
check("緊急停止で、送信待ちの AI の文を捨てる", h.worker.agent_texts == [] and any("AIの文2件を捨てました" in m for m in h.logs),
      h.logs[-2:])
h.resume_agent()
h.worker.is_running = False
for key, value in (("output_mode", "voice"), ("chat_send_mode", "approve")):
    h._set_agent_config_value(key, value)
pump(h)

print("■ 静かなときに自分から話しかける（既定OFF）")
check("既定はOFF", h.agent_initiative_var.get() is False)
answers.append(False)
h.agent_initiative_var.set(True)
h.on_agent_initiative_toggled()
check("ONにするときは確かめる。「いいえ」ならOFFのまま", dialogs[-1][0] == "ask" and h.agent_initiative_var.get() is False
      and db.get_setting("agent.initiative_enabled") != "1")
answers.append(True)
h.agent_initiative_var.set(True)
h.on_agent_initiative_toggled()
check("「はい」ならONにする（動いているエージェントにもすぐ効く）", db.get_setting("agent.initiative_enabled") == "1"
      and h.agent_runtime.config.initiative_enabled is True)
h.agent_initiative_var.set(False)
h.on_agent_initiative_toggled()
check("OFFに戻せる", db.get_setting("agent.initiative_enabled") == "0" and h.agent_runtime.config.initiative_enabled is False)

print("■ 記憶（既定OFF・ONにするとき確かめる・見て消せる）")
check("どれも既定はOFF（会話をファイルに残すも）", all(v.get() is False for v in h.agent_memory_vars.values())
      and "journal_enabled" in h.agent_memory_vars)
answers.append(False)
h.agent_memory_vars["memory_enabled"].set(True)
h.on_agent_memory_toggled("memory_enabled")
check("ONにするときは、他の人のことも覚えると書いて確かめる。「いいえ」ならOFF",
      dialogs[-1][0] == "ask" and "ルームの他の人の名前" in dialogs[-1][2] and "繊細な事柄" in dialogs[-1][2]
      and h.agent_memory_vars["memory_enabled"].get() is False)
answers.append(True)
h.agent_memory_vars["memory_enabled"].set(True)
h.on_agent_memory_toggled("memory_enabled")
check("「はい」ならON（動いているエージェントにもすぐ効く）", db.get_setting("agent.memory_enabled") == "1"
      and h.agent_runtime.config.memory_enabled is True)
answers.append(True)
h.agent_memory_vars["impressions_enabled"].set(True)
h.on_agent_memory_toggled("impressions_enabled")
check("印象は「推定。口に出さない」と書いて確かめる", "口に出さない" in dialogs[-1][2] or "言いません" in dialogs[-1][2])
store = h.agent_store
store.upsert_person("伏せ字3", "伏せ字3")
store.add_memory("person", "伏せ字3", "猫が好き", "high", 0.8, 86400)
store.add_memory("impression", "伏せ字3", "冗談が好きそう", "low", 0.4, 86400)
store.adjust_relationship("伏せ字3", 10, 2, "テスト")
h.refresh_agent_memory_list()
items = h.agent_memory_listbox.get(0, "end")
check("覚えていることの一覧（印象は推定・確からしさ付き）", any("[伏せ字3・人] 猫が好き" == i for i in items)
      and any("[伏せ字3・印象（推定）・確からしさ低] 冗談が好きそう" == i for i in items), items)
check("関係の値の一覧", h.agent_relationship_listbox.get(0, "end") == ("伏せ字3: なじみ 10 ・ 温かさ +2",),
      h.agent_relationship_listbox.get(0, "end"))
h.delete_selected_agent_memory()
check("選ばずに消そうとしたら案内", dialogs[-1][0] == "info")
h.agent_memory_listbox.selection_set(0)
h.delete_selected_agent_memory()
check("選んだ記憶を1件消す", len(store.memories()) == 1)
answers.append(True)
h.reset_agent_relationships()
check("関係の値をリセットできる", store.relationships() == [] and h.agent_relationship_listbox.size() == 0)
answers.append(False)
h.delete_all_agent_memory()
check("全部消すのは確かめてから（いいえなら残す）", len(store.memories()) == 1)
answers.append(True)
h.delete_all_agent_memory()
check("全部消す", store.memories() == [] and h.agent_memory_listbox.get(0) == "（まだありません）")
for name in ("memory_enabled", "impressions_enabled"):
    h.agent_memory_vars[name].set(False)
    h.on_agent_memory_toggled(name)
check("OFFに戻せる", db.get_setting("agent.memory_enabled") == "0" and h.agent_runtime.config.memory_enabled is False)

print("■ 会話をファイルに残す（長期記憶ファイル。2026-10-16）")
answers.append(False)
h.agent_memory_vars["journal_enabled"].set(True)
h.on_agent_memory_toggled("journal_enabled")
check("ONにするときは、他の人の発言がそのまま入る・このPCの中だけ・自動では消さないと書いて確かめる",
      dialogs[-1][0] == "ask" and "他の人の名前と発言がそのまま入ります" in dialogs[-1][2]
      and "このPCの中だけ" in dialogs[-1][2] and "自動では消しません" in dialogs[-1][2]
      and h.agent_memory_vars["journal_enabled"].get() is False and db.get_setting("agent.journal_enabled") != "1")
answers.append(True)
h.agent_memory_vars["journal_enabled"].set(True)
h.on_agent_memory_toggled("journal_enabled")
check("「はい」ならON（動いているエージェントにもすぐ効く）", db.get_setting("agent.journal_enabled") == "1"
      and h.agent_runtime.config.journal_enabled is True)
check("書く場所はアプリのフォルダの「AIの記憶」", h.agent_runtime.deps.journal.root == A.AGENT_JOURNAL_DIR)
opened = []
real_startfile = A.os.startfile
A.os.startfile = opened.append
h.open_agent_journal_folder()
A.os.startfile = real_startfile
check("「フォルダを開く」で、無ければ作って開く", opened == [A.AGENT_JOURNAL_DIR] and os.path.isdir(A.AGENT_JOURNAL_DIR))
h.agent_memory_vars["journal_enabled"].set(False)
h.on_agent_memory_toggled("journal_enabled")
check("OFFに戻せる（確かめない）", db.get_setting("agent.journal_enabled") == "0"
      and h.agent_runtime.config.journal_enabled is False)
store.add_memory("person", "テスト垢／伏せ字3", "犬が好き", "high", 0.8, 86400, "テスト垢")
store.upsert_person("テスト垢／伏せ字3", "伏せ字3", "テスト垢")
h.refresh_agent_memory_list()
check("記憶の一覧に、どのアカウントで覚えたかを出す", "[テスト垢／伏せ字3・人] 犬が好き" in h.agent_memory_listbox.get(0, "end"),
      h.agent_memory_listbox.get(0, "end"))
store.delete_all_memories()

print("■ チャットしているGRAVITYのアカウント")
saved_self_names, h._agent_self_names = h._agent_self_names, []
check("見分ける前で、名前も分からなければ「本体のGRAVITY」", h._gravity_account_name() == "本体のGRAVITY", h._gravity_account_name())
h._agent_self_names = ["設定の名前"]
check("設定の「自分のアカウント名」があればそれ", h._gravity_account_name() == "設定の名前")
h._agent_self_names = saved_self_names
db.save_setting(A.GravityTaskWorker.ACCOUNTS_SETTING, '{"10": {"name": "複製の名前", "custom_id": "x"}}')
h._agent_task_names = h._load_task_account_names()
h.worker.agent_account_user = "10"
check("タスク機能が覚えた名前を使う（アプリ複製はユーザーごと）", h._gravity_account_name() == "複製の名前"
      and "複製の名前" in h._agent_my_names())
h.worker.agent_account_user = "0"
h._learn_gravity_account_name("テストちゃ👼", "送っていない文")
h._learn_gravity_account_name("テストちゃ👼", "送っていない文")
check("送った文とまったく同じ本文でなければ、名前を覚えない", h._agent_account_names.get("0") is None)
h.worker.sent = ["こんばんは", "またね"]
h._learn_gravity_account_name("テストちゃ👼", "こんばんは")
check("1回見ただけでは覚えない（他の人がたまたま同じ文を書いたときに取り違えない）", h._agent_account_names.get("0") is None)
h._learn_gravity_account_name("テストちゃ👼", "またね")
check("同じ名前を2回見たら覚える", h._agent_account_names.get("0") == "テストちゃ👼"
      and db.get_setting(A.App.AGENT_ACCOUNT_NAMES_SETTING) == '{"0": "テストちゃ👼"}')
check("覚えたことを判断のログに出す", pump(h, lambda: "🪪 チャットしているGRAVITYのアカウントを覚えました: 本体のGRAVITY「テストちゃ👼」"
                                                  in agent_log(h)), agent_log(h)[-200:])
check("覚えた名前がアカウントの名前になる・自分の発言の見分けにも使う",
      h._gravity_account_name() == "テストちゃ👼" and "テストちゃ👼" in h._agent_my_names())
h._learn_gravity_account_name("テストちゃ..", "またね")
check("切れて出た名前で上書きしない", h._agent_account_names["0"] == "テストちゃ👼")

print("■ ルームの様子")
h._on_gravity_room({"name": "伏せ字1", "guests": "ゲスト（1人）", "seated": 4, "empty_seats": 2, "announcement": "x"})
check("判断のログに短く出す", pump(h, lambda: "🏠 ルームの様子: 「伏せ字1」・ゲスト（1人）・席4人（アナウンスあり）" in agent_log(h)),
      agent_log(h)[-200:])
check("AI にも渡る", h.agent_runtime._room_info["name"] == "伏せ字1")

print("■ 停止")
h.stop_agent()
check("止まる", h.agent_runtime.join(2.0))
pump(h)
check("停止中に戻る", h.agent_state_label.cget("text") == "状態: 停止中" and h.agent_start_btn.cget("state") == "normal")
h.agent_event_text_entry.insert(0, "止まった？")
h.submit_agent_manual_event()
check("止まっていたら開始を促す", dialogs[-1][0] == "info" and "開始" in dialogs[-1][2])

print("■ Gemini（キーが無ければ始めない・チャットを渡す了解）")
db.save_setting("ai_api_provider", "gemini")
answers.append(False)
h.start_agent()
check("渡すスイッチがONのまま Gemini にしたら、始める前に聞き直す", dialogs[-2][0] == "ask" and "無料枠" in dialogs[-2][2]
      and "他の人の名前と発言" in dialogs[-2][2], dialogs[-2:])
check("了解が無ければスイッチを切る", h.agent_gravity_var.get() is False and db.get_setting("agent.gravity_bridge") == "0")
answers.append(True)
h.agent_gravity_var.set(True)
h.on_agent_gravity_toggled()
check("了解したら、提供元ごとに覚える", db.get_setting("agent.gravity_consent") == "gemini" and h._agent_gravity_on)
asks = len([d for d in dialogs if d[0] == "ask"])
h.agent_gravity_var.set(False); h.on_agent_gravity_toggled()
h.agent_gravity_var.set(True); h.on_agent_gravity_toggled()
check("同じ提供元なら聞き直さない", len([d for d in dialogs if d[0] == "ask"]) == asks)
h._refresh_agent_provider_label()
check("使うAIにモデルと無料枠の注意を出す", "Gemini（Google）（gemini-3.1-flash-lite）" in h.agent_provider_label.cget("text")
      and "無料枠" in h.agent_provider_label.cget("text"), h.agent_provider_label.cget("text"))
os.environ.pop("GEMINI_API_KEY", None)
h.start_agent()
check("キーが無ければ、保存するよう言って始めない", dialogs[-1][0] == "info" and "APIキーがありません" in dialogs[-1][2]
      and not h.agent_runtime.running, dialogs[-1])

h.speech_service.shutdown(timeout=0.5)
h.agent_store.close()
h.destroy()

print("■ 作り直したとき、保存した人格が欄に出る")
h2 = Harness(db)
h2.build_agent_tab()
check("前に使っていれば記録を開いて人格を出す", h2.agent_persona_widgets["name"].get() == "ミント")
h2.speech_service.shutdown(timeout=0.5)
h2.agent_store.close()
h2.destroy()

print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
