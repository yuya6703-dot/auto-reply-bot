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

    def __init__(self, screens, start):
        self.screens = screens          # 名前 → [Activityのクラス, ダンプ]
        self.screen = start
        self.inputs = []                # 実際に送られた input コマンド
        self.taps = []                  # (画面の名前, x, y)
        self.focused = None
        self.on_tap = {}                # 画面の名前 → 関数(x, y) が次の画面名を返す（None なら同じ画面）
        self.on_swipe = {}
        self.on_back = {}

    # --- worker から呼ばれるもの ---
    def dump_hierarchy(self):
        return self.screens[self.screen][1]

    def shell(self, command):
        if command.startswith("dumpsys activity activities"):
            cls = self.screens[self.screen][0]
            package = "app.lawnchair" if cls.startswith(".Lawnchair") else GRAVITY
            return Resp("Display #0 (activities from top to bottom):\n"
                        "      topResumedActivity=ActivityRecord{2 u0 app.lawnchair/.LawnchairLauncher t2}\n"
                        "Display #2 (activities from top to bottom):\n"
                        f"    topResumedActivity=ActivityRecord{{1 u0 {package}/{cls} t56}}\n")
        self.inputs.append(command)
        parts = command.split()
        assert parts[:3] == ["input", "-d", "2"], f"画面2以外へ送った: {command}"
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

print("■ タスク: 投稿しても回数が増えなければ知らせる")
w, db, logs = new_worker()
screens = base_screens()
screens["task_top"][1] = edit_task_row(screens["task_top"][1], "投稿する", "0/1回", finish_mark=False)
mu = FakeMuMu(screens, "mypage")
wire_navigation(mu)
result = w._run_daily_tasks(mu)
check("知らせる", result is not None and "回数が増えていません" in result[1], result)

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

print("■ フォロー: 詳細画面でフォローして、すぐに外す")
w, db, logs = new_worker()
mu = FakeMuMu(social_screens(), "mypage")
wire_social(mu)
w._do_follow(mu)
order = [s for s, _, _ in mu.taps if s in ("detail_follow", "detail_following", "unfollow_dialog")]
check("フォロー → フォロー中 → 確認 の順に押した", order == ["detail_follow", "detail_following", "unfollow_dialog"], order)
check("最後はフォローしていない状態", mu.screen == "detail_follow", mu.screen)

print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
