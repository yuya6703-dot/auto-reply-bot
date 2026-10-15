# -*- coding: utf-8 -*-
"""
AIの判断の場面集（tests/fixtures/agent_scenarios.json）を流して、「喋るべき/黙るべき」と判断が合う割合を測る（設計書/09 の S4）。

    python tests/run_agent_scenarios.py              # 模擬のAIで流す（通信しない・費用0。場面集と流れの確認）
    python tests/run_agent_scenarios.py --live       # ⚠️ 本物の Gemini で流す（費用がかかる。本人の了解をとってから）
    python tests/run_agent_scenarios.py --live --with-text   # 喋る場面で、文も作らせる（費用が増える）

--live のキーは、環境変数 GEMINI_API_KEY か、アプリに保存したキー（files/app_data.db。DPAPI）を使う。キーは表示しない。
本物のアプリと同じ部品（コンテキストの組み立て・判断の型・作り直し）を使う。規則の関所は通さない（AIの判断だけを測る）。
"""
import argparse, json, os, sys, time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
from agent.cancel import CancelToken
from agent.config import AgentConfig
from agent.context import ConversationWindow, build_decide_request, build_generate_request, rules_note
from agent.decision import DecisionFailed, SPEAKING_ACTIONS, request_decision
from agent.events import AgentEvent, KIND_CHAT_MESSAGE, KIND_CHAT_NOTICE, SOURCE_TEST, new_event_id
from agent.generation import request_utterance
from agent.llm.base import LLMError
from agent.llm.mock import MockProvider
from agent.persona import Persona
from agent.usage import estimate_cost

SCENARIOS = os.path.join(_HERE, "fixtures", "agent_scenarios.json")


def to_event(item, at):
    if "notice" in item:
        return AgentEvent(new_event_id(), KIND_CHAT_NOTICE, SOURCE_TEST, new_event_id(), None, item["notice"], at)
    return AgentEvent(new_event_id(), KIND_CHAT_MESSAGE, SOURCE_TEST, new_event_id(), item["who"], item["text"], at,
                      is_self=bool(item.get("self")))


def live_provider():
    """本物の Gemini。キーは環境変数か、アプリに保存したもの"""
    import auto_reply_app as A
    from agent.api_keys import ApiKeyStore
    from agent.llm.gemini import DEFAULT_MODEL, GeminiProvider
    db = A.DatabaseManager(A.DB_FILE)
    key = ApiKeyStore(db).load("gemini", "GEMINI_API_KEY")
    if not key:
        sys.exit("Gemini のキーがありません。アプリの設定タブ「🤖 AI API」で保存するか、GEMINI_API_KEY を設定してください。")
    model = db.get_setting("agent.model", "") or DEFAULT_MODEL
    return GeminiProvider(key, model=model)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="本物の Gemini で流す（費用がかかる）")
    parser.add_argument("--with-text", action="store_true", help="喋る場面で文も作らせる")
    args = parser.parse_args()

    with open(SCENARIOS, encoding="utf-8") as f:
        data = json.load(f)
    config = AgentConfig(ai_name=data["ai_name"])
    persona = Persona()
    provider = live_provider() if args.live else MockProvider()
    print(f"提供元: {provider.name}（{getattr(provider, 'model', '-')}）  場面: {len(data['scenes'])}件")
    print()

    usage = {"calls": 0, "input": 0, "output": 0, "cost": 0.0}

    def on_call(response, error):
        usage["calls"] += 1
        if response is not None:
            usage["input"] += response.usage.input_tokens or 0
            usage["output"] += response.usage.output_tokens or 0
            usage["cost"] += estimate_cost(response.provider, response.model, response.usage.input_tokens,
                                           response.usage.output_tokens, response.usage.cached_input_tokens)

    agree = judged = 0
    latencies = []
    for scene in data["scenes"]:
        now = time.time()
        window = ConversationWindow()
        recent = [to_event(item, now - 60 + i * 5) for i, item in enumerate(scene["recent"])]
        window.add_events(recent)
        for e in recent:
            if e.is_self:
                window.add_own(e.text, e.observed_at)
        events = [to_event(item, now - 1) for item in scene["events"]]
        request = build_decide_request(events, window, persona, config, rules_note(2, 100), now)
        started = time.monotonic()
        try:
            decision = request_decision(provider, request, scene["id"], CancelToken(), on_call)
            action, reason = decision.action, decision.reason
        except (DecisionFailed, LLMError) as e:
            decision, action, reason = None, "（失敗）", getattr(e, "kind", str(e))
        latencies.append(time.monotonic() - started)
        speaks = action in SPEAKING_ACTIONS
        expect = scene["expect"]
        if expect == "either":
            mark = "・"
        else:
            judged += 1
            ok = (expect == "speak") == speaks
            agree += ok
            mark = "○" if ok else "×"
        print(f"{mark} {scene['id']} {scene['title']}")
        print(f"    期待: {expect:7} 判断: {action}（{reason}） {latencies[-1]:.1f}秒")
        if args.with_text and decision is not None and speaks:
            gen = build_generate_request(decision, events, window, persona, config, now)
            try:
                utterance = request_utterance(provider, gen, scene["id"], CancelToken(), on_call)
                print(f"    文: 「{utterance.text}」（{utterance.emotion}）")
            except (DecisionFailed, LLMError) as e:
                print(f"    文: （作れなかった: {getattr(e, 'kind', e)}）")

    print()
    if judged:
        print(f"判断が合った割合: {agree}/{judged}（{agree / judged:.0%}）  ※ either の場面は数えない")
    print(f"AIを呼んだ回数: {usage['calls']}  入力 {usage['input']}・出力 {usage['output']} トークン  "
          f"費用の見積もり: ${usage['cost']:.4f}（請求額ではありません）")
    if latencies:
        print(f"判断にかかった時間: 平均 {sum(latencies) / len(latencies):.1f}秒・最長 {max(latencies):.1f}秒")


if __name__ == "__main__":
    main()
