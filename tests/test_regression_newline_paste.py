# -*- coding: utf-8 -*-
"""
回帰テスト: 入力欄が改行を捨てるアプリで、文字が二重に入らないこと。

【不具合】
`_fill_reply_text` は貼り付けたあと「入れた文字が入力欄にあるか」を厳密一致で
確かめ、無ければ貼り付け失敗とみなして直接入力に切り替える。
アプリ側の入力欄が1行用(android:singleLine)だと Android が改行を捨てるため、
貼り付けは成功しているのに一致せず、**既に入っている文字の上からもう一度打ち込む**。
結果、送信される文が二重になる。

【なぜ今まで表面化しなかったか】
v1.6.0までは返信ワードが1行のCTkEntryからしか来ず、改行を含み得なかった。
v1.7.0で複数行の「手入力送信」を足した時点で到達可能になる。

⚠️ 模擬しているのはエミュレータ（外部依存）だけ。判定ロジックは本物を通している。
"""
import os, sys, tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import auto_reply_app as A

FAILS = []

def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


class SingleLineFieldDevice:
    """
    入力欄が1行用のアプリを模したエミュレータ。
    Androidは android:singleLine="true" の EditText に入った改行を捨てる。
    """
    PKG = "anonymous.sns.community.gravity"

    def __init__(self):
        self.field = ""
        self.typed = []        # send_keys で打ち込まれた履歴
        self._clipboard = ""

    # --- uiautomator2 の Device が持つもののうち、この経路で使われるものだけ ---
    def set_clipboard(self, text, label=""):
        self._clipboard = text

    def send_keys(self, text):
        self.typed.append(text)
        self.field += text.replace("\n", "")      # 1行用の欄は改行を捨てる

    def clear_text(self):
        self.field = ""

    def shell(self, command):
        if f"keyevent {A.ANDROID_KEYCODE_PASTE}" in command:
            self.field += self._clipboard.replace("\n", "")
        return type("Result", (), {"output": ""})()

    def dump_hierarchy(self, compressed=True):
        shown = (self.field.replace("&", "&amp;").replace('"', "&quot;")
                           .replace("<", "&lt;").replace("\n", "&#10;"))
        if not shown:
            return f'<hierarchy><node class="android.widget.EditText" package="{self.PKG}" bounds="[28,1178][318,1241]" /></hierarchy>'
        return (f'<hierarchy><node class="android.widget.EditText" text="{shown}" '
                f'package="{self.PKG}" bounds="[28,1178][318,1241]" /></hierarchy>')


def make_worker():
    db = A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db"))
    return A.AutoReplyWorker(db, lambda m: None)


TEXT = "1行目のあいさつ\n2行目のおしらせ"

print("\n[1] 改行を捨てる入力欄へ、改行入りの文を入れる")
w = make_worker()
w._target_display = None
d = SingleLineFieldDevice()

ok = w._fill_reply_text(d, TEXT)

check("入力は成功したと返す", ok is True, ok)
check("入力欄の中身が二重になっていない",
      d.field == "1行目のあいさつ2行目のおしらせ", repr(d.field))
check("貼り付けが効いたのに直接入力へ切り替えていない",
      d.typed == [], d.typed)
check("この端末では貼り付けが使えると判断したまま",
      w._clipboard_paste_available is True, w._clipboard_paste_available)


print("\n[2] 改行を保持する入力欄でも従来どおり動く")
class MultiLineFieldDevice(SingleLineFieldDevice):
    def send_keys(self, text):
        self.typed.append(text)
        self.field += text
    def shell(self, command):
        if f"keyevent {A.ANDROID_KEYCODE_PASTE}" in command:
            self.field += self._clipboard
        return type("Result", (), {"output": ""})()

w2 = make_worker()
w2._target_display = None
d2 = MultiLineFieldDevice()
ok2 = w2._fill_reply_text(d2, TEXT)
check("入力は成功したと返す", ok2 is True, ok2)
check("改行を保ったまま1回だけ入る", d2.field == TEXT, repr(d2.field))
check("直接入力へ切り替えていない", d2.typed == [], d2.typed)


print("\n[3] 本当に入らなかった場合は、従来どおり直接入力へ切り替える")
class DeadFieldDevice(SingleLineFieldDevice):
    """貼り付けキーを受け付けない端末（クリップボード制限のある環境）"""
    def shell(self, command):
        return type("Result", (), {"output": ""})()

w3 = make_worker()
w3._target_display = None
d3 = DeadFieldDevice()
ok3 = w3._fill_reply_text(d3, TEXT)
check("直接入力にフォールバックする", d3.typed == [TEXT], d3.typed)
check("入力は成功したと返す", ok3 is True, ok3)
check("以降は貼り付けを試さないと覚える",
      w3._clipboard_paste_available is False, w3._clipboard_paste_available)


print("\n" + "=" * 50)
if FAILS:
    print(f"FAILED {len(FAILS)}件: {FAILS}")
    sys.exit(1)
print("すべて通りました")
