# -*- coding: utf-8 -*-
"""
反応しない人（1）・オーナーの合図（2）（2026-10-16 本人「1から6まで」）。
模擬の AI・にせの声とチャット。音は鳴らさない・通信しない。テストの名前・内容は作り物（リポジトリは公開）。

⚠️ オーナーは表示名でしか見分けられない（なりすましもありうる）→ 合図は悪用されても困らないもの（静かに・戻る・
   「（オーナーから）」と付けたふつうの記憶）だけ。AI に呼びかけていない発言は合図にしない
"""
import time

from agent_harness import Agent, check, finish, wait_until
from agent.config import AgentConfig
from agent.llm.mock import MODE_ENGAGE
from agent.owner import CMD_MUTE, CMD_REMEMBER, CMD_UNMUTE, is_owner, mute_minutes, parse_command
from agent_harness import make_event
from agent.events import SOURCE_GRAVITY

NAMES = ["アイ", "@アイ"]


def chat(text, speaker="たろう", **kw):
    return make_event(text, speaker=speaker, source=SOURCE_GRAVITY, account="テスト垢", **kw)


print("■ 合図の読み方")
check("呼びかけて「静かにして」→ 30分", parse_command("アイ、ちょっと静かにしてて", NAMES) == (CMD_MUTE, 30))
check("「10分」「1時間」「ずっと」", mute_minutes("10分黙って") == 10 and mute_minutes("1時間静かに") == 60
      and mute_minutes("ずっと静かにして") == 360 and mute_minutes("999分") == 360)
check("「もういいよ」「ミュート解除」で戻る（静かにしている間）", parse_command("アイ、もういいよ", NAMES, muted=True) == (CMD_UNMUTE, None)
      and parse_command("@アイ.. ミュート解除", NAMES, muted=True) == (CMD_UNMUTE, None))
check("静かにしていなければ「もういいよ」は合図にしない（ふつうの会話として AI が判断する）",
      parse_command("アイ、もういいよ", NAMES) is None and parse_command("アイ、もう大丈夫？", NAMES) is None)
# 2026-10-22 本人「静かにしてって言ってないのにそう言ったと認識してる」。言葉を含むだけで合図にしていた（実際に3回）。
# 頼む形（静かにして・黙って・ミュートして…）のときだけ合図にする。下の文は実際の言い回しをまねた作り物
for text in ("@アイ.. 聞こえてる理由教えて、そもそもミュートしてるのに",       # マイクのミュートの話（してる＝様子）
             "@アイ.. なんで静かにしてるん",                                   # 静かにしている様子を聞いている
             "アイ、黙ってないでなんか話して",                                   # 黙らないで（反対の意味）
             "アイ、静かにしてって言われたの？",                                 # 言われたことの話
             "アイ、ミュートになってるよ",
             "アイ、静かにしてた？"):
    check(f"合図にしない:「{text}」", parse_command(text, NAMES) is None, parse_command(text, NAMES))
check("「マイクのミュートするんだけど、…伝えといて」は、静かにする合図ではなく、代わりに伝える頼み（2026-10-23 から）",
      parse_command("@アイ.. ちょっと席外すからマイクのミュートするんだけど、みんなに伝えといて", NAMES)[0] == "delegate")
for text, minutes in (("アイ、ミュートして", 30), ("アイ、静かにしてね", 30), ("アイ黙って", 30), ("アイ、静かにしてください", 30),
                      ("アイ、10分黙っててくれる？", 10), ("アイ、しゃべらないで", 30), ("アイ、お口チャック", 30),
                      ("@アイ.. ちょっとミュートにしてて", 30), ("アイ、1時間静かにしてくれ", 60)):
    check(f"合図にする:「{text}」→ {minutes}分", parse_command(text, NAMES) == (CMD_MUTE, minutes), parse_command(text, NAMES))
check("「〇〇って覚えておいて」", parse_command("アイ、たろうさんは猫が好きって覚えておいて！", NAMES)
      == (CMD_REMEMBER, "たろうさんは猫が好き"))
check("呼びかけていなければ合図にしない（「静かにしてって言われた」など）",
      parse_command("静かにしてって言われた", NAMES) is None and parse_command("覚えておいて", NAMES) is None)
check("覚えることが書いていなければ合図にしない", parse_command("アイ、覚えておいて", NAMES) is None)
cfg = AgentConfig(owner_names="オーナー")
check("オーナーは表示名で見る（切れて出ても）", is_owner(chat("x", speaker="オーナー"), cfg)
      and is_owner(chat("x", speaker="オーナ.."), cfg) and not is_owner(chat("x", speaker="たろう"), cfg))


def agent(**config):
    defaults = dict(ai_name="アイ", owner_names="オーナー", min_gap_after_speaking=0.0)
    defaults.update(config)
    return Agent(mode=MODE_ENGAGE, **defaults)


print("■ オーナーの「静かにして」「もういいよ」")
a = agent()
a.runtime.submit(chat("アイ、10分静かにしてて", speaker="オーナー"))
check("返事をしてから静かにする（AIは呼ばない）", wait_until(lambda: a.speaker.spoken == ["わかった、静かにしてるね"]
                                                   and a.runtime.muted_until is not None, 5.0)
      and len(a.decide_calls()) == 0, (a.speaker.spoken, a.logs[-3:]))
check("どのくらいかを判断のログに", any("10分、静かにします" in line for line in a.logs))
a.runtime.submit(chat("アイ、聞いてる？"))
check("静かな間は、呼ばれても記録だけ（R12）", wait_until(lambda: any("R12" in line for line in a.logs), 5.0)
      and len(a.decide_calls()) == 0 and len(a.speaker.spoken) == 1)
a.runtime.submit(chat("アイ、もういいよ", speaker="オーナー"))
check("「もういいよ」で戻る", wait_until(lambda: a.speaker.spoken[-1:] == ["はーい、戻ったよ！"], 5.0)
      and a.runtime.muted_until is None)
a.runtime.submit(chat("アイ、聞いてる？"))
check("戻ったら、また判断する（合図への返事は回数の上限に数えない）", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0),
      a.logs[-3:])
a.runtime.submit(chat("アイ、静かにして", speaker="たろう"))
check("オーナーでない人の「静かにして」は合図にしない（ふつうに判断）", wait_until(lambda: len(a.decide_calls()) >= 2, 5.0)
      and a.runtime.muted_until is None)
spoken = len(a.speaker.spoken)
a.runtime.submit(chat("@アイ.. 席外すからマイクのミュートするんだけど、みんなに伝えといて", speaker="オーナー"))
check("オーナーが「ミュート」と書いても、頼む形でなければ静かにしない（伝言の頼みとして AI が判断する。2026-10-22）",
      wait_until(lambda: len(a.decide_calls()) >= 3, 5.0) and a.runtime.muted_until is None
      and "わかった、静かにしてるね" not in a.speaker.spoken[spoken:], (a.speaker.spoken[spoken:], a.logs[-3:]))
check("（2026-10-23 から）代わりに伝える頼みとして覚える", a.runtime._delegation is not None)
a.runtime._delegation = None          # 頼まれごとが無いときの「もういいよ」を確かめる
a.runtime.submit(chat("アイ、もういいよ", speaker="オーナー"))
check("静かにしていないとき（頼まれごとも無いとき）の「もういいよ」には「戻ったよ」と返さない（ふつうに判断）",
      wait_until(lambda: len(a.decide_calls()) >= 4, 5.0) and "はーい、戻ったよ！" not in a.speaker.spoken[spoken:],
      a.speaker.spoken[spoken:])
a.runtime.set_muted(5)
a.runtime._muted_until = time.time() - 1
check("時間が過ぎたら、ひとりでに戻る", a.runtime.muted_until is None)
a.close()

print("■ オーナーの代わりに伝える（2026-10-23 本人「チャットで（AIの名前）に代わりとして頼んだ時にそれを実行してくれたりしたら助かる」）")
from dataclasses import replace as _replace
from agent.events import KIND_CHAT_NOTICE
from agent.owner import CMD_DELEGATE, CMD_DELEGATE_END
check("頼み方を読む（実物 10/22 の言い回しをまねた文）: 代わりに伝える・既定60分",
      parse_command("@アイ.. トイレ行くから、マイクのミュートするんだけど、主が話せない理由も伝えといて", NAMES) == (CMD_DELEGATE, 60))
check("「30分」と書けば30分", parse_command("アイ、30分くらい代わりに入ってきた人に説明しといて", NAMES) == (CMD_DELEGATE, 30))
check("頼まれごとの間だけ「ただいま」「もういいよ」で終わる", parse_command("アイ、ただいま", NAMES, delegating=True)
      == (CMD_DELEGATE_END, None) and parse_command("アイ、もういいよ", NAMES, delegating=True) == (CMD_DELEGATE_END, None)
      and parse_command("アイ、ただいま", NAMES) is None)


def notice(name):
    return _replace(chat(f"{name}が音声ルームに参加しました", speaker=name), kind=KIND_CHAT_NOTICE)


a = agent(output_mode="chat", chat_send_mode="auto", chat_max_per_minute=10, max_decisions_per_minute=20,
          reconsider_enabled=False)
a.runtime.submit(chat("@アイ.. トイレ行ってくるから、入ってきた人に主は今トイレで話せないって伝えといて", speaker="オーナー"))
check("頼まれたら、覚えて、ふつうに返事をする（返事は AI が作る）", wait_until(lambda: len(a.chat.posted) == 1, 5.0)
      and any("代わりに伝える（60分" in line for line in a.logs) and a.runtime._delegation is not None, a.logs[-3:])
check("返事を作るときに、頼まれていること（オーナーの文は区切りの中）を渡す",
      "## オーナーから頼まれていること" in a.decide_calls()[-1].messages[0].content
      and "主は今トイレで話せない" in a.decide_calls()[-1].messages[0].content)
a.mock.script_decide = [{"action": "silent", "reason": "入室のお知らせだけ", "target": None}]
a.runtime.submit(notice("はなこ"))
check("新しく入ってきた人には、AI が黙ろうとしても代わりに伝える（目印を付けて渡す）", wait_until(lambda: len(a.chat.posted) == 2, 5.0)
      and "［オーナーの代わりに伝える相手］" in a.decide_calls()[-1].messages[0].content
      and any("オーナーの代わりに伝える相手なので黙らずに" in line for line in a.logs), a.logs[-3:])
gen = [r for r in a.mock.requests if r.purpose == "generate"]
check("文を作るときに「オーナーの代わりに、今の状況を短く伝える」と伝える・相手は入ってきた人",
      gen and "オーナーの代わりに" in gen[-1].messages[0].content and "相手: はなこ" in gen[-1].messages[0].content)
calls = len(a.decide_calls())
a.mock.script_decide = [{"action": "silent", "reason": "入室のお知らせだけ", "target": None}]
a.runtime.submit(notice("はなこ"))
check("同じ人には2度言わない", wait_until(lambda: len(a.decide_calls()) > calls, 5.0) and (time.sleep(0.5) or len(a.chat.posted) == 2),
      a.chat.posted)
a.mock.script_decide = [{"action": "silent", "reason": "割り込まない", "target": None}]
a.runtime.submit(chat("オーナーさん、いる？", speaker="じろう"))
check("オーナーに話しかけた人にも、代わりに伝える", wait_until(lambda: len(a.chat.posted) == 3, 5.0), a.chat.posted)
a.runtime.submit(chat("アイ、ただいま", speaker="オーナー"))
check("「ただいま」で終わり（決まった返事）", wait_until(lambda: a.chat.posted[-1:] == ["おかえり！伝えるのはやめておくね"], 5.0)
      and a.runtime._delegation is None, a.chat.posted[-2:])
calls = len(a.decide_calls())
a.mock.script_decide = [{"action": "silent", "reason": "入室のお知らせだけ", "target": None}]
a.runtime.submit(notice("さぶろう"))
check("終わったら、入ってきた人にも、ふつうに（黙ってよい）", wait_until(lambda: len(a.decide_calls()) > calls, 5.0)
      and (time.sleep(0.5) or a.chat.posted[-1] == "おかえり！伝えるのはやめておくね"), a.chat.posted[-2:])
a.runtime._delegation = {"text": "x", "owner": "オーナー", "until": time.time() - 1, "told": set()}
check("時間が過ぎたら終わり", a.runtime._delegation_active() is None and any("時間が過ぎた" in line for line in a.logs))
a.close()

print("■ オーナーの「タスクして」（2026-10-24 本人「チャットからタスクしてって言ったらこなしてくれるのかな」→ 作る）")
from agent.owner import CMD_TASKS
for text in ("アイ、タスクして", "@アイ.. タスクやっといて", "アイ デイリータスクこなしてきて", "アイ、タスクお願い",
             "アイ、タスク行ってきて"):
    check(f"頼む形なら合図:「{text}」", parse_command(text, NAMES) == (CMD_TASKS, None), parse_command(text, NAMES))
for text in ("アイ、タスクしてる？", "アイ、タスクやってないの？", "アイ、タスクやった？", "アイ、タスク終わった？",
             "タスクして"):           # 最後は AI に呼びかけていない
    check(f"様子・呼びかけなしは合図にしない:「{text}」", parse_command(text, NAMES) is None, parse_command(text, NAMES))


class FakeTasks:
    """画面側のにせもの。tasks_ready が返すわけと、run_tasks が呼ばれた時刻・そのときまでに出した返事を覚える"""

    def __init__(self, a, reason=None):
        self.a, self.reason, self.runs = a, reason, []

    def ready(self):
        return self.reason

    def run(self):
        self.runs.append(list(self.a.speaker.spoken))


a = agent()
tasks = FakeTasks(a)
a.runtime.deps.tasks_ready, a.runtime.deps.run_tasks = tasks.ready, tasks.run
a.runtime.submit(chat("アイ、タスクして", speaker="オーナー"))
check("「やってくるね」と返してから、画面側にタスクを頼む（AIは呼ばない）",
      wait_until(lambda: len(tasks.runs) == 1, 5.0)
      and tasks.runs[0] == ["わかった、タスクやってくるね！少しのあいだチャットを見られなくなるよ"]
      and len(a.decide_calls()) == 0, (tasks.runs, a.speaker.spoken))
check("判断のログに", any("タスクして → 監視を止めて" in line for line in a.logs), a.logs[-3:])
a.runtime.announce_tasks_result("done")
check("終わったら（画面側に頼まれて）「ただいま！タスク終わったよ」",
      wait_until(lambda: a.speaker.spoken[-1:] == ["ただいま！タスク終わったよ"], 5.0), a.speaker.spoken)
a.runtime.announce_tasks_result("already")
check("今日の分が済んでいたら、そう言う", wait_until(lambda: a.speaker.spoken[-1:] == ["ただいま！今日のタスクはもう終わってたよ"], 5.0),
      a.speaker.spoken)
a.runtime.submit(chat("アイ、タスクして", speaker="たろう"))
check("オーナーでない人の「タスクして」ではタスクをしない（ふつうに判断）", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
      and len(tasks.runs) == 1, tasks.runs)
a.close()

a = agent()
tasks = FakeTasks(a, reason="チャット欄を見ていないから")
a.runtime.deps.tasks_ready, a.runtime.deps.run_tasks = tasks.ready, tasks.run
a.runtime.submit(chat("アイ、タスクして", speaker="オーナー"))
check("始められなければ、わけを言って頼まない", wait_until(
    lambda: a.speaker.spoken == ["ごめん、今はタスクを始められないんだ（チャット欄を見ていないから）"], 5.0)
      and tasks.runs == [], (a.speaker.spoken, tasks.runs))
a.close()

a = agent(owner_tasks_enabled=False)
tasks = FakeTasks(a)
a.runtime.deps.tasks_ready, a.runtime.deps.run_tasks = tasks.ready, tasks.run
a.runtime.submit(chat("アイ、タスクして", speaker="オーナー"))
check("OFFなら断る", wait_until(lambda: a.speaker.spoken == ["ごめん、今はタスクをこなす設定がOFFなんだ"], 5.0)
      and tasks.runs == [], (a.speaker.spoken, tasks.runs))
a.close()
a = agent()
a.runtime.submit(chat("アイ、タスクして", speaker="オーナー"))
check("画面側の道具が無ければ（AIタブの手入力など）断る", wait_until(
    lambda: a.speaker.spoken == ["ごめん、今はタスクをこなす設定がOFFなんだ"], 5.0), a.speaker.spoken)
check("既定はON", AgentConfig().owner_tasks_enabled is True)
a.close()

print("■ オーナーの「覚えておいて」")
a = agent(memory_enabled=True)
a.runtime.submit(chat("こんばんは", speaker="たろう"))
wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
a.runtime.submit(chat("アイ、たろうさんは猫が好きって覚えておいて", speaker="オーナー"))
check("「覚えたよ！」と返す", wait_until(lambda: "覚えたよ！" in a.speaker.spoken, 5.0), a.speaker.spoken)
mems = a.store.memories_with_account(10)
check("「（オーナーから）」と付けて、その人の記憶にする（確かなメモにはしない）",
      [(m[1], m[2], m[3], m[4]) for m in mems] == [("テスト垢", "person", "たろう", "（オーナーから）たろうさんは猫が好き")], mems)
a.runtime.submit(chat("アイ、明日はイベントの日って覚えて", speaker="オーナー"))
check("人の名前が無ければ、この場の記憶", wait_until(
    lambda: any(m[2] == "room" and "明日はイベントの日" in m[4] for m in a.store.memories_with_account(10)), 5.0))
a.runtime.submit(chat("アイ、たろうさんは最近病院に通ってるって覚えて", speaker="オーナー"))
check("繊細な事柄は覚えない（そう返す）", wait_until(lambda: "それは覚えないでおくね" in a.speaker.spoken, 5.0)
      and not any("病院" in m[4] for m in a.store.memories_with_account(10)))
a.close()
a = agent(memory_enabled=False)
a.runtime.submit(chat("アイ、たろうさんは猫が好きって覚えて", speaker="オーナー"))
check("「会話を覚える」がOFFなら覚えない（そう返す）", wait_until(
    lambda: a.speaker.spoken == ["ごめん、今は覚える設定がOFFなんだ"], 5.0) and a.store.memories() == [])
a.close()

print("■ 反応しない人")
a = agent(ignored_people="荒らし、いたずら", memory_enabled=True)
a.runtime.submit(chat("アイ、なんか言えよ", speaker="荒らし"))
check("その人の発言だけなら記録だけ（AIを呼ばない・R11）", wait_until(lambda: any("R11" in line for line in a.logs), 5.0)
      and len(a.decide_calls()) == 0 and a.speaker.spoken == [])
a.runtime.submit(chat("アイ、聞いて", speaker="いたずら.."))
check("名前が切れて出ても見分ける", wait_until(lambda: sum("R11" in line for line in a.logs) >= 2, 5.0)
      and len(a.decide_calls()) == 0)
check("その人のことは覚えない", "荒らし" not in [r[1] for r in a.store.persons()])
a.runtime.submit(chat("今日は寒いね", speaker="はなこ"))
check("ほかの人の発言は判断する。窓の中の反応しない人の行には目印", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
      and "荒らし: アイ、なんか言えよ ［反応しない人］" in a.decide_calls()[-1].messages[0].content,
      a.decide_calls()[-1].messages[0].content[-500:] if a.decide_calls() else None)
check("固定の指示に「反応しない人には返事をしない」", "［反応しない人］には、反応も返事もしない" in a.decide_calls()[-1].system)
a.mock.script_decide = [{"action": "engage", "reason": "x", "target": "荒らし"}]
before = len(a.speaker.spoken)
a.runtime.submit(chat("アイ、どう思う？", speaker="はなこ"))
check("AIが反応しない人に話しかけようとしても喋らない", wait_until(
    lambda: any("は反応しない人です" in line for line in a.logs), 5.0) and len(a.speaker.spoken) == before)
a.close()

finish()
