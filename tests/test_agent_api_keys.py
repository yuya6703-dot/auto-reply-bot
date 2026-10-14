# -*- coding: utf-8 -*-
"""
AI API のキーの保存（files/agent/api_keys.py）を確かめる。設計書/05「3.3 テスト」。

⚠️ ここで使うキーはすべてテスト用の作り物。本物のキーを書かないこと（リポジトリは公開）。
"""
import os, sys, sqlite3, tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import auto_reply_app as A
from agent import api_keys as K
from agent.llm import PROVIDERS, DEFAULT_PROVIDER_ID, provider_by_label, provider_by_id
from agent.llm.base import KIND_AUTH, KIND_OK, KIND_TIMEOUT
from agent.llm.mock import MockProvider

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


def all_bytes_of_db(path):
    """DB 本体と WAL（書き込みの途中が残るファイル）の中身をまとめて返す"""
    data = b""
    for p in (path, path + "-wal", path + "-shm"):
        if os.path.exists(p):
            with open(p, "rb") as f:
                data += f.read()
    return data


FAKE_KEY = "fake-test-key-0123456789abcdef"   # どの提供元の形でもない（未定の提供元の想定）

print("■ キーの形の確認")
check("前後の空白は取る", K.validate_api_key("  abc12345  ") == ("abc12345", ""))
check("空は不可", K.validate_api_key("   ")[0] is None)
check("途中の空白・改行は不可", K.validate_api_key("abc 123")[0] is None and K.validate_api_key("abc\n123")[0] is None)
check("日本語は不可（キー以外を貼った）", K.validate_api_key("キーです")[0] is None)
check("長すぎるのは不可", K.validate_api_key("a" * (K.MAX_KEY_LENGTH + 1))[0] is None)
check("説明にキーの中身を入れない", "abc 123" not in K.validate_api_key("abc 123")[1])

print("■ 保存→読み出し→削除（DPAPI）")
path = os.path.join(tempfile.mkdtemp(), "t.db")
db = A.DatabaseManager(path)
store = K.ApiKeyStore(db, env={})
check("最初は未保存", store.status("unassigned") == K.STATUS_NONE)
store.save("unassigned", "  " + FAKE_KEY + "  ")
raw = db.get_setting("ai_api_key.unassigned", "")
check("保存したのは暗号文（dpapi:v1: で始まる）", raw.startswith(K.DPAPI_PREFIX), raw[:12])
check("保存した値にキーの文字列が無い", FAKE_KEY not in raw)
check("DB のファイル（WAL も含む）にキーの文字列が無い", FAKE_KEY.encode() not in all_bytes_of_db(path))
check("読み出すと同じキー（前後の空白は取ったもの）", store.load("unassigned") == FAKE_KEY)
check("状態は保存済み", store.status("unassigned") == K.STATUS_SAVED)
check("提供元ごとに別（模擬には保存されていない）", store.status("mock") == K.STATUS_NONE)
check("削除すると True", store.delete("unassigned") is True)
check("削除した後は未保存", store.status("unassigned") == K.STATUS_NONE and store.load("unassigned") is None)
check("無いものを削除すると False", store.delete("unassigned") is False)

print("■ 読み出せない暗号文で止まらない")
db.save_setting("ai_api_key.mock", K.DPAPI_PREFIX + "QUFBQUFBQUFBQUFB")   # 壊れた暗号文
check("状態は「読み出せない」", store.status("mock") == K.STATUS_UNREADABLE)
check("読み出しは None（例外にならない）", store.load("mock") is None)
db.save_setting("ai_api_key.mock", "plain-text-key-12345")                 # 平文（あってはならないもの）
check("平文で入っていたら使わない（読み出せない扱い）", store.load("mock") is None
      and store.status("mock") == K.STATUS_UNREADABLE)
check("読み出せないものは削除できる", store.delete("mock") is True and store.status("mock") == K.STATUS_NONE)

print("■ 環境変数のキーを優先する")
env_store = K.ApiKeyStore(db, env={"FAKE_PROVIDER_KEY": "env-test-key-987654321"})
check("状態は環境変数", env_store.status("unassigned", "FAKE_PROVIDER_KEY") == K.STATUS_ENV)
check("読み出しは環境変数のキー", env_store.load("unassigned", "FAKE_PROVIDER_KEY") == "env-test-key-987654321")
check("環境変数のキーは保存しない", db.get_setting("ai_api_key.unassigned", "") == "")

print("■ 提供元の名前の確かめ")
try:
    store.save("../evil", FAKE_KEY)
    check("変な名前は拒否", False)
except ValueError:
    check("変な名前は拒否", True)

print("■ ログに出さない（伏せ字）")
store.save("unassigned", FAKE_KEY)
check("保存したキーは、そのまま伏せる", K.REDACTED in K.redact_secrets(f"エラー: key={FAKE_KEY}")
      and FAKE_KEY not in K.redact_secrets(f"エラー: key={FAKE_KEY}"))
check("Anthropic・OpenAI の形", "sk-ant-api03-abcdefghijklmnop" not in K.redact_secrets("x sk-ant-api03-abcdefghijklmnop y"))
check("Google の形", "AIzaSyA1234567890abcdefghij" not in K.redact_secrets("key=AIzaSyA1234567890abcdefghij"))
check("暗号文も出さない", K.DPAPI_PREFIX not in K.redact_secrets("値: " + raw))
check("普通の文はそのまま", K.redact_secrets("⚙️ 監視を開始しました") == "⚙️ 監視を開始しました")
check("短い言葉は伏せない（覚えたキーが短い場合の歯止め）", K.redact_secrets("おはよう") == "おはよう")

# 既存のログの入口: エラーログ・DB のログ
error_log = os.path.join(tempfile.mkdtemp(), "error_log.txt")
A.ERROR_LOG_FILE = error_log
A.write_error_log(f"例外: 認証に失敗 key={FAKE_KEY}")
with open(error_log, encoding="utf-8") as f:
    written = f.read()
check("error_log.txt にキーが残らない", FAKE_KEY not in written and K.REDACTED in written, written)
db.save_log(f"🔐 テスト {FAKE_KEY}")
rows = sqlite3.connect(path).execute("SELECT message FROM logs").fetchall()
check("DB のログにキーが残らない", all(FAKE_KEY not in r[0] for r in rows), rows[-1:])
store.delete("unassigned")
check("削除したキーは、もう覚えていない（伏せない）", K.redact_secrets(FAKE_KEY) == FAKE_KEY)

print("■ 提供元の一覧（2026-10-15 本人の決定: まだ決めない）")
check("未定と模擬だけ", set(PROVIDERS) == {"unassigned", "mock"}, list(PROVIDERS))
check("既定は未定", DEFAULT_PROVIDER_ID == "unassigned")
check("未定は接続確認できない", PROVIDERS["unassigned"].factory is None)
check("表示名から引ける", provider_by_label("テスト用（模擬）").provider_id == "mock")
check("知らない名前は既定に", provider_by_label("知らない").provider_id == "unassigned"
      and provider_by_id("nope").provider_id == "unassigned")

print("■ 模擬の接続確認（通信しない）")
check("成功", MockProvider(FAKE_KEY).ping().ok is True and MockProvider(FAKE_KEY).ping().message == "つながりました。")
auth = MockProvider(FAKE_KEY, behavior=KIND_AUTH).ping()
check("認証の失敗", auth.ok is False and "キーが違う" in auth.message)
check("時間切れ", "時間内に応答" in MockProvider(FAKE_KEY, behavior=KIND_TIMEOUT).ping().message)
check("知らない種類は「確認できませんでした」", MockProvider(FAKE_KEY, behavior="weird").ping().message == "確認できませんでした。")

print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
