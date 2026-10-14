# -*- coding: utf-8 -*-
"""
AI API のキーを、このPCの Windows ユーザーだけが復元できる形（DPAPI）で暗号化して保存する。
設計: 設計書/05_アダプター設計書.md「3. AI API キーの入力と保存」（段階1）

⚠️ キーを平文で保存しない・ログに出さない・URL に入れない。
⚠️ 保存先は get_setting / save_setting を持つもの（DatabaseManager）を受け取って使う。
   既存の settings 表に、キー名 ai_api_key.<提供元>、値 dpapi:v1:<base64>（暗号文だけ）で入れる。
"""
import base64
import os
import re
import sys
import threading

DPAPI_PREFIX = "dpapi:v1:"
SETTING_PREFIX = "ai_api_key."
MAX_KEY_LENGTH = 512
# 同じ Windows ユーザーの別のアプリが、このアプリの暗号文をそのまま復元しにくくするための合言葉（秘密ではない）
_ENTROPY = b"GuraHojoTool/AIAPIKey/v1"
_PROVIDER_ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")

STATUS_NONE = "none"              # 保存されていない
STATUS_SAVED = "saved"            # 保存されていて、読み出せる
STATUS_ENV = "env"                # 環境変数のキーを使う（保存はしていない）
STATUS_UNREADABLE = "unreadable"  # 保存されているが、このPCのユーザーでは読み出せない（別のユーザー・別のPC・壊れている）


class SecretStoreError(Exception):
    """暗号化・復元ができなかった"""


# ----------------------------------------------------------------------
# DPAPI（Windows の CryptProtectData / CryptUnprotectData を標準の ctypes で呼ぶ。新しい依存は要らない）
def _dpapi():
    if not sys.platform.startswith("win"):
        raise SecretStoreError("この保存方法はWindowsでのみ使えます。")
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for name in ("CryptProtectData", "CryptUnprotectData"):
        fn = getattr(crypt32, name)
        fn.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.POINTER(DataBlob),
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
        fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return ctypes, DataBlob, crypt32, kernel32


_CRYPTPROTECT_UI_FORBIDDEN = 0x01   # 画面を出さない（出せないときは失敗にする）


def _dpapi_call(name, data):
    ctypes, DataBlob, crypt32, kernel32 = _dpapi()
    in_buf = ctypes.create_string_buffer(data, len(data))
    ent_buf = ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY))
    in_blob = DataBlob(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    ent_blob = DataBlob(len(_ENTROPY), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = DataBlob()
    ok = getattr(crypt32, name)(ctypes.byref(in_blob), None, ctypes.byref(ent_blob), None, None,
                                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob))
    if not ok:
        raise SecretStoreError(f"{name} に失敗しました（Windowsのエラー {ctypes.get_last_error()}）。")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def dpapi_protect(data: bytes) -> bytes:
    return _dpapi_call("CryptProtectData", data)


def dpapi_unprotect(data: bytes) -> bytes:
    return _dpapi_call("CryptUnprotectData", data)


# ----------------------------------------------------------------------
# ログに出さない（設計書/06 の 7章）
REDACTED = "＊＊＊(秘密)"
# 提供元のキーの形（どれにも当たらない形のキーは、下の「覚えたキー」でそのまま伏せる）
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),          # Anthropic（sk-ant-…）・OpenAI（sk-…）の形
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),          # Google の API キーの形
    re.compile(re.escape(DPAPI_PREFIX) + r"[A-Za-z0-9+/=]{8,}"),   # 暗号文も念のため出さない
)
# 保存・読み出し・入力の確認をしたキー。形がわからない提供元（未定）でも、そのものを伏せられるようにする。
# ⚠️ メモリの中だけ。削除したら忘れる
_known_secrets = set()
_known_lock = threading.Lock()
_MIN_REMEMBERED_LENGTH = 8   # 短すぎる文字列を伏せると、普通の言葉まで消える


def remember_secret(value):
    if value and len(value) >= _MIN_REMEMBERED_LENGTH:
        with _known_lock:
            _known_secrets.add(value)


def forget_secret(value):
    with _known_lock:
        _known_secrets.discard(value)


def redact_secrets(text):
    """ログ・エラーの文字列から、APIキーらしいものを伏せる"""
    if not text or not isinstance(text, str):
        return text
    with _known_lock:
        known = sorted(_known_secrets, key=len, reverse=True)
    for secret in known:
        if secret in text:
            text = text.replace(secret, REDACTED)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


# ----------------------------------------------------------------------
def validate_api_key(text):
    """
    入力されたキーを整える。戻り値: (整えたキー, 問題の説明)。問題があればキーは None。
    ⚠️ 説明の文にキーそのものを入れない
    """
    key = (text or "").strip()
    if not key:
        return None, "APIキーが入力されていません。"
    if len(key) > MAX_KEY_LENGTH:
        return None, f"長すぎます（{MAX_KEY_LENGTH}文字まで）。キーだけを貼り付けてください。"
    if any(c.isspace() for c in key):
        return None, "空白や改行が含まれています。キーだけを貼り付けてください。"
    if not (key.isascii() and key.isprintable()):
        return None, "英数字と記号以外の文字が含まれています。キーだけを貼り付けてください。"
    return key, ""


class ApiKeyStore:
    """
    提供元ごとの AI API キーの保存・読み出し・削除。

    settings: get_setting(key, default) と save_setting(key, value) を持つもの（DatabaseManager）
    env: 環境変数（テストで差し替える）。提供元の標準の環境変数があれば、保存したキーより優先する
    """

    def __init__(self, settings, env=None, protect=dpapi_protect, unprotect=dpapi_unprotect):
        self.settings = settings
        self.env = os.environ if env is None else env
        self._protect = protect
        self._unprotect = unprotect

    @staticmethod
    def _setting_name(provider_id):
        if not _PROVIDER_ID_RE.match(provider_id or ""):
            raise ValueError("提供元の名前が正しくありません。")
        return SETTING_PREFIX + provider_id

    def save(self, provider_id, key_text):
        """キーを確かめて暗号化して保存し、整えたキーを返す。形が悪ければ ValueError（説明つき）"""
        key, problem = validate_api_key(key_text)
        if key is None:
            raise ValueError(problem)
        encrypted = self._protect(key.encode("utf-8"))
        self.settings.save_setting(self._setting_name(provider_id),
                                   DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii"))
        remember_secret(key)
        return key

    def _read_saved(self, provider_id):
        """保存済みのキーを復元する。戻り値: (キー, 状態)。読めなければキーは None"""
        raw = self.settings.get_setting(self._setting_name(provider_id), "") or ""
        if not raw:
            return None, STATUS_NONE
        if not raw.startswith(DPAPI_PREFIX):
            return None, STATUS_UNREADABLE
        try:
            key = self._unprotect(base64.b64decode(raw[len(DPAPI_PREFIX):], validate=True)).decode("utf-8")
        except Exception:
            # 別の Windows ユーザー・別のPCで暗号化されたもの、壊れたもの。例外で止めず「読み出せない」にする
            return None, STATUS_UNREADABLE
        checked, _ = validate_api_key(key)
        if checked is None:
            return None, STATUS_UNREADABLE
        remember_secret(checked)
        return checked, STATUS_SAVED

    def _env_key(self, env_var):
        if not env_var:
            return None
        key, _ = validate_api_key(self.env.get(env_var, ""))
        if key:
            remember_secret(key)
        return key

    def load(self, provider_id, env_var=None):
        """使う直前に呼ぶ。環境変数 → 保存済み の順。無ければ None"""
        env_key = self._env_key(env_var)
        if env_key:
            return env_key
        key, _ = self._read_saved(provider_id)
        return key

    def status(self, provider_id, env_var=None):
        if self._env_key(env_var):
            return STATUS_ENV
        _, state = self._read_saved(provider_id)
        return state

    def delete(self, provider_id):
        """保存済みのキーを消す。消すものがあったら True"""
        key, state = self._read_saved(provider_id)
        if state == STATUS_NONE:
            return False
        self.settings.save_setting(self._setting_name(provider_id), "")
        if key:
            forget_secret(key)
        return True
