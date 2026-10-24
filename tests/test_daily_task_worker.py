# -*- coding: utf-8 -*-
"""
GravityTaskWorker（タスク・ルーレットの実行役）を、実機の代わりの「にせのMuMu」で動かして確かめる。
にせのMuMuは fixtures/ の実物のダンプを画面として返し、押された場所に応じて次の画面へ切り替える。

確かめたいのは主に2つ:
  ・守り: 知らない画面（広告・音声ルーム）や、押してはいけないボタンの近くでは、押す操作を1つも送らない
  ・流れ: マイページから目的の画面まで移動し、こなし、結果を確かめるところまで通る
"""
import os, sys, re, tempfile
import xml.etree.ElementTree as ET

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import auto_reply_app as A

FAILS = []

def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILS.append(name)

def fixture(name):
    with open(os.path.join(_HERE, "fixtures", name), encoding="utf-8") as f:
        return f.read()

GRAVITY = "anonymous.sns.community.gravity"
CLS = "com.hiclub.android.gravity"


def edit_task_row(xml_text, title, progress, finish_mark):
    """タスク画面のダンプの1行だけを書き換える（未達成の状態の実物はまだ無いため）"""
    root = ET.fromstring(xml_text)
    parent = {c: p for p in root.iter() for c in p}
    title_node = next(n for n in root.iter("node") if n.get("text") == title)
    row = parent[parent[title_node]]
    for node in list(row.iter("node")):
        rid = A._resource_name(node)
        if rid == A.TASK_ROW_PROGRESS_ID:
            node.set("text", progress)
        if rid == A.TASK_ROW_FINISH_MARK_ID and not finish_mark:
            parent[node].remove(node)
    return ET.tostring(root, encoding="unicode")


def set_text_by_id(xml_text, resource_name, text):
    root = ET.fromstring(xml_text)
    for node in root.iter("node"):
        if A._resource_name(node) == resource_name:
            node.set("text", text)
    return ET.tostring(root, encoding="unicode")


AD_SCREEN = ('<hierarchy rotation="0"><node index="0" text="63s left to be rewarded" resource-id="" '
             'class="android.widget.TextView" package="anonymous.sns.community.gravity" content-desc="" '
             'clickable="false" bounds="[0,0][540,960]" display-id="2" />'
             '<node index="1" text="install" resource-id="" class="android.widget.TextView" '
             'package="anonymous.sns.community.gravity" content-desc="" clickable="true" '
             'bounds="[300,800][500,860]" display-id="2" /></hierarchy>')


class Resp:
    def __init__(self, output=""):
        self.output = output


class FakeMuMu:
    """worker が使う d.dump_hierarchy / d.shell / d.send_keys だけを持つ、にせの端末"""

    def __init__(self, screens, start, display="2", user="0"):
        self.screens = screens          # 名前 → [Activityのクラス, ダンプ]
        self.screen = start
        # GRAVITYが出ているディスプレイと、Androidのユーザー（本体=0、MuMuの「アプリ複製」=10〜）。
        # 画面のダンプは fixtures/ のまま（ディスプレイ2）持ち、返すときだけ番号を差し替える
        self.display = display
        self.user = user
        self.inputs = []                # 実際に送られた input コマンド
        self.taps = []                  # (画面の名前, x, y)
        self.focused = None
        self.on_tap = {}                # 画面の名前 → 関数(x, y) が次の画面名を返す（None なら同じ画面）
        self.on_swipe = {}
        self.on_back = {}

    # --- worker から呼ばれるもの ---
    def dump_hierarchy(self):
        return self.screens[self.screen][1].replace('display-id="2"', f'display-id="{self.display}"')

    def display_section(self):
        """dumpsys activity activities の、このディスプレイの区切り"""
        cls = self.screens[self.screen][0]
        package = "app.lawnchair" if cls.startswith(".Lawnchair") else GRAVITY
        return (f"Display #{self.display} (activities from top to bottom):\n"
                f"    topResumedActivity=ActivityRecord{{1 u{self.user} {package}/{cls} t56}}\n")

    def shell(self, command):
        if command.startswith("dumpsys activity activities"):
            return Resp("Display #0 (activities from top to bottom):\n"
                        "      topResumedActivity=ActivityRecord{2 u0 app.lawnchair/.LawnchairLauncher t2}\n"
                        + self.display_section())
        self.inputs.append(command)
        parts = command.split()
        assert parts[:3] == ["input", "-d", self.display], f"画面{self.display}以外へ送った: {command}"
        kind = parts[3]
        if kind == "tap":
            x, y = int(parts[4]), int(parts[5])
            self.taps.append((self.screen, x, y))
            handler = self.on_tap.get(self.screen)
            nxt = handler(x, y) if handler else None
        elif kind == "swipe":
            nxt = self.on_swipe.get(self.screen)
        elif kind == "keyevent":
            nxt = self.on_back.get(self.screen)
        else:
            nxt = None
        if nxt:
            self.screen = nxt
        return Resp("")

    def send_keys(self, text):
        name = self.screen
        cls, xml = self.screens[name]
        self.screens[name] = [cls, set_text_by_id(xml, self.focused, text)]


def inside(box, x, y):
    return box is not None and box[0] <= x <= box[2] and box[1] <= y <= box[3]


def new_worker():
    db = A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db"))
    db.save_setting("mumu_target_package", GRAVITY)
    logs = []
    w = A.GravityTaskWorker(db, logs.append)
    w.is_running = True
    w.SCREEN_WAIT_SECONDS = 0.3
    w.ROULETTE_RESULT_WAIT_SECONDS = 0.3
    return w, db, logs


# 実機を待たないように、待ち時間を0にする（このテストの中だけ）
A.time.sleep = lambda seconds: None


def base_screens():
    return {
        "mypage": [f"{CLS}.MainActivity", fixture("mypage.xml")],
        "feed": [f"{CLS}.MainActivity", fixture("feed_home.xml")],
        "task_top": [f"{CLS}.point.TaskCenterActivity", fixture("task_center_top.xml")],
        "task_scrolled": [f"{CLS}.point.TaskCenterActivity", fixture("task_center_scrolled.xml")],
        "task_points": [f"{CLS}.point.TaskCenterActivity", fixture("task_center_points.xml")],
        "roulette_before": [f"{CLS}.web.RewardAdWheelLotteryWebActivity", fixture("roulette_before.xml")],
        "roulette_dialog": [f"{CLS}.web.RewardAdWheelLotteryWebActivity", fixture("roulette_result_dialog.xml")],
        "roulette_after": [f"{CLS}.web.RewardAdWheelLotteryWebActivity", fixture("roulette_after.xml")],
        "compose": [f"{CLS}.addfeed.view.AddFeedActivity", fixture("compose.xml")],
        "ad": ["com.mbridge.msdk.reward.player.MBRewardVideoActivity", AD_SCREEN],
        "voiceroom": [f"{CLS}.metaverse.voiceroom.VoiceRoomType2Activity", fixture("mypage.xml")],
        # 実物の音声ルーム（ゲストの画面）と、「小さくする」を押した後のホーム画面（右に丸い窓が重なる）
        "room_guest": [f"{CLS}.metaverse.voiceroom.VoiceRoomActivity", fixture("voiceroom_guest.xml")],
        "room_minimized": [f"{CLS}.MainActivity", fixture("voiceroom_minimized.xml")],
    }


def wire_navigation(mu):
    """実機で確かめた画面の移り方を、にせのMuMuに教える"""
    s = mu.screens
    tab = lambda name, rid: A.find_by_id(s[name][1], rid, display=2)[0]

    def main_tabs(name):
        def handler(x, y):
            if inside(tab(name, "tab_center"), x, y):
                return "mypage"
            if inside(tab(name, "tab_feed"), x, y):
                return "feed"
            if name == "mypage" and inside(A.find_function_entry(s["mypage"][1], "タスク", display=2), x, y):
                return "task_top"
            if name == "feed" and inside(A.find_feed_add_button(s["feed"][1], display=2), x, y):
                return "compose"
            return None
        return handler

    mu.on_tap["mypage"] = main_tabs("mypage")
    mu.on_tap["feed"] = main_tabs("feed")
    mu.on_tap["room_minimized"] = main_tabs("room_minimized")
    mu.exited_room = False

    def room_tap(x, y):
        room = s["room_guest"][1]
        if inside(A.find_by_id(room, "ivExit", display=2)[0], x, y):
            mu.exited_room = True          # 押してはいけない（ルームから出てしまう）
            return "mypage"
        if inside(A.find_by_id(room, "ivZoomout", display=2)[0], x, y):
            return "room_minimized"
        return None
    mu.on_tap["room_guest"] = room_tap
    mu.on_swipe.update({"task_top": "task_scrolled", "task_scrolled": "task_points", "task_points": "task_points"})
    for name in ("task_top", "task_scrolled", "task_points"):
        mu.on_back[name] = "mypage"
    mu.on_tap["task_points"] = lambda x, y: (
        "roulette_before" if inside(A.find_point_shop_buttons(s["task_points"][1], display=2)[0], x, y) else None)
    mu.on_tap["roulette_before"] = lambda x, y: (
        "roulette_dialog" if inside(A.find_by_text(s["roulette_before"][1], A.ROULETTE_FREE_LABEL, display=2)[0], x, y)
        else None)
    mu.on_tap["roulette_dialog"] = lambda x, y: (
        "roulette_after" if inside(A.find_roulette_result_close(s["roulette_dialog"][1], display=2)[0], x, y) else None)
    mu.on_back["roulette_before"] = "task_top"
    mu.on_back["roulette_after"] = "task_top"
    mu.on_back["compose"] = "feed"

    def compose_tap(x, y):
        if inside(A.find_by_id(s["compose"][1], "etContent", display=2)[0], x, y):
            mu.focused = "etContent"
        if inside(A.find_by_id(s["compose"][1], "btnAddFeedSubmit", display=2)[0], x, y):
            mu.posted = A.text_by_id(s["compose"][1], "etContent", display=2)
            return "feed"
        return None
    mu.on_tap["compose"] = compose_tap


# ----------------------------------------------------------------------
print("■ 守り: 押してはいけないボタンの近くは押さない")
w, db, logs = new_worker()
mu = FakeMuMu(base_screens(), "roulette_before")
wire_navigation(mu)
try:
    w._tap(mu, 470, 925)
    check("2000/10回の余白内で止まる", False)
except A.TaskStop as e:
    check("2000/10回の余白内で止まる", "押してはいけないボタン" in str(e), str(e))
check("押す操作は1つも送っていない", mu.inputs == [], mu.inputs)
w._tap(mu, 274, 840)
check("「今日の初回チャンス」の中央は送る", mu.inputs == ["input -d 2 tap 274 840"], mu.inputs)

print("■ 守り: 広告の画面では、どこも押さない・戻るも押さない")
w, db, logs = new_worker()
mu = FakeMuMu(base_screens(), "ad")
for action in (lambda: w._tap(mu, 400, 830), lambda: w._keyevent(mu, A.ANDROID_KEYCODE_BACK),
               lambda: w._swipe(mu, 270, 760, 270, 520, 500), lambda: w._type_text(mu, "タスク")):
    try:
        action()
        check("広告の画面で止まる", False)
    except A.TaskStop as e:
        check("広告の画面で止まる", "知らない画面" in str(e), str(e))
check("広告の「install」を含め、何も送っていない", mu.inputs == [], mu.inputs)

print("■ 守り: 途中で音声ルームの画面になったら止める")
w, db, logs = new_worker()
mu = FakeMuMu(base_screens(), "voiceroom")
try:
    w._open_task_center(mu)
    check("音声ルームで止まる", False)
except A.TaskStop as e:
    check("音声ルームで止まる", "音声ルーム" in str(e), str(e))
check("戻るも押していない（勝手にルームを出ない）", mu.inputs == [], mu.inputs)

print("■ 守り: 中止ボタンが押されたら次の操作をしない")
w, db, logs = new_worker()
mu = FakeMuMu(base_screens(), "mypage")
w.is_running = False
try:
    w._tap(mu, 10, 10)
    check("中止で止まる", False)
except A.TaskCancelled:
    check("中止で止まる", True)
check("何も送っていない", mu.inputs == [])

# ----------------------------------------------------------------------
print("■ ルーレット: マイページから無料の1回を回して戻る")
w, db, logs = new_worker()
screens = base_screens()
mu = FakeMuMu(screens, "mypage")
wire_navigation(mu)
# 回した後はマイポイントが増えている（実機では 80200 → 80500）
def back_from_roulette():
    screens["task_top"][1] = set_text_by_id(screens["task_top"][1], "tvPoint", "80500")
mu.on_back["roulette_after"] = "task_top"
orig_shell = mu.shell
def shell_with_points(command):
    if "keyevent" in command and mu.screen == "roulette_after":
        back_from_roulette()
    return orig_shell(command)
mu.shell = shell_with_points
result = w._run_roulette(mu)
check("終わったらタスク画面に戻っている", mu.screen == "task_top", mu.screen)
check("お知らせは出さない（本人の番が無い）", result is None)
check("景品をログに出す", any("x300" in m for m in logs), logs)
check("ポイントの増減をログに出す", any("80200 → 80500" in m for m in logs), [m for m in logs if "ポイント" in m])
roulette_taps = [(s, x, y) for s, x, y in mu.taps if s.startswith("roulette")]
check("ルーレットの画面で押したのは2回（初回チャンスと×）", len(roulette_taps) == 2, roulette_taps)
for name, x, y in roulette_taps:
    boxes = A.find_forbidden_boxes(screens[name][1], display=2)
    check(f"{name} で押した ({x},{y}) は押してはいけない枠の外", A.tap_is_safe(x, y, boxes))

print("■ ルーレット: 今日はもう回していれば何もしない")
w, db, logs = new_worker()
screens = base_screens()
screens["roulette_before"] = screens["roulette_after"]   # 開いたら最初から「再チャレンジ」になっている
mu = FakeMuMu(screens, "mypage")
wire_navigation(mu)
mu.on_tap["task_points"] = lambda x, y: (
    "roulette_after" if inside(A.find_point_shop_buttons(screens["task_points"][1], display=2)[0], x, y) else None)
w._run_roulette(mu)
check("「もう回してあります」と出す", any("もう回してあります" in m for m in logs), logs[-3:])
check("ルーレットの画面では何も押していない", [t for t in mu.taps if t[0].startswith("roulette")] == [], mu.taps)

# ----------------------------------------------------------------------
print("■ タスク: 全部済みなら何もしない")
w, db, logs = new_worker()
mu = FakeMuMu(base_screens(), "mypage")
wire_navigation(mu)
result = w._run_daily_tasks(mu)
check("お知らせは出さない", result is None, result)
check("「全部済み」と出す", any("全部済み" in m for m in logs), logs[-2:])
check("タスク画面より先へは行っていない", mu.screen.startswith("task"), mu.screen)
check("ボットの番は全部済み（今日の分は済みと覚えてよい）", w._bot_part_complete is True)

print("■ タスク: 未達成の「投稿する」を投稿してから、済みになったか確かめる")
w, db, logs = new_worker()
screens = base_screens()
done_top = screens["task_top"][1]
screens["task_top"][1] = edit_task_row(done_top, "投稿する", "0/1回", finish_mark=False)
mu = FakeMuMu(screens, "mypage")
wire_navigation(mu)
mu.posted = None
compose_tap = mu.on_tap["compose"]
def compose_then_done(x, y):
    nxt = compose_tap(x, y)
    if nxt == "feed":
        screens["task_top"][1] = done_top     # 投稿したのでタスク画面の回数が 1/1 になる
    return nxt
mu.on_tap["compose"] = compose_then_done
result = w._run_daily_tasks(mu)
check("文面「タスク」で投稿した", mu.posted == "タスク", mu.posted)
check("済みになったのを確かめた", any("投稿する: 済みになりました" in m for m in logs), logs[-4:])
check("お知らせは出さない", result is None, result)
check("こなして済んだので、ボットの番は全部済み", w._bot_part_complete is True)

print("■ タスク: 投稿しても回数が増えなければ知らせる")
w, db, logs = new_worker()
screens = base_screens()
screens["task_top"][1] = edit_task_row(screens["task_top"][1], "投稿する", "0/1回", finish_mark=False)
mu = FakeMuMu(screens, "mypage")
wire_navigation(mu)
result = w._run_daily_tasks(mu)
check("知らせる", result is not None and "回数が増えていません" in result[1], result)
check("済んでいないので、今日の分は済みと覚えない", w._bot_part_complete is False)

print("■ タスク: 広告が残っていれば、ご自身の番として知らせる（広告には触らない）")
w, db, logs = new_worker()
screens = base_screens()
screens["task_scrolled"][1] = edit_task_row(screens["task_scrolled"][1], "広告を最後まで見る", "2/5回", finish_mark=False)
mu = FakeMuMu(screens, "mypage")
wire_navigation(mu)
result = w._run_daily_tasks(mu)
check("知らせる", result is not None and "広告を最後まで見る（2/5回）" in result[1], result)
check("理由を添える", result is not None and "人が見るもの" in result[1], result)
check("タスク画面では何も押していない", [t for t in mu.taps if t[0].startswith("task")] == [], mu.taps)
check("広告はご自身の番なので、ボットの番は全部済み", w._bot_part_complete is True)

print("■ タスク: 回数は達成・印なし（受け取り待ち）なら、受け取りはせずに知らせる")
w, db, logs = new_worker()
screens = base_screens()
screens["task_top"][1] = edit_task_row(screens["task_top"][1], "投稿する", "1/1回", finish_mark=False)
mu = FakeMuMu(screens, "mypage")
wire_navigation(mu)
result = w._run_daily_tasks(mu)
check("受け取り待ちとして知らせる", result is not None and "受け取り待ち" in result[1] and "2倍" in result[1], result)
check("「判断できない」とは言わない", result is not None and "判断できませんでした" not in result[1], result)
check("もう一度投稿したりしない", not any(s == "compose" for s, _, _ in mu.taps), mu.taps)
check("受け取り待ちは、ボットの番としては済み", w._bot_part_complete is True)
check("タスク画面では何も押していない", [t for t in mu.taps if t[0].startswith("task")] == [], mu.taps)

print("■ タスク: こなした後に受け取り待ちになったら、「回数が増えていない」ではなく受け取り待ちと知らせる")
w, db, logs = new_worker()
screens = base_screens()
done_top = screens["task_top"][1]
screens["task_top"][1] = edit_task_row(done_top, "投稿する", "0/1回", finish_mark=False)
mu = FakeMuMu(screens, "mypage")
wire_navigation(mu)
compose_tap = mu.on_tap["compose"]
def compose_then_unclaimed(x, y):
    nxt = compose_tap(x, y)
    if nxt == "feed":
        screens["task_top"][1] = edit_task_row(done_top, "投稿する", "1/1回", finish_mark=False)
    return nxt
mu.on_tap["compose"] = compose_then_unclaimed
result = w._run_daily_tasks(mu)
check("こなして受け取り待ちと知らせる", result is not None and "こなしました。報酬の受け取り待ち" in result[1], result)
check("「回数が増えていません」とは言わない", result is not None and "回数が増えていません" not in result[1], result)

print("■ タスク: 途中で報酬の受け取りの画面が出たら、どちらのボタンも押さずに止める（⚠️ 画面は仮）")
w, db, logs = new_worker()
screens = base_screens()
screens["task_top"][1] = edit_task_row(screens["task_top"][1], "投稿する", "0/1回", finish_mark=False)
reward_xml = ('<hierarchy rotation="0"><node index="0" text="" resource-id="" class="android.widget.FrameLayout" '
              f'package="{GRAVITY}" content-desc="" clickable="false" bounds="[0,0][540,960]" display-id="2">'
              f'<node index="0" text="そのまま受け取る" resource-id="" class="android.widget.TextView" package="{GRAVITY}" '
              'content-desc="" clickable="true" bounds="[80,600][260,660]" display-id="2" />'
              f'<node index="1" text="広告を見て2倍受け取る" resource-id="" class="android.widget.TextView" package="{GRAVITY}" '
              'content-desc="" clickable="true" bounds="[280,600][460,660]" display-id="2" /></node></hierarchy>')
screens["reward"] = [f"{CLS}.MainActivity", reward_xml]
mu = FakeMuMu(screens, "mypage")
wire_navigation(mu)
compose_tap = mu.on_tap["compose"]
mu.on_tap["compose"] = lambda x, y: "reward" if compose_tap(x, y) == "feed" else None   # 投稿したら受け取りの画面が出る
try:
    w._run_daily_tasks(mu)
    check("止まる", False)
except A.TaskStop as e:
    check("止まる", "報酬の受け取りの画面" in str(e) and "どちらも押していません" in str(e), str(e))
check("受け取りの画面では何も押していない", [t for t in mu.taps if t[0] == "reward"] == [], mu.taps)

print("■ タスク: 送り先が未設定なら、メッセージは飛ばして知らせる")
w, db, logs = new_worker()
screens = base_screens()
screens["task_scrolled"][1] = edit_task_row(screens["task_scrolled"][1], "ユーザーにメッセージを送る", "0/1回", False)
mu = FakeMuMu(screens, "mypage")
wire_navigation(mu)
result = w._run_daily_tasks(mu)
check("飛ばして知らせる", result is not None and "送り先が決まっていない" in result[1], result)
check("飛ばしたので、今日の分は済みと覚えない", w._bot_part_complete is False)

print("■ タスク: 途中で知らない画面（広告）が出たら、その場で止める")
w, db, logs = new_worker()
screens = base_screens()
screens["task_top"][1] = edit_task_row(screens["task_top"][1], "投稿する", "0/1回", finish_mark=False)
mu = FakeMuMu(screens, "mypage")
wire_navigation(mu)
feed_tap = mu.on_tap["feed"]
mu.on_tap["feed"] = lambda x, y: "ad" if feed_tap(x, y) == "compose" else feed_tap(x, y)
try:
    w._run_daily_tasks(mu)
    check("止まる", False)
except A.TaskStop as e:
    check("止まる", "知らない画面" in str(e), str(e))
check("広告の画面では何も押していない", [t for t in mu.taps if t[0] == "ad"] == [], mu.taps)

# ----------------------------------------------------------------------
print("■ 音声ルームから始めたら、退出せずに「小さくする」を押してから始める（本人の指示）")
w, db, logs = new_worker()
screens = base_screens()
mu = FakeMuMu(screens, "room_guest")
wire_navigation(mu)
w._connect_to_emulator = lambda: mu        # 実機につながずに _job_main を通す
notices = []
w.notify_callback = lambda title, message: notices.append((title, message))
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("最初に押したのは「小さくする」(449,28)", mu.taps[:1] == [("room_guest", 449, 28)], mu.taps[:2])
check("退出は押していない", not mu.exited_room)
check("ルームの画面で押したのは1回だけ", len([t for t in mu.taps if t[0] == "room_guest"]) == 1, mu.taps)
check("小さくした後、そのままルーレットを回した", any("x300" in m for m in logs), logs[-5:])
check("終わってもルームには戻らない（丸は押していない）", not any(
    s == "room_minimized" and inside((412, 650, 540, 778), x, y) for s, x, y in mu.taps), mu.taps)
check("戻り方をログで伝える", any("右の丸を押すとルームに戻れます" in m for m in logs), logs[-2:])
check("止まった知らせは出ない", notices == [], notices)

# ----------------------------------------------------------------------
# 2026-10-24 本人「チャットからタスクしてって言ったら」→ 作る・「ルームに戻る」。チャットで頼まれたときだけ、終わったら丸を押して戻る
BUBBLE = (f'<node index="0" text="" resource-id="{GRAVITY}:id/bpvVoiceRoom" class="android.widget.RelativeLayout" '
          f'package="{GRAVITY}" content-desc="" clickable="false" bounds="[412,650][540,778]" display-id="2" />')


class BubbleMuMu(FakeMuMu):
    """小さくしたあとは、ルーム以外のどの画面にも丸(bpvVoiceRoom)が重なって読める（実機の記録 2026-10-14）。丸を押すとルームに戻る"""

    def __init__(self, *args, bubble=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.minimized, self.bubble = False, bubble

    def dump_hierarchy(self):
        xml = super().dump_hierarchy()
        if self.minimized and self.bubble and self.screen != "room_guest" and "bpvVoiceRoom" not in xml:
            xml = xml.replace("</hierarchy>", BUBBLE.replace('display-id="2"', f'display-id="{self.display}"') + "</hierarchy>")
        return xml


def bubble_room(start="room_guest", bubble=True):
    mu = BubbleMuMu(base_screens(), start, bubble=bubble)
    wire_navigation(mu)
    room_tap = mu.on_tap["room_guest"]

    def minimize(x, y):
        nxt = room_tap(x, y)
        if nxt == "room_minimized":
            mu.minimized = True
        return nxt
    mu.on_tap["room_guest"] = minimize
    for name in list(mu.screens):
        if name == "room_guest":
            continue
        original = mu.on_tap.get(name)

        def tap(x, y, original=original):
            if mu.minimized and mu.bubble and inside((412, 650, 540, 778), x, y):
                mu.minimized = False
                return "room_guest"
            return original(x, y) if original else None
        mu.on_tap[name] = tap
    return mu


print("■ チャットで頼まれたら、終わったあと小さくしたルームの丸を押してルームに戻る（2026-10-24）")
w, db, logs = new_worker()
mu = bubble_room()
w._connect_to_emulator = lambda: mu
w.return_to_room = True
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("始めに「小さくする」を押した", mu.taps[:1] == [("room_guest", 449, 28)], mu.taps[:2])
check("ルーレットを回した", any("x300" in m for m in logs), logs[-6:])
check("最後に押したのは丸（ルームに戻る）", inside((412, 650, 540, 778), mu.taps[-1][1], mu.taps[-1][2])
      and mu.taps[-1][0] != "room_guest", mu.taps[-2:])
check("ルームの画面に戻った", mu.screen == "room_guest" and w.returned_to_room is True, (mu.screen, w.returned_to_room))
check("終わり方は done", w.outcome == "done", w.outcome)
check("戻ったことをログに", any("音声ルームに戻りました" in m for m in logs)
      and not any("小さくしたままです" in m for m in logs), logs[-3:])
check("退出は押していない", not mu.exited_room)
check("入力はすべて、こなした画面へ", all(c.startswith(f"input -d {mu.display} ") for c in mu.inputs), mu.inputs[-3:])

print("■ 丸が見つからなければ、戻れなかったと返す（押さない）")
w, db, logs = new_worker()
mu = bubble_room(bubble=False)
w._connect_to_emulator = lambda: mu
w.return_to_room = True
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("戻れなかった", w.returned_to_room is False and mu.screen != "room_guest", (w.returned_to_room, mu.screen))
check("わけをログに", any("丸が見つからない" in m for m in logs), logs[-3:])
check("丸のあたりは押していない", not any(inside((412, 650, 540, 778), x, y) for _, x, y in mu.taps), mu.taps[-3:])

print("■ ルームから始めていなければ（小さくしていなければ）、戻るものは無い")
w, db, logs = new_worker()
mu = bubble_room(start="mypage")
w._connect_to_emulator = lambda: mu
w.return_to_room = True
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("戻れた扱い（そのまま監視を再開してよい）・丸は押していない", w.returned_to_room is True
      and not any(inside((412, 650, 540, 778), x, y) for _, x, y in mu.taps), (w.returned_to_room, mu.taps[-2:]))

print("■ ボタンで始めたときは、今まで通り戻らない（2026-10-14 本人の決定）")
w, db, logs = new_worker()
mu = bubble_room()
w._connect_to_emulator = lambda: mu
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("丸は押さず、戻り方をログで伝える", mu.screen != "room_guest" and any("小さくしたままです" in m for m in logs)
      and not any(s != "room_guest" and inside((412, 650, 540, 778), x, y) for s, x, y in mu.taps), (mu.screen, logs[-2:]))

print("■ 今日の分が済んでいたら、終わり方は already（ルームは小さくしない）")
w, db, logs = new_worker()
mu = bubble_room()
w._connect_to_emulator = lambda: mu
w._open_windows = lambda d: [{"user": "0", "display": mu.display}]
w._load_accounts = lambda: {"0": {w.JOB_DONE_FIELDS[A.GravityTaskWorker.JOB_ROULETTE]: w._today()}}
w.return_to_room = True
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("already・ルームのまま・何も押していない", w.outcome == "already" and w.returned_to_room is True and mu.taps == []
      and mu.screen == "room_guest", (w.outcome, mu.taps))

print("■ 「小さくする」が退出に近すぎたら、押さずに止める")
w, db, logs = new_worker()
screens = base_screens()
# 「小さくする」の位置を、退出(483〜530)にくっつく [466,5][484,52] にずらす。
# 中央 x=475 は、退出の左端483から余白10pxの内側（473〜）に入る
root = ET.fromstring(screens["room_guest"][1])
for node in root.iter("node"):
    if A._resource_name(node) == "ivZoomout":
        node.set("bounds", "[466,5][484,52]")
screens["room_guest"][1] = ET.tostring(root, encoding="unicode")
mu = FakeMuMu(screens, "room_guest")
wire_navigation(mu)
try:
    w._minimize_voice_room_if_needed(mu)
    check("止まる", False)
except A.TaskStop as e:
    check("止まる", "近すぎた" in str(e), str(e))
check("何も押していない", mu.inputs == [], mu.inputs)

print("■ 音声ルームでなければ、何もしない")
w, db, logs = new_worker()
mu = FakeMuMu(base_screens(), "mypage")
w._minimize_voice_room_if_needed(mu)
check("押していない", mu.inputs == [], mu.inputs)

print("■ 小さくしたルームの丸は押さない")
w, db, logs = new_worker()
mu = FakeMuMu(base_screens(), "room_minimized")
try:
    w._tap(mu, 476, 714)
    check("止まる", False)
except A.TaskStop as e:
    check("止まる", "押してはいけない" in str(e), str(e))
check("何も押していない", mu.inputs == [], mu.inputs)

# ⚠️ 2026-10-14 実測: ルームを小さくすると、ホームではなくルームに入る前の画面に戻る
#    （グループチャットの案内から入っていたので、グループチャットに戻った）
SEARCH_SCREEN = (f'<hierarchy rotation="0"><node index="0" text="" resource-id="" class="android.widget.FrameLayout" '
                 f'package="{GRAVITY}" content-desc="" clickable="false" bounds="[0,0][540,960]" display-id="2" />'
                 '</hierarchy>')


def room_entered_from(entry_screens, entry):
    """ルームに entry から入っていた端末。小さくすると entry に戻る"""
    screens = base_screens()
    screens.update(entry_screens)
    mu = FakeMuMu(screens, "room_guest")
    wire_navigation(mu)
    room_tap = mu.on_tap["room_guest"]
    mu.on_tap["room_guest"] = lambda x, y: entry if room_tap(x, y) == "room_minimized" else room_tap(x, y)
    return mu


print("■ グループチャットから入ったルームで始めたら、小さくした後、戻るでホームへ移ってからこなす")
w, db, logs = new_worker()
mu = room_entered_from({"group_chat": [f"{CLS}.message.view.MsgDetailGroupActivity", fixture("group_chat.xml")]},
                       "group_chat")
mu.on_back["group_chat"] = "room_minimized"
w._connect_to_emulator = lambda: mu
notices = []
w.notify_callback = lambda title, message: notices.append((title, message))
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("止まらずにルーレットまで回した", any("x300" in m for m in logs) and notices == [], (notices, logs[-4:]))
check("グループチャットでは何も押していない（ルームの案内を押すと入室する）",
      not any(s == "group_chat" for s, _, _ in mu.taps), mu.taps)
check("グループチャットで押したのは戻るだけ",
      any("keyevent 4" in c for c in mu.inputs), [c for c in mu.inputs if "keyevent" in c])
check("ルームに入る前の画面に戻ったことをログに出す", any("ルームに入る前の画面" in m for m in logs), logs[:6])
check("退出は押していない", not mu.exited_room)

print("■ ルームの検索から入ったルーム: 1回目の戻るはキーボードを閉じるだけでも、続けて戻る")
w, db, logs = new_worker()
search_cls = f"{CLS}.metaverse.voiceroom.VoiceRoomSearchActivity"
mu = room_entered_from({"room_search_kb": [search_cls, SEARCH_SCREEN], "room_search": [search_cls, SEARCH_SCREEN]},
                       "room_search_kb")
mu.on_back.update({"room_search_kb": "room_search", "room_search": "room_minimized"})
w._connect_to_emulator = lambda: mu
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("ホームまで戻ってルーレットを回した", any("x300" in m for m in logs), logs[-4:])
check("ルームの検索では何も押していない（ルームが並んでいる）",
      not any(s.startswith("room_search") for s, _, _ in mu.taps), mu.taps)

print("■ グループチャットの画面から始めても、戻るでホームへ移ってからこなす")
w, db, logs = new_worker()
screens = base_screens()
screens["group_chat"] = [f"{CLS}.message.view.MsgDetailGroupActivity", fixture("group_chat.xml")]
mu = FakeMuMu(screens, "group_chat")
wire_navigation(mu)
mu.on_back["group_chat"] = "mypage"
w._connect_to_emulator = lambda: mu
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("ルーレットを回した", any("x300" in m for m in logs), logs[-4:])
check("グループチャットでは何も押していない", not any(s == "group_chat" for s, _, _ in mu.taps), mu.taps)

print("■ 小さくした後に知らない画面が出たら、戻るも押さずに止める")
w, db, logs = new_worker()
mu = room_entered_from({}, "ad")
try:
    w._minimize_voice_room_if_needed(mu)
    w._go_main(mu, "tab_center")
    check("止まる", False)
except A.TaskStop as e:
    check("止まる", "知らない画面" in str(e), str(e))
check("押したのは「小さくする」だけ（広告の画面では戻るも押さない）", mu.inputs == ["input -d 2 tap 449 28"], mu.inputs)

# ----------------------------------------------------------------------
# 心のこもった「いいね」（本人の指示: 行の「チャレンジ」→ 一覧で普通のハートを押す）
HEART_TITLE = "心のこもった「いいね」をする"


def set_like_count(xml_text, index, value):
    """一覧の index 番目の投稿の、いいね数の表示を書き換える"""
    root = ET.fromstring(xml_text)
    parent = {c: p for p in root.iter() for c in p}
    cards = [n for n in root.iter("node") if A._resource_name(n) == "cvRoot"]
    for node in cards[index].iter("node"):
        if A._resource_name(node) == "tvLike" and A._resource_name(parent[parent[node]]) == "includeFeedActionBar":
            node.set("text", str(value))
    return ET.tostring(root, encoding="unicode")


def heart_screens(progress, already_liked=()):
    """タスク画面（いいねの行が progress）と、いいねの一覧。already_liked の番号の投稿は、いいね済み"""
    s = base_screens()
    s["task_top"][1] = edit_task_row(fixture("task_center_todo_top.xml"), HEART_TITLE, progress, finish_mark=False)
    s["task_top"][0] = f"{CLS}.point.TaskCenterActivity"
    s["heart"] = [f"{CLS}.feed.view.FeedListActivity", fixture("feed_heart_list.xml")]
    return s


def wire_heart(mu, already_liked=()):
    s = mu.screens
    wire_navigation(mu)
    base = [t["count"] for t in A.find_feed_like_targets(s["heart"][1], display=2)]
    liked = [i in already_liked for i in range(len(base))]   # いいね済みなら、表示の数に自分の分が入っている
    shown_base = [b - (1 if liked[i] else 0) for i, b in enumerate(base)]
    mu.on_tap["task_top"] = lambda x, y: (
        "heart" if inside(A.find_task_challenge(s["task_top"][1], HEART_TITLE, display=2), x, y) else None)
    mu.on_back["heart"] = "task_top"

    def heart_tap(x, y):
        for i, t in enumerate(A.find_feed_like_targets(s["heart"][1], display=2)):
            if inside(t["like_box"], x, y):
                liked[i] = not liked[i]            # ハートは押すたびに「いいね」と「取り消し」が入れ替わる
                s["heart"][1] = set_like_count(s["heart"][1], i, shown_base[i] + (1 if liked[i] else 0))
        return None
    mu.on_tap["heart"] = heart_tap
    mu.on_swipe["heart"] = "heart"                 # これ以上の投稿は無い
    return liked


print("■ 心のこもった「いいね」: 「チャレンジ」→ 一覧でハートを押し、数が1増えたかを確かめる")
w, db, logs = new_worker()
mu = FakeMuMu(heart_screens("38/40回"), "mypage")
liked = wire_heart(mu)
row = next(r for r in A.parse_task_rows(mu.screens["task_top"][1], display=2) if r["title"] == HEART_TITLE)
w._do_like(mu, row)
check("残り2件をいいねした", liked == [True, True], liked)
check("「いいね 2/2」まで数えた", any("いいね 2/2" in m for m in logs), logs[-4:])
check("いいねの行の「チャレンジ」から開いた", any(s == "task_top" for s, _, _ in mu.taps), mu.taps)
check("「クリア」（投稿の受け取り）は押していない", not any(
    s == "task_top" and inside((386, 719, 488, 757), x, y) for s, x, y in mu.taps), mu.taps)

print("■ 心のこもった「いいね」: いいね済みの投稿は、押して減ったらもう一度押して元に戻し、数えない")
w, db, logs = new_worker()
w.MAX_LIKE_SCROLLS = 2
mu = FakeMuMu(heart_screens("38/40回"), "mypage")
liked = wire_heart(mu, already_liked=(0,))
w._do_like(mu, row)
check("いいね済みの投稿は、いいねされたまま（元に戻した）", liked[0] is True, liked)
check("もう1件はいいねした", liked[1] is True, liked)
check("元に戻したことをログに出す", any("元に戻しました" in m for m in logs), logs[-6:])
check("数えたのは1件だけ（2件目は見つからない）", any("1/2 件" in m for m in logs), logs[-3:])
heart_taps = [(x, y) for s, x, y in mu.taps if s == "heart"]
check("1件目は2回（取り消し→戻す）、2件目は1回押した", len(heart_taps) == 3, heart_taps)

print("■ 心のこもった「いいね」: 一覧の投稿が尽きたら、開き直して続ける（2026-10-12 実機: 1回目は20件で尽きた）")
w, db, logs = new_worker()
screens = heart_screens("37/40回")                  # 残り3件。1つ目の一覧には2件しかない
# 開き直したときに出る、別の投稿の一覧（名前と時刻を変えて、新しい投稿にする）
root = ET.fromstring(screens["heart"][1])
for node in root.iter("node"):
    if A._resource_name(node) == "tv_time" and node.get("text"):
        node.set("text", "10/12 " + node.get("text")[-5:])
screens["heart2"] = [screens["heart"][0], ET.tostring(root, encoding="unicode")]
mu = FakeMuMu(screens, "mypage")
liked = wire_heart(mu)
opened = []
def open_list(x, y):
    if inside(A.find_task_challenge(screens["task_top"][1], HEART_TITLE, display=2), x, y):
        opened.append(1)
        return "heart" if len(opened) == 1 else "heart2"
    return None
mu.on_tap["task_top"] = open_list
mu.on_back["heart2"] = "task_top"
mu.on_swipe["heart2"] = "heart2"
liked2 = []
def heart2_tap(x, y):
    for i, t in enumerate(A.find_feed_like_targets(screens["heart2"][1], display=2)):
        if inside(t["like_box"], x, y):
            liked2.append(i)
            screens["heart2"][1] = set_like_count(screens["heart2"][1], i, t["count"] + 1)
mu.on_tap["heart2"] = heart2_tap
row = next(r for r in A.parse_task_rows(screens["task_top"][1], display=2) if r["title"] == HEART_TITLE)
w._do_like(mu, row)
check("一覧を開き直した", len(opened) == 2, opened)
check("1つ目の一覧で2件、開き直した一覧で1件", liked == [True, True] and liked2 == [0], (liked, liked2))
check("「開き直します」とログに出す", any("開き直します" in m for m in logs), logs[-6:])
check("3/3件で終わる", any("いいねを 3 件しました" in m for m in logs), logs[-2:])
check("一覧の下まで来たら、何十回もスクロールしない（送っても動かないことが2回で気付く）",
      len([c for c in mu.inputs if "swipe" in c]) <= 4, [c for c in mu.inputs if "swipe" in c])


def heart_page(xml_text, label, dy=0, hide_time=False):
    """
    いいねの一覧を送った先の画面を作る。時刻の頭を label にして別の投稿にし、投稿の枠を dy だけずらす。
    hide_time なら時刻を消す（縦に長い投稿の途中で、名前と時刻が上に隠れ、いいねできる投稿が見えない画面）
    """
    root = ET.fromstring(xml_text)
    for card in [n for n in root.iter("node") if A._resource_name(n) == "cvRoot"]:
        for node in card.iter("node"):
            if A._resource_name(node) == "tv_time" and node.get("text"):
                node.set("text", "" if hide_time else f"{label} {node.get('text')[-5:]}")
            x1, y1, x2, y2 = map(int, re.findall(r"-?\d+", node.get("bounds")))
            node.set("bounds", f"[{x1},{y1 + dy}][{x2},{y2 + dy}]")
    return ET.tostring(root, encoding="unicode")


print("■ 心のこもった「いいね」: 長い一覧は、いいねしながら下まで送り続ける"
      "（2026-10-13 本人: ほとんど送っていないのに「できない」と出た）")
w, db, logs = new_worker()
screens = heart_screens("34/40回")                  # 残り6件。いいねできる投稿は 1・4・7 枚目の画面に2件ずつ
base_heart = screens["heart"][1]
pages = [("p0", heart_page(base_heart, "10/01")),
         ("gap1", heart_page(base_heart, "", dy=-60, hide_time=True)),
         ("gap2", heart_page(base_heart, "", dy=-120, hide_time=True)),
         ("p1", heart_page(base_heart, "10/02")),
         ("gap3", heart_page(base_heart, "", dy=-60, hide_time=True)),
         ("gap4", heart_page(base_heart, "", dy=-120, hide_time=True)),
         ("p2", heart_page(base_heart, "10/03"))]
for name, xml_text in pages:
    screens[name] = [screens["heart"][0], xml_text]
mu = FakeMuMu(screens, "mypage")
wire_navigation(mu)
opened, liked_keys = [], []
def open_long_list(x, y):
    if inside(A.find_task_challenge(screens["task_top"][1], HEART_TITLE, display=2), x, y):
        opened.append(1)
        return "p0"
    return None
mu.on_tap["task_top"] = open_long_list
def long_list_tap(page):
    def handler(x, y):
        for i, t in enumerate(A.find_feed_like_targets(screens[page][1], display=2)):
            if inside(t["like_box"], x, y):
                liked_keys.append(t["key"])
                screens[page][1] = set_like_count(screens[page][1], i, t["count"] + 1)
        return None
    return handler
for i, (name, _) in enumerate(pages):
    mu.on_tap[name] = long_list_tap(name)
    mu.on_swipe[name] = pages[i + 1][0] if i + 1 < len(pages) else name   # 最後の画面より下は無い
    mu.on_back[name] = "task_top"
row = next(r for r in A.parse_task_rows(screens["task_top"][1], display=2) if r["title"] == HEART_TITLE)
w._do_like(mu, row)
check("6件ともいいねした", len(liked_keys) == 6 and len(set(liked_keys)) == 6, liked_keys)
check("いちばん下の画面の投稿までいいねした", sum(1 for k in liked_keys if k[1].startswith("10/03")) == 2, liked_keys)
check("途中の画面で「下まで来た」と誤らない（開き直していない）", len(opened) == 1, opened)
check("「いいねを 6 件しました」で終わる", any("いいねを 6 件しました" in m for m in logs), logs[-3:])

print("■ 一覧の目印は、いいね数が変わっても同じ・送ると変わる")
heart_xml = fixture("feed_heart_list.xml")
check("いいね数だけ変えても同じ", A.feed_list_signature(heart_xml, 2)
      == A.feed_list_signature(set_like_count(heart_xml, 0, 999), 2))
check("枠がずれたら変わる", A.feed_list_signature(heart_xml, 2)
      != A.feed_list_signature(heart_page(heart_xml, "", dy=-60, hide_time=True), 2))

print("■ 一覧の題名だけ出て投稿がまだ無いうちは、読み始めない（空の一覧を送って「下まで来た」と誤らない）")
w, db, logs = new_worker()
screens = heart_screens("39/40回")
mu = FakeMuMu(screens, "mypage")
liked = wire_heart(mu)
loaded = screens["heart"][1]
root = ET.fromstring(loaded)
parent = {c: p for p in root.iter() for c in p}
for card in [n for n in root.iter("node") if A._resource_name(n) == "cvRoot"]:
    parent[card].remove(card)
screens["heart"][1] = ET.tostring(root, encoding="unicode")     # 題名はあるが、投稿はまだ出ていない
row = next(r for r in A.parse_task_rows(screens["task_top"][1], display=2) if r["title"] == HEART_TITLE)
reads = [0]
real_dump = mu.dump_hierarchy
def dump_then_load():
    if mu.screen == "heart":
        reads[0] += 1
        if reads[0] == 3:                          # 3回目に読んだときに投稿が出る
            screens["heart"][1] = loaded
    return real_dump()
mu.dump_hierarchy = dump_then_load
w._do_like(mu, row)
check("投稿が出てからいいねした", liked[0] is True, liked)
check("投稿が出る前に送っていない", not any("swipe" in c for c in mu.inputs), mu.inputs)

print("■ 増えたが済みになっていないときは「前 → 後」で知らせる（2026-10-12 実機で誤って「増えていません」と出た）")
w, db, logs = new_worker()
w.MAX_LIKE_SCROLLS = 2
screens = heart_screens("38/40回")
mu = FakeMuMu(screens, "mypage")
liked = wire_heart(mu, already_liked=(0,))       # 2件のうち1件はいいね済み → 1件しか増やせない
heart_tap = mu.on_tap["heart"]
def heart_tap_and_count(x, y):
    heart_tap(x, y)
    screens["task_top"][1] = edit_task_row(fixture("task_center_todo_top.xml"), HEART_TITLE,
                                           f"{38 + sum(liked) - 1}/40回", finish_mark=False)
mu.on_tap["heart"] = heart_tap_and_count
result = w._run_daily_tasks(mu)
check("「38/40回 → 39/40回」と前後を並べる", result is not None and "38/40回 → 39/40回" in result[1], result)
check("「回数が増えていません」とは言わない", result is not None and "心のこもった「いいね」をする: こなしましたが、回数が増えていません"
      not in result[1], result)

# ----------------------------------------------------------------------
# コメント・メッセージ・フォロー。送り先は仮の名前「テストの相手さんです」
# （実物の一覧には、送り先と、その名前の一部を含む似た名前の別人がいた。その関係を仮の名前で保ってある）
WANTED = "テストの相手さんです"


def social_screens():
    s = base_screens()
    s.update({
        "rel_recommended": [f"{CLS}.center.view.profile.RelationshipListActivityV2", fixture("friends_list_recommended.xml")],
        "rel_friends": [f"{CLS}.center.view.profile.RelationshipListActivityV2", fixture("friends_list.xml")],
        "profile_top": [f"{CLS}.center.view.profile.CenterActivity", fixture("friend_profile_top.xml")],
        "profile_pinned": [f"{CLS}.center.view.profile.CenterActivity", fixture("friend_profile_pinned_only.xml")],
        "profile_posts": [f"{CLS}.center.view.profile.CenterActivity", fixture("friend_profile_posts.xml")],
        "friend_detail": [f"{CLS}.feed.view.NewFeedDetailActivity", fixture("friend_post_detail.xml")],
        "chat": [f"{CLS}.message.view.MessageDetailActivity", fixture("chat.xml")],
        "detail_follow": [f"{CLS}.feed.view.NewFeedDetailActivity", fixture("post_detail_follow.xml")],
        "detail_following": [f"{CLS}.feed.view.NewFeedDetailActivity", fixture("post_detail_following.xml")],
        "unfollow_dialog": [f"{CLS}.feed.view.NewFeedDetailActivity", fixture("unfollow_dialog.xml")],
    })
    return s


def wire_social(mu):
    s = mu.screens
    wire_navigation(mu)
    mu.sent = []
    mypage_tap = mu.on_tap["mypage"]
    mu.on_tap["mypage"] = lambda x, y: (
        "rel_recommended" if inside(A.find_by_id(s["mypage"][1], "llFriend", display=2)[0], x, y) else mypage_tap(x, y))
    # ⚠️ 実機では「友達」を押しても最初は「おすすめ」タブが開く
    mu.on_tap["rel_recommended"] = lambda x, y: (
        "rel_friends" if inside(A.find_tab(s["rel_recommended"][1], ("友達",), display=2)[0], x, y) else None)
    mu.on_tap["rel_friends"] = lambda x, y: (
        "profile_top" if inside(A.find_friend_in_list(s["rel_friends"][1], WANTED, display=2)[0], x, y) else None)
    for name in ("rel_recommended", "rel_friends"):
        mu.on_back[name] = "mypage"
    mu.on_swipe.update({"profile_top": "profile_pinned", "profile_pinned": "profile_posts", "profile_posts": "profile_posts"})
    for name in ("profile_top", "profile_pinned", "profile_posts"):
        mu.on_back[name] = "rel_friends"
    mu.on_tap["profile_top"] = lambda x, y: (
        "chat" if inside(A.find_by_id(s["profile_top"][1], "tvIm", display=2)[0], x, y) else None)
    mu.on_tap["profile_posts"] = lambda x, y: (
        "friend_detail" if inside(A.find_latest_unpinned_post(s["profile_posts"][1], display=2), x, y) else None)
    mu.on_back["friend_detail"] = "profile_posts"
    mu.on_back["chat"] = "profile_top"

    def input_screen(name, field, send_id, placeholder):
        def handler(x, y):
            if inside(A.find_by_id(s[name][1], field, display=2)[0], x, y):
                mu.focused = field
            elif inside(A.find_by_id(s[name][1], send_id, display=2)[0], x, y):
                mu.sent.append((name, A.text_by_id(s[name][1], field, display=2)))
                s[name][1] = set_text_by_id(s[name][1], field, placeholder)   # 送ると欄は案内文に戻る
            return None
        return handler
    mu.on_tap["friend_detail"] = input_screen("friend_detail", "etContent", "btnSend", "すてきなコメントを残そう！")
    mu.on_tap["chat"] = input_screen("chat", "msg_detail_et", "ivSendText", "メッセージを作成")

    feed_tap = mu.on_tap["feed"]
    mu.on_tap["feed"] = lambda x, y: (
        "detail_follow" if inside(A.find_unfollowed_post(s["feed"][1], display=2), x, y) else feed_tap(x, y))
    mu.on_tap["detail_follow"] = lambda x, y: (
        "detail_following" if inside(A.find_by_id(s["detail_follow"][1], "btnFollow", display=2)[0], x, y) else None)
    mu.on_tap["detail_following"] = lambda x, y: (
        "unfollow_dialog" if inside(A.find_by_id(s["detail_following"][1], "btnFollow", display=2)[0], x, y) else None)
    mu.on_tap["unfollow_dialog"] = lambda x, y: (
        "detail_follow" if inside(A.find_by_text(s["unfollow_dialog"][1], "確認", display=2)[0], x, y) else None)
    mu.on_back["detail_follow"] = "feed"


print("■ コメント: 友達の一覧（おすすめタブから選び直す）→ 送り先の直近の投稿へ")
w, db, logs = new_worker()
mu = FakeMuMu(social_screens(), "task_top")
wire_social(mu)
w._do_comment(mu, WANTED, "タスク")
check("送り先の投稿に「タスク」とコメントした", mu.sent == [("friend_detail", "タスク")], mu.sent)
check("「友達」タブを選び直した", any(s == "rel_recommended" for s, _, _ in mu.taps), mu.taps)
check("似た名前の人は押していない", not any(
    s == "rel_friends" and inside((104, 217, 278, 244), x, y) for s, x, y in mu.taps), mu.taps)

print("■ メッセージ: プロフィールの「メッセージ」から送る（ギフトは押さない）")
w, db, logs = new_worker()
screens = social_screens()
mu = FakeMuMu(screens, "mypage")
wire_social(mu)
w._do_message(mu, WANTED, "タスク")
check("「タスク」と送った", mu.sent == [("chat", "タスク")], mu.sent)
gift = A.find_by_text(screens["profile_top"][1], "ギフトを贈る", display=2)[0]
check("「ギフトを贈る」は押していない", not any(s == "profile_top" and inside(gift, x, y) for s, x, y in mu.taps), mu.taps)

print("■ メッセージ: 一覧に送り先がいなければ、何も送らずに止める")
w, db, logs = new_worker()
mu = FakeMuMu(social_screens(), "mypage")
wire_social(mu)
try:
    w._do_message(mu, "いない人の名前", "タスク")
    check("止まる", False)
except A.TaskStop as e:
    check("止まる", "見つかりませんでした" in str(e), str(e))
check("何も送っていない", mu.sent == [], mu.sent)

# ⚠️ 2026-10-12 本人: 新規ユーザーのフォローは、行の「チャレンジ」から入った先でしないと数えられない
#    （実機の通しで、ホームのタイムラインからのフォローは 0/1回 のままだった）。
#    「チャレンジ」の先の画面はまだ見ていないので、ここでは友達一覧の「おすすめ」タブ（フォローボタン付きの人が並ぶ）を仮に置く
FOLLOW_TITLE = "新規ユーザーを1人フォローする"


def add_challenge(xml_text, title):
    """タスク画面の行を「未達成・チャレンジあり」にする（その行の実物はまだ無いため）"""
    root = ET.fromstring(edit_task_row(xml_text, title, "0/1回", finish_mark=False))
    parent = {c: p for p in root.iter() for c in p}
    title_node = next(n for n in root.iter("node") if n.get("text") == title)
    row = parent[parent[title_node]]
    execute = next(n for n in row.iter("node") if A._resource_name(n) == A.TASK_ROW_EXECUTE_ID)
    button = ET.SubElement(execute, "node")
    button.attrib.update({"index": "0", "text": "チャレンジ", "class": "android.widget.TextView",
                          "resource-id": f"{GRAVITY}:id/{A.TASK_ROW_CHALLENGE_ID}", "package": GRAVITY,
                          "content-desc": "", "clickable": "true", "bounds": execute.get("bounds"), "display-id": "2"})
    return ET.tostring(root, encoding="unicode")


def follow_screens(button_disappears=False):
    s = social_screens()
    s["task_scrolled"][1] = add_challenge(s["task_scrolled"][1], FOLLOW_TITLE)
    rel = f"{CLS}.center.view.profile.RelationshipListActivityV2"
    s["follow_list"] = [rel, fixture("friends_list_recommended.xml")]
    s["follow_dialog"] = [rel, fixture("unfollow_dialog.xml")]
    return s


def wire_follow(mu, button_disappears=False):
    s = mu.screens
    wire_social(mu)
    original = s["follow_list"][1]
    first = A.find_by_id(original, "btnFollow", display=2, text="フォロー")[0]
    mu.on_tap["task_scrolled"] = lambda x, y: (
        "follow_list" if inside(A.find_task_challenge(s["task_scrolled"][1], FOLLOW_TITLE, display=2), x, y) else None)

    def list_tap(x, y):
        root = ET.fromstring(s["follow_list"][1])
        for node in root.iter("node"):
            if A._resource_name(node) == "btnFollow" and inside(A._node_box(node), x, y):
                if node.get("text") == "フォロー":
                    mu.followed = True
                    if button_disappears:
                        node.set("text", "")          # ホームのタイムラインのように、押すとボタンが消える
                        node.set("bounds", "[0,0][0,0]")
                    else:
                        node.set("text", "フォロー中")
                    s["follow_list"][1] = ET.tostring(root, encoding="unicode")
                    return None
                if node.get("text") == "フォロー中":
                    return "follow_dialog"
        return None
    mu.on_tap["follow_list"] = list_tap

    def dialog_tap(x, y):
        if inside(A.find_by_text(s["follow_dialog"][1], "確認", display=2)[0], x, y):
            mu.unfollowed = True
            s["follow_list"][1] = original
            return "follow_list"
        return None
    mu.on_tap["follow_dialog"] = dialog_tap
    mu.followed = mu.unfollowed = False
    return first


print("■ フォロー: 行の「チャレンジ」から入り、1人フォローして、すぐに外す")
w, db, logs = new_worker()
mu = FakeMuMu(follow_screens(), "mypage")
first = wire_follow(mu)
row = next(r for r in A.parse_task_rows(mu.screens["task_scrolled"][1], display=2) if r["title"] == FOLLOW_TITLE)
w._follow_left_on = False
w._do_follow(mu, row)
check("フォローの行の「チャレンジ」から入った", any(s == "task_scrolled" for s, _, _ in mu.taps), mu.taps)
check("ホームのタイムラインは使っていない", not any(s == "feed" for s, _, _ in mu.taps), mu.taps)
check("フォローして、すぐ外した", mu.followed and mu.unfollowed, (mu.followed, mu.unfollowed))
check("フォローしたのは一覧の1人目", any(s == "follow_list" and inside(first, x, y) for s, x, y in mu.taps), mu.taps)
check("フォローしたままの印は付かない", w._follow_left_on is False)

print("■ フォロー: 外すボタンが出ない画面なら、フォローしたままにして知らせる")
w, db, logs = new_worker()
mu = FakeMuMu(follow_screens(), "mypage")
wire_follow(mu, button_disappears=True)
w._follow_left_on = False
w._do_follow(mu, row)
check("フォローした", mu.followed)
check("外していない（外すボタンが無い）", not mu.unfollowed)
check("フォローしたままの印が付く", w._follow_left_on is True)
check("ログで伝える", any("フォローしたままにしました" in m for m in logs), logs[-2:])

print("■ フォロー: 行が受け取り待ち（「チャレンジ」が無い）なら何もしない")
w, db, logs = new_worker()
mu = FakeMuMu(base_screens(), "mypage")
wire_navigation(mu)
done_row = next(r for r in A.parse_task_rows(mu.screens["task_scrolled"][1], display=2) if r["title"] == FOLLOW_TITLE)
w._follow_left_on = False
w._do_follow(mu, done_row)
check("タスク画面では何も押していない", [t for t in mu.taps if t[0].startswith("task")] == [], mu.taps)

# ----------------------------------------------------------------------
# アカウントが複数開いているとき（MuMuの「アプリ複製」。本体=ユーザー0、複製=ユーザー10〜。画面はそれぞれ別のディスプレイ）
# ⚠️ 2026-10-14 本人: 本体を閉じて複製で始めたら、複製には触れず、タスクの済んだ本体をわざわざ起動してこなそうとした
import json


class MultiMuMu:
    """GRAVITYを複数開いている端末。ディスプレイごとに FakeMuMu を1つ持ち、入力は番号で振り分ける"""

    def __init__(self, accounts):
        self.accounts = accounts
        self.last = accounts[0]

    def dump_hierarchy(self):
        merged = ET.Element("hierarchy", {"rotation": "0"})
        for account in self.accounts:
            merged.extend(list(ET.fromstring(account.dump_hierarchy())))
        return ET.tostring(merged, encoding="unicode")

    def shell(self, command):
        if command.startswith("dumpsys activity activities"):
            text = ("Display #0 (activities from top to bottom):\n"
                    "      topResumedActivity=ActivityRecord{2 u0 app.lawnchair/.LawnchairLauncher t2}\n"
                    + "".join(a.display_section() for a in self.accounts))
            # 実物は後半に、同じ画面を別の番号の「Display #」で並べ直した区切りがある（2026-10-14 実測）
            text += "Display #19 (activities from top to bottom):\n" + "".join(
                f"  ResumedActivity: ActivityRecord{{1 u{a.user} {GRAVITY}/{a.screens[a.screen][0]} t56}}\n"
                for a in self.accounts)
            return Resp(text)
        display = command.split()[2]
        self.last = next(a for a in self.accounts if a.display == display)
        return self.last.shell(command)

    def send_keys(self, text):
        self.last.send_keys(text)


def two_accounts():
    """本体（ユーザー0）は画面2、複製（ユーザー10）は画面5。どちらもマイページから"""
    main = FakeMuMu(base_screens(), "mypage")
    clone = FakeMuMu(base_screens(), "mypage", display="5", user="10")
    for mu in (main, clone):
        wire_navigation(mu)
    return main, clone


def records(db):
    return json.loads(db.get_setting(A.GravityTaskWorker.ACCOUNTS_SETTING, "") or "{}")


print("■ 複数のアカウント: 開いているGRAVITYを順に回し、どれも今日の分は済みと覚える")
w, db, logs = new_worker()
notices = []
w.notify_callback = lambda title, message: notices.append((title, message))
main, clone = two_accounts()
w._connect_to_emulator = lambda: MultiMuMu([main, clone])
w._today = lambda: "2026-10-14"
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("本体の画面で回した", any(s == "roulette_before" for s, _, _ in main.taps), main.taps)
check("複製の画面でも回した", any(s == "roulette_before" for s, _, _ in clone.taps), clone.taps)
check("景品を2回ログに出す", sum("x300" in m for m in logs) == 2, [m for m in logs if "x300" in m])
saved = records(db)
check("両方とも今日は回したと覚える",
      saved.get("0", {}).get("roulette_date") == saved.get("10", {}).get("roulette_date") == "2026-10-14", saved)
check("タスクの方は済みと覚えていない（別の仕事）", "tasks_date" not in saved.get("0", {}), saved)
check("マイページで読んだ名前を覚える", saved.get("10", {}).get("name") == "伏せ字1", saved)
check("ログでアカウントを呼び分ける", any("複製のGRAVITY（u10）" in m for m in logs)
      and any("本体のGRAVITY" in m for m in logs), [m for m in logs if "GRAVITY" in m][:4])
check("止まった知らせは出ない", notices == [], notices)

print("■ 複数のアカウント: 同じ日にもう一度押しても、済んだアカウントには触らない")
sent_before = (len(main.inputs), len(clone.inputs))
w.is_running = True
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("どちらの画面にも何も送っていない", (len(main.inputs), len(clone.inputs)) == sent_before,
      (sent_before, len(main.inputs), len(clone.inputs)))
check("「今日の分は済んでいます」と知らせる", notices and "今日の分は済んでいます" in notices[-1][0], notices)
check("飛ばしたことを、名前で呼んでログに出す", any("⏭️ 複製のGRAVITY（u10）「伏せ字1」" in m for m in logs), logs[-4:])

print("■ 複数のアカウント: 0時を過ぎて日付が変わったら、また触る（タスクは毎日0時にリセット）")
w._today = lambda: "2026-10-15"
main.screen = clone.screen = "mypage"
w.is_running = True
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("両方とも、また回した", len(main.inputs) > sent_before[0] and len(clone.inputs) > sent_before[1],
      (sent_before, len(main.inputs), len(clone.inputs)))
check("新しい日付で覚える", records(db)["10"]["roulette_date"] == "2026-10-15", records(db))

print("■ 複数のアカウント: 今日の「済み」の記録を消すと、また触る")
w.forget_today()
check("今日の分の記録が消える", "roulette_date" not in records(db)["10"], records(db))
check("名前は残す", records(db)["10"].get("name") == "伏せ字1", records(db))

print("■ 本体を閉じて複製だけ開いているときは、複製をこなす")
w, db, logs = new_worker()
clone = FakeMuMu(base_screens(), "mypage", display="5", user="10")
wire_navigation(clone)
w._connect_to_emulator = lambda: clone
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("複製の画面（5）で回した", any(s == "roulette_before" for s, _, _ in clone.taps), clone.taps)
check("入力はすべて画面5へ", all(c.split()[2] == "5" for c in clone.inputs), clone.inputs[:3])


class FakeController:
    """MuMuManager の代役。起動を頼まれたパッケージを覚える"""

    def __init__(self):
        self.launched = []

    def is_available(self):
        return True

    def launch(self, index=None, package="", wait_seconds=120):
        self.launched.append(package)
        return True, "MuMuは既に起動しています。"

    def get_info(self, index=None):
        return {"index": "1", "is_android_started": True, "player_state": "start_finished",
                "adb_port": 16416, "adb_host_ip": "127.0.0.1"}

    is_android_ready = staticmethod(A.MuMuController.is_android_ready)
    get_adb_address = staticmethod(A.MuMuController.get_adb_address)


print("■ タスク・ルーレットでは、自動起動がONでもGRAVITYのアプリは起動しない（起動すると本体が開く）")
db.save_setting("mumu_auto_launch", "1")
w.mumu = FakeController()
address = w._prepare_mumu()
check("MuMu本体だけを頼み、アプリは頼まない", w.mumu.launched == [""], w.mumu.launched)
check("接続先は返す", address == "127.0.0.1:16416", address)
monitor = A.AutoReplyWorker(db, logs.append)
monitor.mumu = FakeController()
monitor._prepare_mumu()
check("自動返信の監視は、これまでどおりアプリも起動する", monitor.mumu.launched == [GRAVITY], monitor.mumu.launched)

print("■ GRAVITYが1つも開いていなければ、何も押さずに知らせる")
w, db, logs = new_worker()
notices = []
w.notify_callback = lambda title, message: notices.append((title, message))
home = FakeMuMu({"home": [".LawnchairLauncher", '<hierarchy rotation="0" />']}, "home")
w._connect_to_emulator = lambda: home
w._job_main(A.GravityTaskWorker.JOB_TASKS)
check("知らせる", notices and "GRAVITYの画面が開いていません" in notices[-1][1], notices)
check("何も送っていない", home.inputs == [], home.inputs)

print("■ 複数のアカウント: 途中で止まったら、残りのアカウントには進まず、どのアカウントで止まったかを知らせる")
w, db, logs = new_worker()
notices = []
w.notify_callback = lambda title, message: notices.append((title, message))
main, clone = two_accounts()
mypage_tap = main.on_tap["mypage"]
main.on_tap["mypage"] = lambda x, y: "ad" if mypage_tap(x, y) == "task_top" else mypage_tap(x, y)   # 本体で広告が出る
w._connect_to_emulator = lambda: MultiMuMu([main, clone])
w._job_main(A.GravityTaskWorker.JOB_ROULETTE)
check("止めて知らせる", notices and "知らない画面" in notices[-1][1], notices)
check("どのアカウントで止まったかを、名前で添える", notices and notices[-1][1].startswith("【本体のGRAVITY「伏せ字1」】"), notices)
check("複製には何も送っていない", clone.inputs == [], clone.inputs)
check("本体は済みと覚えない", "roulette_date" not in records(db).get("0", {}), records(db))
check("名前は覚える（次からの知らせで使う）", records(db).get("0", {}).get("name") == "伏せ字1", records(db))

print("■ 複数のアカウント（タスク）: ボットの番が済んだアカウントだけ済みと覚え、知らせはアカウントごとに分ける")
w, db, logs = new_worker()
notices = []
w.notify_callback = lambda title, message: notices.append((title, message))
w._today = lambda: "2026-10-14"
main, clone = two_accounts()                       # 本体は全部済み
clone.screens["task_top"][1] = edit_task_row(clone.screens["task_top"][1], "投稿する", "0/1回", finish_mark=False)
w._connect_to_emulator = lambda: MultiMuMu([main, clone])
w._job_main(A.GravityTaskWorker.JOB_TASKS)
check("複製で投稿した", clone.posted == "タスク", getattr(clone, "posted", None))
check("本体では投稿していない", not any(s == "compose" for s, _, _ in main.taps), main.taps)
saved = records(db)
check("本体は今日の分は済みと覚える", saved.get("0", {}).get("tasks_date") == "2026-10-14", saved)
check("複製は回数が増えなかったので、済みと覚えない", "tasks_date" not in saved.get("10", {}), saved)
check("知らせに、どのアカウントの話かを添える", notices and "【複製のGRAVITY（u10）「伏せ字1」】" in notices[-1][1]
      and "回数が増えていません" in notices[-1][1], notices)

print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
