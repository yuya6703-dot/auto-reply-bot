# -*- coding: utf-8 -*-
"""
本物の AI の提供元（Gemini）が、エージェントの頼み方（返事の形）を受け付けるかを、種類ごとに1回ずつ確かめる。

    python tests/run_agent_live_check.py          # ⚠️ 本物の Gemini に送る（費用がかかる。合わせて $0.01 前後。本人の了解をとってから）

2026-10-16、返事の形に項目をたくさん足した（心の中・調べる・話し方・予定・古い記憶・オーナーの気づき・聞き取りの補正 など）。
形が受け付けられないと判断そのものが止まる（症状は「何も返事しない」）ので、リリースの前に通しておく。

- 送る中身は作り物（リポジトリは公開。本物の名前・会話・本人の自己分析は送らない）
- 文字起こしの音は、手元の VOICEVOX（無ければ AivisSpeech）で作り物の文を合成して使う。どちらも無ければ飛ばす
- キーは run_agent_scenarios.py と同じ（環境変数 GEMINI_API_KEY か、アプリに保存したキー）。キーは表示しない
"""
import argparse, os, sys, time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
sys.path.insert(0, _HERE)
from agent.cancel import CancelToken
from agent.config import AgentConfig
from agent.context import (ConversationWindow, build_combined_request, build_decide_request, build_generate_request,
                           rules_note)
from agent.decision import Decision, DECIDED_BY_LLM, SPEAKING_ACTIONS, parse_decision, request_structured
from agent.events import AgentEvent, KIND_CHAT_MESSAGE, SOURCE_GRAVITY, new_event_id
from agent.generation import parse_utterance
from agent.llm.base import LLMMessage, LLMRequest, PURPOSE_DIGEST, PURPOSE_PROFILE, PURPOSE_TRANSCRIBE
from agent.memory.recall import MemoryKeeper
from agent.memory.store import AgentStore
from agent.persona import Persona
from agent.runtime import AgentRuntime
from agent.tools.lookup import LookupResult
from agent.usage import estimate_cost
from run_agent_scenarios import live_provider

RESULTS = []
COST = {"usd": 0.0, "calls": 0}


def ev(text, who="たろう", ago=0):
    return AgentEvent(new_event_id(), KIND_CHAT_MESSAGE, SOURCE_GRAVITY, new_event_id(), who, text, time.time() - ago,
                      meta={"account": "テスト垢"})


def on_call(response, error):
    COST["calls"] += 1
    if response is not None:
        u = response.usage
        COST["usd"] += estimate_cost(response.provider, response.model, u.input_tokens or 0, u.output_tokens or 0,
                                     u.cached_input_tokens or 0) or 0.0


def run(name, request, parse):
    if ONLY and ONLY not in name:
        return
    started = time.time()
    try:
        if request.response_schema:
            value = request_structured(PROVIDER, request, CancelToken(), on_call, parse)
        else:
            response = PROVIDER.complete(request, CancelToken())
            on_call(response, None)
            value = parse(response)
        RESULTS.append((name, True, f"{time.time() - started:.1f}秒", value))
    except Exception as e:      # 形が受け付けられない・読めない・通信の失敗
        RESULTS.append((name, False, f"{time.time() - started:.1f}秒", f"{type(e).__name__}: {str(e)[:200]}"))


def tts_wav(text):
    """手元の読み上げツールで作り物の音を作る（無ければ None）"""
    from agent.speech.voicevox_compat import VoicevoxCompatibleEngine
    for name, url, speaker in (("voicevox", "http://127.0.0.1:50021", 3), ("aivisspeech", "http://127.0.0.1:10101", 888753760)):
        engine = VoicevoxCompatibleEngine(name, lambda u=url: u)
        if engine.health():
            try:
                return engine.synthesize(text, speaker)
            except Exception:
                continue
    return None


ONLY = argparse.ArgumentParser()
ONLY.add_argument("--only", default="", help="名前にこの言葉を含むものだけ流す（流し直し用）")
ONLY = ONLY.parse_args().only
PROVIDER = live_provider()
now = time.time()
config = AgentConfig(ai_name="アイ", owner_names="オーナー", lookup_enabled=True, output_mode="voice_room",
                     memory_enabled=True, impressions_enabled=True, relationships_enabled=True)
config.self_voice = "テストの声（ノーマル）"
window = ConversationWindow()
history = [ev("今日は雨すごいね", "はなこ", 60), ev("傘忘れた〜", "たろう", 40), ev("来週の土曜は花火大会だよ", "たろう", 20)]
window.add_events(history)
persona = Persona()
memory = {"facts": ["[たろう] 猫を飼っている"], "thoughts": ["[30秒前] たろうは少し疲れていそう"],
          "pending": ["「雨の日は家で映画がいいよね」（会話が進んだので出さなかった。20秒前）"]}
styles = ["ノーマル", "あまあま", "ツンツン", "ささやき"]
note = rules_note(2, 100, config.output_mode)

print("■ 本物の Gemini で、返事の形を種類ごとに確かめます（作り物の中身）")
current = [ev("アイ、富士山の高さって知ってる？", "たろう")]
window.add_events(current)
run("判断（調べる・心の中も返せる）", build_decide_request(current, window, persona, config, note, time.time(), memory_lines=memory),
    lambda r: parse_decision(r.structured, "t", r.model))
run("判断と文を1回で（声の出し方・心の中も返せる）",
    build_combined_request(current, window, persona, config, note, time.time(), memory_lines=memory, voice_styles=styles),
    # 呼ばれても、調べる・黙ると決めたら文は無い（正しい）。喋ると決めたときだけ文を読む
    lambda r: (lambda d: (d, parse_utterance(r.structured, "t") if d.action in SPEAKING_ACTIONS else None))(
        parse_decision(r.structured, "t", r.model)))
decision = Decision("engage", "呼ばれた", DECIDED_BY_LLM, "t", target="たろう")
lookup = LookupResult(True, "wikipedia", "富士山", text="記事の見出し: 富士山\n富士山は日本の活火山。標高は3776m。",
                      source="Wikipedia「富士山」")
run("文を作る（調べた結果・声の出し方）",
    build_generate_request(decision, current, window, persona, config, time.time(), memory_lines=memory, lookup=lookup,
                           voice_styles=styles),
    lambda r: parse_utterance(r.structured, "t"))
chat = AgentConfig(ai_name="アイ", output_mode="chat")
run("文を作る（チャット・メンション・絵文字）",
    build_generate_request(decision, current, window, persona, chat, time.time(), memory_lines=memory),
    lambda r: parse_utterance(r.structured, "t", keep_newlines=True))

store = AgentStore(os.path.join(__import__("tempfile").mkdtemp(), "agent_data.db"))
store.open()
keeper = MemoryKeeper(store, lambda: config, account_getter=lambda: "テスト垢")
keeper.observe(history)
store.add_memory("person", "テスト垢／たろう", "猫を飼っている", "mid", 0.6, 86400, "テスト垢")
summarize = keeper.build_request(window, "アイ", owner_notes=["- 人の話を最後まで聞く"])
run("会話の整理（予定・古い記憶・オーナーの気づきも返せる）", summarize, lambda r: r.structured)

wav = tts_wav("アイ、明日の花火大会って何時から？") if not ONLY or ONLY in "声を文字にする" else b""
if wav is None:
    RESULTS.append(("声を文字にする", None, "", "読み上げツールが動いていないので飛ばしました"))
else:
    request = LLMRequest(purpose=PURPOSE_TRANSCRIBE, system=AgentRuntime.TRANSCRIBE_SYSTEM,
                         messages=[LLMMessage("user", "## 出てきそうな名前・言葉\nアイ / たろう / はなこ / 花火大会\n"
                                                      "この音声の話し声を文字にしてください（heard・text・confidence）。",
                                              attachments=[("audio/wav", wav)])],
                         response_schema=AgentRuntime.TRANSCRIBE_SCHEMA, max_output_tokens=400, timeout_seconds=30.0)
    if wav:
        run("声を文字にする（聞き取りの補正・話の種類）", request, lambda r: r.structured)

digest = LLMRequest(purpose=PURPOSE_DIGEST, system=AgentRuntime.DIGEST_SYSTEM,
                    messages=[LLMMessage("user", "## 2026-10-16 の会話の記録\n<<<直近の会話ここから>>>\n"
                                                 "21:00 たろう: 今日は雨すごいね\n21:01 はなこ: 傘忘れた〜\n"
                                                 "21:02 アイ（AI・声）: 雨の日は家で映画がいいよね\n<<<直近の会話ここまで>>>\n"
                                                 "この日のまとめを書いてください。")],
                    max_output_tokens=700, timeout_seconds=40.0)
run("1日のまとめ（文字で返す）", digest, lambda r: (r.text or "").strip()[:120])
profile = LLMRequest(purpose=PURPOSE_PROFILE, system=AgentRuntime.OWNER_PROFILE_SYSTEM,
                     messages=[LLMMessage("user", "## オーナーの自己分析\n### 作り物.md\n- 作ったものの理由を書き残す\n"
                                                  "- 反復に強い\n\n人物像をまとめてください。")],
                     max_output_tokens=600, timeout_seconds=40.0)
run("オーナーの自己分析をまとめる（文字で返す）", profile, lambda r: (r.text or "").strip()[:120])

print()
for name, ok, took, value in RESULTS:
    mark = "ok  " if ok else ("飛ばし" if ok is None else "FAIL")
    print(f"  {mark} {name} {took}")
    print(f"       → {value}")
print(f"\nAIを呼んだ回数: {COST['calls']}  費用の見積もり: ${COST['usd']:.4f}（請求額ではありません）")
sys.exit(1 if any(ok is False for _n, ok, _t, _v in RESULTS) else 0)
