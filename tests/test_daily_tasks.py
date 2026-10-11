# -*- coding: utf-8 -*-
"""
デイリータスクの「タスク画面を読む」部分の検証。実機は使わない。
fixtures/ のダンプは 2026-10-11 に実機(MuMu)のタスク画面から取ったもの
（GRAVITYのディスプレイ2の部分だけを残してある）。調べた日は全タスク達成済みだった。
"""
import os, sys

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


print("■ 回数の表示を読む")
check("1/1回", A.parse_task_progress("1/1回") == (1, 1))
check("40/40回", A.parse_task_progress("40/40回") == (40, 40))
check("途中 3/5回", A.parse_task_progress("3/5回") == (3, 5))
check("全角 ３／５回", A.parse_task_progress("３／５回") == (3, 5))
check("読めない表示は None", A.parse_task_progress("達成") is None)
check("空は None", A.parse_task_progress("") is None)

print("■ タスク画面の上の方（投稿・いいね）")
rows = A.parse_task_rows(fixture("task_center_top.xml"), display=2)
check("2行読める", [r["title"] for r in rows] == ["投稿する", "心のこもった「いいね」をする"],
      [r["title"] for r in rows])
check("投稿 1/1", rows[0]["progress"] == (1, 1), rows[0])
check("いいね 40/40", rows[1]["progress"] == (40, 40), rows[1])
check("ポイント", [r["award"] for r in rows] == ["2000", "5000"], [r["award"] for r in rows])

print("■ スクロールした後（メッセージ〜フォロー）")
rows = A.parse_task_rows(fixture("task_center_scrolled.xml"), display=2)
titles = [r["title"] for r in rows]
check("4行読める", titles == ["ユーザーにメッセージを送る", "広告を最後まで見る",
                              "人気投稿をXにシェアする", "新規ユーザーを1人フォローする"], titles)
check("広告 5/5", rows[1]["progress"] == (5, 5), rows[1])
check("全部にクリアの印", all(r["finish_mark"] for r in rows), rows)
# 一番下の行は画面の端で切れているが、タイトルは見えているので読める
check("切れかけの最後の行も回数が読める", rows[3]["progress"] == (1, 1), rows[3])

print("■ クリア済みの行が画面の下端で切れたとき（印だけ画面外）")
# 実物のダンプから、最後の行(フォロー)の右側の枠を取り除いて「印が画面外」を再現する。
# 読み飛ばさずに返すと「1/1回なのに印が無い」になり、済んだタスクを未達成と取り違えかねない。
import xml.etree.ElementTree as ET

def without_part(xml_text, title, part_id):
    root = ET.fromstring(xml_text)
    parent = {c: p for p in root.iter() for c in p}
    title_node = next(n for n in root.iter("node") if n.get("text") == title)
    row = parent[parent[title_node]]          # タイトル → llPointTaskInfo → 行の枠
    for node in list(row.iter("node")):
        if A._resource_name(node) == part_id:
            parent[node].remove(node)
    return ET.tostring(root, encoding="unicode")

clipped = without_part(fixture("task_center_scrolled.xml"), "新規ユーザーを1人フォローする",
                       A.TASK_ROW_EXECUTE_ID)
titles = [r["title"] for r in A.parse_task_rows(clipped, display=2)]
check("印が画面外の行は読み飛ばす", "新規ユーザーを1人フォローする" not in titles, titles)
check("他の3行はそのまま読める", len(titles) == 3, titles)

clipped = without_part(fixture("task_center_scrolled.xml"), "新規ユーザーを1人フォローする",
                       A.TASK_ROW_PROGRESS_ID)
titles = [r["title"] for r in A.parse_task_rows(clipped, display=2)]
check("回数が画面外の行も読み飛ばす", "新規ユーザーを1人フォローする" not in titles, titles)

print("■ 別のディスプレイを指定すると何も読まない")
check("display=0 では0行", A.parse_task_rows(fixture("task_center_scrolled.xml"), display=0) == [])

print("■ 前面の画面が押してよい画面か")
GRAVITY = "anonymous.sns.community.gravity"
line = ("  topResumedActivity=ActivityRecord{152072028 u0 anonymous.sns.community.gravity/"
        "com.hiclub.android.gravity.point.TaskCenterActivity t56}")
check("dumpsysの行から読む", A.parse_top_activity(line) ==
      GRAVITY + "/com.hiclub.android.gravity.point.TaskCenterActivity", A.parse_top_activity(line))
check("省略形 pkg/.Cls を直す",
      A.parse_top_activity("ActivityRecord{1 u0 app.lawnchair/.LawnchairLauncher t2}") ==
      "app.lawnchair/app.lawnchair.LawnchairLauncher")
check("読めない行は空", A.parse_top_activity("") == "")
check("タスク画面は押してよい",
      A.is_known_task_screen(GRAVITY + "/com.hiclub.android.gravity.point.TaskCenterActivity", GRAVITY))
check("ルーレットは押してよい",
      A.is_known_task_screen(GRAVITY + "/com.hiclub.android.gravity.web.RewardAdWheelLotteryWebActivity", GRAVITY))
# 2026-10-11 に本人が広告を見たときの実際の画面。GRAVITYと同じパッケージの中に出る
check("広告の画面は押さない（同じパッケージでも）", not A.is_known_task_screen(
      GRAVITY + "/com.mbridge.msdk.reward.player.MBRewardVideoActivity", GRAVITY))
check("ランチャーは押さない", not A.is_known_task_screen("app.lawnchair/app.lawnchair.LawnchairLauncher", GRAVITY))
check("複製アプリは押さない（クラス名が同じでも）", not A.is_known_task_screen(
      "other.clone.package/com.hiclub.android.gravity.point.TaskCenterActivity", GRAVITY))
check("対象パッケージが未設定なら押さない", not A.is_known_task_screen(
      GRAVITY + "/com.hiclub.android.gravity.MainActivity", ""))

print("■ 押してはいけないボタン（ルーレット・回す前）")
boxes = A.find_forbidden_boxes(fixture("roulette_before.xml"), display=2)
check("200/1回の押せる枠", (73, 891, 234, 957) in boxes, boxes)
check("2000/10回の押せる枠", (244, 891, 466, 957) in boxes, boxes)
check("「今日の初回チャンス」の中央は押してよい", A.tap_is_safe(274, 840, boxes))
check("2000/10回の右端の余白内は押さない", not A.tap_is_safe(470, 925, boxes))
# 調査中に画面を取り違えて押した位置。枠から20px外れていた（余白10pxの外）
check("誤って押した(486,925)は、枠の外だった", A.tap_is_safe(486, 925, boxes))

print("■ 押してはいけないボタン（ルーレット・回した後）")
boxes = A.find_forbidden_boxes(fixture("roulette_after.xml"), display=2)
check("同じ場所の大きいボタンが、回した後は押せない", not A.tap_is_safe(274, 840, boxes), boxes)

print("■ 押してはいけないボタン（結果のダイアログ）")
boxes = A.find_forbidden_boxes(fixture("roulette_result_dialog.xml"), display=2)
check("ダイアログの「広告を見て再チャレンジ」は押さない", not A.tap_is_safe(270, 677, boxes), boxes)
check("右上の×は押してよい", A.tap_is_safe(469, 210, boxes))

print("■ タスク画面には押してはいけないボタンが無い")
# 「広告を最後まで見る」はタスク名で、「広告を見て」には当たらない
check("タスク画面(上)", A.find_forbidden_boxes(fixture("task_center_top.xml"), display=2) == [])
check("タスク画面(スクロール後)", A.find_forbidden_boxes(fixture("task_center_scrolled.xml"), display=2) == [])

print("■ ディスプレイごとの前面の画面（MuMuは画面を4枚持つ）")
dumpsys = fixture("dumpsys_activities_voiceroom.txt")
check("画面2はGRAVITYの音声ルーム", A.parse_display_activity(dumpsys, 2).endswith(
      ".metaverse.voiceroom.VoiceRoomType2Activity"), A.parse_display_activity(dumpsys, 2))
check("画面0はランチャー（同じ出力の別の区切り）",
      A.parse_display_activity(dumpsys, 0) == "app.lawnchair/app.lawnchair.LawnchairLauncher",
      A.parse_display_activity(dumpsys, 0))
check("無い画面番号は空", A.parse_display_activity(dumpsys, 7) == "")
check("音声ルームは押してよい画面ではない（勝手にルームを出ない）",
      not A.is_known_task_screen(A.parse_display_activity(dumpsys, 2), GRAVITY))

print("■ タスクの扱い")
check("投稿はボットがこなす", A.task_kind("投稿する") == A.TASK_KIND_POST)
check("コメント", A.task_kind("ユーザーの投稿にコメントする") == A.TASK_KIND_COMMENT)
check("メッセージ", A.task_kind("ユーザーにメッセージを送る") == A.TASK_KIND_MESSAGE)
check("フォロー", A.task_kind("新規ユーザーを1人フォローする") == A.TASK_KIND_FOLLOW)
for title in ("広告を最後まで見る", "人気投稿をXにシェアする", "心のこもった「いいね」をする"):
    check(f"{title} はご自身で", A.task_kind(title) == A.TASK_KIND_MANUAL and title in A.TASK_MANUAL_REASONS)
check("知らないタスクは空", A.task_kind("新しいタスク") == "")

print("■ 画面の中から目当ての部品を探す")
check("マイページの「タスク」", A.find_function_entry(fixture("mypage.xml"), "タスク", display=2) ==
      (219, 344, 318, 435), A.find_function_entry(fixture("mypage.xml"), "タスク", display=2))
check("マイページの「友達」", A.find_by_id(fixture("mypage.xml"), "llFriend", display=2) == [(223, 260, 255, 318)])
feed = fixture("feed_home.xml")
check("右下の「+」（下タブのホームと取り違えない）", A.find_feed_add_button(feed, display=2) == (449, 798, 519, 868),
      A.find_feed_add_button(feed, display=2))
post = A.find_unfollowed_post(feed, display=2)
check("フォローしていない人の投稿（2件目）の時刻", post is not None and post[1] >= 444, post)
check("詳細のコメント欄", A.find_by_id(fixture("post_detail_comments.xml"), "etContent", display=2) == [(21, 824, 430, 881)])
check("詳細の「送る」", A.find_by_id(fixture("post_detail_comments.xml"), "btnSend", display=2, text="送る") ==
      [(433, 832, 511, 874)])
check("詳細の「フォロー中」", A.find_by_id(fixture("post_detail_following.xml"), "btnFollow", display=2,
                                     text="フォロー中") == [(407, 99, 519, 136)])
check("解除の確認ダイアログの「確認」", A.find_by_text(fixture("unfollow_dialog.xml"), "確認", display=2) ==
      [(86, 495, 263, 560)])
check("投稿の本文欄", A.find_by_id(fixture("compose.xml"), "etContent", display=2) == [(31, 122, 509, 357)])
check("「投稿」ボタン", A.find_by_id(fixture("compose.xml"), "btnAddFeedSubmit", display=2) == [(409, 5, 524, 52)])
check("メッセージの入力欄", A.find_by_id(fixture("chat.xml"), "msg_detail_et", display=2) == [(42, 825, 454, 859)])
check("メッセージの送信", A.find_by_id(fixture("chat.xml"), "ivSendText", display=2) == [(462, 813, 519, 870)])

check("タスク画面の「ディリータスク」は選ばれている",
      A.find_tab(fixture("task_center_top.xml"), ("ディリータスク", "デイリータスク"), display=2)[1])
box, selected = A.find_tab(fixture("friends_list.xml"), ("友達",), display=2)
check("友達の一覧で「友達」タブが選ばれている（選び直した後のダンプ）", selected and box is not None, (box, selected))
check("マイポイントを読む", A.text_by_id(fixture("task_center_top.xml"), "tvPoint", display=2) == "80200")
check("無い部品は None", A.text_by_id(fixture("task_center_top.xml"), "noSuchId", display=2) is None)
check("解除の確認の文言がある", A.has_text(fixture("unfollow_dialog.xml"), "フォローを外しますか", display=2))
check("ルーレットの回した後に「再チャレンジ」がある", A.has_text(fixture("roulette_after.xml"), "再チャレンジ", display=2))

print("■ 送り先の名前（一覧では途中で切れる）")
# 実物の一覧には、送り先と、その名前の一部を含む似た名前の別人がいた。仮の名前で同じ関係を再現している
WANTED = "テストの相手さんです"
check("切れた名前は先頭が一致すれば本人", A.friend_name_matches("テストの相手さ..", WANTED))
check("一部を含むだけの似た名前は別人", not A.friend_name_matches("ストの相手さん", WANTED))
check("切れていない名前は完全一致だけ", not A.friend_name_matches("テストの相手さん", WANTED))
check("完全一致は本人", A.friend_name_matches(WANTED, WANTED))
check("切れた残りが1文字なら判定しない", not A.friend_name_matches("テ..", WANTED))
check("半角カナで書いても同じ人", A.friend_name_matches("ﾃｽﾄの相手さ..", WANTED))
check("空の設定は誰とも一致しない", not A.friend_name_matches("テストの相手さ..", ""))
friends = fixture("friends_list.xml")
check("一覧から本人だけが見つかる", A.find_friend_in_list(friends, WANTED, display=2) == [(104, 562, 282, 589)],
      A.find_friend_in_list(friends, WANTED, display=2))

print("■ 送り先の直近の投稿（ピン留めを除く）")
check("ピン留めの次の「1時間前」の投稿", A.find_latest_unpinned_post(fixture("friend_profile_posts.xml"), display=2) ==
      (34, 419, 96, 444), A.find_latest_unpinned_post(fixture("friend_profile_posts.xml"), display=2))
check("ピン留めしか見えていなければ無し（スクロールして探す）",
      A.find_latest_unpinned_post(fixture("friend_profile_pinned_only.xml"), display=2) is None)

print("■ ルーレット")
check("タスク画面のカードの「交換する」を並び順で", A.find_point_shop_buttons(fixture("task_center_points.xml"), display=2) ==
      [(80, 873, 224, 911), (315, 873, 459, 911)])
check("回す前は「今日の初回チャンス」がある",
      A.find_by_text(fixture("roulette_before.xml"), A.ROULETTE_FREE_LABEL, display=2) == [(75, 807, 474, 873)])
check("回した後は無い（＝今日はもう回した）",
      A.find_by_text(fixture("roulette_after.xml"), A.ROULETTE_FREE_LABEL, display=2) == [])
check("結果のダイアログの×と景品", A.find_roulette_result_close(fixture("roulette_result_dialog.xml"), display=2) ==
      ((453, 193, 486, 228), "x300"), A.find_roulette_result_close(fixture("roulette_result_dialog.xml"), display=2))
check("ダイアログが無ければ×も無い（回した後）",
      A.find_roulette_result_close(fixture("roulette_after.xml"), display=2) == (None, ""))
check("ダイアログが無ければ×も無い（回す前）",
      A.find_roulette_result_close(fixture("roulette_before.xml"), display=2) == (None, ""))

print("■ 判定（答えがはっきりしているもの）")
try:
    check("済み＋印あり → 済み", A.classify_task((1, 1), True) == A.TASK_STATE_DONE)
    check("0/1＋印なし → こなす", A.classify_task((0, 1), False) == A.TASK_STATE_TODO)
    check("39/40＋印なし → こなす", A.classify_task((39, 40), False) == A.TASK_STATE_TODO)
    check("回数が読めず印もない → 判断できない",
          A.classify_task(None, False) == A.TASK_STATE_UNKNOWN)

    print("■ 判定（判断が分かれるもの。2026-10-11 に方針を決めた）")
    # 「迷ったら止めて知らせる」「他の人に余計なものを届けない」に合わせる
    check("回数は達成なのに印が無い → 止める（受け取り待ち？まだ見たことがない）",
          A.classify_task((5, 5), False) == A.TASK_STATE_UNKNOWN)
    check("回数は途中なのに印がある → 止める（食い違い）",
          A.classify_task((3, 5), True) == A.TASK_STATE_UNKNOWN)
    check("回数は読めないが印はある → 済み（読み違えてもこなし損ねるだけ）",
          A.classify_task(None, True) == A.TASK_STATE_DONE)
    check("必要な回数が0 → 止める", A.classify_task((0, 0), False) == A.TASK_STATE_UNKNOWN)

    print("■ 実物のタスク画面（全部クリア済み）はすべて「済み」になる")
    for name in ("task_center_top.xml", "task_center_scrolled.xml"):
        rows = A.parse_task_rows(fixture(name), display=2)
        states = {r["title"]: A.classify_task(r["progress"], r["finish_mark"]) for r in rows}
        check(name, all(s == A.TASK_STATE_DONE for s in states.values()), states)
except NotImplementedError:
    print("  ..   classify_task はまだ書かれていない（TODO）")
    FAILS.append("classify_task 未実装")

print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
