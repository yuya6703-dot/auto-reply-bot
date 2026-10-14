# -*- coding: utf-8 -*-
"""
実機の画面ダンプから、テスト用の画面(fixtures/)を作る。

⚠️ このリポジトリは公開されている。画面には他の人の名前や投稿がそのまま出ているので、
   ボタン名などの決まった文言・数字・時刻以外は、すべて「伏せ字N」に置き換える。
   ルーレットの上に流れる当選表示（「〇〇が…をGET！」）は名前が伏せられていないことがあるので、部品ごと消す。
   作った後に「残った文言」を必ず目で見ること。

使い方:
    python tests/make_fixture.py 元のダンプ.xml 保存する名前.xml [--name 元の名前=仮の名前 ...]

  --name は、名前で探す処理を試すために、特定の名前だけ仮の名前に置き換えて残すときに使う
  （例: 送り先と、それによく似た名前の関係を保ったまま、本当の名前は出さない）。
"""
import os, re, sys
import xml.etree.ElementTree as ET

_HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = "anonymous.sns.community.gravity"
DISPLAY = "2"

# そのまま残してよい、GRAVITYの決まった文言
KEEP = {
    "ホーム", "コミュニティ", "音声ルーム", "メッセージ", "マイページ", "新着", "みつける", "フォロー", "フォロー中",
    "フォロワー", "友達", "おすすめ", "すべて", "投稿", "投稿を作成", "惑星を選択", "今思っていることを書いちゃおう！",
    "すてきなコメントを残そう！", "送る", "コメント", "注目", "返信", "メッセージを作成", "ギフトを贈る", "全ての投稿",
    "アルバム", "マイデータ", "つながり", "確認", "キャンセル", "フォローを外しますか", "もっとみる", "タスク",
    "マイポイント", "ポイントを使う", "交換する", "ディリータスク", "デイリータスク", "新規タスク", "クランタスク",
    "毎日深夜0時にリセット", "情報編集", "ガチャ", "質問ボックス", "心理テスト", "いいね数", "NEW",
    "一部公開・一部コメント可能", "pt交換でアイテム獲得", "今すぐチェック", "iUぷらねっと", "ショップ", "グルチャ",
    "投稿する", "心のこもった「いいね」をする", "ユーザーの投稿にコメントする", "ユーザーにメッセージを送る",
    "広告を最後まで見る", "人気投稿をXにシェアする", "新規ユーザーを1人フォローする",
    "ラッキールーレット", "今日の初回チャンス", "GRAVITY",
    # タスクの行の右のボタン（未達成=チャレンジ / 報酬の受け取り待ち=クリア）
    "チャレンジ", "クリア", "心のこもった「いいね」をする",
    # 音声ルーム
    "ミッションへ", "毎日報酬をGET", "未受取の報酬あり", "ようこそ！", "メッセージを送信", "プライベート音声ルーム",
    "応募する",
}
# そのまま残してよい形（数字・回数・時刻・景品）
PATTERNS = [r"\d+", r"\d+/\d+回", r"\d+時間前", r"\d+分前", r"\d{2}/\d{2}( \d{2}:\d{2})?", r"\d+(\.\d+)?K",
            r"昨日\s+\d{2}:\d{2}", r"\d{2}:\d{2}", r"x\d+", r"\s*\d+/\d+回", r"広告を見て再チャレンジ.*",
            r"広告を１回見るとルーレットを１回まわせるよ！", r"(永久|\d+日间)",
            r"ゲスト（\d+人）", r"あと\d+日"]

# 音声ルームのチャット欄のお知らせ。名前（やルーム名）の部分だけを伏せ字にして、決まった文言は残す。
# ⚠️ 丸ごと伏せ字にすると、お知らせの見分け方（parse_chat_rows）をテストできなくなる
NOTICE_TEMPLATES = [
    re.compile(r"^(?P<lead>)(?P<name>.+?)(?P<tail>が音声ルームに参加しました)$"),
    re.compile(r"^(?P<lead>)(?P<name>.+?)(?P<tail>さんが音声ルームにいいねをしました)$"),
    re.compile(r"^(?P<lead>)(?P<name>.+?)(?P<tail>がマイクをもらいました)$"),
    re.compile(r"^(?P<lead>ルーム名を)(?P<name>.+?)(?P<tail>に変更しました)$"),
    re.compile(r"^(?P<lead>\s*)(?P<name>.+?)(?P<tail>さんはアナウンスを更新した)$"),
]


def make(src, dst, names):
    root = ET.parse(src).getroot()
    for top in list(root):
        if not (top.get("display-id") == DISPLAY and top.get("package") == PACKAGE):
            root.remove(top)
    parent = {c: p for p in root.iter() for c in p}
    for node in list(root.iter("node")):
        # 当選表示は「〇〇が 永久フレーム たこはさみ をGET！」の形。
        # ⚠️ 「GET」だけで消すと、ミッションの「毎日報酬をGET」まで消える（実際に消えた）
        if "をGET！" in (node.get("text") or ""):
            parent[node].remove(node)

    masked = [0]
    # ⚠️ 同じ文字には同じ伏せ字を付ける。番号が毎回変わると「同じ人の発言か」「いいねをしたのは発言した人か」を
    #    テストで確かめられなくなる（実際、同じ人の2つの発言といいねが3つの別の番号になっていた）
    tokens = {}

    def token(original):
        key = original.strip()
        if key in names:
            return names[key]
        if key not in tokens:
            masked[0] += 1
            tokens[key] = f"伏せ字{masked[0]}"
        return tokens[key]

    def clean(value):
        v = value or ""
        if not v.strip():
            return v
        if v in names:
            return names[v]
        if v.strip() in KEEP or any(re.fullmatch(p, v.strip()) for p in PATTERNS):
            return v
        for template in NOTICE_TEMPLATES:
            m = template.match(v)
            if m:
                return f"{m.group('lead')}{token(m.group('name'))}{m.group('tail')}"
        return token(v)

    for node in root.iter("node"):
        node.set("text", clean(node.get("text")))
        node.set("content-desc", clean(node.get("content-desc")))
        node.set("hint", "")
    out = os.path.join(_HERE, "fixtures", dst)
    ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    kept = sorted({n.get("text") for n in root.iter("node")
                   if n.get("text") and not n.get("text").startswith("伏せ字")})
    print(f"{dst}: 伏せ字 {masked[0]} 件")
    print(f"  残った文言（他の人の名前が無いか目で確かめること）: {kept}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    names = {}
    rest = args[2:]
    while rest:
        if rest[0] == "--name" and len(rest) > 1 and "=" in rest[1]:
            original, replacement = rest[1].split("=", 1)
            names[original] = replacement
            rest = rest[2:]
        else:
            print(f"読めない引数: {rest[0]}")
            sys.exit(1)
    make(args[0], args[1], names)
