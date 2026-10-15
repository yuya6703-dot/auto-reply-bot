# -*- coding: utf-8 -*-
"""
入力欄へ文字を入れる・消すのを速くした（2026-10-16 本人「応答遅いの気になる」）。

【分かったこと】MuMu は uiautomator2 の文字入力（AdbKeyboard）への切り替えを止める（2026-10-14 の記録: MuMuIMETrace: ime shell BLOCKED）。
d.clear_text() と d.send_keys() は先にその切り替えを5秒待ち、3回やり直してから、
- send_keys は「今選ばれている部品に直接入れる」やり方に切り替わって入る（約9秒）
- clear_text は代わりが無く、例外で終わる（約8秒）
送る1回あたり約17秒を捨てていた（実際のログ: 入力欄を押してから送るまで19秒）。

【直し方】はじめから今選ばれている部品を直接さわる（d(focused=True).set_text / clear_text）。入らなかったときだけ前のやり方。
⚠️ 実機には触らない。にせの端末で、遅いやり方を呼ばないことと、入らないときに前のやり方へ戻ることを確かめる。
"""
import os, sys, tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import auto_reply_app as A

FAILS = []
GRAVITY = "anonymous.sns.community.gravity"


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


class FocusedField:
    """d(focused=True) の代わり"""

    def __init__(self, device):
        self.device = device

    def set_text(self, text, timeout=None):
        self.device.calls.append("focused.set_text")
        if self.device.direct_broken:
            raise RuntimeError("UiObjectNotFoundError")
        if not self.device.direct_ignored:
            self.device.field = text or ""

    def clear_text(self, timeout=None):
        self.device.calls.append("focused.clear_text")
        if self.device.direct_broken:
            raise RuntimeError("UiObjectNotFoundError")
        self.device.field = ""


class FakeRoomInput:
    """音声ルームの入力のシートが開いた画面（入力欄と「送る」）。遅いやり方を呼んだら記録する"""

    def __init__(self, field="前の文字", direct_broken=False, direct_ignored=False):
        self.field = field
        self.calls = []
        self.direct_broken = direct_broken      # 部品を直接さわれない
        self.direct_ignored = direct_ignored    # さわれるが、文字が入らない
        self.sent = []

    def __call__(self, **selector):
        assert selector == {"focused": True}, selector
        return FocusedField(self)

    # --- 遅いやり方（MuMu では約8〜9秒） ---
    def clear_text(self):
        self.calls.append("d.clear_text")
        raise RuntimeError("AdbBroadcastError")

    def send_keys(self, text):
        self.calls.append("d.send_keys")
        self.field = text

    def set_clipboard(self, text, label=None):
        raise RuntimeError("java.lang.SecurityException")

    def shell(self, command):
        if "input" in str(command) and "tap" in str(command):
            self.sent.append(self.field)
            self.field = ""
        return type("R", (), {"output": ""})()

    def dump_hierarchy(self, compressed=True):
        shown = self.field.replace("&", "&amp;").replace('"', "&quot;").replace("\n", "&#10;") or "メッセージを送信"
        return ('<hierarchy>'
                f'<node class="android.widget.EditText" resource-id="{GRAVITY}:id/etText" text="{shown}" '
                f'package="{GRAVITY}" display-id="2" bounds="[147,896][433,948]" focused="true" />'
                f'<node class="android.widget.TextView" resource-id="{GRAVITY}:id/btnSend" text="送る" '
                f'package="{GRAVITY}" display-id="2" bounds="[433,904][511,941]" clickable="true" />'
                '</hierarchy>')

    def window_size(self):
        return 540, 960


def worker():
    w = A.AutoReplyWorker(A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db")), lambda m: None)
    w.db.save_setting("mumu_target_package", GRAVITY)
    w._target_display = "2"
    w._clipboard_paste_available = False      # この MuMu では貼り付けが使えない（分かったあとの状態）
    w._check_after_action = lambda d, what: None
    return w


A.time.sleep = lambda seconds: None
TEXT = "テストさん、おはよう。\n今起きたよ😊"

print("■ 入れる: 遅いやり方を呼ばない")
d = FakeRoomInput(field="")
w = worker()
check("入ったと返す", w._type_reply_text(d, TEXT) is True)
check("今選ばれている部品に直接入れる（改行もそのまま）", d.field == TEXT, repr(d.field))
check("d.send_keys（約9秒）を呼ばない", "d.send_keys" not in d.calls, d.calls)

print("■ 消す: 遅いやり方を呼ばない")
d = FakeRoomInput(field="前に打ちかけた文字")
w._clear_input(d)
check("入力欄が空になる", d.field == "", repr(d.field))
check("d.clear_text（約8秒・しかも失敗）を呼ばない", "d.clear_text" not in d.calls, d.calls)

print("■ 送る（消す → 入れる → 「送る」）の全体")
d = FakeRoomInput(field="前に打ちかけた文字")
w = worker()
check("送れたと返す", w._send_reply(d, TEXT) is True)
check("送った文は、前の文字が混ざらず、入れた文だけ", d.sent == [TEXT], d.sent)
check("遅いやり方を1回も呼ばない", not any(c.startswith("d.") for c in d.calls), d.calls)

print("■ 直接さわれないとき・入らないときは、前のやり方へ戻る")
d = FakeRoomInput(field="", direct_broken=True)
w = worker()
check("部品が見つからなければ d.send_keys で入れる", w._type_reply_text(d, TEXT) is True and d.calls[-1] == "d.send_keys"
      and d.field == TEXT, d.calls)
d = FakeRoomInput(field="", direct_ignored=True)
check("直接入れても文字が入らなければ d.send_keys で入れる", w._type_reply_text(d, TEXT) is True and d.calls[-1] == "d.send_keys"
      and d.field == TEXT, d.calls)
d = FakeRoomInput(field="消せない文字", direct_broken=True)
w._clear_input(d)
check("消すのに失敗しても止まらない（そのあとの入れ方が中身を置き換える）", d.calls == ["focused.clear_text"], d.calls)

print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
