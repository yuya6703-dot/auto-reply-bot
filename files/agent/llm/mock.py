# -*- coding: utf-8 -*-
"""
テスト用（模擬）の提供元。通信しない。保存と接続確認の流れを試すため・テストのため。

段階3で「判断」と「文章生成」にも答えるようにした（台本どおり。設計書/09 の S3）。
AIタブの「模擬AIの返事」で、いつも沈黙・いつも反応… のように返事を決めて、沈黙と発言の流れを確かめられる。
"""

from .base import (KIND_OK, KIND_TIMEOUT, PURPOSE_DECIDE, PURPOSE_GENERATE, PURPOSE_SUMMARIZE, STOP_END,
                   STOP_REFUSAL, LLMError, LLMResponse, LLMUsage, PingResult, PURPOSE_DIGEST,
                   PURPOSE_TRANSCRIBE)

# 判断の返し方
MODE_SCRIPT = "script"       # 台本: 「？」があれば参加、「笑・w・草」があれば反応、ほかは沈黙
MODE_SILENT = "silent"
MODE_OBSERVE = "observe"
MODE_REACT = "react"
MODE_ENGAGE = "engage"
MODE_HOLD = "hold"
MODE_BROKEN = "broken"       # 型に合わない返事（作り直しの確認用）
MODE_REFUSAL = "refusal"     # 提供元が答えなかった（安全上の拒否）
MODE_TIMEOUT = "timeout"     # 時間切れ

MODE_LABELS = {
    MODE_SCRIPT: "台本（？で参加・笑で反応・ほかは沈黙）",
    MODE_SILENT: "いつも沈黙",
    MODE_OBSERVE: "いつも記録だけ",
    MODE_REACT: "いつも短く反応",
    MODE_ENGAGE: "いつも参加",
    MODE_HOLD: "いつも保留",
    MODE_BROKEN: "壊れた返事（型に合わない）",
    MODE_REFUSAL: "答えない（拒否）",
    MODE_TIMEOUT: "時間切れ",
}

REACT_MARKS = ("笑", "草", "ｗ", "w")
QUESTION_MARKS = ("？", "?")

# 喋る文は順番に変える。⚠️ 毎回同じ文だと、出す前の確認 C4（直前とほぼ同じ）で2回目から黙ってしまう
REACT_LINES = ("うんうん、なるほどね。", "へえ、そうなんだ。", "わかる、それ。", "たしかにね。")
ENGAGE_LINES = ("それ面白いね。もう少し聞かせて。", "いいね。どうしてそう思ったの？",
                "それ、ちょっと気になるな。", "なるほど、そういう見方もあるんだね。")


class MockProvider:
    name = "mock"
    model = "mock-1"

    def __init__(self, api_key="", behavior=KIND_OK, mode=MODE_SCRIPT):
        # behavior: 接続確認で返す結果の種類（テストで失敗の表示を確かめるときに変える）
        self._has_key = bool(api_key)
        self.behavior = behavior
        self.mode = mode
        self.delay_seconds = 0.0          # 返事を遅らせる（古い結果を捨てる確認用）
        self.script_decide = []           # 先に入れたものから順に返す（dict / LLMError / MODE_*）
        self.script_generate = []
        self.script_summarize = []        # 覚えることの整理の返事（無ければ「何も無い」）
        self.script_transcribe = []       # 声を文字にした返事（無ければ「（模擬）聞こえた声」）
        self.requests = []                # 受け取った依頼（テストが中身を確かめる）
        self._generated = 0

    def ping(self, timeout_seconds=10.0):
        return PingResult(ok=self.behavior == KIND_OK, kind=self.behavior)

    def complete(self, request, cancel):
        self.requests.append(request)
        if self.delay_seconds:
            cancel.wait(self.delay_seconds)
        if request.purpose == PURPOSE_DECIDE:
            item = self.script_decide.pop(0) if self.script_decide else self.mode
            if request.hints.get("combined"):       # 判断と文を1回で（呼ばれたとき）
                return self._respond(item, lambda mode: self._decide_with_text(mode, request.hints))
            return self._respond(item, lambda mode: self._decide(mode, request.hints))
        if request.purpose == PURPOSE_GENERATE:
            item = self.script_generate.pop(0) if self.script_generate else None
            return self._respond(item, lambda _: self._generate(request.hints))
        if request.purpose == PURPOSE_SUMMARIZE:
            item = self.script_summarize.pop(0) if self.script_summarize else None
            return self._respond(item, lambda _: {"memories": [], "impressions": [], "relationships": []})
        if request.purpose == PURPOSE_TRANSCRIBE:
            item = self.script_transcribe.pop(0) if self.script_transcribe else None
            return self._respond(item, lambda _: {"text": "（模擬）聞こえた声"})
        if request.purpose == PURPOSE_DIGEST:      # 1日のまとめは文字で返す
            return LLMResponse(text="- （模擬）今日は穏やかな一日だった", structured=None, stop=STOP_END,
                               usage=LLMUsage(100, 20), provider=self.name, model=self.model)
        return self._response({"ok": True})

    # --- 中身 ---
    def _respond(self, item, build):
        if isinstance(item, LLMError):
            raise item
        if isinstance(item, dict):
            return self._response(item)
        if item == MODE_TIMEOUT:
            raise LLMError(KIND_TIMEOUT, "模擬の時間切れ")
        if item == MODE_BROKEN:
            return LLMResponse(text="これは型に合わない返事です", structured=None, stop=STOP_END,
                               usage=LLMUsage(10, 5), provider=self.name, model=self.model)
        if item == MODE_REFUSAL:
            return LLMResponse(text=None, structured=None, stop=STOP_REFUSAL,
                               usage=LLMUsage(10, 0), provider=self.name, model=self.model)
        return self._response(build(item))

    def _response(self, structured):
        return LLMResponse(text=None, structured=structured, stop=STOP_END, usage=LLMUsage(100, 20),
                           provider=self.name, model=self.model, latency_ms=0)

    @staticmethod
    def _decide(mode, hints):
        events = [e for e in hints.get("events", []) if not e.get("is_self")]
        target = next((e.get("speaker") for e in reversed(events) if e.get("speaker")), None)
        if mode == MODE_SCRIPT:
            texts = [e.get("text", "") for e in events]
            if any(m in t for t in texts for m in QUESTION_MARKS):
                mode = MODE_ENGAGE
            elif any(m in t for t in texts for m in REACT_MARKS):
                mode = MODE_REACT
            else:
                mode = MODE_SILENT
        reasons = {MODE_SILENT: "（模擬）話す場面ではない", MODE_OBSERVE: "（模擬）覚えておく",
                   MODE_REACT: "（模擬）短く反応する", MODE_ENGAGE: "（模擬）話しかけられた",
                   MODE_HOLD: "（模擬）少し待つ"}
        return {"action": mode, "reason": reasons.get(mode, "（模擬）"),
                "urgency": 0.8 if mode == MODE_ENGAGE else 0.3,
                "target": target, "hold_seconds": 3 if mode == MODE_HOLD else None}

    def _decide_with_text(self, mode, hints):
        decision = self._decide(mode, hints)
        if decision["action"] in (MODE_REACT, MODE_ENGAGE):
            decision.update(self._generate({"action": decision["action"], "target": decision.get("target")}))
        else:
            decision.update(text=None, emotion=None)
        return decision

    def _generate(self, hints):
        target = hints.get("target")
        call = f"{target}さん、" if target else ""
        n, self._generated = self._generated, self._generated + 1
        if hints.get("action") == MODE_ENGAGE:
            return {"text": call + ENGAGE_LINES[n % len(ENGAGE_LINES)], "emotion": "joy"}
        return {"text": call + REACT_LINES[n % len(REACT_LINES)], "emotion": "calm"}
