# -*- coding: utf-8 -*-
"""
Gemini（Google）のアダプター（設計書/05 の 2.3・2.4。段階4。2026-10-15 本人の決定）。

【事実: Google の公式資料（ai.google.dev、2026-10-15 に確認）】
- REST `POST https://generativelanguage.googleapis.com/v1beta/models/<モデル>:generateContent`
- キーは `x-goog-api-key` ヘッダーで渡す（URL に入れない）
- 構造化出力: generationConfig の `responseMimeType: "application/json"` と `responseJsonSchema`（JSON Schema）。
  `responseSchema` は非推奨
- 返事: candidates[0].content.parts[].text（考えた中身の部分は `thought: true`）、finishReason（STOP / MAX_TOKENS / SAFETY ...）、
  promptFeedback.blockReason（入力が止められた）、usageMetadata（promptTokenCount・candidatesTokenCount・thoughtsTokenCount・
  cachedContentTokenCount）。考えた分のトークンも出力として課金される
- 失敗: 429・503 などは一時的（やり直してよい）。400・402・403 はやり直さない（キーが違う・前払いの残高が無い・形が違う）
- generateContent は「legacy だが完全に使える」。新しい Interactions API は既定で会話を Google 側に保存する（store=true）ので、
  会話を相手に保存させない generateContent を使う（設計書/05 の 2.2「提供元の会話の保存機能は使わない」）

⚠️ SDK は使わない（標準の urllib だけ。新しい依存を増やさない・exe に同梱しやすい）。
⚠️ 通信先はこのホストだけ。リダイレクトは追わない（キーのヘッダーを別のところへ送らないため）。
⚠️ 失敗の文にキーや相手の返した本文を入れない（ログに出るため。種類と HTTP の番号だけ）。
"""
import base64
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from .base import (KIND_AUTH, KIND_BAD_REQUEST, KIND_BILLING, KIND_CANCELLED, KIND_NETWORK, KIND_OK, KIND_RATE_LIMITED,
                   KIND_SERVER, KIND_TIMEOUT, KIND_UNKNOWN, STOP_END, STOP_MAX_TOKENS, STOP_OTHER, STOP_REFUSAL,
                   LLMError, LLMResponse, LLMUsage, PingResult)

API_HOST = "generativelanguage.googleapis.com"
API_BASE = f"https://{API_HOST}/v1beta"

# 選べるモデル（2026-10-15 の公式の一覧で「安定版」のもの）。既定は安くて速いもの
MODELS = (
    ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite（安い・速い。既定）"),
    ("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite（さらに安い）"),
    ("gemini-3.8-flash", "Gemini 3.8 Flash（賢いが高い）"),
)
DEFAULT_MODEL = MODELS[0][0]

MAX_REQUEST_BYTES = 128 * 1024       # 1回に送る量の上限（ひといきと同じ考え。会話を送りすぎない）
# 音を添えるとき（声を文字にする）の上限。⚠️ 128KB のままだと声は2秒ほどで超え、文字起こしがいつも失敗していた
# （2026-10-16 本物の Gemini で確かめて見つけた）。Gemini の1回の上限は20MB。15秒の声（44.1kHz）でも2MBほど
MAX_MEDIA_REQUEST_BYTES = 8 * 1024 * 1024

# 安全上の理由で答えなかった、とみなす終わり方
REFUSAL_FINISH = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "LANGUAGE"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None      # 追わない（HTTPError になる）


def _default_opener():
    opener = urllib.request.build_opener(_NoRedirect())

    def send(method, url, headers, body, timeout):
        """(HTTP の番号, 本文 bytes) を返す。HTTP の失敗も番号で返す。つながらなければ例外"""
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with opener.open(req, timeout=timeout) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as e:
            try:
                data = e.read()
            except Exception:
                data = b""
            return e.code, data
    return send


def _retry_after(body):
    """429 の本文の RetryInfo（"retryDelay": "30s"）から待つ秒数を読む"""
    try:
        details = json.loads(body.decode("utf-8")).get("error", {}).get("details", [])
    except (ValueError, AttributeError, UnicodeDecodeError):
        return None
    for d in details:
        delay = d.get("retryDelay") if isinstance(d, dict) else None
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                return None
    return None


def classify_http_error(status, body):
    """HTTP の失敗を LLMError にする。⚠️ 本文（相手の文）は入れない"""
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body or "")
    if status in (401, 403) or (status == 400 and ("API_KEY_INVALID" in text or "API key not valid" in text)):
        return LLMError(KIND_AUTH, f"HTTP {status}")
    if status == 402:
        return LLMError(KIND_BILLING, f"HTTP {status}")
    if status == 429:
        return LLMError(KIND_RATE_LIMITED, f"HTTP {status}", retry_after=_retry_after(body))
    if status in (408, 500, 502, 503, 504):
        return LLMError(KIND_SERVER if status != 408 else KIND_TIMEOUT, f"HTTP {status}")
    if 400 <= status < 500:
        return LLMError(KIND_BAD_REQUEST, f"HTTP {status}")
    return LLMError(KIND_UNKNOWN, f"HTTP {status}")


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key, model=DEFAULT_MODEL, opener=None, thinking_level=None, clock=time.monotonic):
        if not api_key:
            raise ValueError("APIキーがありません")
        self._key = api_key
        self.model = model or DEFAULT_MODEL
        self.thinking_level = thinking_level      # None なら指定しない（モデルの既定。Flash-Lite は最小）
        self._send = opener or _default_opener()
        self._clock = clock

    # --- 共通 ---
    def _headers(self):
        return {"x-goog-api-key": self._key, "Content-Type": "application/json"}

    def _call(self, method, path, payload, timeout, limit=MAX_REQUEST_BYTES):
        url = f"{API_BASE}/{path}"
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if len(body) > limit:
                raise LLMError(KIND_BAD_REQUEST, "送る量が多すぎる")
        try:
            status, data = self._send(method, url, self._headers(), body, timeout)
        except (socket.timeout, TimeoutError):
            raise LLMError(KIND_TIMEOUT, "時間切れ")
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
                raise LLMError(KIND_TIMEOUT, "時間切れ")
            raise LLMError(KIND_NETWORK, "つながらない")
        except OSError:
            raise LLMError(KIND_NETWORK, "つながらない")
        if status != 200:
            raise classify_http_error(status, data)
        try:
            return json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise LLMError(KIND_SERVER, "返事が読めない")

    # --- 接続確認（費用のかからない、モデルの情報の取得で確かめる） ---
    def ping(self, timeout_seconds=10.0):
        try:
            self._call("GET", f"models/{urllib.parse.quote(self.model)}", None, timeout_seconds)
        except LLMError as e:
            return PingResult(ok=False, kind=e.kind if e.kind != KIND_BAD_REQUEST else KIND_UNKNOWN)
        return PingResult(ok=True, kind=KIND_OK)

    # --- 送受信 ---
    def build_payload(self, request):
        contents = [{"role": "model" if m.role == "assistant" else "user",
                     "parts": [{"text": m.content}] + [{"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode("ascii")}}
                                                       for mime, data in getattr(m, "attachments", None) or []]}
                    for m in request.messages]
        config = {"maxOutputTokens": int(request.max_output_tokens)}
        if request.response_schema is not None:
            config["responseMimeType"] = "application/json"
            config["responseJsonSchema"] = request.response_schema
        if self.thinking_level:
            config["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        payload = {"contents": contents, "generationConfig": config}
        if request.system:
            payload["systemInstruction"] = {"parts": [{"text": request.system}]}
        return payload

    def complete(self, request, cancel):
        started = self._clock()
        media = any(getattr(m, "attachments", None) for m in request.messages)
        data = self._call("POST", f"models/{urllib.parse.quote(self.model)}:generateContent",
                          self.build_payload(request), request.timeout_seconds,
                          limit=MAX_MEDIA_REQUEST_BYTES if media else MAX_REQUEST_BYTES)
        if cancel.cancelled:
            raise LLMError(KIND_CANCELLED, "取り消した")
        return self.parse_response(data, request, int((self._clock() - started) * 1000))

    def parse_response(self, data, request, latency_ms=0):
        meta = data.get("usageMetadata") or {}
        output = meta.get("candidatesTokenCount")
        thoughts = meta.get("thoughtsTokenCount")
        if output is not None or thoughts is not None:
            output = (output or 0) + (thoughts or 0)      # 考えた分も出力として課金される
        usage = LLMUsage(input_tokens=meta.get("promptTokenCount"), output_tokens=output,
                         cached_input_tokens=meta.get("cachedContentTokenCount"))

        def response(text, structured, stop):
            return LLMResponse(text=text, structured=structured, stop=stop, usage=usage,
                               provider=self.name, model=self.model, latency_ms=latency_ms)

        if (data.get("promptFeedback") or {}).get("blockReason"):
            return response(None, None, STOP_REFUSAL)
        candidates = data.get("candidates") or []
        if not candidates:
            return response(None, None, STOP_OTHER)
        candidate = candidates[0]
        finish = candidate.get("finishReason") or "STOP"
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
        if finish in REFUSAL_FINISH:
            return response(None, None, STOP_REFUSAL)
        stop = STOP_END if finish == "STOP" else (STOP_MAX_TOKENS if finish == "MAX_TOKENS" else STOP_OTHER)
        structured = None
        if request.response_schema is not None and text:
            try:
                parsed = json.loads(text)
                structured = parsed if isinstance(parsed, dict) else None
            except ValueError:
                structured = None
        return response(text, structured, stop)
