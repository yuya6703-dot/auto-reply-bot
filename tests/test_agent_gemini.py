# -*- coding: utf-8 -*-
"""
Gemini のアダプター（files/agent/llm/gemini.py。設計書/08 の T40。段階4）。にせの HTTP で確かめる。**通信しない**。

返事の形は、Google の公式資料（2026-10-15 に確認）の generateContent の形に合わせて作った作り物。
⚠️ キーはテスト用の作り物。本物のキーを書かないこと（リポジトリは公開）。
"""
import json, socket, urllib.error

from agent_harness import check, finish
from agent.cancel import CancelToken, NEVER
from agent.context import GENERATION_SCHEMA
from agent.decision import DECISION_SCHEMA, request_decision
from agent.llm import gemini as G
from agent.llm.base import (KIND_AUTH, KIND_BAD_REQUEST, KIND_BILLING, KIND_NETWORK, KIND_RATE_LIMITED, KIND_SERVER,
                            KIND_TIMEOUT, STOP_END, STOP_MAX_TOKENS, STOP_REFUSAL, LLMError, LLMMessage, LLMRequest)

FAKE_KEY = "AIzaFAKE-test-key-0123456789abcdefghij"


class FakeHttp:
    def __init__(self, replies):
        self.replies = list(replies)      # (status, dict or bytes) または例外
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": dict(headers),
                           "body": json.loads(body.decode("utf-8")) if body else None, "timeout": timeout})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, data = reply
        return status, data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")


def ok_reply(text, finish="STOP", thought=None, usage=None):
    parts = ([{"text": thought, "thought": True}] if thought else []) + [{"text": text}]
    return (200, {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}],
                  "usageMetadata": usage or {"promptTokenCount": 1200, "candidatesTokenCount": 40,
                                             "thoughtsTokenCount": 10, "totalTokenCount": 1250},
                  "modelVersion": "gemini-3.5-flash-lite"})


def request(schema=DECISION_SCHEMA):
    return LLMRequest(purpose="decide", system="固定の指示", response_schema=schema, max_output_tokens=300,
                      timeout_seconds=12.0,
                      messages=[LLMMessage("user", "今回の出来事"), LLMMessage("assistant", "前の返事"),
                                LLMMessage("user", "直して")])


print("■ 送るもの")
http = FakeHttp([ok_reply('{"action": "react", "reason": "話しかけられた"}')])
provider = G.GeminiProvider(FAKE_KEY, opener=http)
response = provider.complete(request(), NEVER)
call = http.calls[0]
check("宛先は generateContent（既定のモデル）", call["method"] == "POST" and call["url"] ==
      "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent", call["url"])
check("⚠️ キーは URL に入れない", FAKE_KEY not in call["url"])
check("キーは x-goog-api-key ヘッダーで渡す", call["headers"].get("x-goog-api-key") == FAKE_KEY)
check("固定の指示は systemInstruction", call["body"]["systemInstruction"] == {"parts": [{"text": "固定の指示"}]})
check("会話の役割（assistant → model）", [c["role"] for c in call["body"]["contents"]] == ["user", "model", "user"])
config = call["body"]["generationConfig"]
check("構造化出力は responseMimeType と responseJsonSchema（非推奨の responseSchema は使わない）",
      config["responseMimeType"] == "application/json" and config["responseJsonSchema"] == DECISION_SCHEMA
      and "responseSchema" not in config)
check("出力の上限", config["maxOutputTokens"] == 300)
check("考える深さは、指定しなければ送らない（モデルの既定）", "thinkingConfig" not in config)
check("時間制限を渡す", call["timeout"] == 12.0)
provider.thinking_level = "MINIMAL"
http.replies.append(ok_reply('{"action": "silent", "reason": "x"}'))
provider.complete(request(), NEVER)
check("指定したら thinkingConfig.thinkingLevel", http.calls[-1]["body"]["generationConfig"]["thinkingConfig"]
      == {"thinkingLevel": "MINIMAL"})
plain = LLMRequest(purpose="ping", system="", messages=[LLMMessage("user", "x")])
http.replies.append(ok_reply("ok"))
provider.complete(plain, NEVER)
check("構造化出力が要らなければ付けない・固定の指示が空なら付けない",
      "responseMimeType" not in http.calls[-1]["body"]["generationConfig"]
      and "systemInstruction" not in http.calls[-1]["body"])
try:
    provider.complete(LLMRequest(purpose="decide", system="", messages=[LLMMessage("user", "あ" * 50000)]), NEVER)
    check("送る量が多すぎたら送らない", False)
except LLMError as e:
    check("送る量が多すぎたら送らない", e.kind == KIND_BAD_REQUEST and len(http.calls) == 3)

print("■ 返事を読む")
check("構造化出力を読む", response.structured == {"action": "react", "reason": "話しかけられた"} and response.stop == STOP_END)
check("利用量: 入力・出力（考えた分を足す）", response.usage.input_tokens == 1200 and response.usage.output_tokens == 50)
check("提供元・モデル", response.provider == "gemini" and response.model == "gemini-3.5-flash-lite")
http = FakeHttp([ok_reply('{"text": "うん", "emotion": "calm"}', thought="考えた中身")])
r = G.GeminiProvider(FAKE_KEY, opener=http).complete(request(GENERATION_SCHEMA), NEVER)
check("考えた中身（thought）は返事に入れない", r.structured == {"text": "うん", "emotion": "calm"} and "考えた" not in r.text)
http = FakeHttp([ok_reply("これはJSONではない")])
r = G.GeminiProvider(FAKE_KEY, opener=http).complete(request(), NEVER)
check("JSON でなければ structured は None（作り直しは呼ぶ側）", r.structured is None and r.text == "これはJSONではない")
http = FakeHttp([ok_reply('["配列"]')])
check("JSON でも形が違えば None", G.GeminiProvider(FAKE_KEY, opener=http).complete(request(), NEVER).structured is None)
http = FakeHttp([ok_reply('{"action": "silent"', finish="MAX_TOKENS")])
r = G.GeminiProvider(FAKE_KEY, opener=http).complete(request(), NEVER)
check("上限で切れたら max_tokens", r.stop == STOP_MAX_TOKENS and r.structured is None)
for reason in ("SAFETY", "PROHIBITED_CONTENT", "SPII", "BLOCKLIST", "RECITATION"):
    http = FakeHttp([ok_reply("", finish=reason)])
    check(f"安全上の止まり（{reason}）は refusal", G.GeminiProvider(FAKE_KEY, opener=http).complete(request(), NEVER).stop
          == STOP_REFUSAL)
http = FakeHttp([(200, {"promptFeedback": {"blockReason": "SAFETY"}, "usageMetadata": {"promptTokenCount": 10}})])
r = G.GeminiProvider(FAKE_KEY, opener=http).complete(request(), NEVER)
check("入力が止められた（promptFeedback.blockReason）も refusal", r.stop == STOP_REFUSAL and r.usage.input_tokens == 10)
http = FakeHttp([(200, {"candidates": []})])
check("候補が無ければ other", G.GeminiProvider(FAKE_KEY, opener=http).complete(request(), NEVER).stop == "other")

print("■ 判断の流れにつなぐ（作り直し・拒否）")
http = FakeHttp([ok_reply("形が違う"), ok_reply('{"action": "engage", "reason": "質問された", "target": "A"}')])
calls = []
d = request_decision(G.GeminiProvider(FAKE_KEY, opener=http), request(), "t1", CancelToken(), lambda r, e: calls.append((r, e)))
check("形が違えば1回だけ作り直して読む", d.action == "engage" and d.target == "A" and len(http.calls) == 2 and len(calls) == 2)

print("■ 失敗の種類（やり直してよいか）")
cases = [
    ((400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                      "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}}), KIND_AUTH, False),
    ((403, {"error": {"code": 403, "status": "PERMISSION_DENIED"}}), KIND_AUTH, False),
    ((402, {"error": {"code": 402}}), KIND_BILLING, False),
    ((404, {"error": {"code": 404, "status": "NOT_FOUND"}}), KIND_BAD_REQUEST, False),
    ((400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "bad schema"}}), KIND_BAD_REQUEST, False),
    ((429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                      "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17s"}]}}),
     KIND_RATE_LIMITED, True),
    ((500, b"oops"), KIND_SERVER, True),
    ((503, {"error": {"code": 503, "status": "UNAVAILABLE"}}), KIND_SERVER, True),
    ((504, b""), KIND_SERVER, True),
    (socket.timeout("timed out"), KIND_TIMEOUT, True),
    (urllib.error.URLError(socket.timeout("timed out")), KIND_TIMEOUT, True),
    (urllib.error.URLError("no route"), KIND_NETWORK, True),
    (ConnectionResetError("reset"), KIND_NETWORK, True),
]
for reply, kind, retryable in cases:
    http = FakeHttp([reply])
    try:
        G.GeminiProvider(FAKE_KEY, opener=http).complete(request(), NEVER)
        check(f"{reply!r:.40} → {kind}", False)
    except LLMError as e:
        check(f"{str(reply)[:40]} → {kind}（やり直し{'可' if retryable else '不可'}）",
              e.kind == kind and e.retryable == retryable, (e.kind, e.retryable))
        check(f"  失敗の文にキーも相手の本文も入れない（{kind}）", FAKE_KEY not in str(e) and "API key not valid" not in str(e)
              and "bad schema" not in str(e), str(e))
http = FakeHttp([cases[5][0]])
try:
    G.GeminiProvider(FAKE_KEY, opener=http).complete(request(), NEVER)
except LLMError as e:
    check("429 の待つ秒数（retryDelay）を読む", e.retry_after == 17.0, e.retry_after)
http = FakeHttp([(200, b"{not json")])
try:
    G.GeminiProvider(FAKE_KEY, opener=http).complete(request(), NEVER)
except LLMError as e:
    check("200 でも本文が読めなければ server", e.kind == KIND_SERVER)

print("■ 接続確認（費用のかからない、モデルの情報の取得）")
http = FakeHttp([(200, {"name": "models/gemini-3.8-flash"})])
result = G.GeminiProvider(FAKE_KEY, model="gemini-3.8-flash", opener=http).ping()
check("つながれば ok", result.ok and http.calls[0]["method"] == "GET"
      and http.calls[0]["url"].endswith("/v1beta/models/gemini-3.8-flash") and http.calls[0]["body"] is None)
http = FakeHttp([cases[0][0]])
check("キーが違えば auth", G.GeminiProvider(FAKE_KEY, opener=http).ping().kind == KIND_AUTH)
http = FakeHttp([(404, {"error": {"code": 404}})])
check("モデルが無ければ「確認できませんでした」", G.GeminiProvider(FAKE_KEY, opener=http).ping().ok is False)
try:
    G.GeminiProvider("")
    check("キーが無ければ作れない", False)
except ValueError:
    check("キーが無ければ作れない", True)

print("■ 取り消し・リダイレクト")
token = CancelToken()
token.cancel()
http = FakeHttp([ok_reply('{"action": "engage", "reason": "x"}')])
try:
    G.GeminiProvider(FAKE_KEY, opener=http).complete(request(), token)
    check("取り消されたら結果を捨てる", False)
except LLMError as e:
    check("取り消されたら結果を捨てる", e.kind == "cancelled")
handler = G._NoRedirect()
check("⚠️ リダイレクトは追わない（キーのヘッダーを別の宛先へ送らない）",
      handler.redirect_request(None, None, 302, "Found", {}, "https://example.com/") is None)

print("■ 費用の見積もり")
from datetime import date
from agent.usage import estimate_cost, has_price
check("3.5 Flash-Lite: 入力100万=$0.30・出力100万=$2.50",
      abs(estimate_cost("gemini", "gemini-3.5-flash-lite", 1_000_000, 1_000_000) - 2.80) < 1e-9)
check("キャッシュ済みの入力は安い値段", abs(estimate_cost("gemini", "gemini-3.5-flash-lite", 1_000_000, 0, 1_000_000) - 0.03) < 1e-9)
check("3.8 Flash は 2027-01-01 から値上がり",
      abs(estimate_cost("gemini", "gemini-3.8-flash", 1_000_000, 0, on=date(2026, 12, 31)) - 0.75) < 1e-9
      and abs(estimate_cost("gemini", "gemini-3.8-flash", 1_000_000, 0, on=date(2027, 1, 1)) - 1.50) < 1e-9)
check("選べるモデルにはすべて値段がある", all(has_price("gemini", code) for code, _ in G.MODELS))
check("値段の表に無いものは0", estimate_cost("gemini", "unknown", 1000, 1000) == 0.0)

finish()
