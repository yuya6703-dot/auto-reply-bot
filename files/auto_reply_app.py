import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import sqlite3
import threading
import time
import datetime
import re
import os
import sys
import json
import subprocess
import shutil
import tempfile
import traceback
import zipfile
import urllib.request
import urllib.error
import io
import math
import struct
import wave
import array
import urllib.parse
import html
import unicodedata
import contextlib
import ctypes
import queue
import difflib
import socket
import secrets
import ssl
import ipaddress

# HTTPSで配信するための自己署名証明書を作るのに使う。
# ⚠️ ブラウザの音声認識・マイクは「安全なページ(https)」でしか動かない。
# 入っていない環境ではHTTPSを諦めて平文で配信する（従来どおり動く）。
try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
except Exception:
    x509 = None
import http.server
# 画面ダンプを「木」として読むために使う。正規表現ではノードが平らに潰れて
# 親子関係が失われるため、「目印とボタンが同じダイアログの中にあるか」を判定できない。
import xml.etree.ElementTree as ET

try:
    import winsound  # Windows標準ライブラリ。アラーム音の再生に使用（Windows以外では利用不可）
except ImportError:
    winsound = None

# 出力デバイスを選んで鳴らすために使う。
# ⚠️ winsound.PlaySound は「Windowsの既定の再生デバイス」にしか鳴らせず、
# 送り先を指定する術がない。VB-CABLE等の仮想デバイスへ流したい場合は
# こちらが要る。入っていない環境でも既定デバイスへは鳴らせるよう、
# 読み込めなければ従来どおり winsound を使う作りにしてある。
try:
    import sounddevice
except Exception:
    # ImportErrorだけでなく、PortAudioのDLLが読めない場合もここに来る
    sounddevice = None

import uiautomator2 as u2
import pygetwindow as gw
import pyautogui
from adbutils import adb

# ====================================================
# 📁 パス設定
# ====================================================
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_FILE = os.path.join(BASE_DIR, "app_data.db")
DB_FILE_NAME = os.path.basename(DB_FILE)

# ====================================================
# 🔄 アップデート設定
# ====================================================
# ⚠️ 重要: この値は、GitHubでpushするタグ名（例: v1.1.0 の "1.1.0"部分）と必ず一致させてください。
# ずれると「最新なのに古いと表示される」「古いのに最新と表示される」といった誤判定の原因になります。
APP_VERSION = "1.7.0"  # リリースするたびにこの値を上げ、同じ番号でタグ(例: v1.2.0)をpushしてください

# GitHubリポジトリ情報（owner/repo）の既定値。
# 設定タブで変更でき、その場合は settings テーブルの github_owner / github_repo が優先される。
# ここはあくまで「まだ何も設定されていないとき」に使われる出荷時の値。
# ⚠️ アプリの更新確認は「未認証」でGitHub APIを叩くため、指定するリポジトリは
# public である必要がある。private だと利用者側では常に404になり、更新を検知できない。
GITHUB_OWNER = "yuya6703-dot"
GITHUB_REPO = "auto-reply-bot"

# GitHubのowner名・リポジトリ名として許される文字。
# 設定値はそのままURLに埋め込むため、ここで弾いておかないと
# 「../」やクエリ文字列を紛れ込ませて別のURLを叩かせることができてしまう。
GITHUB_OWNER_RE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$')
GITHUB_REPO_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')


def build_release_api_url(owner, repo):
    """最新リリースを取得するAPIのURLを組み立てる"""
    return (
        "https://api.github.com/repos/"
        f"{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo, safe='')}"
        "/releases/latest"
    )


def parse_github_repository(text):
    """
    入力されたリポジトリ指定を (owner, repo) に正規化する。

    ブラウザのアドレスバーからそのまま貼り付けられることを想定し、
    「owner/repo」以外に以下の形も受け付ける:
        https://github.com/owner/repo  /  同 .git 付き  /  git@github.com:owner/repo.git

    戻り値: (owner, repo, エラーメッセージ)。エラー時は owner と repo が None。
    """
    raw = (text or "").strip()
    if not raw:
        return None, None, "リポジトリを「owner/repo」の形式で入力してください。"

    # URLから貼られた場合は、owner/repo より後ろ（/releases など）が付いていても切り捨てる
    from_url = False

    # SSH形式 git@github.com:owner/repo(.git) を owner/repo に寄せる
    if raw.startswith("git@"):
        raw = raw.split(":", 1)[1] if ":" in raw else raw
        from_url = True

    # URL形式ならホストを確認してからパス部分だけを取り出す
    if "://" in raw:
        parsed = urllib.parse.urlparse(raw)
        host = (parsed.netloc or "").lower().split("@")[-1].split(":")[0]
        if host and host not in ("github.com", "www.github.com"):
            return None, None, f"github.com以外のURLには対応していません: {host}"
        raw = parsed.path
        from_url = True

    raw = raw.strip("/")

    # スキームを省いた「github.com/owner/repo」も受け付ける
    head, _, rest = raw.partition("/")
    if head.lower() in ("github.com", "www.github.com") and rest:
        raw = rest
        from_url = True

    parts = [p for p in raw.split("/") if p]
    if from_url and len(parts) > 2:
        parts = parts[:2]   # 例: owner/repo/releases/latest をそのまま貼られた場合
    if len(parts) != 2:
        return None, None, "「owner/repo」の形式で入力してください（例: yuya6703-dot/auto-reply-bot）。"

    owner, repo = parts
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not GITHUB_OWNER_RE.match(owner):
        return None, None, f"ユーザー名/組織名として使えない文字が含まれています: {owner}"
    if not GITHUB_REPO_RE.match(repo):
        return None, None, f"リポジトリ名として使えない文字が含まれています: {repo}"
    return owner, repo, ""

# 自動アップデートの確認間隔（時間）。起動直後に1回確認し、以降はこの間隔で繰り返す。
# このアプリは監視ボットとして長時間起動しっぱなしになるため、起動時の1回だけでは新版に気付けない。
# GitHub APIは未認証でも1時間あたり60回叩けるので、この頻度でも制限には全く届かない。
AUTO_UPDATE_CHECK_INTERVAL_HOURS = 6

# ダウンロード済みの新バージョンを、適用するまで置いておく場所。
# ⚠️ ここをアプリフォルダ(BASE_DIR)の中にしてはいけない。差し替えはrobocopyでフォルダ一式を
# コピーするため、コピー元がコピー先の内側にあると自分自身を無限にコピーしてしまう。
PENDING_UPDATE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
    "AutoReplyTool", "pending_update"
)
PENDING_UPDATE_MANIFEST = os.path.join(PENDING_UPDATE_DIR, "manifest.json")

# キーワード自動返信のマスタースイッチ（設定キー）。"1"でON、"0"でOFF。
# ⚠️ セット/ペアごとの有効・無効フラグは書き換えない。ここをOFFにしている間だけ
# 「有効キーワードが0件」として扱い、ONに戻せば元の組み合わせがそのまま復活する。
KEYWORD_AUTO_REPLY_SETTING = "keyword_auto_reply_enabled"

# 絶対に反応させない（無視する）ワードのリスト
IGNORE_WORDS = [
    "がマイクをもらいました"
]

DEFAULT_KEYWORDS = {
    "が音声ルームに参加しました": "よろしくお願いします！"
}

# ====================================================
# 📤 返信の送信まわり
# ====================================================
# Androidのキーコード。貼り付けは KEYCODE_PASTE。
ANDROID_KEYCODE_PASTE = 279

# uiautomator2がエミュレータに入れる入力補助IMEのパッケージ名。
# ⚠️ この補助バーには「Send」「Clear Text」ボタンが並んでいる。
# 送信ボタンを画面から探すとき、アプリ側の「送る」ではなく
# この「Send」を押してしまわないよう、パッケージ名で除外する。
UIAUTOMATOR_IME_PACKAGE = "com.github.uiautomator"

# 監視対象アプリの裏に常に居座り、画面ダンプに混ざってくるもの。
# MuMuのランチャーはアプリのアイコン名を10件以上ばらまくため、除外しないと
# 「読み取れた文字」がランチャーで埋まり、肝心のチャットが見えなくなる。
BACKGROUND_NOISE_PACKAGES = (
    "app.lawnchair",            # MuMuのホーム画面（ランチャー）
    "com.android.systemui",     # ステータスバー（時計・電池・通知）
    "com.mumu.launcher",        # 旧バージョンのランチャー
    "com.android.launcher3",
)

# 送信ボタンの文言。完全一致を優先する。
# ⚠️ 部分一致だけで探すと、入力欄のプレースホルダー「メッセージを送信」が
# 「送信」を含むために引っかかり、送信ボタンのつもりで入力欄を押してしまう。
SEND_BUTTON_EXACT_LABELS = ("送る", "送信", "送信する", "Send", "send", "SEND")
SEND_BUTTON_PARTIAL_LABELS = ("送る", "送信", "Send", "send")
# 部分一致で探すときに、これを含む要素は送信ボタンではないとみなす（入力欄の案内文）
SEND_BUTTON_EXCLUDE_WORDS = ("メッセージ", "コメント", "入力", "チャット")

# ====================================================
# ✅ ダイアログの自動OK
# ====================================================
# 自動で閉じてよいダイアログを見分ける目印（カンマ区切り・設定で変更可）。
# ⚠️ この目印が画面に無いダイアログには絶対に触らない。
DEFAULT_AUTO_OK_KEYWORDS = "当選者,選ばれました"

# 押す対象にするボタンの文言。完全一致で探す。
AUTO_OK_BUTTON_LABELS = ("OK", "ok", "Ok", "はい", "確認", "確認する", "閉じる", "とじる")

# bounds属性の中身 "[左,上][右,下]" を読むための式（属性値そのものに当てる）
RE_BOUNDS_VALUE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")

# ⚠️ MuMuは画面を4枚（mumuscreen000〜003）同時に動かしており、
# アプリごとに別のディスプレイへ表示されることがある。実測(2026-08-08):
#   ディスプレイ0 = ホーム画面(app.lawnchair) ※入力フォーカスを持つ
#   ディスプレイ2 = GRAVITYの音声ルーム
#   ディスプレイ3 = 設定アプリ
# 画面ダンプ(dump_hierarchy)は全ディスプレイをまとめて返すので読み取りはできるが、
# uiautomator2の click/press/swipe は既定のディスプレイ0にしか届かない。
# そのため対象アプリを操作したつもりでホーム画面を触ってしまい、
# 「設定アプリが開く」「ホーム画面に切り替わる」が起きていた。
# 各ノードの display-id を見て対象アプリのディスプレイを特定し、
# 入力は `input -d <番号>` でそのディスプレイへ送ること。
RE_DISPLAY_ID = re.compile(r'display-id="(\d+)"')

# Androidのキーコード（input keyevent に渡す番号）
ANDROID_KEYCODE_BACK = 4
ANDROID_KEYCODE_ENTER = 66

# 同じダイアログを連打しないための最短間隔（秒）
AUTO_OK_MIN_INTERVAL_SECONDS = 2.0

# ====================================================
# 🔔 アラーム音設定
# ====================================================
# アラーム音の種類
ALARM_TYPE_BEEP = "beep"          # 内蔵のビープ音
ALARM_TYPE_ZUNDAMON = "zundamon"  # VOICEVOXでずんだもんに読み上げさせる
ALARM_TYPE_FILE = "file"          # 手持ちの音声ファイル

# VOICEVOX（ローカルで起動しているエンジン）のデフォルトURL
DEFAULT_VOICEVOX_URL = "http://127.0.0.1:50021"

# ずんだもんのスタイルと話者ID。エンジンに接続できた場合は実際の一覧で上書きされる
DEFAULT_ZUNDAMON_STYLES = {
    "ノーマル": 3,
    "あまあま": 1,
    "ツンツン": 7,
    "セクシー": 5,
    "ささやき": 22,
    "ヒソヒソ": 38,
    "ヘロヘロ": 75,
    "なみだめ": 76,
}

# ずんだもんに読み上げさせるワードの初期値
DEFAULT_ZUNDAMON_TEXT = "時間になったのだ！"

# キャラ一覧の初期値 {キャラ名: {スタイル名: 話者ID}}。
# VOICEVOXに接続できたら、実際に入っている全キャラで上書きされる。
DEFAULT_VOICEVOX_SPEAKERS = {"ずんだもん": dict(DEFAULT_ZUNDAMON_STYLES)}

# 読み上げの既定キャラ（設定が無いときに使う）
DEFAULT_SPEECH_SPEAKER_NAME = "ずんだもん"
DEFAULT_SPEECH_STYLE_NAME = "ノーマル"

# AivisSpeech（VOICEVOXと同じAPI形式のローカルエンジン。既定のポートが違う）のデフォルトURL
DEFAULT_AIVISSPEECH_URL = "http://127.0.0.1:10101"

# ⚠️ 話者の選択は "engine:話者ID" という文字列で保存する（例: "voicevox:3"）。
# VOICEVOXとAivisSpeechは別エンジンなので、同じ話者IDが別のキャラを指すことがあり、
# IDだけではどちらのエンジンに投げればよいか判別できない。
# 旧バージョン（AivisSpeech対応前）が保存した裸の数値文字列は voicevox とみなして読む。
TTS_ENGINE_VOICEVOX = "voicevox"
TTS_ENGINE_AIVISSPEECH = "aivisspeech"
TTS_ENGINES = {
    TTS_ENGINE_VOICEVOX: {"label": "VOICEVOX", "default_url": DEFAULT_VOICEVOX_URL},
    TTS_ENGINE_AIVISSPEECH: {"label": "AivisSpeech", "default_url": DEFAULT_AIVISSPEECH_URL},
}

# AivisSpeechの起動を待つ最大秒数（VOICEVOXと同じく、初回起動には時間がかかる）
AIVISSPEECH_STARTUP_TIMEOUT_SECONDS = 90

# ====================================================
# 🗣️ 読み上げ / スマホ連携の設定
# ====================================================
# 1回に読み上げる文字数の上限。長文をそのまま投げるとVOICEVOXの合成に時間がかかり、
# その間ずっと他の読み上げが待たされるため、入口で切っておく。
MAX_SPEECH_TEXT_LENGTH = 200

# ====================================================
# ❓ 疑問文の自動判定（音声認識は句読点を返さないため）
# ====================================================
# ⚠️ 音声認識の結果には「？」が付かない。そのままだと疑問文が
# 平叙文の抑揚で読まれ、質問に聞こえない。
# 実測: AivisSpeechは「？」「！」の両方で音が変わる。
#       VOICEVOXは「？」では変わるが「！」では変わらない。
# 文字の形から疑問文を見分けて「。」を「？」に差し替える。
# 調整に使っていない文での正解率は90%（実測）。

# 文末が疑問を表す形
RE_QUESTION_TAIL = re.compile(
    r"(ますか|ですか|でしょうか|だろうか|ましたか|でしたか|かな|かしら|のか|"
    r"ないか|ませんか|ありますか|いますか|できますか|か)$")

# 「〜たの」「〜るの」など、動詞に「の」が付いた疑問
RE_QUESTION_NO_TAIL = re.compile(r"(た|る|ない|てる|でる|んだ)の$")

# 「か」で終わるが疑問ではない語
RE_NOT_QUESTION = re.compile(
    r"(そうか|確か|たしか|まさか|静か|しずか|明らか|あきらか|"
    r"豊か|ゆたか|細か|こまか|柔らか|やわらか)$")

# 文中にあれば疑問の手がかりになる語
QUESTION_WORDS = ("何", "なに", "なん", "どこ", "いつ", "誰", "だれ", "なぜ",
                  "どうして", "どっち", "どちら", "どれ", "どの", "いくら",
                  "いくつ", "どう", "どんな")

# 疑問詞を含むが疑問ではない決まり文句
QUESTION_FIXED_PHRASES = ("どうもありがとう", "どうも", "どういたしまして",
                          "どうぞ", "どうか", "なんでもない", "なんとなく")

# 断定で終わっていれば、疑問詞があっても疑問とはみなさない
RE_ASSERTIVE_TAIL = re.compile(r"(です|ます|だ|である|した|ない)$")

# 文の区切り（この記号で文を分ける）
RE_SENTENCE_SPLIT = re.compile(r"([。．.！!？?])")


def looks_like_question(sentence):
    """その一文が疑問文らしいか（音声認識には「？」が付かないため、形で見分ける）"""
    s = (sentence or "").strip()
    if not s:
        return False
    if any(s == p or s.startswith(p) for p in QUESTION_FIXED_PHRASES):
        return False
    if RE_NOT_QUESTION.search(s):
        return False
    if RE_QUESTION_TAIL.search(s):
        return True
    if RE_QUESTION_NO_TAIL.search(s):
        return True
    if any(w in s for w in QUESTION_WORDS) and not RE_ASSERTIVE_TAIL.search(s):
        return True
    return False


# ⚠️ 感嘆（！）は文字だけでは判定できない。
# 「すごいですね」は感嘆にも平静にもなり、決めるのは声の勢いだから。
# そのため主な手がかりは「話した声の大きさ」で、文字は補助に使う。
# 実測(AivisSpeech): 「！」を付けると音量が31%増え(RMS 4334->5677)、やや短くなる。
#
# 文字だけで感嘆と言い切れるのは、感動詞がそれ単体で一文になっている場合。
# 「すごいですね」ではなく「すごい」「やった」のような短い一言。
EXCLAIM_WORDS = ("やった", "すごい", "すご", "うわ", "わあ", "わー", "おお", "おー",
                 "えー", "ええ", "うそ", "まじ", "やば", "いいね", "最高", "よし",
                 "おめでとう", "ありがとう", "がんばれ", "頑張れ", "おはよう")

# 言い方の癖を取り除いて見比べるための処理。
# ⚠️ 促音「っ」をどこでも消してはいけない。「やった」が「やた」になり、
#    肝心の語が一致しなくなる。促音を削るのは語尾だけにする。
# ⚠️ 伸ばし棒は語尾だけでは足りない。「すごーい」のように語中に入るため。
RE_EXCLAIM_LONG = re.compile(r"[ー〜~]+")        # 伸ばし棒はどこでも消す
RE_EXCLAIM_TAIL = re.compile(r"[ッっ!！\s]+$")   # 促音・記号は語尾だけ消す


def looks_like_exclamation(sentence):
    """
    その一文が、文字だけで感嘆と言い切れるか。

    ⚠️ 迷ったらFalseにする。余計な「！」は付け忘れよりずっと耳障りなため。
    """
    s = (sentence or "").strip()
    if not s:
        return False
    if looks_like_question(s):
        return False        # 疑問が優先（「すごいですか」は感嘆ではない）
    core = RE_EXCLAIM_TAIL.sub("", RE_EXCLAIM_LONG.sub("", s))
    return core in EXCLAIM_WORDS


def apply_sentence_marks(text, loud=False):
    """
    文ごとに区切りの「。」を「？」「！」へ差し替える。

    loud=True は「普段より大きな声で言われた」という合図。
    感嘆かどうかは声の勢いで決まるので、これが主な手がかりになる。

    ⚠️ 既に「？」「！」が付いている文は触らない。
    自分で打った文（定型文など）の意図を勝手に変えないため。
    """
    raw = (text or "")
    if not raw.strip():
        return raw

    parts = RE_SENTENCE_SPLIT.split(raw)
    out = []
    # split の結果は [本文, 区切り, 本文, 区切り, ...] の並びになる
    for i in range(0, len(parts), 2):
        body = parts[i]
        mark = parts[i + 1] if i + 1 < len(parts) else ""
        if body.strip() and mark in ("。", "．", "."):
            if looks_like_question(body):
                mark = "？"          # 疑問が最優先
            elif loud or looks_like_exclamation(body):
                mark = "！"
        out.append(body + mark)
    return "".join(out)


def apply_question_marks(text):
    """文ごとに疑問文かを見て「。」を「？」に差し替える（声の大きさは使わない）"""
    return apply_sentence_marks(text, loud=False)

# 読み上げ待ちの上限。ここを超える要求は捨てる（連打・誤送信で延々と喋り続けるのを防ぐ）
MAX_SPEECH_QUEUE_SIZE = 20

# 読み上げ履歴として覚えておく件数（アプリを閉じると消える。残したい文は定型文に保存する）
MAX_SPEECH_HISTORY = 30

# 合成済みWAVをメモリに保持する件数の上限。
# 読み上げは毎回違う文が来るため、上限を設けないと使い続けるほどメモリを食い続ける。
MAX_SPEECH_WAV_CACHE = 40

# スマホ連携用の簡易Webサーバーが待ち受けるポート
DEFAULT_PHONE_BRIDGE_PORT = 8765

# 暗証番号を連続で何回間違えたら締め出すか、締め出す秒数。
# 6桁は同じWi-Fi内から総当たりできてしまう桁数なので、失敗が続いたら
# しばらく門を閉じて、総当たりに現実的でない時間がかかるようにする。
PHONE_BRIDGE_MAX_PIN_FAILURES = 5
PHONE_BRIDGE_LOCKOUT_SECONDS = 30

# 解析結果(audio_query)をサーバー側に取っておく件数。
# ⚠️ 解析結果はスマホへ丸ごと返さない。audio_queryは39文字の文でも約7.7KBあり、
# 編集のたびに往復させると重いうえ、スマホから来たJSONをそのままエンジンへ
# 転送することになる。サーバーが預かっておき、スマホからは
# 「どの解析の、何番目の句を、どのアクセントにするか」だけを送らせる。
PHONE_BRIDGE_MAX_ANALYSES = 8

# VOICEVOXの起動を待つ最大秒数（起動には数十秒かかることがある）
VOICEVOX_STARTUP_TIMEOUT_SECONDS = 90

# 起動時エラーやDBエラーを記録するファイル（exeと同じ場所に出力される）
ERROR_LOG_FILE = os.path.join(BASE_DIR, "error_log.txt")
ERROR_LOG_FILE_NAME = os.path.basename(ERROR_LOG_FILE)


def safe_print(message):
    """
    exe(--windowed)ではsys.stdoutがNoneになり、print()がAttributeErrorで落ちる。
    コンソールがあれば出力し、無ければエラーログファイルに追記する。
    """
    try:
        if sys.stdout is not None:
            print(message)
    except Exception:
        pass
    write_error_log(message)


def write_error_log(message):
    """エラー内容をファイルに追記する（exeでの原因調査用）"""
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


# 画面から読み取った文字列をログに保存する際に伏せるための設定。
# チャット画面には他の利用者の名前が表示されるため、そのまま保存すると
# 「誰がいつルームに入ったか」という第三者の情報がDBに残り続けてしまう。
SCREEN_TEXT_MASK = "＊＊＊"
# 最初の「から最後の」までをまとめて対象にする（貪欲マッチ）。
# 「[^」]*」のように最短で区切ると、画面の文字に」が含まれていた場合
# （例: 名前が "」ゆうや"）にそこで切れてしまい、後半が伏せられずに残る。
# 監視ログのメッセージは「」を1組しか含まないため、貪欲でも過剰にはならない。
# reply_messageは改行を含むことがあるのでDOTALLが必須。
_QUOTED_TEXT_RE = re.compile(r'「(.*)」', re.DOTALL)


def mask_screen_text(message, keep_words=()):
    """
    ログメッセージのうち、画面から読み取った部分（＝他人の名前が入りうる箇所）を伏せる。

    - 「」で囲まれた画面由来の文字列を ＊＊＊ に置き換える
    - ただし自分で登録した検知ワード・返信ワードは、後から見て何が起きたか
      分からなくなるため、そのまま残す
    - 初回スキャンの一覧（" - 読み取った文字"）は行ごと伏せる

    画面(GUI)の表示には適用しない。監視中は実際の内容が見えたほうが確認しやすく、
    そちらは画面を閉じれば残らないため。
    """
    if not message:
        return message

    if message.startswith(" - "):
        return " - " + SCREEN_TEXT_MASK

    keep_words = [w for w in keep_words if w]

    def mask_one(content):
        if not content:
            return content
        for word in keep_words:
            if word in content:
                # 登録ワードは残し、その前後（名前などが入る部分）だけ伏せる
                head, _, tail = content.partition(word)
                return (SCREEN_TEXT_MASK if head else "") + word + (SCREEN_TEXT_MASK if tail else "")
        return SCREEN_TEXT_MASK

    return _QUOTED_TEXT_RE.sub(lambda m: "「" + mask_one(m.group(1)) + "」", message)


def normalize_number_text(text):
    """
    日本語入力のまま数字を打つと「１０」のような全角数字が入る。
    Pythonのint()は全角も解釈するため動作自体は問題ないが、
    そのままDBに保存すると見た目が揃わないので半角に正規化しておく。
    """
    if not text:
        return ""
    return unicodedata.normalize("NFKC", str(text)).strip()


def format_hms(total_seconds):
    """秒数を 00:00:00 形式にする。タイマーの残り時間表示と保存済みタイマー一覧の両方で使う。"""
    total_seconds = max(0, int(total_seconds))
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# ====================================================
# 🗄️ 1. データ永続化 (SQLite3)
# ====================================================
class DatabaseManager:
    # logsテーブルに残す最大件数。監視中は1行ログが出るたびにINSERTされるため、
    # 上限を設けないとDBが際限なく肥大化する。
    MAX_LOG_ROWS = 5000

    def __init__(self, db_name=DB_FILE):
        self.db_name = db_name
        self._log_insert_count = 0
        self.init_db()

    @contextlib.contextmanager
    def get_connection(self):
        """
        接続を作り、ブロックを抜けるときにコミットして必ず閉じる。
        以前は接続を閉じておらず、GCによる解放任せになっていた。
        呼び出し側の `with self.get_connection() as conn:` はそのまま使える。
        """
        conn = sqlite3.connect(self.db_name, timeout=10.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def init_db(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # ログ用テーブル
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT,
                        message TEXT
                    )
                ''')
                # 設定用テーブル（座標・自動スクロール等の単一値設定）
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                ''')
                # キーワードセット（グループ）テーブル。セットごとに有効/無効を切り替えられる
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS keyword_sets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE,
                        enabled INTEGER DEFAULT 1,
                        sort_order INTEGER DEFAULT 0
                    )
                ''')
                # キーワード（検知ワード⇔返信ワード）テーブル。set_idでキーワードセットに属する
                # enabled: ペア単位の有効/無効。0のペアはセットが有効でも監視対象から外れる
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS keywords (
                        set_id INTEGER,
                        trigger_word TEXT,
                        reply_message TEXT,
                        enabled INTEGER DEFAULT 1,
                        PRIMARY KEY (set_id, trigger_word)
                    )
                ''')
                # 保存したタイマー（プリセット）テーブル。名前を付けて何個でも登録し、一覧から呼び出せる。
                # settingsテーブルのtimer_hours等は「最後に使った時間」として引き続き使うため、こことは別物。
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS timer_presets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE,
                        total_seconds INTEGER NOT NULL,
                        sort_order INTEGER DEFAULT 0
                    )
                ''')
                # よく使う読み上げ文（定型文）。PCの読み上げタブとスマホの両方から呼び出せる
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS speech_phrases (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        text TEXT UNIQUE,
                        sort_order INTEGER DEFAULT 0
                    )
                ''')
                conn.commit()

                self._migrate_legacy_keywords_table(conn, cursor)
                self._migrate_keyword_enabled_column(conn, cursor)
                self._cleanup_legacy_backup_table(conn, cursor)

                # デフォルトセットが1つも無ければ作成する（初回起動時、またはマイグレーション後）
                cursor.execute('SELECT COUNT(*) FROM keyword_sets')
                set_count = cursor.fetchone()[0]
                if set_count == 0:
                    cursor.execute(
                        'INSERT INTO keyword_sets (name, enabled, sort_order) VALUES (?, 1, 0)',
                        ("デフォルト",)
                    )
                    default_set_id = cursor.lastrowid
                    conn.commit()

                    # 初回起動時はデフォルトキーワードをデフォルトセットに投入
                    cursor.execute('SELECT COUNT(*) FROM keywords')
                    kw_count = cursor.fetchone()[0]
                    if kw_count == 0:
                        for k, v in DEFAULT_KEYWORDS.items():
                            cursor.execute(
                                'INSERT OR REPLACE INTO keywords (set_id, trigger_word, reply_message) VALUES (?, ?, ?)',
                                (default_set_id, k, v)
                            )
                        conn.commit()
        except sqlite3.Error as e:
            safe_print(f"DB初期化エラー: {e}")

    def _migrate_legacy_keywords_table(self, conn, cursor):
        """
        旧バージョン（キーワードセット導入前）のkeywordsテーブルは
        trigger_word単独が主キーで、set_idの概念が無かった。
        既存データがある場合は「デフォルト」セットを作成し、その中に移す。
        すでに新しいスキーマ(set_id列あり)であれば何もしない。
        """
        try:
            cursor.execute("PRAGMA table_info(keywords)")
            columns = [row[1] for row in cursor.fetchall()]
            if "set_id" in columns:
                return  # 既に新しいスキーマなのでマイグレーション不要

            # 旧テーブル（set_id列が無い）が存在する場合、退避してから作り直す
            cursor.execute("SELECT trigger_word, reply_message FROM keywords")
            legacy_rows = cursor.fetchall()

            cursor.execute("ALTER TABLE keywords RENAME TO keywords_legacy_backup")
            cursor.execute('''
                CREATE TABLE keywords (
                    set_id INTEGER,
                    trigger_word TEXT,
                    reply_message TEXT,
                    enabled INTEGER DEFAULT 1,
                    PRIMARY KEY (set_id, trigger_word)
                )
            ''')

            if legacy_rows:
                cursor.execute(
                    'INSERT INTO keyword_sets (name, enabled, sort_order) VALUES (?, 1, 0)',
                    ("デフォルト",)
                )
                default_set_id = cursor.lastrowid
                for trigger_word, reply_message in legacy_rows:
                    cursor.execute(
                        'INSERT OR REPLACE INTO keywords (set_id, trigger_word, reply_message) VALUES (?, ?, ?)',
                        (default_set_id, trigger_word, reply_message)
                    )

            conn.commit()
            safe_print(f"旧キーワードデータ({len(legacy_rows)}件)を「デフォルト」セットに移行しました。")
        except sqlite3.Error as e:
            safe_print(f"キーワードデータの移行中にエラー: {e}")

    def _migrate_keyword_enabled_column(self, conn, cursor):
        """
        ペア単位の有効/無効(enabled列)を後から追加したバージョンへの移行。
        既存DBのkeywordsテーブルにenabled列が無ければ追加し、既存ペアは全て有効(1)にする。
        """
        try:
            cursor.execute("PRAGMA table_info(keywords)")
            columns = [row[1] for row in cursor.fetchall()]
            if "enabled" in columns:
                return
            cursor.execute("ALTER TABLE keywords ADD COLUMN enabled INTEGER DEFAULT 1")
            cursor.execute("UPDATE keywords SET enabled = 1 WHERE enabled IS NULL")
            conn.commit()
            safe_print("keywordsテーブルにenabled列を追加しました（既存ペアは全て有効）。")
        except sqlite3.Error as e:
            safe_print(f"enabled列の追加中にエラー: {e}")

    def _cleanup_legacy_backup_table(self, conn, cursor):
        """
        旧テーブルの移行時に作られる退避テーブル(keywords_legacy_backup)を削除する。
        keywordsが新スキーマ(set_id列あり)になっていれば移行は完了しているため、
        退避テーブルを残しておく理由はない。
        """
        try:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='keywords_legacy_backup'"
            )
            if not cursor.fetchone():
                return

            cursor.execute("PRAGMA table_info(keywords)")
            columns = [row[1] for row in cursor.fetchall()]
            if "set_id" not in columns:
                return  # 移行が完了していないので退避データは残しておく

            cursor.execute("DROP TABLE keywords_legacy_backup")
            conn.commit()
            safe_print("移行済みの退避テーブル(keywords_legacy_backup)を削除しました。")
        except sqlite3.Error as e:
            safe_print(f"退避テーブルの削除中にエラー: {e}")

    # --- 設定(単一値) ---
    def save_setting(self, key, value):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
                conn.commit()
        except sqlite3.Error as e:
            safe_print(f"設定保存エラー: {e}")

    def get_setting(self, key, default_value=None):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
                row = cursor.fetchone()
                return row[0] if row else default_value
        except sqlite3.Error:
            return default_value

    # --- キーワードセット ---
    def get_keyword_sets(self):
        """全キーワードセットを [{'id':, 'name':, 'enabled':}, ...] の形で返す（sort_order順）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id, name, enabled FROM keyword_sets ORDER BY sort_order, id')
                return [
                    {"id": row[0], "name": row[1], "enabled": bool(row[2])}
                    for row in cursor.fetchall()
                ]
        except sqlite3.Error:
            return []

    def create_keyword_set(self, name):
        name = name.strip()
        if not name:
            return False, "セット名を入力してください。", None
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COALESCE(MAX(sort_order), -1) + 1 FROM keyword_sets')
                next_order = cursor.fetchone()[0]
                cursor.execute(
                    'INSERT INTO keyword_sets (name, enabled, sort_order) VALUES (?, 1, ?)',
                    (name, next_order)
                )
                conn.commit()
                return True, "", cursor.lastrowid
        except sqlite3.IntegrityError:
            return False, "同じ名前のセットが既に存在します。", None
        except sqlite3.Error as e:
            return False, str(e), None

    def rename_keyword_set(self, set_id, new_name):
        new_name = new_name.strip()
        if not new_name:
            return False, "セット名を入力してください。"
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE keyword_sets SET name = ? WHERE id = ?', (new_name, set_id))
                conn.commit()
            return True, ""
        except sqlite3.IntegrityError:
            return False, "同じ名前のセットが既に存在します。"
        except sqlite3.Error as e:
            return False, str(e)

    def delete_keyword_set(self, set_id):
        """セットと、それに属するキーワードを削除する。最後の1セットは削除させない（呼び出し側で確認済みの前提）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM keywords WHERE set_id = ?', (set_id,))
                cursor.execute('DELETE FROM keyword_sets WHERE id = ?', (set_id,))
                conn.commit()
            return True, ""
        except sqlite3.Error as e:
            return False, str(e)

    def set_keyword_set_enabled(self, set_id, enabled):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'UPDATE keyword_sets SET enabled = ? WHERE id = ?',
                    (1 if enabled else 0, set_id)
                )
                conn.commit()
            return True, ""
        except sqlite3.Error as e:
            return False, str(e)

    # --- キーワード ---
    def get_keywords_in_set(self, set_id):
        """
        指定セット内のペアを [{'trigger':, 'reply':, 'enabled':}, ...] で返す
        （キーワード設定タブの一覧表示用）
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT trigger_word, reply_message, COALESCE(enabled, 1) FROM keywords WHERE set_id = ?',
                    (set_id,)
                )
                return [
                    {"trigger": row[0], "reply": row[1], "enabled": bool(row[2])}
                    for row in cursor.fetchall()
                ]
        except sqlite3.Error:
            return []

    def get_active_keywords(self):
        """
        有効になっているセットに属し、かつペア自体も有効なキーワードだけを
        1つの {検知ワード: 返信ワード} にまとめて返す。
        監視ループはセットの概念を意識せず、この結果だけを見れば良い。
        複数の有効セットで同じ検知ワードが重複している場合は、後勝ちで上書きされる。

        「キーワード自動返信」がOFFのときは、有効なセットがあっても空で返す。
        監視ループは元から「有効キーワードが0件なら何も送らない」作りなので、
        ここで止めればループ側を一切変えずに自動返信だけを切れる。
        画面の読み取り・ログ・手入力送信はそのまま動き続ける。
        """
        if self.get_setting(KEYWORD_AUTO_REPLY_SETTING, "1") != "1":
            return {}
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT k.trigger_word, k.reply_message
                    FROM keywords k
                    JOIN keyword_sets s ON k.set_id = s.id
                    WHERE s.enabled = 1 AND COALESCE(k.enabled, 1) = 1
                ''')
                return dict(cursor.fetchall())
        except sqlite3.Error:
            return {}

    def upsert_keyword(self, set_id, trigger_word, reply_message):
        """新規追加は有効状態で作成し、既存ペアの更新時は現在の有効/無効をそのまま維持する"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    INSERT INTO keywords (set_id, trigger_word, reply_message, enabled)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(set_id, trigger_word)
                    DO UPDATE SET reply_message = excluded.reply_message
                    ''',
                    (set_id, trigger_word, reply_message)
                )
                conn.commit()
            return True, ""
        except sqlite3.Error as e:
            return False, str(e)

    def set_keyword_enabled(self, set_id, trigger_word, enabled):
        """ペア単位の有効/無効を切り替える"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'UPDATE keywords SET enabled = ? WHERE set_id = ? AND trigger_word = ?',
                    (1 if enabled else 0, set_id, trigger_word)
                )
                conn.commit()
            return True, ""
        except sqlite3.Error as e:
            return False, str(e)

    def delete_keyword(self, set_id, trigger_word):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'DELETE FROM keywords WHERE set_id = ? AND trigger_word = ?',
                    (set_id, trigger_word)
                )
                conn.commit()
            return True, ""
        except sqlite3.Error as e:
            return False, str(e)

    # --- 保存したタイマー ---
    def get_timer_presets(self):
        """
        保存済みタイマーを [{'id':, 'name':, 'total_seconds':}, ...] の形で返す（sort_order順）。
        タイマータブの一覧表示用。
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT id, name, total_seconds FROM timer_presets ORDER BY sort_order, id'
                )
                return [
                    {"id": row[0], "name": row[1], "total_seconds": int(row[2])}
                    for row in cursor.fetchall()
                ]
        except sqlite3.Error:
            return []

    def create_timer_preset(self, name, total_seconds):
        """
        新しいタイマーを保存する。同名が既にある場合はIntegrityErrorになるので失敗を返す。
        上書きするかどうかは呼び出し側で確認し、update_timer_presetを使うこと。
        """
        name = name.strip()
        if not name:
            return False, "タイマー名を入力してください。", None
        if total_seconds <= 0:
            return False, "1秒以上の時間を設定してください。", None
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COALESCE(MAX(sort_order), -1) + 1 FROM timer_presets')
                next_order = cursor.fetchone()[0]
                cursor.execute(
                    'INSERT INTO timer_presets (name, total_seconds, sort_order) VALUES (?, ?, ?)',
                    (name, int(total_seconds), next_order)
                )
                conn.commit()
                return True, "", cursor.lastrowid
        except sqlite3.IntegrityError:
            return False, "同じ名前のタイマーが既に保存されています。", None
        except sqlite3.Error as e:
            return False, str(e), None

    def update_timer_preset(self, preset_id, total_seconds):
        """既存タイマーの時間だけを書き換える（名前と並び順はそのまま）"""
        if total_seconds <= 0:
            return False, "1秒以上の時間を設定してください。"
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'UPDATE timer_presets SET total_seconds = ? WHERE id = ?',
                    (int(total_seconds), preset_id)
                )
                conn.commit()
            return True, ""
        except sqlite3.Error as e:
            return False, str(e)

    def rename_timer_preset(self, preset_id, new_name):
        new_name = new_name.strip()
        if not new_name:
            return False, "タイマー名を入力してください。"
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'UPDATE timer_presets SET name = ? WHERE id = ?',
                    (new_name, preset_id)
                )
                conn.commit()
            return True, ""
        except sqlite3.IntegrityError:
            return False, "同じ名前のタイマーが既に保存されています。"
        except sqlite3.Error as e:
            return False, str(e)

    def delete_timer_preset(self, preset_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM timer_presets WHERE id = ?', (preset_id,))
                conn.commit()
            return True, ""
        except sqlite3.Error as e:
            return False, str(e)

    # --- 保存した読み上げ文（定型文） ---
    def get_speech_phrases(self):
        """保存済みの定型文を [{'id':, 'text':}, ...] で返す（登録順）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id, text FROM speech_phrases ORDER BY sort_order, id')
                return [{"id": row[0], "text": row[1]} for row in cursor.fetchall()]
        except sqlite3.Error:
            return []

    def create_speech_phrase(self, text):
        """
        定型文を保存する。同じ文が既にあれば、増やさずにその既存のidを返す
        （同じ文を何度も読み上げてから保存しても、一覧が重複で埋まらないように）。
        """
        text = (text or "").strip()
        if not text:
            return False, "保存する文を入力してください。", None
        text = text[:MAX_SPEECH_TEXT_LENGTH]
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id FROM speech_phrases WHERE text = ?', (text,))
                existing = cursor.fetchone()
                if existing:
                    return True, "already", existing[0]

                cursor.execute('SELECT COALESCE(MAX(sort_order), -1) + 1 FROM speech_phrases')
                next_order = cursor.fetchone()[0]
                cursor.execute(
                    'INSERT INTO speech_phrases (text, sort_order) VALUES (?, ?)',
                    (text, next_order)
                )
                conn.commit()
                return True, "", cursor.lastrowid
        except sqlite3.Error as e:
            return False, str(e), None

    def delete_speech_phrase(self, phrase_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM speech_phrases WHERE id = ?', (phrase_id,))
                conn.commit()
            return True, ""
        except sqlite3.Error as e:
            return False, str(e)

    # --- ログ ---
    def save_log(self, message):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute('INSERT INTO logs (timestamp, message) VALUES (?, ?)', (timestamp, message))

                # 毎回COUNTを取ると重いので、一定件数INSERTするごとにまとめて古い行を捨てる
                self._log_insert_count += 1
                if self._log_insert_count >= 200:
                    self._log_insert_count = 0
                    cursor.execute(
                        'DELETE FROM logs WHERE id NOT IN '
                        '(SELECT id FROM logs ORDER BY id DESC LIMIT ?)',
                        (self.MAX_LOG_ROWS,)
                    )
                conn.commit()
        except sqlite3.Error:
            pass

    def prune_logs(self):
        """起動時に呼び、過去バージョンでたまった古いログを上限件数まで削減する"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM logs')
                total = cursor.fetchone()[0]
                if total <= self.MAX_LOG_ROWS:
                    return 0
                cursor.execute(
                    'DELETE FROM logs WHERE id NOT IN '
                    '(SELECT id FROM logs ORDER BY id DESC LIMIT ?)',
                    (self.MAX_LOG_ROWS,)
                )
                conn.commit()
                return total - self.MAX_LOG_ROWS
        except sqlite3.Error:
            return 0


# ----------------------------------------------------
# 🖱️ 視覚的に範囲を選択するためのGUIクラス（tkinter Toplevelのまま流用）
# ----------------------------------------------------
class ScreenSelector:
    # これより小さい範囲は「ドラッグせずクリックしただけ」とみなして選択失敗にする
    MIN_SELECTION_SIZE = 20

    def __init__(self, parent):
        self.parent = parent
        self.root = tk.Toplevel(parent)
        self.root.attributes("-alpha", 0.3)

        # -fullscreen はプライマリモニタしか覆わないため、エミュレータをサブモニタに
        # 置いていると範囲選択できなかった。仮想デスクトップ全体を覆うように配置する。
        self.origin_x, self.origin_y, width, height = self._virtual_screen_geometry()
        self.root.overrideredirect(True)
        self.root.geometry(f"{width}x{height}+{self.origin_x}+{self.origin_y}")
        self.root.attributes("-topmost", True)
        self.root.config(cursor="cross")

        self.canvas = tk.Canvas(self.root, cursor="cross", bg="grey", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        # 枠なしウインドウには閉じるボタンが無いため、Escapeで抜けられるようにする
        self.root.bind("<Escape>", self.on_cancel)
        self.root.focus_force()

        self.start_x = self.start_y = self.end_x = self.end_y = 0
        self.rect = None
        self.coords = None
        self.error_message = None

    @staticmethod
    def _virtual_screen_geometry():
        """
        全モニタを含む仮想デスクトップの (左端X, 上端Y, 幅, 高さ) を返す。
        取得に失敗した場合はプライマリモニタのサイズにフォールバックする。
        """
        try:
            user32 = ctypes.windll.user32
            SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
            SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
            x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
            if w > 0 and h > 0:
                return x, y, w, h
        except Exception:
            pass
        try:
            w, h = pyautogui.size()
            return 0, 0, int(w), int(h)
        except Exception:
            return 0, 0, 1920, 1080

    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, 1, 1, outline="red", width=2)

    def on_drag(self, event):
        if self.rect is not None:
            self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_cancel(self, event=None):
        self.coords = None
        self.root.destroy()

    def on_release(self, event):
        self.end_x, self.end_y = event.x, event.y

        left = min(self.start_x, self.end_x)
        top = min(self.start_y, self.end_y)
        right = max(self.start_x, self.end_x)
        bottom = max(self.start_y, self.end_y)

        if (right - left) < self.MIN_SELECTION_SIZE or (bottom - top) < self.MIN_SELECTION_SIZE:
            # クリックしただけ・極端に狭い範囲だと監視範囲として意味を成さないので選択失敗にする
            self.coords = None
            self.error_message = (
                "❌ 選択範囲が小さすぎます。監視したいチャットエリアをドラッグして囲んでください。"
            )
            self.root.destroy()
            return

        # キャンバス内座標から、モニタ全体での絶対座標に戻す
        self.coords = (left + self.origin_x, top + self.origin_y,
                       right + self.origin_x, bottom + self.origin_y)
        self.root.destroy()

    def get_coordinates(self):
        self.parent.wait_window(self.root)
        return self.coords


# ====================================================
# 🔄 2. アップデート管理 (GitHub Releases)
# ====================================================
class UpdateManager:
    def __init__(self, db=None, log_callback=None):
        # 監視ワーカーと同じく、設定は都度DBから読む（設定タブで変えたら即座に反映される）。
        # dbを渡さない場合はソースの既定リポジトリを使う。
        self.db = db
        self.log_callback = log_callback or (lambda msg: None)

    def get_repository(self):
        """設定されている(owner, repo)を返す。未設定・空欄なら出荷時の既定値を使う。"""
        owner = repo = ""
        if self.db is not None:
            owner = (self.db.get_setting("github_owner", "") or "").strip()
            repo = (self.db.get_setting("github_repo", "") or "").strip()
        return owner or GITHUB_OWNER, repo or GITHUB_REPO

    def log(self, message):
        try:
            self.log_callback(message)
        except Exception:
            pass

    @staticmethod
    def _parse_version(version_str):
        """'v1.2.3' や '1.2.3' のような文字列をタプル (1,2,3) に変換する"""
        cleaned = version_str.strip().lstrip("vV")
        parts = []
        for p in cleaned.split("."):
            digits = "".join(ch for ch in p if ch.isdigit())
            parts.append(int(digits) if digits else 0)
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])

    def is_newer(self, latest_version_str, current_version_str):
        try:
            return self._parse_version(latest_version_str) > self._parse_version(current_version_str)
        except Exception:
            return False

    def fetch_latest_release(self, timeout=10, owner=None, repo=None):
        """
        GitHub Releases APIから最新リリース情報を取得する。
        owner/repoを渡すと、保存済みの設定ではなくその指定で問い合わせる（接続テスト用）。
        戻り値: dict{tag_name, name, body, assets:[{name, browser_download_url}, ...]} または None（取得失敗時）
        """
        if owner is None or repo is None:
            owner, repo = self.get_repository()
        try:
            req = urllib.request.Request(
                build_release_api_url(owner, repo),
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "auto-reply-tool-updater"
                }
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # リポジトリ名の打ち間違いとpublic/privateの取り違えが同じ404になるため、
                # どのリポジトリを見に行ったのかを必ず添える
                self.log(
                    f"ℹ️ {owner}/{repo} にリリースが見つかりません。"
                    "（リポジトリ名の誤り、またはprivateリポジトリの可能性があります）"
                )
            elif e.code == 403:
                self.log("⚠️ GitHubのアクセス制限に達しました。しばらく待ってからお試しください。")
            else:
                self.log(f"⚠️ アップデート確認中にHTTPエラー: {e}")
            return None
        except Exception as e:
            self.log(f"⚠️ アップデート確認中にエラー: {e}")
            return None

    def find_zip_asset(self, release_data):
        """リリースのアセット一覧から.zipファイルを探す"""
        assets = release_data.get("assets", []) if release_data else []
        for asset in assets:
            name = asset.get("name", "")
            if name.lower().endswith(".zip"):
                return asset
        return None

    def download_asset(self, download_url, dest_path, progress_callback=None, timeout=60):
        """指定URLのファイルをdest_pathへダウンロードする"""
        try:
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "auto-reply-tool-updater"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 1024 * 256
                with open(dest_path, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            progress_callback(downloaded, total_size)
            return True, ""
        except Exception as e:
            return False, str(e)

    def extract_zip(self, zip_path, extract_dir):
        """zipファイルを指定フォルダに展開する"""
        try:
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
            return True, ""
        except Exception as e:
            return False, str(e)

    def find_exe_in_extracted(self, extract_dir, exe_name):
        """
        展開したフォルダの中から目的のexeを再帰的に探す。
        zip内がフォルダで一段ネストされていても対応できるようにするため。
        戻り値: 見つかったexeが入っているフォルダのパス（=新しいアプリ本体一式のルート）
        """
        exe_name_lower = exe_name.lower()
        for root, dirs, files in os.walk(extract_dir):
            for f in files:
                if f.lower() == exe_name_lower:
                    return root
        return None

    def backup_current_installation(self, backup_root_dir):
        """
        現在のアプリフォルダ(BASE_DIR)一式を、アプリフォルダの外側にzipでバックアップする。
        exe単体ではなくフォルダ構成になったため、フォルダごと丸ごと保存する。
        バックアップ先をアプリフォルダの外に置くことで、コピー処理が自分自身を巻き込まないようにしている。
        """
        if not getattr(sys, 'frozen', False):
            self.log("ℹ️ 開発環境（.py実行）のため、バックアップはスキップされます。")
            return None
        try:
            os.makedirs(backup_root_dir, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_base_name = os.path.join(backup_root_dir, f"backup_{timestamp}")
            archive_path = shutil.make_archive(backup_base_name, "zip", BASE_DIR)
            self.log(f"🗂️ 現在のアプリ一式をバックアップしました: {archive_path}")
            return archive_path
        except Exception as e:
            self.log(f"⚠️ バックアップに失敗しました: {e}")
            return None

    @staticmethod
    def _ps_quote(path):
        """PowerShellのシングルクォート文字列として安全に埋め込むため、内部の ' を '' にエスケープする"""
        return str(path).replace("'", "''")

    def create_update_batch_and_launch(self, source_dir, target_dir, target_exe_path,
                                       cleanup_dirs=None, relaunch=True):
        """
        展開済みの新しいアプリ一式(source_dir)を、現在のインストール先(target_dir)へ上書きコピーし、
        再起動するためのPowerShellスクリプトを作成・実行する。
        実行中のexeは自分自身のフォルダを直接上書きできないため、外部スクリプトに処理を委譲してから終了する。

        relaunch=False にすると、差し替え後にアプリを起動し直さない。
        「終了時に自動適用」では、ユーザーが自分でアプリを閉じたのに勝手に再起動しては困るため、
        コピーだけ済ませて終わる（次に手動で起動したときには新バージョンになっている）。

        ユーザーデータ(app_data.db)やエラーログ、backupフォルダは上書き対象から除外する。

        注意: 以前はcmdのbatファイルを使っていたが、フォルダパスに日本語が含まれる場合、
        Shift-JIS(CP932)の一部の漢字（例: 「表」「ソ」など）は2バイト目がバックスラッシュ(\\)や
        キャレット(^)と同じ値になり、cmd.exeのバッチパーサーがコマンドを誤分割してしまう
        既知の問題がある。ユーザーのインストール先フォルダ名は自由な日本語になり得るため、
        この問題を構造的に回避できるPowerShellスクリプト(.ps1、UTF-8 BOM付き)に切り替えている。
        PowerShellはテキストをUnicodeとして正しく解釈するため、この種の文字化け・誤分割は起きない。
        """
        ps1_path = os.path.join(tempfile.gettempdir(), "auto_reply_tool_update.ps1")
        pid = os.getpid()
        cleanup_dirs = cleanup_dirs or []

        cleanup_commands = "\n".join(
            f"Remove-Item -LiteralPath '{self._ps_quote(d)}' -Recurse -Force -ErrorAction SilentlyContinue"
            for d in cleanup_dirs
        )

        source_dir_q = self._ps_quote(source_dir)
        target_dir_q = self._ps_quote(target_dir)
        target_exe_q = self._ps_quote(target_exe_path)
        db_name_q = self._ps_quote(DB_FILE_NAME)
        error_log_name_q = self._ps_quote(ERROR_LOG_FILE_NAME)
        error_log_path_q = self._ps_quote(ERROR_LOG_FILE)
        self_path_q = self._ps_quote(ps1_path)

        # 再起動する場合のみ新しいexeを起動する。しない場合も、何が起きたかは画面に残しておく。
        relaunch_command = (
            f"Start-Process -FilePath '{target_exe_q}'" if relaunch
            else 'Write-Host "The update is ready. It will be used the next time you start the app."'
        )
        # 再起動しない（＝終了時適用）ときは、コピー失敗時にも起動しないので待つ意味がない
        failure_tail = (
            'Write-Host "Update failed. The previous version will be started."\n    Start-Sleep -Seconds 5'
            if relaunch else
            'Write-Host "Update failed. The app was left unchanged."\n    Start-Sleep -Seconds 5'
        )

        # 1. 現在のプロセスの終了を待つ
        # 2. robocopyで新しいファイル一式を上書きコピー（ユーザーデータ等は除外）
        # 3. コピー結果を確認する（robocopyは 0〜7 が成功、8以上が失敗）
        # 4. 新しいexeを起動する
        # 5. 展開に使った一時フォルダを削除する
        # 6. 自分自身(このスクリプト)を削除する
        #
        # コピーに失敗した場合でもアプリが起動しないままになるのは困るので、
        # 旧バージョンの起動は行いつつ、error_log.txtに失敗を記録して気付けるようにする。
        ps1_content = f'''Write-Host "Applying update. Please wait..."

while (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{
    Start-Sleep -Seconds 1
}}
Start-Sleep -Seconds 1

robocopy '{source_dir_q}' '{target_dir_q}' /E /XF '{db_name_q}' '{error_log_name_q}' /XD 'backup' /R:3 /W:1 | Out-Null
$copyExit = $LASTEXITCODE

if ($copyExit -ge 8) {{
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$stamp] アップデートのファイル差し替えに失敗しました (robocopy exit code: $copyExit)。更新は適用されていません。"
    Add-Content -LiteralPath '{error_log_path_q}' -Value $line -Encoding UTF8
    Write-Host $line
    {failure_tail}
}} else {{
    Write-Host "Update applied successfully."
}}

{relaunch_command}

{cleanup_commands}

Remove-Item -LiteralPath '{self_path_q}' -Force -ErrorAction SilentlyContinue
'''
        try:
            # BOM付きUTF-8で保存することで、システムの既定コードページに関係なく
            # PowerShellが常に正しくUnicodeとして読み込むようにする。
            with open(ps1_path, "w", encoding="utf-8-sig") as f:
                f.write(ps1_content)
            subprocess.Popen(
                [
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", ps1_path
                ],
                creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0
            )
            return True
        except Exception as e:
            self.log(f"⚠️ 更新用スクリプトの起動に失敗しました: {e}")
            return False

    # --- 自動アップデート用のステージング（ダウンロードだけ先に済ませておく仕組み） ---
    def stage_update(self, release_data, exe_name):
        """
        新バージョンをダウンロード・展開し、「いつでも適用できる」状態にして置いておく。
        実際の差し替えはアプリ終了時に行うため、ここではファイルを一切書き換えない。

        時間のかかる処理なので、必ずワーカースレッドから呼ぶこと（UIスレッドから呼ぶと固まる）。
        戻り値: (成功したか, エラーメッセージ)
        """
        version = release_data.get("tag_name", "")
        asset = self.find_zip_asset(release_data)
        if not asset:
            return False, "リリースにzipファイルが見つかりませんでした。"
        download_url = asset.get("browser_download_url")
        if not download_url:
            return False, "ダウンロードURLが取得できませんでした。"

        # 前回の準備物が残っていると、新旧のファイルが混ざったフォルダから
        # exeを探すことになってしまうため、必ず作り直す
        self.clear_pending_update()
        try:
            os.makedirs(PENDING_UPDATE_DIR, exist_ok=True)
        except Exception as e:
            return False, f"作業フォルダを作成できませんでした: {e}"

        zip_path = os.path.join(PENDING_UPDATE_DIR, "update.zip")
        success, err = self.download_asset(download_url, zip_path)
        if not success:
            self.clear_pending_update()
            return False, f"ダウンロードに失敗しました: {err}"

        extract_dir = os.path.join(PENDING_UPDATE_DIR, "extracted")
        success, err = self.extract_zip(zip_path, extract_dir)
        if not success:
            self.clear_pending_update()
            return False, f"zipの展開に失敗しました: {err}"

        # zipの中身が想定通りか（目的のexeが入っているか）を、適用前のこの時点で確かめておく。
        # 終了時に初めて気付くと、ユーザーは何も操作できないまま失敗することになる。
        source_dir = self.find_exe_in_extracted(extract_dir, exe_name)
        if not source_dir:
            self.clear_pending_update()
            return False, f"zip内に「{exe_name}」が見つかりませんでした。"

        try:
            os.remove(zip_path)  # 展開後のzipは不要（フォルダを無駄に太らせない）
        except OSError:
            pass

        manifest = {
            "version": version,
            "source_dir": source_dir,
            "exe_name": exe_name,
            "downloaded_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        try:
            with open(PENDING_UPDATE_MANIFEST, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False)
        except Exception as e:
            self.clear_pending_update()
            return False, f"更新情報の保存に失敗しました: {e}"

        return True, ""

    def read_pending_update(self, current_version=APP_VERSION):
        """
        適用待ちの更新情報を返す（無ければNone）。
        アプリを強制終了された場合などに、実体の無い・古い情報が残っていることがあるため、
        「manifestが読める」「展開フォルダが実在する」「現在より新しい」の3点を必ず確かめる。
        """
        try:
            with open(PENDING_UPDATE_MANIFEST, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, ValueError):
            return None

        source_dir = manifest.get("source_dir", "")
        version = manifest.get("version", "")
        if not source_dir or not os.path.isdir(source_dir):
            return None
        if not version or not self.is_newer(version, current_version):
            # 既に適用済み（またはユーザーが手動で新しくした）ので、準備物は用済み
            return None
        return manifest

    def clear_pending_update(self):
        """準備済みの更新一式を削除する（適用後や、失敗して中途半端に残った場合の後片付け）"""
        try:
            shutil.rmtree(PENDING_UPDATE_DIR, ignore_errors=True)
        except Exception:
            pass


# ====================================================
# 📱 スマホ連携（同じWi-Fi内のスマホから文字を受け取る簡易Webサーバー）
# ====================================================
# スマホのブラウザで表示される入力ページ。
# スマホのメッセージアプリと同じ「1行の入力欄＋右に送信ボタン」を画面下端に固定し、
# キーボードが出ている間もその真上に留まるようにしてある。
# 暗証番号は端末のlocalStorageに覚えさせ、2回目以降は入力不要。
PHONE_BRIDGE_PAGE = """<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>ずんだもんに読み上げてもらう</title>
<style>
  :root {
    --bg:#f2f2f7; --fg:#1c1c1e; --sub:#8e8e93; --bar:#f7f7f8;
    --line:#d1d1d6; --field:#ffffff; --send:#0b84ff; --mine:#e9e9eb;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#000000; --fg:#f2f2f7; --sub:#8e8e93; --bar:#1c1c1e;
      --line:#38383a; --field:#2c2c2e; --send:#0b84ff; --mine:#2c2c2e;
    }
  }
  /* border-boxは見た目の都合ではなく必須。content-boxのままだと、入力欄の高さ調整で
     scrollHeight(パディング込み)をheight(パディング別)に書き戻すことになり、
     refreshのたびに欄が16pxずつ伸びていってしまう。 */
  *, *::before, *::after { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  /* 本体を position:fixed で固定し、ドキュメント自体は一切スクロールさせない。
     iOSはキーボードを出すときにレイアウトビューポートを勝手にスクロールさせるため、
     通常フローのままだと入力欄がずれて揺れる。固定してしまえばその影響を受けない。 */
  html { height:100%; overflow:hidden; }
  body {
    position:fixed; top:0; left:0; right:0;
    height:100%;          /* JSが実際に見えている高さへ書き換える */
    margin:0;
    background:var(--bg); color:var(--fg);
    font-family:-apple-system,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;
    display:flex; flex-direction:column; overflow:hidden;
  }
  header {
    flex:none; padding:10px 14px; font-size:13px; color:var(--sub);
    border-bottom:1px solid var(--line); background:var(--bar);
    display:flex; align-items:center; gap:8px;
    padding-top:calc(10px + env(safe-area-inset-top));
  }
  header span { flex:1; }
  header a, header button {
    flex:none; font-size:13px; color:var(--send); background:none;
    border:none; padding:4px 2px; text-decoration:none;
  }
  /* 暗証番号は普段は隠しておき、未入力のときと認証に失敗したときだけ開く */
  #pinrow { flex:none; display:none; padding:10px 14px; background:var(--bar);
            border-bottom:1px solid var(--line); }
  #pinrow.open { display:block; }
  #pin {
    width:100%; box-sizing:border-box; font-size:16px; padding:10px 12px;
    border:1px solid var(--line); border-radius:10px;
    background:var(--field); color:var(--fg);
  }
  /* 画面を左右に分ける。左=送信した内容 / 右=登録したワード */
  #panes { flex:1; display:flex; min-height:0; }
  .pane { flex:1 1 50%; min-width:0; display:flex; flex-direction:column; }
  #logpane { border-right:1px solid var(--line); }
  .panehead {
    flex:none; padding:6px 8px; font-size:12px; font-weight:600; color:var(--sub);
    background:var(--bar); border-bottom:1px solid var(--line);
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }
  .panebody { flex:1; overflow-y:auto; -webkit-overflow-scrolling:touch; min-height:0; }

  /* 左: 送った文の履歴。新しいものが下に積まれる */
  #log { padding:10px 8px; }
  #hint { color:var(--sub); font-size:13px; text-align:center; margin-top:18px; line-height:1.6; }
  .item { margin:0 0 8px auto; max-width:92%; width:fit-content;
          background:var(--mine); border-radius:14px; padding:7px 10px;
          font-size:14px; line-height:1.4; word-break:break-word; cursor:pointer; }
  .item:active { opacity:.5; }
  .meta { display:block; text-align:right; font-size:10px; color:var(--sub); margin-top:3px; }
  .item.ng { background:#3a2326; }
  .item.ng .meta { color:#ff8a8a; }

  /* 右: 登録したワード。各行の左に送信ボタン、右に削除ボタン */
  #phrases { padding:4px 0; }
  #nophrase { color:var(--sub); font-size:13px; text-align:center; margin-top:18px; line-height:1.6; }
  .prow { display:flex; align-items:center; gap:6px;
          padding:6px 6px; border-bottom:1px solid var(--line); }
  .psend {
    flex:none; width:30px; height:30px; padding:0; border:none; border-radius:15px;
    background:var(--send); color:#fff; font-size:13px; line-height:1;
  }
  .psend:active { opacity:.6; }
  .ptext { flex:1; min-width:0; font-size:14px; line-height:1.35; word-break:break-word; }
  .pdel {
    flex:none; width:26px; height:26px; padding:0; border-radius:13px;
    background:transparent; color:var(--sub); border:1px solid var(--line); font-size:14px;
  }
  .pdel:active { background:#c0392b; color:#fff; }

  /* 入力欄はキーボードに合わせて動かす */
  #dock { flex:none; }

  /* 入力バー。キーボードが出たらその真上に来るようJSでずらす */
  #bar {
    display:flex; align-items:flex-end; gap:8px;
    padding:8px 10px calc(8px + env(safe-area-inset-bottom));
    background:var(--bar); border-top:1px solid var(--line);
  }
  /* キーボードが出ている間はホームインジケータ用の余白が要らない。
     env()の値はキーボードの開閉では変わらないため、そのままだと
     キーボードとの間に34px前後の隙間が残ってしまう。 */
  #bar.kb { padding-bottom:6px; }
  #text {
    flex:1; min-width:0; resize:none; overflow-y:auto;
    max-height:110px; height:38px;
    font-size:16px;               /* 16px未満だとiOSがフォーカス時に勝手にズームする */
    line-height:20px; padding:8px 14px;   /* 20 + 上下8 + 枠2 = ちょうど38pxの1行 */
    border:1px solid var(--line); border-radius:19px;
    background:var(--field); color:var(--fg);
    font-family:inherit;
  }
  #send {
    flex:none; height:38px; padding:0 18px; border:none; border-radius:19px;
    background:var(--send); color:#fff; font-size:16px; font-weight:600;
  }
  #send:disabled { background:var(--line); color:var(--sub); }
  #star {
    flex:none; width:38px; height:38px; border:1px solid var(--line); border-radius:19px;
    background:var(--field); color:var(--fg); font-size:17px; padding:0;
  }
  #star:disabled { opacity:.4; }
</style></head><body>

<header>
  <span id="head">🗣️ ずんだもんに読み上げてもらう</span>
  <a href="/mic">声で話す</a>
  <a href="/voice">声の解析</a>
  <button id="pintoggle" type="button">暗証番号</button>
</header>
<div id="pinrow">
  <input id="pin" type="text" inputmode="numeric" autocomplete="off"
         placeholder="PCの画面に表示されている6桁の番号">
</div>

<div id="panes">
  <div class="pane" id="logpane">
    <div class="panehead">送信した内容</div>
    <div class="panebody"><div id="log"><div id="hint">下の欄に入力して<br>「送る」を押すと<br>読み上げます。<br><br>送った文はタップで<br>もう一度読み上げ。</div></div></div>
  </div>
  <div class="pane" id="phrasepane">
    <div class="panehead">登録したワード</div>
    <div class="panebody"><div id="phrases"><div id="nophrase">⭐ で登録すると<br>ここに並びます。</div></div></div>
  </div>
</div>

<div id="dock">
  <div id="bar">
    <textarea id="text" rows="1" placeholder="メッセージを送信"
              enterkeyhint="send" autocomplete="off" autocapitalize="sentences"></textarea>
    <button id="star" type="button" title="定型文に保存" disabled>⭐</button>
    <button id="send" type="button" disabled>送る</button>
  </div>
</div>

<script>
(function () {
  var pin = document.getElementById('pin'), pinrow = document.getElementById('pinrow');
  var pintoggle = document.getElementById('pintoggle');
  var text = document.getElementById('text'), send = document.getElementById('send');
  var log = document.getElementById('log'), hint = document.getElementById('hint');
  var bar = document.getElementById('bar'), star = document.getElementById('star');
  var phrases = document.getElementById('phrases'), dock = document.getElementById('dock');
  // 実際にスクロールするのは中身ではなく、それを包んでいるペイン側
  var logBody = log.parentNode;

  pin.value = localStorage.getItem('pin') || '';
  if (!pin.value) { pinrow.classList.add('open'); }
  pintoggle.onclick = function () { pinrow.classList.toggle('open'); };
  pin.onchange = function () { localStorage.setItem('pin', pin.value.trim()); };

  // --- キーボードに追従させる ---
  // iOSはキーボードが出てもwindow.innerHeightが変わらないため、position:fixedでは
  // 入力欄がキーボードの裏に隠れてしまう。visualViewportで実際に見えている高さを取り、
  // 隠れる分だけバーを持ち上げる。
  var vv = window.visualViewport;
  if (vv) {
    // 画面全体を「実際に見えている高さ」に縮める。
    // こうすると左右のリストもキーボードの上に収まり、打ちながらワードを選べる。
    //
    // ⚠️ ここで vv.offsetTop を足してはいけない。
    // 「innerHeight - 隠れた分」という書き方は展開すると vv.height + vv.offsetTop になり、
    // iOSがレイアウトビューポートをスクロールさせた分だけ本体が可視領域より高くなって、
    // 入力欄が画面外へはみ出す。見えている高さは vv.height そのもの。
    var applyFit = function () {
      document.body.style.height = vv.height + 'px';
      // iOSはキーボードを出すときにページをスクロールさせる。戻さないと表示がずれる。
      if (window.scrollX || window.scrollY) { window.scrollTo(0, 0); }
      bar.classList.toggle('kb', vv.height < window.innerHeight - 1);
      logBody.scrollTop = logBody.scrollHeight;
    };

    // キーボードの開閉アニメーション中は resize/scroll が毎フレーム飛んでくる。
    // 都度レイアウトし直すと揺れるので、短くまとめてから1回だけ反映する。
    //
    // requestAnimationFrameを使わないのは、画面が描画されていないとき
    // （タブが裏に回っている等）にコールバックが来ず、以後ずっと
    // 反映されないままになるため。setTimeoutなら必ず発火する。
    var pending = null;
    var fit = function () {
      if (pending) { return; }
      pending = setTimeout(function () { pending = null; applyFit(); }, 16);
    };
    vv.addEventListener('resize', fit);
    vv.addEventListener('scroll', fit);
    // 入力欄に触れた瞬間にもiOSは画面をスクロールさせるので、そこでも整え直す
    text.addEventListener('focus', fit);
    text.addEventListener('blur', fit);
    window.addEventListener('orientationchange', fit);
    applyFit();          // 初期表示のぶん
  }

  // --- 入力欄の高さを内容に合わせる（1行から最大数行まで） ---
  // scrollHeightは枠線を含まないので、border-box指定のheightに使うぶんだけ足す
  function autosize() {
    text.style.height = 'auto';
    text.style.height = Math.min(text.scrollHeight + 2, 110) + 'px';
  }
  function refresh() {
    var empty = text.value.trim() === '';
    send.disabled = empty;
    star.disabled = empty;
    autosize();
  }
  text.addEventListener('input', refresh);

  // Enterで送信。改行を入れたいときはShift+Enter（スマホでは改行キー長押し相当）
  text.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  });

  function post(path, body) {
    body.pin = pin.value.trim();
    return fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().then(function (d) { return { status: r.status, data: d }; });
    });
  }

  // --- 登録したワード（左に送信ボタン、右に削除ボタン） ---
  function drawPhrases(list) {
    phrases.textContent = '';
    if (!list || !list.length) {
      var empty = document.createElement('div');
      empty.id = 'nophrase';
      empty.innerHTML = '⭐ で登録すると<br>ここに並びます。';
      phrases.appendChild(empty);
      return;
    }
    list.forEach(function (body) {
      var row = document.createElement('div');
      row.className = 'prow';

      var send = document.createElement('button');
      send.type = 'button';
      send.className = 'psend';
      send.textContent = '▶';
      send.title = '読み上げる';
      send.onclick = function () { speak(body); };

      var label = document.createElement('div');
      label.className = 'ptext';
      label.textContent = body;
      // 文字部分をタップしても送れるようにしておく（ボタンが小さいため）
      label.onclick = function () { speak(body); };

      var del = document.createElement('button');
      del.type = 'button';
      del.className = 'pdel';
      del.textContent = '×';
      del.title = '削除';
      del.onclick = function () { removePhrase(body); };

      row.appendChild(send);
      row.appendChild(label);
      row.appendChild(del);
      phrases.appendChild(row);
    });
  }

  function removePhrase(body) {
    // 消すつもりが無いのに消えるのを防ぐため、一度だけ確認する
    if (!confirm('「' + body + '」を削除しますか？')) { return; }
    post('/phrases/delete', { text: body }).then(function (res) {
      if (res.data.ok) {
        drawPhrases(res.data.phrases);
      } else if (res.status === 403) {
        pinrow.classList.add('open');
      }
    }).catch(function () { /* 消せなくても一覧はそのまま残る */ });
  }

  function loadPhrases() {
    if (!pin.value.trim()) { return; }
    post('/phrases', {}).then(function (res) {
      if (res.data.ok) { drawPhrases(res.data.phrases); }
    }).catch(function () { /* 取得できなくても入力はできるので黙って諦める */ });
  }

  function add(body, ok, note) {
    if (hint) { hint.remove(); hint = null; }
    var item = document.createElement('div');
    item.className = 'item' + (ok ? '' : ' ng');
    var label = document.createTextNode(body);
    item.appendChild(label);
    var meta = document.createElement('span');
    meta.className = 'meta';
    meta.textContent = note;
    item.appendChild(meta);
    // 一度送った文はタップでもう一度読み上げられるようにする
    item.onclick = function () { speak(body); };
    log.appendChild(item);
    while (log.children.length > 30) { log.removeChild(log.firstChild); }
    logBody.scrollTop = logBody.scrollHeight;
    return { item: item, meta: meta };
  }

  // 入力欄・定型文チップ・履歴のタップ、すべてここを通る
  function speak(body) {
    if (!body) { return; }
    var entry = add(body, true, '送信中...');
    post('/speak', { text: body }).then(function (res) {
      if (res.data.ok) {
        localStorage.setItem('pin', pin.value.trim());
        entry.meta.textContent = '✓ ' + res.data.message;
        if (!phrases.querySelector('.prow')) { loadPhrases(); }
      } else {
        entry.item.className = 'item ng';
        entry.meta.textContent = '✕ ' + res.data.message;
        // 暗証番号が違うときは、入れ直せるよう自動で開く
        if (res.status === 403) { pinrow.classList.add('open'); }
      }
    }).catch(function () {
      entry.item.className = 'item ng';
      entry.meta.textContent = '✕ PCに接続できません（同じWi-Fiか確認してください）';
    });
  }

  function submit() {
    var body = text.value.trim();
    if (!body) { return; }
    // 応答を待たずに欄を空にする。ここでフォーカスを外すとiOSではキーボードが
    // 閉じてしまい、連続で送れなくなるため、blurもfocus()のやり直しもしない。
    text.value = '';
    refresh();
    speak(body);
  }

  star.onclick = function () {
    var body = text.value.trim();
    if (!body) { return; }
    post('/phrases/add', { text: body }).then(function (res) {
      if (res.data.ok) {
        drawPhrases(res.data.phrases);
        text.value = '';
        refresh();
      } else if (res.status === 403) {
        pinrow.classList.add('open');
      }
    }).catch(function () { /* 保存できなくても入力内容は残るので何もしない */ });
  };

  send.onclick = submit;
  pin.addEventListener('change', loadPhrases);
  refresh();
  loadPhrases();
})();
</script></body></html>
"""


# スマホの「声の解析」ページ。
# ⚠️ 声の取り込みはスマホのキーボードの音声入力（Gboard等のマイク）に任せている。
# ブラウザのマイク(Web Speech API / getUserMedia)は「安全なページ」でしか使えず、
# このサーバーは平文HTTPで配信しているため、ページ側からマイクは開けない。
# キーボードの音声入力ならOS側の機能なので、平文HTTPでもそのまま使える。
PHONE_BRIDGE_VOICE_PAGE = """<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>声の解析</title>
<style>
  :root {
    --bg:#f2f2f7; --fg:#1c1c1e; --sub:#8e8e93; --bar:#f7f7f8;
    --line:#d1d1d6; --field:#ffffff; --send:#0b84ff; --card:#ffffff;
    --hi:#0b84ff; --lo:#8e8e93;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#000000; --fg:#f2f2f7; --sub:#8e8e93; --bar:#1c1c1e;
      --line:#38383a; --field:#2c2c2e; --send:#0b84ff; --card:#1c1c1e;
    }
  }
  *, *::before, *::after { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  html { height:100%; overflow:hidden; }
  body {
    position:fixed; top:0; left:0; right:0; height:100%; margin:0;
    background:var(--bg); color:var(--fg);
    font-family:-apple-system,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;
    display:flex; flex-direction:column; overflow:hidden;
  }
  header {
    flex:none; padding:10px 14px; font-size:13px; color:var(--sub);
    border-bottom:1px solid var(--line); background:var(--bar);
    display:flex; align-items:center; gap:8px;
    padding-top:calc(10px + env(safe-area-inset-top));
  }
  header span { flex:1; }
  header a, header button {
    flex:none; font-size:13px; color:var(--send); background:none;
    border:none; padding:4px 2px; text-decoration:none;
  }
  #pinrow { flex:none; display:none; padding:10px 14px; background:var(--bar);
            border-bottom:1px solid var(--line); }
  #pinrow.open { display:block; }
  #pin {
    width:100%; font-size:16px; padding:10px 12px;
    border:1px solid var(--line); border-radius:10px;
    background:var(--field); color:var(--fg);
  }

  #body { flex:1; overflow-y:auto; -webkit-overflow-scrolling:touch; padding:12px; }
  #guide { color:var(--sub); font-size:13px; line-height:1.7; margin:4px 2px 14px; }

  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:12px; margin-bottom:12px; }
  .cardhead { font-size:12px; font-weight:600; color:var(--sub); margin-bottom:8px; }
  #kana { font-size:15px; line-height:1.6; word-break:break-all; }
  #engine { font-size:11px; color:var(--sub); margin-top:6px; }

  /* アクセント句。モーラを横に並べ、高いモーラを線でつなぐ */
  .phrase { border-top:1px solid var(--line); padding:10px 0 4px; }
  .phrase:first-of-type { border-top:none; }
  .plabel { font-size:11px; color:var(--sub); margin-bottom:6px; }
  .moras { display:flex; flex-wrap:wrap; gap:4px; }
  .mora {
    min-width:38px; padding:6px 4px 4px; border-radius:8px; text-align:center;
    border:1px solid var(--line); background:var(--field); font-size:15px;
    line-height:1.2;
  }
  /* 高く発音されるモーラ。上に線を引いてピッチの高さを示す */
  .mora.high { border-top:3px solid var(--hi); color:var(--fg); }
  .mora.low  { border-top:3px solid var(--lo); color:var(--sub); }
  .mora small { display:block; font-size:9px; color:var(--sub); margin-top:2px; }
  /* アクセント核（ここの直後で下がる） */
  .mora.nucleus { font-weight:700; }
  .mora.nucleus small { color:var(--hi); }

  .accentrow { display:flex; align-items:center; gap:8px; margin-top:10px; flex-wrap:wrap; }
  .accentrow label { font-size:12px; color:var(--sub); }
  .accentrow select {
    font-size:15px; padding:6px 8px; border-radius:8px;
    border:1px solid var(--line); background:var(--field); color:var(--fg);
  }

  #dock { flex:none; background:var(--bar); border-top:1px solid var(--line);
          padding:8px 10px calc(8px + env(safe-area-inset-bottom)); }
  #dock.kb { padding-bottom:8px; }
  #inrow { display:flex; align-items:flex-end; gap:8px; }
  #text {
    flex:1; min-width:0; font-size:16px; line-height:1.35; padding:9px 12px;
    border:1px solid var(--line); border-radius:18px;
    background:var(--field); color:var(--fg); resize:none; max-height:110px;
    font-family:inherit;
  }
  #btns { display:flex; gap:8px; margin-top:8px; }
  #btns button { flex:1; font-size:15px; padding:11px 0; border:none; border-radius:10px; }
  #analyze { background:var(--send); color:#fff; }
  #speak { background:#34c759; color:#fff; }
  #btns button:disabled { opacity:.4; }
  #msg { font-size:12px; color:var(--sub); margin-top:7px; min-height:1.2em; text-align:center; }
  #msg.ng { color:#ff6b6b; }
</style>
</head><body>

<header>
  <span>声の解析</span>
  <a href="/mic">声で話す</a>
  <a href="/">送信</a>
  <button id="pintoggle" type="button">暗証番号</button>
</header>

<div id="pinrow">
  <input id="pin" type="text" inputmode="numeric" autocomplete="off"
         placeholder="PCの画面に表示されている6桁の番号">
</div>

<div id="body">
  <div id="guide">
    下の欄をタップして、<b>キーボードのマイク</b>から話しかけてください。<br>
    文字になったら「解析」を押すと、読み方とアクセントが出ます。<br>
    アクセントを直してから「この読みで喋る」を押すと、PCがその通りに喋ります。
  </div>
  <div id="result"></div>
</div>

<div id="dock">
  <div id="inrow">
    <textarea id="text" rows="1" placeholder="🎤 キーボードのマイクで話す"
              enterkeyhint="done" autocomplete="off"></textarea>
  </div>
  <div id="btns">
    <button id="analyze" type="button" disabled>解析</button>
    <button id="speak" type="button" disabled>この読みで喋る</button>
  </div>
  <div id="msg"></div>
</div>

<script>
(function () {
  var pin = document.getElementById('pin'), pinrow = document.getElementById('pinrow');
  var pintoggle = document.getElementById('pintoggle');
  var text = document.getElementById('text');
  var analyze = document.getElementById('analyze'), speak = document.getElementById('speak');
  var result = document.getElementById('result'), msg = document.getElementById('msg');
  var dock = document.getElementById('dock'), bodyEl = document.getElementById('body');

  var current = null;      // 直近の解析結果 {token, phrases, text}

  pin.value = localStorage.getItem('pin') || '';
  if (!pin.value) { pinrow.classList.add('open'); }
  pintoggle.onclick = function () { pinrow.classList.toggle('open'); };
  pin.onchange = function () { localStorage.setItem('pin', pin.value.trim()); };

  // キーボードに追従させる（送信ページと同じ考え方）。
  // 実際に見えている高さへ body を縮めれば、入力欄がキーボードに隠れない。
  var vv = window.visualViewport;
  if (vv) {
    var pending = null;
    var applyFit = function () {
      document.body.style.height = vv.height + 'px';
      if (window.scrollX || window.scrollY) { window.scrollTo(0, 0); }
      dock.classList.toggle('kb', vv.height < window.innerHeight - 1);
    };
    var fit = function () {
      if (pending) { return; }
      pending = setTimeout(function () { pending = null; applyFit(); }, 16);
    };
    vv.addEventListener('resize', fit);
    vv.addEventListener('scroll', fit);
    text.addEventListener('focus', fit);
    text.addEventListener('blur', fit);
    window.addEventListener('orientationchange', fit);
    applyFit();
  }

  function autosize() {
    text.style.height = 'auto';
    text.style.height = Math.min(text.scrollHeight + 2, 110) + 'px';
  }
  function refresh() {
    analyze.disabled = text.value.trim() === '';
    autosize();
  }
  text.addEventListener('input', refresh);

  function post(path, body) {
    body.pin = pin.value.trim();
    return fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().then(function (d) { return { status: r.status, data: d }; });
    });
  }

  function say(message, ng) {
    msg.textContent = message || '';
    msg.className = ng ? 'ng' : '';
  }

  // --- 解析結果を描く ---
  // アクセントは「何モーラ目の直後で下がるか」。0は平板（下がらない）。
  // 高く読むモーラを線で示し、核のモーラに印を付ける。
  function draw(data) {
    result.textContent = '';

    var head = document.createElement('div');
    head.className = 'card';
    var h1 = document.createElement('div');
    h1.className = 'cardhead';
    h1.textContent = '読み方';
    var kana = document.createElement('div');
    kana.id = 'kana';
    kana.textContent = data.kana || '(読みを取得できませんでした)';
    var eng = document.createElement('div');
    eng.id = 'engine';
    eng.textContent = '解析: ' + data.engine + ' ／ 「' + data.text + '」';
    head.appendChild(h1); head.appendChild(kana); head.appendChild(eng);
    result.appendChild(head);

    if (!data.phrases || !data.phrases.length) { return; }

    var card = document.createElement('div');
    card.className = 'card';
    var h2 = document.createElement('div');
    h2.className = 'cardhead';
    h2.textContent = 'アクセント（直したいところを選び直せます）';
    card.appendChild(h2);

    data.phrases.forEach(function (phrase, index) {
      var box = document.createElement('div');
      box.className = 'phrase';

      var label = document.createElement('div');
      label.className = 'plabel';
      label.textContent = (index + 1) + 'つ目「' + phrase.surface + '」'
                          + (phrase.pause ? '（このあと間があく）' : '');
      box.appendChild(label);

      var moras = document.createElement('div');
      moras.className = 'moras';
      box.appendChild(moras);

      var row = document.createElement('div');
      row.className = 'accentrow';
      var sel = document.createElement('select');
      var opt0 = document.createElement('option');
      opt0.value = '0';
      opt0.textContent = '平板（下がらない）';
      sel.appendChild(opt0);
      phrase.moras.forEach(function (m, i) {
        var o = document.createElement('option');
        o.value = String(i + 1);
        o.textContent = (i + 1) + '「' + m + '」のあとで下がる';
        sel.appendChild(o);
      });
      sel.value = String(phrase.accent);

      // 高低の帯を引き直す。日本語のアクセントの決まり:
      //   ・1モーラ目と2モーラ目は必ず高さが違う
      //   ・核(accent)のモーラまでが高く、その直後から低くなる
      //   ・核が0(平板)なら、1モーラ目だけ低くて以降ずっと高い
      function paint() {
        var accent = parseInt(sel.value, 10);
        moras.textContent = '';
        phrase.moras.forEach(function (m, i) {
          var pos = i + 1;
          var high;
          if (accent === 0) { high = pos !== 1; }
          else if (accent === 1) { high = pos === 1; }
          else { high = pos > 1 && pos <= accent; }

          var cell = document.createElement('div');
          cell.className = 'mora ' + (high ? 'high' : 'low')
                           + (accent !== 0 && pos === accent ? ' nucleus' : '');
          cell.textContent = m;
          var tag = document.createElement('small');
          tag.textContent = (accent !== 0 && pos === accent) ? '↓' : (high ? '高' : '低');
          cell.appendChild(tag);
          // モーラを直接たたいても、そこを核にできる
          cell.onclick = function () {
            sel.value = (parseInt(sel.value, 10) === pos) ? '0' : String(pos);
            paint();
          };
          moras.appendChild(cell);
        });
      }
      sel.onchange = paint;
      paint();

      var caption = document.createElement('label');
      caption.textContent = 'アクセント:';
      row.appendChild(caption);
      row.appendChild(sel);
      box.appendChild(row);

      phrase._select = sel;
      card.appendChild(box);
    });

    result.appendChild(card);
  }

  function doAnalyze() {
    var body = text.value.trim();
    if (!body) { return; }
    analyze.disabled = true;
    speak.disabled = true;
    say('解析しています...');
    post('/analyze', { text: body }).then(function (res) {
      analyze.disabled = false;
      if (!res.data.ok) {
        if (res.status === 403) { pinrow.classList.add('open'); }
        current = null;
        say(res.data.message || '解析できませんでした。', true);
        return;
      }
      current = res.data;
      draw(res.data);
      speak.disabled = false;
      say(res.data.message || '解析しました。');
      bodyEl.scrollTop = 0;
    }).catch(function () {
      analyze.disabled = false;
      say('PCにつながりませんでした。', true);
    });
  }

  function doSpeak() {
    if (!current) { return; }
    var accents = current.phrases.map(function (p) {
      return p._select ? parseInt(p._select.value, 10) : p.accent;
    });
    speak.disabled = true;
    say('PCで読み上げています...');
    post('/speak_accent', { token: current.token, accents: accents, label: current.text })
      .then(function (res) {
        speak.disabled = false;
        if (!res.data.ok) {
          if (res.status === 403) { pinrow.classList.add('open'); }
          // 解析結果が消えていたら、案内どおり解析し直せるようにする
          if (res.status === 404) { current = null; }
          say(res.data.message || '読み上げられませんでした。', true);
          return;
        }
        say(res.data.message || '読み上げました。');
      }).catch(function () {
        speak.disabled = false;
        say('PCにつながりませんでした。', true);
      });
  }

  analyze.onclick = doAnalyze;
  speak.onclick = doSpeak;
  refresh();
})();
</script></body></html>
"""


# スマホの「声で話す」ページ。
# ⚠️ ブラウザの音声認識(Web Speech API)は「安全なページ」でしか動かない。
# 平文HTTP(http://192.168.x.x:8765/)では使えないため、Tailscale等でHTTPS化した
# アドレスから開く必要がある。使えない場合はその旨を画面に出し、
# キーボードの音声入力を使う既存ページへ誘導する。
#
# ⚠️ 音声そのものはPCへ送らない。必要なのは「話した内容の文字」だけで、
# 読み上げは既存の /speak がそのまま使える。音声を送る仕組みは要らない。
PHONE_BRIDGE_MIC_PAGE = """<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>声で話す</title>
<style>
  :root {
    --bg:#f2f2f7; --fg:#1c1c1e; --sub:#8e8e93; --bar:#f7f7f8;
    --line:#d1d1d6; --field:#ffffff; --send:#0b84ff; --card:#ffffff; --rec:#ff3b30;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#000000; --fg:#f2f2f7; --sub:#8e8e93; --bar:#1c1c1e;
      --line:#38383a; --field:#2c2c2e; --send:#0b84ff; --card:#1c1c1e;
    }
  }
  *, *::before, *::after { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  html { height:100%; overflow:hidden; }
  body {
    position:fixed; top:0; left:0; right:0; height:100%; margin:0;
    background:var(--bg); color:var(--fg);
    font-family:-apple-system,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;
    display:flex; flex-direction:column; overflow:hidden;
  }
  header {
    flex:none; padding:10px 14px; font-size:13px; color:var(--sub);
    border-bottom:1px solid var(--line); background:var(--bar);
    display:flex; align-items:center; gap:8px;
    padding-top:calc(10px + env(safe-area-inset-top));
  }
  header span { flex:1; }
  header a, header button {
    flex:none; font-size:13px; color:var(--send); background:none;
    border:none; padding:4px 2px; text-decoration:none;
  }
  #pinrow { flex:none; display:none; padding:10px 14px; background:var(--bar);
            border-bottom:1px solid var(--line); }
  #pinrow.open { display:block; }
  #pin { width:100%; font-size:16px; padding:10px 12px;
         border:1px solid var(--line); border-radius:10px;
         background:var(--field); color:var(--fg); }

  #body { flex:1; overflow-y:auto; -webkit-overflow-scrolling:touch; padding:12px; }
  #warn { display:none; background:#3a2326; color:#ffb4b4; border-radius:12px;
          padding:12px; font-size:13px; line-height:1.7; margin-bottom:12px; }
  #warn.show { display:block; }
  #warn a { color:#ffd0d0; }

  #heard { background:var(--card); border:1px solid var(--line); border-radius:12px;
           padding:14px; min-height:90px; font-size:17px; line-height:1.6;
           word-break:break-word; }
  #heard .interim { color:var(--sub); }
  #heard:empty::before { content:"ここに、話した内容が出ます"; color:var(--sub); font-size:14px; }

  #sent { margin-top:12px; }
  .row { background:var(--card); border:1px solid var(--line); border-radius:10px;
         padding:8px 10px; margin-bottom:6px; font-size:14px; line-height:1.4;
         word-break:break-word; }
  .row .t { display:block; font-size:10px; color:var(--sub); margin-top:3px; }
  .row.ng { background:#3a2326; }

  #dock { flex:none; background:var(--bar); border-top:1px solid var(--line);
          padding:10px 12px calc(12px + env(safe-area-inset-bottom)); }
  #mic {
    width:100%; padding:18px 0; border:none; border-radius:14px;
    font-size:17px; font-weight:600; background:var(--send); color:#fff;
  }
  #mic.on { background:var(--rec); }
  #mic:disabled { opacity:.4; }
  #opts { display:flex; align-items:center; gap:14px; margin-top:10px;
          font-size:13px; color:var(--sub); flex-wrap:wrap; }
  #opts label { display:flex; align-items:center; gap:5px; }
  #msg { font-size:12px; color:var(--sub); margin-top:8px; min-height:1.2em; text-align:center; }
  #msg.ng { color:#ff6b6b; }
</style>
</head><body>

<header>
  <span>声で話す</span>
  <a href="/voice">声の解析</a>
  <a href="/">送信</a>
  <button id="pintoggle" type="button">暗証番号</button>
</header>

<div id="pinrow">
  <input id="pin" type="text" inputmode="numeric" autocomplete="off"
         placeholder="PCの画面に表示されている6桁の番号">
</div>

<div id="body">
  <div id="warn">
    <b>このページでは声を聞き取れません。</b><br>
    ブラウザの音声認識は「https://」で開いたときしか使えません。<br>
    いまは「http://」で開いているか、この端末が対応していません。<br><br>
    <a href="/">送信ページ</a>なら、キーボードのマイクで同じことができます。
  </div>

  <div id="heard"></div>
  <div id="sent"></div>
</div>

<div id="dock">
  <button id="mic" type="button">🎤 押して話す</button>
  <div id="opts">
    <label><input type="checkbox" id="auto" checked> 話し終えたら自動で読み上げ</label>
    <label><input type="checkbox" id="cont"> 続けて聞き取る</label>
  </div>
  <div id="msg"></div>
</div>

<script>
(function () {
  var pin = document.getElementById('pin'), pinrow = document.getElementById('pinrow');
  var pintoggle = document.getElementById('pintoggle');
  var micBtn = document.getElementById('mic'), heard = document.getElementById('heard');
  var sent = document.getElementById('sent'), msg = document.getElementById('msg');
  var warn = document.getElementById('warn');
  var autoChk = document.getElementById('auto'), contChk = document.getElementById('cont');

  pin.value = localStorage.getItem('pin') || '';
  if (!pin.value) { pinrow.classList.add('open'); }
  pintoggle.onclick = function () { pinrow.classList.toggle('open'); };
  pin.onchange = function () { localStorage.setItem('pin', pin.value.trim()); };

  function say(text, ng) { msg.textContent = text || ''; msg.className = ng ? 'ng' : ''; }

  function post(path, body) {
    body.pin = pin.value.trim();
    return fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().then(function (d) { return { status: r.status, data: d }; });
    });
  }

  function addRow(text, ng) {
    var row = document.createElement('div');
    row.className = 'row' + (ng ? ' ng' : '');
    row.textContent = text;
    var t = document.createElement('span');
    t.className = 't';
    t.textContent = new Date().toLocaleTimeString();
    row.appendChild(t);
    // タップでもう一度読み上げ
    row.onclick = function () { speak(text); };
    sent.insertBefore(row, sent.firstChild);
  }

  function speak(text, loud) {
    text = (text || '').trim();
    if (!text) { return; }
    say('PCで読み上げています...');
    // from_speech を付けると、PC側が疑問文を見分けて「。」を「？」に直す。
    // 音声認識は「？」を返さないため、これが無いと質問が平叙文の抑揚で読まれる。
    // loud は「普段より大きな声だった」という合図。「！」の判定に使う。
    post('/speak', { text: text, from_speech: true, loud: !!loud }).then(function (res) {
      if (!res.data.ok) {
        if (res.status === 403) { pinrow.classList.add('open'); }
        say(res.data.message || '読み上げられませんでした。', true);
        return;
      }
      say(res.data.message || '読み上げます。');
    }).catch(function () { say('PCにつながりませんでした。', true); });
  }

  // --- 音声認識 ---
  // ⚠️ 安全なページ(https)でしか使えない。使えない端末・状況では
  //     黙って無反応にせず、理由を画面に出す。
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR || !window.isSecureContext) {
    warn.classList.add('show');
    micBtn.disabled = true;
    micBtn.textContent = '🎤 このページでは使えません';
    say(!window.isSecureContext ? 'https:// で開き直してください。'
                                : 'この端末のブラウザが音声認識に対応していません。', true);
    return;
  }

  var rec = new SR();
  rec.lang = 'ja-JP';
  rec.interimResults = true;
  rec.continuous = false;      // 「続けて聞き取る」ONのときは終了時に自分で再開する

  var listening = false;
  var finalText = '';

  function render(interim) {
    heard.textContent = '';
    if (finalText) { heard.appendChild(document.createTextNode(finalText)); }
    if (interim) {
      var s = document.createElement('span');
      s.className = 'interim';
      s.textContent = interim;
      heard.appendChild(s);
    }
  }

  rec.onstart = function () {
    listening = true;
    micBtn.classList.add('on');
    micBtn.textContent = '■ 聞き取り中（押すと止める）';
    say('話してください...');
  };

  var ENDS_WITH_PUNCT = /[。、！？!?,.]$/;

  // ⚠️ 音声認識は句読点を返さない。そのまま繋ぐと
  //   「こんにちは今日はいい天気ですね」のように一続きになり、
  //   PC側の音声合成が文の切れ目を掴めず、息継ぎのない棒読みになる。
  //   （実測: 句読点なしだと「コンニチワキョオワ」が1つの句として繋がる）
  //   認識が確定した区切り＝話の区切りなので、そこに「。」を補って渡す。
  //
  // ⚠️ 確定した文を「足していく」書き方にしてはいけない。
  //   onresult は同じ結果を何度も配り直すことがある（iOSでよく起きる。
  //   e.resultIndex が既に確定した位置まで巻き戻ってくる）。
  //   足す書き方だと、そのたびに同じ言葉が二重三重に混ざる。
  //   毎回 results 全体から組み立て直せば、何度呼ばれても結果は変わらない。
  function buildFinal(results) {
    var out = '';
    for (var i = 0; i < results.length; i++) {
      if (!results[i].isFinal) { continue; }
      var t = (results[i][0].transcript || '').trim();
      if (!t) { continue; }
      if (out && !ENDS_WITH_PUNCT.test(out)) { out += '。'; }
      out += t;
    }
    return out;
  }

  rec.onresult = function (e) {
    var interim = '';
    for (var i = 0; i < e.results.length; i++) {
      if (!e.results[i].isFinal) { interim += e.results[i][0].transcript; }
    }
    finalText = buildFinal(e.results);
    render(interim);
  };

  rec.onerror = function (e) {
    if (e.error === 'no-speech') { say('声が聞き取れませんでした。'); return; }
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
      say('マイクの使用が許可されていません。ブラウザの設定を確認してください。', true);
      stopListening();
      return;
    }
    say('聞き取りに失敗しました（' + e.error + '）。', true);
  };

  rec.onend = function () {
    var text = finalText.trim();
    // 文末にも区切りを付ける（尻切れの読み方になるのを防ぐ）
    if (text && !/[。、！？!?,.]$/.test(text)) { text += '。'; }
    finalText = '';
    var loud = wasLoud();
    rememberLevel();
    if (text) {
      render('');
      if (autoChk.checked) { addRow(text); speak(text, loud); }
      else { addRow(text); say('「読み上げ」は各行をタップしてください。'); }
    }
    // 「続けて聞き取る」なら、止めるまで繰り返す
    if (listening && contChk.checked) {
      try { rec.start(); return; } catch (err) { /* すぐには再開できない場合は下で止める */ }
    }
    stopListening();
  };

  // --- 声の大きさを測る（感嘆「！」の判定に使う） ---
  // ⚠️ 「！」かどうかは文字だけでは決まらない。
  //    「すごいですね」は感嘆にも平静にもなり、決めるのは声の勢い。
  //    そこでマイクの音量を測り、その人の普段の声より大きければ感嘆とみなす。
  //    絶対値ではなく「その人の平均との比」で見るので、声の大きさや
  //    マイクの感度が人それぞれでも成り立つ。
  //
  // ⚠️ 音声認識と同時にマイクを開けるかは端末によって違う。
  //    開けなかった場合は黙って諦め、文字の手がかりだけで判定する。
  var audioCtx = null, analyser = null, micStream = null, levelTimer = null;
  var peakLevel = 0;          // この発話でいちばん大きかった音量
  var loudHistory = [];       // 過去の発話の音量（その人の普段の声を知るため）
  var MAX_LOUD_HISTORY = 12;
  var LOUD_RATIO = 1.35;      // 普段の何倍で「大きな声」とみなすか

  function startLevelMeter() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { return; }
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) { return; }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      micStream = stream;
      audioCtx = new Ctx();
      var src = audioCtx.createMediaStreamSource(stream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      src.connect(analyser);
      var buf = new Uint8Array(analyser.fftSize);
      levelTimer = setInterval(function () {
        analyser.getByteTimeDomainData(buf);
        var sum = 0;
        for (var i = 0; i < buf.length; i++) {
          var v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        var rms = Math.sqrt(sum / buf.length);
        if (rms > peakLevel) { peakLevel = rms; }
      }, 50);
    }).catch(function () {
      // マイクを二重に開けない端末では、文字の手がかりだけで判定する
      analyser = null;
    });
  }

  function stopLevelMeter() {
    if (levelTimer) { clearInterval(levelTimer); levelTimer = null; }
    if (micStream) {
      micStream.getTracks().forEach(function (t) { t.stop(); });
      micStream = null;
    }
    if (audioCtx) { try { audioCtx.close(); } catch (e) {} audioCtx = null; }
    analyser = null;
  }

  // この発話が「普段より大きな声」だったか。
  // 測れていない、または比べる相手が少ないうちは判定しない（false）。
  function wasLoud() {
    if (!peakLevel) { return false; }
    if (loudHistory.length < 3) { return false; }
    var sum = 0;
    for (var i = 0; i < loudHistory.length; i++) { sum += loudHistory[i]; }
    var avg = sum / loudHistory.length;
    return avg > 0 && peakLevel > avg * LOUD_RATIO;
  }

  function rememberLevel() {
    if (peakLevel > 0) {
      loudHistory.push(peakLevel);
      if (loudHistory.length > MAX_LOUD_HISTORY) { loudHistory.shift(); }
    }
    peakLevel = 0;
  }

  function startListening() {
    finalText = '';
    heard.textContent = '';
    peakLevel = 0;
    if (!analyser) { startLevelMeter(); }
    try { rec.start(); }
    catch (err) { say('聞き取りを開始できませんでした。', true); }
  }

  function stopListening() {
    listening = false;
    micBtn.classList.remove('on');
    micBtn.textContent = '🎤 押して話す';
    try { rec.stop(); } catch (err) { /* 既に止まっている */ }
    stopLevelMeter();     // マイクを掴んだままにしない
  }

  micBtn.onclick = function () {
    if (listening) { stopListening(); say(''); }
    else { startListening(); }
  };
})();
</script></body></html>
"""


class _BridgeHTTPServer(http.server.ThreadingHTTPServer):
    """
    待ち受け用のHTTPサーバー。

    ⚠️ allow_reuse_address を明示的に切っている。
    HTTPServerは既定でこれを1にするが、WindowsのSO_REUSEADDRはLinuxと意味が違い、
    「他のプロセスが現に待ち受けているポート」にも後から割り込んで bind できてしまう。
    そのままだと、アプリを二重起動したり他アプリが同じポートを使っていたりしても
    bindが成功し、送った文がどちらのプロセスに届くか分からない状態になる。
    ここでは素直に失敗させ、「ポートが使用中です」と伝えられるようにする。
    """
    allow_reuse_address = False
    daemon_threads = True


class PhoneBridgeServer:
    """
    同じWi-Fi内のスマホから文字を受け取り、PC側で読み上げるための簡易Webサーバー。

    ⚠️ このサーバーは「受け取った文字をPCに喋らせる」ものなので、無防備に開くと
    同じネットワークにいる第三者が自由にPCから音を出せてしまう。そのため
    　・既定では起動しない（設定で明示的にONにしたときだけ待ち受ける）
    　・すべての送信に暗証番号(PIN)を要求する
    　・受け付けるのは読み上げ用の文字だけで、ファイル等には一切触れない
    という前提で作ってある。
    """

    def __init__(self, on_text, log_callback=None, port=DEFAULT_PHONE_BRIDGE_PORT,
                 list_phrases=None, save_phrase=None, delete_phrase=None,
                 analyze_text=None, speak_query=None):
        self.on_text = on_text                       # 受け取った文字を渡す先（読み上げキューへの投入）
        # 定型文の取得・保存・削除。渡されない場合は定型文機能なしで動く
        self.list_phrases = list_phrases or (lambda: [])
        self.save_phrase = save_phrase or (lambda text: False)
        self.delete_phrase = delete_phrase or (lambda text: False)
        # 声の解析ページ用。渡されない場合は解析機能なしで動く
        self.analyze_text = analyze_text or (lambda text: (None, "解析機能が使えません。"))
        self.speak_query = speak_query or (lambda query, label="": (False, "読み上げ機能が使えません。"))
        self.log_callback = log_callback or (lambda m: None)
        self.port = port
        self.pin = ""
        self._httpd = None
        self._thread = None
        # 暗証番号の総当たり対策。連続で失敗したら一定時間すべて受け付けない
        self._fail_count = 0
        self._blocked_until = 0.0
        self._fail_lock = threading.Lock()
        # 解析結果の預かり所（PHONE_BRIDGE_MAX_ANALYSES 参照）
        self._analyses = {}
        self._analysis_lock = threading.Lock()
        # HTTPSで配信しているか。スマホのブラウザでマイク（音声認識）を使うには
        # 「安全なページ」である必要があり、平文HTTPでは使えない。
        self.use_https = False
        self.cert_hostname = ""      # 証明書に書かれている名前（この名前で開いてもらう）
        self.cert_is_trusted = False # 正規の証明書か（自己署名なら警告が出る）

    def remember_analysis(self, query):
        """解析結果を預かり、それを指す合言葉を返す（古いものから捨てる）"""
        token = secrets.token_urlsafe(12)
        with self._analysis_lock:
            self._analyses[token] = query
            while len(self._analyses) > PHONE_BRIDGE_MAX_ANALYSES:
                try:
                    del self._analyses[next(iter(self._analyses))]
                except (StopIteration, KeyError):
                    break
        return token

    def get_analysis(self, token):
        with self._analysis_lock:
            return self._analyses.get(token)

    def check_pin(self, pin):
        """
        暗証番号を照合する。戻り値: (通ったか, 待たされる残り秒数)

        6桁は総当たりが現実的な桁数で、同じWi-Fiにいる相手なら
        スクリプトで数時間も回せば当てられてしまう。失敗が続いたら
        しばらく門を閉じることで、総当たりを非現実的な時間に引き延ばす。
        """
        now = time.time()
        with self._fail_lock:
            if now < self._blocked_until:
                return False, int(self._blocked_until - now) + 1

            ok = bool(self.pin) and secrets.compare_digest(str(pin), self.pin)
            if ok:
                self._fail_count = 0
                return True, 0

            self._fail_count += 1
            if self._fail_count >= PHONE_BRIDGE_MAX_PIN_FAILURES:
                self._fail_count = 0
                self._blocked_until = now + PHONE_BRIDGE_LOCKOUT_SECONDS
                self.log(
                    f"🚫 スマホ連携: 暗証番号の失敗が続いたため、"
                    f"{PHONE_BRIDGE_LOCKOUT_SECONDS}秒間すべての送信を受け付けません。"
                )
                return False, PHONE_BRIDGE_LOCKOUT_SECONDS
            return False, 0

    def log(self, message):
        try:
            self.log_callback(message)
        except Exception:
            pass

    @staticmethod
    def get_lan_ip():
        """このPCがLAN内で使っているIPアドレスを調べる（スマホから開くURLの組み立て用）"""
        try:
            # UDPソケットは connect しても実際にはパケットを送らない。
            # OSのルーティング表から「外に出るときに使うIP」を引くための常套手段。
            with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as s:
                s.settimeout(1.0)
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def get_url(self):
        scheme = "https" if self.use_https else "http"
        host = self.cert_hostname or self.get_lan_ip()
        return f"{scheme}://{host}:{self.port}/"

    def is_running(self):
        return self._httpd is not None

    @staticmethod
    def generate_pin():
        """推測されにくい6桁の暗証番号を作る（randomではなくsecretsを使う）"""
        return f"{secrets.randbelow(1000000):06d}"

    def _build_handler(self):
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            # 既定の実装はリクエストのたびに標準エラーへ出力する。
            # exe(--windowed)では出力先が無く、無駄なので黙らせる。
            def log_message(self, fmt, *args):
                pass

            def _send_json(self, status, payload):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    page = PHONE_BRIDGE_PAGE
                elif self.path in ("/voice", "/voice/"):
                    page = PHONE_BRIDGE_VOICE_PAGE
                elif self.path in ("/mic", "/mic/"):
                    page = PHONE_BRIDGE_MIC_PAGE
                else:
                    self.send_error(404)
                    return
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                # ページを端末にキャッシュさせない（PIN入力欄が残り続けないように）
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if self.path not in ("/speak", "/phrases", "/phrases/add", "/phrases/delete",
                                     "/analyze", "/speak_accent"):
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length <= 0 or length > 4096:
                    self._send_json(400, {"ok": False, "message": "送信内容が不正です。"})
                    return

                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    pin = str(payload.get("pin", ""))
                    text = str(payload.get("text", ""))
                except Exception:
                    self._send_json(400, {"ok": False, "message": "送信内容が不正です。"})
                    return

                # compare_digestで比較し、応答時間から桁を推測されないようにする。
                # 定型文の取得も同じ照合を通す（保存した文が誰にでも見えては困るため）
                accepted_pin, wait_seconds = server.check_pin(pin)
                if not accepted_pin:
                    if wait_seconds:
                        self._send_json(429, {
                            "ok": False,
                            "message": f"暗証番号の失敗が続いたため、{wait_seconds}秒お待ちください。"
                        })
                        return
                    server.log("⚠️ スマホ連携: 暗証番号が違う送信を拒否しました。")
                    self._send_json(403, {"ok": False, "message": "暗証番号が違います。"})
                    return

                if self.path == "/phrases":
                    self._send_json(200, {"ok": True, "phrases": server.list_phrases()})
                    return

                # --- 編集したアクセントで喋らせる ---
                # 預けてある解析結果に、スマホから来たアクセント位置だけを当てはめる。
                # スマホから受け取るのは数値の配列だけなので、
                # エンジンへ任意のJSONを転送させずに済む。
                if self.path == "/speak_accent":
                    query = server.get_analysis(str(payload.get("token", "")))
                    if query is None:
                        self._send_json(404, {
                            "ok": False, "message": "解析結果が見つかりません。もう一度解析してください。"})
                        return

                    phrases = query.get("accent_phrases") or []
                    accents = payload.get("accents")
                    if not isinstance(accents, list) or len(accents) != len(phrases):
                        self._send_json(400, {"ok": False, "message": "アクセントの指定が不正です。"})
                        return

                    edited = json.loads(json.dumps(query))     # 預かり分を壊さないよう複製する
                    for phrase, raw_accent in zip(edited["accent_phrases"], accents):
                        mora_count = len(phrase.get("moras") or [])
                        try:
                            value = int(raw_accent)
                        except (TypeError, ValueError):
                            self._send_json(400, {"ok": False, "message": "アクセントの指定が不正です。"})
                            return
                        # 0(平板)〜モーラ数 の範囲に収める。範囲外を渡すとエンジンが落ちる
                        phrase["accent"] = max(0, min(mora_count, value))

                    ok, reason = server.speak_query(edited, str(payload.get("label", "")))
                    if not ok:
                        self._send_json(500, {"ok": False, "message": reason})
                        return
                    self._send_json(200, {"ok": True, "message": "このアクセントで読み上げます。"})
                    return

                text = text.strip()
                if not text:
                    self._send_json(400, {"ok": False, "message": "文が空です。"})
                    return

                truncated = len(text) > MAX_SPEECH_TEXT_LENGTH
                text = text[:MAX_SPEECH_TEXT_LENGTH]

                # --- 文を解析して、アクセント構造をスマホへ返す ---
                if self.path == "/analyze":
                    result, reason = server.analyze_text(text)
                    if result is None:
                        self._send_json(503, {"ok": False, "message": reason})
                        return
                    # audio_queryはサーバーが預かり、スマホには合言葉と要約だけ返す
                    self._send_json(200, {
                        "ok": True,
                        "token": server.remember_analysis(result["query"]),
                        "text": text,
                        "kana": result["kana"],
                        "engine": result["engine_label"],
                        "phrases": result["phrases"],
                        "message": "解析しました。" if not truncated
                                   else f"長かったので先頭{MAX_SPEECH_TEXT_LENGTH}文字だけ解析しました。",
                    })
                    return

                if self.path == "/phrases/add":
                    if not server.save_phrase(text):
                        self._send_json(500, {"ok": False, "message": "保存できませんでした。"})
                        return
                    self._send_json(200, {"ok": True, "message": "定型文に保存しました。",
                                          "phrases": server.list_phrases()})
                    return

                if self.path == "/phrases/delete":
                    if not server.delete_phrase(text):
                        self._send_json(404, {"ok": False, "message": "その定型文は見つかりませんでした。"})
                        return
                    self._send_json(200, {"ok": True, "message": "削除しました。",
                                          "phrases": server.list_phrases()})
                    return

                # ⚠️ 音声認識から来た文にだけ「？」「！」を補う。
                # 自分で打った文（定型文など）は、書いたとおりの記号を尊重する。
                # loud は「普段より大きな声だった」という合図（感嘆の主な手がかり）。
                if payload.get("from_speech"):
                    text = apply_sentence_marks(text, loud=bool(payload.get("loud")))

                accepted = server.on_text(text)
                if not accepted:
                    self._send_json(429, {"ok": False, "message": "読み上げが混み合っています。少し待ってください。"})
                    return

                message = "読み上げます。"
                if truncated:
                    message = f"長かったので先頭{MAX_SPEECH_TEXT_LENGTH}文字だけ読み上げます。"
                self._send_json(200, {"ok": True, "message": message})

        return Handler

    # --- HTTPS用の証明書 ---
    # ⚠️ スマホのブラウザでマイク（音声認識）を使うには「安全なページ」が要る。
    # 平文HTTPだとブラウザがマイクを開かせてくれない。
    #
    # 証明書は2通り。
    #   ① Tailscaleの正規証明書 … 警告なしで開ける。ただしtailnet側で
    #      「HTTPS Certificates」を有効にしていないと発行できない
    #   ② 自作の証明書（自己署名）… いつでも作れるが、初回だけブラウザの
    #      警告を手動でまたぐ必要がある
    # ①が使えるなら①、駄目なら②に落とす。
    TAILSCALE_PATHS = (
        r"C:\Program Files\Tailscale\tailscale.exe",
        r"C:\Program Files (x86)\Tailscale\tailscale.exe",
    )

    @classmethod
    def _tailscale_exe(cls):
        for path in cls.TAILSCALE_PATHS:
            if os.path.exists(path):
                return path
        return shutil.which("tailscale") or ""

    @classmethod
    def tailscale_hostname(cls):
        """このPCのTailscale上の名前（使っていなければ空文字）"""
        exe = cls._tailscale_exe()
        if not exe:
            return ""
        try:
            out = subprocess.run([exe, "status", "--json"], capture_output=True,
                                 timeout=10, text=True, encoding="utf-8",
                                 errors="replace").stdout
            name = (json.loads(out).get("Self") or {}).get("DNSName", "")
            return name.rstrip(".")
        except Exception:
            return ""

    def _try_tailscale_cert(self, cert_dir):
        """Tailscaleの正規証明書を取りにいく。取れたら (証明書, 鍵, 名前)"""
        host = self.tailscale_hostname()
        exe = self._tailscale_exe()
        if not host or not exe:
            return None
        # ⚠️ 保存先が無いと tailscale cert は書き込みに失敗する。
        # 作らずに呼ぶと「正規証明書が取れない」と誤判定して自己署名に落ち、
        # 本来は出ないはずのブラウザ警告が出る（実際にそうなっていた）。
        try:
            os.makedirs(cert_dir, exist_ok=True)
        except Exception:
            return None
        cert_path = os.path.join(cert_dir, "tailscale.crt")
        key_path = os.path.join(cert_dir, "tailscale.key")
        try:
            result = subprocess.run(
                [exe, "cert", "--cert-file", cert_path, "--key-file", key_path, host],
                capture_output=True, timeout=120, text=True,
                encoding="utf-8", errors="replace")
        except Exception:
            return None
        if result.returncode != 0 or not os.path.exists(cert_path):
            # tailnet側でHTTPS証明書が有効になっていない場合はここに来る
            return None
        return cert_path, key_path, host

    def _make_self_signed(self, cert_dir):
        """自作の証明書を用意する。既にあって期限内ならそれを使い回す。"""
        if x509 is None:
            return None
        cert_path = os.path.join(cert_dir, "self.crt")
        key_path = os.path.join(cert_dir, "self.key")
        host = self.tailscale_hostname() or self.get_lan_ip()

        # 使い回せるものがあるか（毎回作り直すと、スマホ側で警告をまたぎ直しになる）
        if os.path.exists(cert_path) and os.path.exists(key_path):
            try:
                with open(cert_path, "rb") as f:
                    existing = x509.load_pem_x509_certificate(f.read())
                not_after = existing.not_valid_after_utc
                names = [n.value for n in existing.subject]
                if not_after > datetime.datetime.now(datetime.timezone.utc) and host in names:
                    return cert_path, key_path, host
            except Exception:
                pass

        try:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
            alt = [x509.DNSName(host), x509.DNSName("localhost")]
            for addr in {self.get_lan_ip(), "127.0.0.1"}:
                try:
                    alt.append(x509.IPAddress(ipaddress.ip_address(addr)))
                except ValueError:
                    pass
            now = datetime.datetime.now(datetime.timezone.utc)
            cert = (x509.CertificateBuilder()
                    .subject_name(subject).issuer_name(subject)
                    .public_key(key.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(now - datetime.timedelta(minutes=5))
                    .not_valid_after(now + datetime.timedelta(days=825))
                    .add_extension(x509.SubjectAlternativeName(alt), critical=False)
                    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                    .sign(key, hashes.SHA256()))
            os.makedirs(cert_dir, exist_ok=True)
            with open(cert_path, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
            with open(key_path, "wb") as f:
                f.write(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.TraditionalOpenSSL,
                                          serialization.NoEncryption()))
            return cert_path, key_path, host
        except Exception:
            return None

    def prepare_https(self, cert_dir):
        """
        HTTPSで配信するための証明書を用意する。
        戻り値: (SSLContext, 名前, 正規の証明書か) / 用意できなければ (None, "", False)
        """
        found = self._try_tailscale_cert(cert_dir)
        trusted = found is not None
        if found is None:
            # ⚠️ どちらの証明書になったかは、スマホでの見え方（警告の有無）を
            # 決める重要な違い。黙って落とさず、必ず理由を残す。
            if self.tailscale_hostname():
                self.log("ℹ️ Tailscaleの正規証明書を取得できなかったため、"
                         "自分で作った証明書を使います（初回だけスマホに警告が出ます）。")
            found = self._make_self_signed(cert_dir)
        if found is None:
            return None, "", False
        cert_path, key_path, host = found
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_path, key_path)
        except Exception:
            return None, "", False
        return context, host, trusted

    def start(self, pin, https=False, cert_dir=None):
        """待ち受けを開始する。戻り値: (成功したか, エラーメッセージ)"""
        if self.is_running():
            return True, ""
        self.pin = pin
        self.use_https = False
        self.cert_hostname = ""
        self.cert_is_trusted = False

        context = None
        if https:
            context, host, trusted = self.prepare_https(cert_dir or BASE_DIR)
            if context is None:
                return False, (
                    "HTTPS用の証明書を用意できませんでした。\n"
                    "HTTPSを使わない設定に戻すか、Tailscaleの管理画面で\n"
                    "「HTTPS Certificates」を有効にしてください。"
                )
            self.cert_hostname, self.cert_is_trusted = host, trusted

        try:
            httpd = _BridgeHTTPServer(("0.0.0.0", self.port), self._build_handler())
        except OSError as e:
            return False, (
                f"ポート{self.port}を使用できませんでした。\n"
                "このアプリを二重に起動していないか、他のアプリが同じポートを使っていないか"
                f"確認してください。\n\n詳細: {e}"
            )

        if context is not None:
            try:
                httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
                self.use_https = True
            except Exception as e:
                httpd.server_close()
                return False, f"HTTPSを開始できませんでした: {str(e).splitlines()[0][:120]}"

        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()
        return True, ""

    def stop(self):
        if not self.is_running():
            return
        httpd, self._httpd = self._httpd, None
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass
        self._thread = None


# ====================================================
# 📱 MuMu Player の操作（公式CLI: MuMuManager.exe 経由）
# ====================================================
class MuMuController:
    """
    MuMu Playerの起動状態を調べ、必要なら本体と対象アプリを起動する。

    ⚠️ adbの接続先を決め打ちしてはいけない。
    MuMu Player 12はインスタンスごとにadbポートが変わり、ホストもlocalhostとは限らない
    （実測環境では 192.168.1.7:5555 で、従来試していた 127.0.0.1:7555 / 16384 はどちらも接続拒否だった）。
    MuMuManager.exe に問い合わせれば正確な host/port が返るので、必ずそちらを使う。

    MuMuが入っていない環境（BlueStacks等）でも困らないよう、
    このクラスが使えない場合は呼び出し側が従来の方法にフォールバックする。
    """

    # インストール先の候補。バージョンや配布版で場所が変わるため複数見る
    KNOWN_PATHS = (
        r"C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe",
        r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0\nx_main\MuMuManager.exe",
        r"C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\MuMuManager.exe",
        r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\MuMuManager.exe",
        r"C:\Program Files (x86)\Netease\MuMuPlayer\nx_main\MuMuManager.exe",
    )

    def __init__(self, log_callback=None, manager_path=""):
        self.log_callback = log_callback or (lambda m: None)
        self.manager_path = manager_path or ""
        # 番号の解決結果を短時間だけ覚えておく (key, resolved, 取得時刻)
        self._index_cache = None

    def log(self, message):
        try:
            self.log_callback(message)
        except Exception:
            pass

    # --- 場所の特定 ---
    @classmethod
    def detect_manager_path(cls):
        """MuMuManager.exeを探す。見つからなければ空文字。"""
        for path in cls.KNOWN_PATHS:
            if os.path.exists(path):
                return path
        return ""

    def resolve_manager_path(self):
        """設定された場所を優先し、無ければ自動検出する"""
        if self.manager_path and os.path.exists(self.manager_path):
            return self.manager_path
        return self.detect_manager_path()

    def is_available(self):
        return bool(self.resolve_manager_path())

    # --- CLI実行 ---
    def _run(self, args, timeout=30):
        """
        MuMuManagerを実行して標準出力を返す。失敗時は None。
        exe(--windowed)から呼ぶため、コンソール窓が一瞬出ないようにしている。
        """
        path = self.resolve_manager_path()
        if not path:
            return None
        try:
            result = subprocess.run(
                [path] + list(args),
                capture_output=True, timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # 環境によって出力がUTF-8でないことがあるため、壊れた文字は無視して読む
            return result.stdout.decode("utf-8", errors="replace")
        except Exception as e:
            self.log(f"⚠️ MuMuManagerの実行に失敗しました: {e}")
            return None

    @staticmethod
    def _parse_json(raw):
        """出力から最初のJSONオブジェクトを取り出す（前後に文言が混ざることがあるため）"""
        if not raw:
            return None
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            return json.loads(raw[start:end + 1])
        except ValueError:
            return None

    # --- 状態の取得 ---
    @staticmethod
    def _error_message(data):
        """MuMuManagerがエラーを返した場合のメッセージ（正常なら空文字）"""
        if isinstance(data, dict) and data.get("errcode") not in (None, 0):
            return str(data.get("errmsg") or f"エラーコード {data.get('errcode')}")
        return ""

    def list_instances(self):
        """
        存在するインスタンスを {番号: 情報} で返す。

        ⚠️ インスタンス番号を決め打ちしてはいけない。
        MuMu 6にアップデートすると番号が変わることがあり（実測で 0 → 1）、
        しかも1台しか無くても is_main が false になる。
        「0番」も「メイン」も当てにならないので、必ずこの一覧から拾う。
        """
        data = self._parse_json(self._run(["info", "-v", "all"], timeout=20))
        if not data:
            return {}
        # MuMu 6 は {"1": {...}} のように番号をキーにした辞書を返す。
        # 旧バージョンは単一のオブジェクトを返すため、両方を受け付ける。
        if "index" in data:
            return {str(data.get("index", "0")): data}
        return {k: v for k, v in data.items() if isinstance(v, dict) and "index" in v}

    def detect_instance_index(self):
        """
        使うインスタンス番号を決める。優先順: 起動中 > メイン指定 > 一番小さい番号。
        1台も無ければNone。
        """
        instances = self.list_instances()
        if not instances:
            return None
        for picker in (lambda v: v.get("is_android_started"), lambda v: v.get("is_main")):
            hit = [k for k, v in instances.items() if picker(v)]
            if hit:
                return hit[0]
        return sorted(instances, key=lambda k: int(k) if str(k).isdigit() else 9999)[0]

    # 番号の解決結果を使い回す秒数。
    # 番号はMuMuの再インストールでもしない限り変わらないのに、解決のたびに
    # MuMuManagerを起動する（1回あたり約0.3秒）。起動待ちのループでは
    # これが積み上がって待ち時間が伸びるため、短時間だけ覚えておく。
    INDEX_CACHE_SECONDS = 30

    def resolve_index(self, preferred=None, use_cache=True):
        """
        使う番号を確定する。指定された番号が実在すればそれを、無ければ自動検出する。
        """
        key = None if preferred is None else str(preferred)
        now = time.time()
        cache = getattr(self, "_index_cache", None)
        if use_cache and cache and cache[0] == key and (now - cache[2]) < self.INDEX_CACHE_SECONDS:
            return cache[1]

        instances = self.list_instances()
        if key is not None and key in instances:
            resolved = key
        else:
            resolved = self.detect_instance_index()
            # 案内は結論が変わったときだけ。毎回出すとログが埋まる。
            if (resolved is not None and key is not None
                    and (cache is None or cache[1] != resolved or cache[0] != key)):
                self.log(f"ℹ️ MuMuのインスタンス番号 {preferred} が見つからないため、{resolved} を使います。")

        self._index_cache = (key, resolved, now)
        return resolved

    def forget_index_cache(self):
        """MuMuの場所を変えた場合など、番号を必ず取り直したいときに呼ぶ"""
        self._index_cache = None

    def get_info(self, index=None):
        """
        インスタンスの情報（adbポート・起動状態など）を辞書で返す。
        indexを省略するか実在しない番号を渡した場合は、自動検出した番号を使う。
        """
        resolved = self.resolve_index(index)
        if resolved is None:
            return None
        data = self._parse_json(self._run(["info", "-v", str(resolved)], timeout=20))
        error = self._error_message(data)
        if error:
            self.log(f"⚠️ MuMu: {error}")
            return None
        return data

    @staticmethod
    def is_android_ready(info):
        """Androidが起動しきっているか。ここがTrueにならないとadb接続もアプリ起動もできない。"""
        if not info:
            return False
        return bool(info.get("is_android_started")) and info.get("player_state") == "start_finished"

    @staticmethod
    def get_adb_address(info):
        """接続すべき 'host:port' を返す（取得できなければNone）"""
        if not info:
            return None
        port = info.get("adb_port")
        if not port:
            return None
        host = info.get("adb_host_ip") or "127.0.0.1"
        return f"{host}:{port}"

    def list_apps(self, index=None):
        """
        インストール済みアプリを (現在起動中のパッケージ, {パッケージ: アプリ名}) で返す。
        パッケージ名を手で入力させずに選ばせるために使う。
        """
        resolved = self.resolve_index(index)
        if resolved is None:
            return "", {}
        data = self._parse_json(
            self._run(["control", "-v", str(resolved), "app", "info", "-i"], timeout=30))
        error = self._error_message(data)
        if error:
            # MuMuが起動していないと "player not running" が返る
            self.log(f"⚠️ MuMu: {error}")
            return "", {}
        if not data:
            return "", {}
        active = data.get("active", "") or ""
        apps = {
            pkg: (value.get("app_name") or pkg)
            for pkg, value in data.items()
            if pkg != "active" and isinstance(value, dict)
        }
        return active, apps

    # --- 起動 ---
    def launch(self, index=None, package="", wait_seconds=120):
        """
        MuMu本体（必要ならアプリも）を起動し、Androidの起動完了まで待つ。
        戻り値: (成功したか, メッセージ)

        packageを渡すと本体の起動とアプリの起動をまとめて依頼できる。
        既に起動済みでも同じ呼び方で問題ない。
        """
        if not self.is_available():
            return False, "MuMuManager.exeが見つかりません。MuMuの場所を設定してください。"

        resolved = self.resolve_index(index)
        if resolved is None:
            return False, ("MuMuのインスタンスが見つかりません。"
                           "MuMuを一度手動で起動して、端末が作成されているか確認してください。")

        info = self.get_info(resolved)
        already = self.is_android_ready(info)

        args = ["control", "-v", str(resolved), "launch"]
        if package:
            args += ["-pkg", package]
        if already and package:
            # 起動済みなら、本体ではなくアプリだけを前面に出す
            args = ["control", "-v", str(resolved), "app", "launch", "-pkg", package]
        elif already and not package:
            return True, "MuMuは既に起動しています。"

        self.log("🚀 MuMuを起動しています..." if not already else "🚀 対象アプリを起動しています...")
        raw = self._run(args, timeout=60)
        if raw is None:
            return False, "起動コマンドの実行に失敗しました。"
        error = self._error_message(self._parse_json(raw))
        if error:
            return False, f"起動できませんでした（{error}）。"

        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self.is_android_ready(self.get_info(resolved)):
                # Androidが起動した直後はアプリ側の準備が整っていないことがあるため少し待つ
                time.sleep(2)
                return True, f"起動しました（インスタンス {resolved}）。"
            time.sleep(3)
        return False, f"{wait_seconds}秒待ってもMuMuの起動が完了しませんでした。"


# ====================================================
# 🤖 2. 監視ワーカー (uiautomator2 + XML解析 + 自動返信)
# ====================================================
class AutoReplyWorker:
    def __init__(self, db: DatabaseManager, log_callback):
        self.db = db
        self.log_callback = log_callback
        self.is_running = False
        self.thread = None

        # MuMuの検出・起動用。dbがNoneのテスト時でも作れるようにしておく
        saved_path = db.get_setting("mumu_manager_path", "") if db is not None else ""
        self.mumu = MuMuController(self.log_callback, manager_path=saved_path or "")

        # 監視開始時に判明する前面アプリ。裏のランチャー等を読み飛ばすのに使う
        self._foreground_package = ""
        # 対象アプリが前面から外れているか（外れたときだけ知らせるための状態）
        self._foreground_away = False
        self._last_foreground_check = 0
        # クリップボード貼り付けが使える端末か。一度失敗したらFalseにして以降は試さない
        self._clipboard_paste_available = True
        # 対象アプリが表示されているディスプレイ番号（MuMuは画面を複数持つ）。
        # ⚠️ このワーカーは起動から終了まで使い回されるので、監視を始めるたびに
        # 消しておくこと。前回の番号が残っていると、対象アプリがまだ表示されて
        # いない間、別の画面のつもりで読み書きしてしまう。
        self._target_display = None

        self.re_node = re.compile(r'<node\s+([^>]+)>')
        self.re_text = re.compile(r'text="([^"]+)"')
        self.re_desc = re.compile(r'content-desc="([^"]+)"')
        self.re_bounds = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
        self.re_class = re.compile(r'class="([^"]+)"')
        self.re_clickable = re.compile(r'clickable="true"')
        # どのアプリの部品かを見分ける（uiautomator2の入力補助バーを除外するのに使う）
        self.re_package = re.compile(r'package="([^"]+)"')

        self._last_seen_any_chat = ""

        # 監視ループから毎回DBを読むと0.3秒ごとに何度も接続することになるため、
        # 短時間だけ結果を保持する（設定変更への追従はこの秒数だけ遅れる）
        self._config_cache = None
        self._config_cache_time = 0.0
        self.CONFIG_CACHE_SECONDS = 1.0

        # ログ保存時にマスクせず残す語（自分で登録した検知ワード・返信ワード）。
        # 設定を読み込むたびに最新化される。
        self._log_keep_words = []

        # 手入力した文字の送信待ちと、直近で手入力送信した文。
        # ⚠️ 送信そのものは必ず監視スレッドにやらせること。別スレッドから直接
        #    エミュレータへ入力すると監視ループの操作と混ざる。MuMuは画面を
        #    4枚同時に動かしていて座標が重なるため、狙いと別の画面を触ってしまい
        #    「設定アプリが勝手に開く」「ホーム画面に戻る」が起きる。
        self._manual_queue = []
        self._recent_manual_texts = []
        self._manual_lock = threading.Lock()

    def log(self, message):
        # 画面には実際の内容を表示し、DBに保存する分だけ第三者の名前を伏せる
        self.log_callback(message)
        self.db.save_log(mask_screen_text(message, self._log_keep_words))

    # --- 起動 / 停止 ---
    def start(self, screen_x1, screen_y1, screen_x2, screen_y2):
        """
        監視スレッドを開始する。開始できた場合のみTrueを返す。
        停止直後はis_runningがFalseでもスレッドがまだ後片付け中のことがあるため、
        スレッドの生存も確認しないと監視が二重に走って同じ返信が2回送られてしまう。
        """
        if self.is_running or self.is_alive():
            return False
        self.is_running = True
        self._config_cache = None
        self._config_cache_time = 0.0
        self.thread = threading.Thread(
            target=self._monitor_loop,
            args=(screen_x1, screen_y1, screen_x2, screen_y2),
            daemon=True
        )
        self.thread.start()
        return True

    def stop(self):
        self.is_running = False
        self.log("⚠️ 停止リクエストを送信しました。現在の処理が終わり次第停止します...")

    def is_alive(self):
        return self.thread is not None and self.thread.is_alive()

    # --- 手入力送信 ---
    # 送信待ちに積める上限。連打などで無限にたまらないようにする
    MAX_MANUAL_QUEUE = 20
    # 「自分が手入力で送った文」として覚えておく件数。
    # 画面から流れて消えるまで持てれば十分なので、返信済み記録より少なくてよい
    MAX_RECENT_MANUAL_TEXTS = 10

    def enqueue_manual_text(self, text):
        """
        手入力した文字を送信待ちに積む。実際の送信は監視スレッドが行う。
        戻り値: (受け付けたか, 画面に出す文言)

        ⚠️ ここからエミュレータへ直接送ってはいけない。UIスレッドを止めてしまううえ、
        監視ループの操作と競合する。積むだけにして、送るのは監視スレッドに任せる。
        """
        text = (text or "").strip()
        if not text:
            return False, "送る文字が入力されていません。"
        if not (self.is_running and self.is_alive()):
            return False, "監視中ではないため送信できません。先に「▶ 開始」で監視を始めてください。"

        with self._manual_lock:
            if len(self._manual_queue) >= self.MAX_MANUAL_QUEUE:
                return False, f"送信待ちが{self.MAX_MANUAL_QUEUE}件たまっています。送り終わるまで少し待ってください。"
            self._manual_queue.append(text)
            waiting = len(self._manual_queue)

        if waiting > 1:
            return True, f"送信待ちに追加しました（順番待ち{waiting}件）。"
        return True, "送信待ちに追加しました。"

    def has_manual_pending(self):
        """送信待ちの手入力があるか（監視ループが毎周回これで様子を見る）"""
        with self._manual_lock:
            return bool(self._manual_queue)

    def _is_own_manual_text(self, chat_line):
        """
        画面のこの行が、自分が手入力で送った文かどうか。

        ⚠️ これが無いと、手入力した文に検知ワードが含まれていた場合に
        自分の発言へ自動返信してしまう（自分相手に延々と返し続ける）。
        既存の「返信ワードを含む行は対象外」という考え方を、手入力にも広げたもの。
        """
        with self._manual_lock:
            recent = list(self._recent_manual_texts)
        return any(text and text in chat_line for text in recent)

    # --- エミュレータ接続 ---
    def _prepare_mumu(self):
        """
        設定に応じてMuMu本体と対象アプリを起動し、接続すべき 'host:port' を返す。
        MuMuを使っていない環境では何もせずNoneを返す（従来の探索に任せる）。
        """
        if not self.mumu.is_available():
            return None

        # 番号は決め打ちしない。保存値が無ければ resolve_index が自動検出する
        index = self.db.get_setting("mumu_instance_index", "") or None
        package = (self.db.get_setting("mumu_target_package", "") or "").strip()
        auto_launch = self.db.get_setting("mumu_auto_launch", "0") == "1"

        if auto_launch:
            success, message = self.mumu.launch(index=index, package=package)
            if success:
                self.log(f"✅ MuMu: {message}")
            else:
                # 起動に失敗しても、既に動いている可能性があるので接続は試す
                self.log(f"⚠️ MuMu: {message}")

        info = self.mumu.get_info(index)
        if not self.mumu.is_android_ready(info):
            # MuMuは見つかっているのにAndroidが動いていない状態。
            # ここで黙ると、この後「エミュレータが見つかりません」という
            # 的外れなメッセージだけが出て、原因にたどり着けない。
            if info:
                state = info.get("player_state") or "Android未起動"
                self.log(f"⚠️ MuMu（インスタンス {info.get('index', '?')}）はまだ使える状態ではありません（{state}）。")
                if not auto_launch:
                    self.log("💡 設定タブの「📱 エミュレータ(MuMu)」で自動起動をONにするか、"
                             "MuMuの端末を起動してから開始してください。")
            else:
                self.log("⚠️ MuMuのインスタンスが見つかりません。"
                         "MuMuを一度手動で起動して、端末が作成されているか確認してください。")
            return None
        address = self.mumu.get_adb_address(info)
        if address:
            self.log(f"📱 MuMuが示すadbの接続先: {address}")
        return address

    def _connect_to_emulator(self):
        self.log("🔄 エミュレータの検出を試みています...")

        # ① MuMuに直接聞くのが最も確実。
        #    ポート決め打ちはインスタンスごとに変わるため当てにならない。
        mumu_address = None
        try:
            mumu_address = self._prepare_mumu()
        except Exception as e:
            self.log(f"⚠️ MuMuの準備中にエラーが発生しました: {e}")

        candidates = []
        if mumu_address:
            candidates.append(mumu_address)
        # ② 従来の決め打ちポート（他のエミュレータや古いMuMu向けの保険）
        candidates += ["127.0.0.1:7555", "127.0.0.1:16384", "127.0.0.1:5555"]

        for address in candidates:
            try:
                adb.connect(address, timeout=3.0)
            except Exception:
                continue

        device_list = adb.device_list()
        if not device_list:
            raise Exception(
                "接続可能なエミュレータが見つかりません。\n"
                "MuMuが起動しているか確認してください。"
                "（設定タブの「エミュレータ(MuMu)」で自動起動を有効にできます）"
            )

        # MuMuから得た接続先が一覧にあるならそれを使う。
        # ⚠️ MuMuが返すのはLAN側のアドレス(例 192.168.1.7:16416)で、
        # adbが実際に持っているのは 127.0.0.1:7555 のような別のものであることがある。
        # 「取得した接続先」と「実際に繋いだ先」が食い違うと原因追跡がしづらいので、
        # 使えなかった場合はその旨をはっきり残す。
        serials = [dev.serial for dev in device_list]
        if mumu_address and mumu_address in serials:
            target_serial = mumu_address
        else:
            target_serial = serials[0]
            if mumu_address:
                self.log(f"ℹ️ {mumu_address} はadbに登録されていないため、{target_serial} を使います。"
                         f"（adbが把握している端末: {', '.join(serials)}）")
        d = u2.connect(target_serial)

        try:
            d.settings['waitForIdleTimeout'] = 0
        except Exception:
            pass
        try:
            d.settings['wait_timeout'] = 0.0
        except Exception:
            pass
        try:
            d.set_fastinput_ime(True)
        except Exception:
            pass

        self.log(f"🔌 エミュレータ ({target_serial}) に接続しました。")
        return d

    def _calculate_y_bounds(self, d, screen_y1, screen_y2):
        """
        画面上でドラッグした監視範囲(PCの絶対座標)を、Android内部の座標に変換する。

        エミュレータのウインドウ位置・サイズを基準にしている。これは意図した仕様で、
        「画面で見えている場所をそのまま指定する」ための作りなので、
        ウインドウ依存を無くそうとしないこと。
        ウインドウを動かしたりサイズを変えたりした場合は、範囲を選び直せばよい。
        """
        emu_window = None
        for w in gw.getAllWindows():
            if w.title and any(k in w.title.lower() for k in ["bluestacks", "ldplayer", "noxplayer", "mumu", "android device"]):
                emu_window = w
                self.log(f"🪟 ウインドウ検出: {w.title}")
                break

        if not emu_window:
            self.log("⚠️ エミュレータのウインドウが見つかりません。画面全体の絶対座標で監視します。")
            emu_top, emu_height = 0, pyautogui.size()[1]
        else:
            emu_top, emu_height = emu_window.top, emu_window.height

        # 最小化中のウインドウは高さが0や負になることがあり、そのまま割り算するとエラーになる
        if emu_height <= 0:
            self.log("⚠️ エミュレータのウインドウサイズを取得できませんでした（最小化されている可能性があります）。")
            self.log("💡 エミュレータを画面に表示した状態でもう一度開始してください。画面全体の座標で代用します。")
            emu_top, emu_height = 0, max(1, pyautogui.size()[1])

        _, w_height = d.window_size()
        if not w_height or w_height <= 0:
            raise Exception("エミュレータの画面サイズを取得できませんでした。")
        y_min = max(0, int(((screen_y1 - emu_top) / emu_height) * w_height) - 150)
        y_max = min(w_height, int(((screen_y2 - emu_top) / emu_height) * w_height) + 150)

        self.log(f"🤖 Android内部の監視範囲確定: Y軸 {y_min}px 〜 {y_max}px")
        return y_min, y_max, w_height

    def _log_active_keywords(self):
        """
        いま実際に使われる検知ワードを開始時に並べる。

        セットが有効でもペアが☐無効だと監視対象から外れるため、
        「有効にしたつもりのワードが動いていない」ことに気付けない。
        検知が起きないときの原因が真っ先にここだと分かるよう、開始時に必ず出す。
        """
        # 自分でOFFにしている場合と、設定し忘れている場合を混同させない。
        # どちらも「有効キーワード0件」になるが、直す場所が全く違うため。
        if self.db and self.db.get_setting(KEYWORD_AUTO_REPLY_SETTING, "1") != "1":
            self.log("⏸️ キーワード自動返信はOFFです。検知しても自動では送りません。")
            self.log("💡 画面の読み取りと手入力送信は、このまま使えます。")
            return

        keywords = self.db.get_active_keywords() if self.db else {}
        if not keywords:
            self.log("⚠️ 有効な検知ワードが1つもありません。このままでは何も反応しません。")
            self.log("💡 キーワード設定タブで、使いたいペアをダブルクリックして☑にしてください。")
            return

        self.log(f"🔑 有効な検知ワード（{len(keywords)}件）:")
        for trigger in keywords:
            self.log(f" ・「{trigger}」")

    def _warn_if_target_app_not_foreground(self, d):
        """
        監視対象のアプリが前面に出ているか確かめ、出ていなければ警告する。

        MuMuのホーム画面のままだと、アイコン名（GRAVITY / 設定 / ギャラリー…）ばかりを
        読み取り続けて検知ワードには永久に一致しない。ログを見ても
        「動いてはいるが何も起きない」という分かりにくい状態になるため、
        開始時にはっきり知らせる。
        """
        target = (self.db.get_setting("mumu_target_package", "") or "").strip() if self.db else ""
        try:
            current = (d.app_current() or {}).get("package", "")
        except Exception:
            self._foreground_package = ""
            return      # 取得できない環境では黙って通す

        # 裏のランチャー等を読み飛ばすために、前面アプリを覚えておく
        self._foreground_package = current or ""
        if not current:
            return
        if target and current == target:
            return

        if not target:
            self.log(f"ℹ️ 現在エミュレータで開いているアプリ: {current}")
            self.log("💡 設定タブの「📱 エミュレータ(MuMu)」で監視対象アプリを選んでおくと、"
                     "違うアプリを見ているときに警告できます。")
            return

        name = (self.db.get_setting("mumu_target_name", "") or target) if self.db else target
        self.log(f"⚠️ 監視対象の「{name}」が前面にありません（今開いているのは {current}）。")
        self.log("💡 このままでは検知ワードに一致しません。対象アプリを開いてから開始するか、"
                 "設定タブの「📱 エミュレータ(MuMu)」で自動起動をONにしてください。")

    def _perform_initial_scan(self, d, y_min, y_max):
        self.log("🔍 [テスト] 監視範囲内から読み取れる文字を調べています...")
        try:
            xml_dump = d.dump_hierarchy(compressed=True)
            # 監視ループより先に、対象アプリがどの画面に出ているかを確定させる。
            # ここで決めておかないと、この最初の一覧に別画面の
            # ランチャーのアイコン名が混ざって「何を見ているか」が分からなくなる。
            self._update_target_display(xml_dump)
            chat_texts, _, _, _ = self._extract_chat_texts(xml_dump, y_min, y_max)

            dumped_texts = []
            for t, _ in chat_texts:
                if t.strip() and t not in dumped_texts:
                    dumped_texts.append(t)

            if dumped_texts:
                self.log("📋 監視範囲内で以下の文字を認識しました（最初の15件）:")
                for t in dumped_texts[:15]:
                    self.log(f" - {t}")
                self._diagnose_keyword_mismatch(dumped_texts)
            else:
                self.log("⚠️ 監視範囲内から文字を全く読み取れませんでした。範囲がずれているか、画像化されています。")
        except Exception as e:
            self.log(f"⚠️ 文字スキャン中にエラーまたはタイムアウト: {e}")
            self.log("💡 アプリの構造が複雑すぎるか、読み取りがブロックされています。")

    # 返信済みとして覚えておくメッセージの件数。
    # 長時間動かすと際限なく増えるため上限を設ける。古い行は画面から流れて消えるので、
    # ある程度で忘れても二重送信にはつながらない。
    MAX_REPLIED_LOGS = 300

    def _remember_replied(self, replied_logs, text):
        """返信済みの行を記録する（古いものから捨てて上限を保つ）"""
        replied_logs[text] = time.time()
        while len(replied_logs) > self.MAX_REPLIED_LOGS:
            try:
                del replied_logs[next(iter(replied_logs))]
            except (StopIteration, KeyError):
                break

    # 同じ行へ再挑戦するまでにあける秒数（前回失敗した行だけ待たせる）
    RETRY_SAME_LOG_SECONDS = 15

    def _select_pending_replies(self, matched_elements, replied_logs, reply_message,
                                last_log, last_time):
        """
        検知ワードに一致した行のうち、これから返信すべきものを古い順に返す。

        ⚠️ 一番下(最新)の1件だけを見てはいけない。
        短時間に複数人が参加すると一致する行が同時に何件も並ぶが、最新の1件へ
        返信して「返信済み」にした後も、次の周回で選ばれるのは同じ最新行なので、
        上に居る人には順番が回らずログにも何も出ないまま流れて消えていた。

        15秒待たせるのは「直前に試して失敗した行」だけにする。
        全体を待たせると、1件の失敗で後続の人への返信まで止まってしまう。

        ⚠️ この選び方は監視ループから切り出してある。以前はループの中に
        直接書かれていたため、検証しようとするとテスト側へ同じ判定を書き写す
        しかなく、実装を変えてもテストが通り続けてしまう状態だった。
        """
        pending = [
            item for item in sorted(matched_elements, key=lambda x: x[1])
            if item[0] not in replied_logs
            and reply_message not in item[0]
            and not self._is_own_manual_text(item[0])
        ]
        now = time.time()
        return [
            item for item in pending
            if item[0] != last_log or (now - last_time) > self.RETRY_SAME_LOG_SECONDS
        ]

    def _forget_replied_off_screen(self, replied_logs, chat_texts):
        """
        画面から消えたメッセージは「返信済み」の記録から外す。

        ⚠️ 「画面に残っている間だけ覚える」のが肝。
        ずっと覚えていると、同じ人が入り直しても文面が同じために二度と返信できない。
        逆にまったく覚えないと、画面に残り続ける行へ延々と返信してしまう。
        「見えている間は送らない／流れて消えたら忘れる」なら両方を満たせる。

        画面を1件も読めなかった周回では何も忘れない。読み取りが一瞬失敗しただけで
        記録が消えると、まだ画面にある行へ返信し直してしまうため。
        """
        if not chat_texts:
            return
        visible = {text for text, _ in chat_texts}
        for logged in [t for t in replied_logs if t not in visible]:
            del replied_logs[logged]

    # 検知ワードの「惜しい間違い」とみなす共通部分の最低文字数。
    # 短すぎると「が」「は」だけで反応してしまい、助言として役に立たない。
    MIN_NEAR_MISS_LENGTH = 4

    def _diagnose_keyword_mismatch(self, screen_texts):
        """
        検知ワードが画面のどの文字とも一致しないとき、惜しい候補を示して直し方を伝える。

        「が音声ルームに参加しました」に対して「がルームに参加しました」のように、
        間に語が挟まっているだけで部分一致しない、という間違いは気付きにくい。
        画面には答えが出ているので、共通部分を計算してそのまま提案する。
        """
        keywords = list(self.db.get_active_keywords().keys()) if self.db else []
        if not keywords or not screen_texts:
            return

        matched = [k for k in keywords if any(k in t for t in screen_texts)]
        if matched:
            return      # 一致しているワードがあるなら助言は不要

        for keyword in keywords:
            best_text, best_common = "", ""
            for text in screen_texts:
                match = difflib.SequenceMatcher(None, keyword, text).find_longest_match(
                    0, len(keyword), 0, len(text)
                )
                common = keyword[match.a:match.a + match.size]
                if len(common) > len(best_common):
                    best_text, best_common = text, common

            if len(best_common) < self.MIN_NEAR_MISS_LENGTH:
                continue

            self.log(f"⚠️ 検知ワード「{keyword}」は、今の画面のどの文字とも一致しません。")
            self.log(f"💡 画面には似た文字があります:「{best_text[:40]}」")
            if best_common != keyword:
                self.log(f"💡 検知ワードを「{best_common}」に変えると一致します"
                         "（キーワード設定タブで書き換えて「➕ 追加 / 更新」）。")

    def _get_auto_ok_keywords(self):
        """自動で閉じてよいダイアログの目印を返す"""
        raw = self.db.get_setting("auto_ok_keywords", DEFAULT_AUTO_OK_KEYWORDS) if self.db else ""
        return [k.strip() for k in (raw or DEFAULT_AUTO_OK_KEYWORDS).split(",") if k.strip()]

    # ダイアログとみなす入れ物の、画面に対する最大の面積比。
    # 本物のダイアログは画面の一部にとどまる。目印とボタンをくくる入れ物が
    # 画面まるごとなら、それは「同じダイアログの中」ではなく単に同じ画面にあるだけ。
    AUTO_OK_MAX_DIALOG_AREA_RATIO = 0.6

    def _element_label(self, el):
        """ElementTreeの要素の表示文字（text と content-desc）"""
        return ((el.get("text") or "") + (el.get("content-desc") or "")).strip()

    def _element_bounds(self, el):
        """bounds属性 "[l,t][r,b]" を (l, t, r, b) にする。読めなければNone"""
        m = RE_BOUNDS_VALUE.match(el.get("bounds") or "")
        return tuple(map(int, m.groups())) if m else None

    def _find_dialog_ok_button(self, xml_dump, keywords):
        """
        目印とOKボタンが「同じダイアログの中」にある場合だけ、押す座標を返す。
        戻り値: (目印, ボタンのラベル, (x, y)) / 該当なしならNone

        ⚠️ 目印が画面のどこかにあるだけで押してはいけない。
        監視しているのはチャット画面であり、抽選機などが「当選者は…」という
        文章を本文として流す。本文と、画面のどこかにあるボタンを結び付けて押すと、
        ダイアログでも何でもないものを押してしまう。
        目印とボタンが同じ入れ物（ダイアログ）に入っていることまで確かめる。

        判定には木構造が要る。正規表現でノードを平らに集めると親子関係が失われ、
        「同じダイアログか」は原理的に判定できない。
        """
        # 目印がダンプのどこにも無いなら、木に組み立てるまでもない。
        # この関数は監視ループ（毎秒3回ほど）から呼ばれるので、
        # 何も起きていない平常時にXMLを解析し直さないようにする。
        # XMLはエスケープされているため、生の形と両方で見る。
        if not any(k in xml_dump or html.escape(k) in xml_dump for k in keywords):
            return None

        try:
            root = ET.fromstring(xml_dump)
        except Exception:
            return None      # 画面ダンプが読めないときは押さない（安全側）

        # 画面の大きさは、ダンプの最上位ノード（＝各ウィンドウ）の一番大きいものから求める。
        # d.window_size()に頼ると、取得に失敗した時に大きさの判定ごと消えてしまい、
        # 「画面まるごと＝ダイアログではない」の歯止めが効かなくなる。
        screen_area = 0
        for window in root:
            box = self._element_bounds(window)
            if box:
                left, top, right, bottom = box
                screen_area = max(screen_area, max(0, right - left) * max(0, bottom - top))
        if not screen_area:
            return None      # 大きさが分からなければ判定できない（安全側）

        parents = {child: parent for parent in root.iter() for child in parent}

        def ancestors(el):
            """自分自身から根までを、近い順に並べて返す"""
            chain = [el]
            while el in parents:
                el = parents[el]
                chain.append(el)
            return chain

        target = self._monitor_target_package()
        display = getattr(self, "_target_display", None)
        markers, buttons = [], []
        for el in root.iter("node"):
            if target and el.get("package") != target:
                continue      # 対象アプリ以外（ランチャー等）は最初から相手にしない
            if display is not None and el.get("display-id") not in (display, None):
                continue      # 別のディスプレイに出ている同名アプリは触らない
            label = self._element_label(el)
            if not label:
                continue
            matched = next((k for k in keywords if k in label), None)
            if matched:
                markers.append((matched, el))
            if el.get("clickable") == "true" and label in AUTO_OK_BUTTON_LABELS:
                buttons.append((label, el))

        if not markers or not buttons:
            return None

        for matched_keyword, marker_el in markers:
            marker_chain = set(ancestors(marker_el))
            for label, button_el in buttons:
                # 目印とボタンを最初にくくる入れ物 ＝ 最も近い共通の親
                container = next((a for a in ancestors(button_el) if a in marker_chain), None)
                if container is None:
                    continue
                box = self._element_bounds(container)
                if not box:
                    continue
                left, top, right, bottom = box
                area = max(0, right - left) * max(0, bottom - top)
                if area > screen_area * self.AUTO_OK_MAX_DIALOG_AREA_RATIO:
                    continue      # 入れ物が画面まるごと ＝ ダイアログではない
                b_box = self._element_bounds(button_el)
                if not b_box:
                    continue
                bl, bt, br, bb = b_box
                return matched_keyword, label, ((bl + br) / 2, (bt + bb) / 2)

        return None

    def _auto_dismiss_dialog(self, d, all_nodes, xml_dump):
        """
        目印を含むダイアログが出ていたら、OKボタンを押して閉じる。
        戻り値: 押したらTrue（呼び出し側は画面を取り直すこと）

        ⚠️ 「OK」ボタンを見つけたら押す、という作りにしてはいけない。
        購入確認・規約同意・権限許可など、押してはいけないダイアログにもOKはあり、
        誤爆すると取り返しがつかない。目印（既定では「当選者」「選ばれました」）が
        そのボタンと同じダイアログの中にあることまで確かめてから押す。
        """
        if not self.db or self.db.get_setting("auto_ok_enabled", "0") != "1":
            return False

        # 連打防止。押した直後は画面が切り替わる途中のことがある
        now = time.time()
        if now - getattr(self, "_last_auto_ok_time", 0) < AUTO_OK_MIN_INTERVAL_SECONDS:
            return False

        keywords = self._get_auto_ok_keywords()
        if not keywords:
            return False

        found = self._find_dialog_ok_button(xml_dump, keywords)
        if not found:
            return False
        matched_keyword, label, (cx, cy) = found

        # ⚠️ 渡すのは絞り込む前の all_nodes。
        # 対象アプリだけに絞ったノードを渡すと、_blocking_overlay_at が見るのは
        # 「対象アプリ以外の押せる部品」なので該当が1件も無く、判定が素通りになる。
        blocker = self._blocking_overlay_at(all_nodes, cx, cy)
        if blocker:
            self.log(f"🛑 ダイアログの「{label}」({int(cx)},{int(cy)})に別アプリの「{blocker}」が"
                     "重なっています。タップを中止しました。")
            return False
        if not self._tap(d, cx, cy):
            return False      # 押せていないので「閉じた」と扱わない
        self._last_auto_ok_time = now
        self.log(f"✅ 「{matched_keyword}」のダイアログを検出し、"
                 f"「{label}」({int(cx)},{int(cy)})を押して閉じました。")
        self._check_after_action(d, f"ダイアログの「{label}」(目印「{matched_keyword}」)")
        return True

    def _is_background_noise_node(self, node):
        """
        監視対象アプリ以外の部品かどうか。

        ⚠️ 画面ダンプには、前面のアプリだけでなく
        　・MuMuのランチャー(app.lawnchair) … 常に裏にいて、ダンプの先頭に来る
        　・ステータスバー(com.android.systemui) … 時計・電池・通知
        　・uiautomator2の入力補助IME
        も一緒に入ってくる。特にランチャーはアイコン名を10件以上ばらまくため、
        除外しないと「読み取れた文字」がランチャーで埋まり、
        肝心のチャットが見えず「対象アプリを見ていない」ように誤解させる。
        """
        p_match = self.re_package.search(node)
        if not p_match:
            return False
        package = p_match.group(1)
        if package.startswith(UIAUTOMATOR_IME_PACKAGE):
            return True
        if package in BACKGROUND_NOISE_PACKAGES:
            return True
        # 監視対象が分かっている場合は、それ以外をすべて裏の部品とみなす。
        # 設定で選んだアプリを最優先にする（開始時に前面だったアプリは、
        # ホーム画面から始めた場合などに対象と食い違うため当てにできない）。
        target = self._monitor_target_package()
        return bool(target) and package != target

    # 前面アプリを見張る間隔（秒）。毎周回だと通信が増えるため間引く。
    FOREGROUND_CHECK_INTERVAL_SECONDS = 10

    def _watch_foreground_change(self, d):
        """
        対象アプリが前面から外れたら知らせ、戻ったら知らせる。

        外れている間は画面を読めないので、検知も送信も何も起きない。
        黙っていると「動いているのに反応しない」という一番分かりにくい状態になる。
        """
        target = self._monitor_target_package()
        if not target:
            return
        now = time.time()
        if now - getattr(self, "_last_foreground_check", 0) < self.FOREGROUND_CHECK_INTERVAL_SECONDS:
            return
        self._last_foreground_check = now

        # 複数画面があるため、前面判定ではなく「どこかの画面に出ているか」で見る
        shown, other = self._target_still_shown(d)

        was_away = getattr(self, "_foreground_away", False)
        if not shown and not was_away:
            self._foreground_away = True
            self.log(f"⚠️ 監視対象のアプリが表示から消えました（今は {other or '不明'}）。"
                     "この間は検知も送信も行われません。")
            # 自動起動をONにしている場合は「対象アプリを開いてよい」と了解済みなので、
            # そのまま戻す。OFFなら知らせるだけにとどめる。
            if self.db is not None and self.db.get_setting("mumu_auto_launch", "0") == "1":
                self._restore_target_app_if_left(d)
                if self._target_still_shown(d)[0]:
                    self._foreground_away = False
            else:
                self.log("💡 設定タブの「📱 エミュレータ(MuMu)」で自動起動をONにしておくと、"
                         "消えたときに自動で戻します。")
        elif shown and was_away:
            self._foreground_away = False
            self.log("✅ 監視対象のアプリが表示に戻りました。監視を再開します。")

    def _current_package(self, d):
        """今前面に出ているアプリのパッケージ名（取得できなければ空文字）"""
        try:
            return (d.app_current() or {}).get("package", "") or ""
        except Exception:
            return ""

    def _target_still_shown(self, d):
        """
        対象アプリが今もどこかのディスプレイに出ているかを調べる。
        戻り値: (出ているか, 参考として見えた別アプリ名)

        ⚠️ app_current() だけで判断してはいけない。
        あれは「入力フォーカスを持つ画面のアプリ」を返すため、MuMuのように
        画面が複数あると、対象アプリが自分の画面に正しく出ていても
        「別のアプリになった」と誤判定する。実測では、GRAVITYがディスプレイ2に
        正常に出ているのにホーム画面(ディスプレイ0)の名前が返り、
        そのたびにアプリを開き直していた。
        ディスプレイごとの最前面を見て、どこかに居れば正常とみなす。
        """
        target = self._monitor_target_package()
        if not target:
            return True, ""
        try:
            out = d.shell("dumpsys activity activities | grep topResumedActivity").output
        except Exception:
            return True, ""      # 確認できないときは騒がない（安全側）
        # ⚠️ 出力が「画面ごとの最前面」の形をしているか必ず確かめる。
        # grepが使えない等でエラー文字列が返ると「対象が消えた」と誤判定し、
        # 自動起動がONだとアプリを開き直して音声ルームから抜けてしまう。
        # 判断できない時は「居る」として扱う（余計なことをしない）。
        packages = re.findall(r"u0 ([\w.]+)/", out or "")
        if not packages:
            return True, ""
        others = [p for p in packages if p != target]
        return (target in packages), (others[-1] if others else "")

    def _check_after_action(self, d, description):
        """
        画面を操作した直後に、対象アプリが表示から消えていないか確認して記録する。

        「いつの間にか別のアプリが開いている／ホームに戻っている」という症状は、
        どの操作が引き金かが分からないと直しようがない。
        操作ごとに確認して、原因になった操作を名指しで残す。
        """
        target = self._monitor_target_package()
        if not target:
            return
        shown, other = self._target_still_shown(d)
        if not shown:
            self.log(f"🔀 【{description}】の直後に対象アプリが表示から消えました"
                     f"（今見えているのは {other or '不明'} / 対象は {target}）")

    def _restore_target_app_if_left(self, d):
        """
        返信のあとで対象アプリが前面から外れていたら、開き直して戻す。
        （BACKの押しすぎなどで背面に落ちた場合の保険）
        """
        target = self._monitor_target_package()
        if not target:
            return
        # ⚠️ app_current() だけで判断しないこと。複数画面では対象アプリが
        # 自分の画面に正しく出ていても別アプリ名が返り、そのたびに
        # app_start() で音声ルームを開き直してしまう（実測で多発した）。
        shown, other = self._target_still_shown(d)
        if shown:
            return

        self.log(f"⚠️ 送信後に対象アプリが表示から消えました（今は {other or '不明'}）。開き直します。")
        try:
            d.app_start(target)
            time.sleep(1.5)
            back_shown, back_other = self._target_still_shown(d)
            if back_shown:
                self.log("✅ 対象アプリに戻りました。")
            else:
                self.log(f"⚠️ 対象アプリに戻せませんでした（今は {back_other or '不明'}）。")
        except Exception as e:
            self.log(f"⚠️ 対象アプリを開き直せませんでした: {str(e).splitlines()[0][:100]}")

    # ------------------------------------------------------------------
    # ディスプレイの扱い
    # MuMuは複数の画面を同時に動かすため、「どの画面を操作するか」を
    # 明示しないと、対象アプリではなくホーム画面を触ってしまう。
    # ------------------------------------------------------------------

    def _update_target_display(self, xml_dump):
        """
        画面ダンプから、対象アプリが表示されているディスプレイ番号を割り出して覚える。
        見つからなければ前回の値を保つ（アプリが一瞬消えても操作先を見失わないため）。

        ⚠️ 「最初に見つかった1件」で決めてはいけない。
        アプリが2つの画面にまたがって残っていることがあり、
        中身がほとんど無い残留ウィンドウの方を選ぶと、そちらへ入力を送ってしまう。
        部品の数が一番多い画面＝実際に描画されている画面を選ぶ。
        """
        target = self._monitor_target_package()
        if not target:
            return None

        counts = {}
        for node in self.re_node.findall(xml_dump):
            p_match = self.re_package.search(node)
            if not (p_match and p_match.group(1) == target):
                continue
            d_match = RE_DISPLAY_ID.search(node)
            if d_match:
                counts[d_match.group(1)] = counts.get(d_match.group(1), 0) + 1

        if not counts:
            return self._target_display

        found = max(counts, key=counts.get)
        if found != self._target_display:
            previous = self._target_display
            self._target_display = found
            others = {k: v for k, v in counts.items() if k != found}
            extra = f"（他の画面にも残っています: {others}）" if others else ""
            if previous is None:
                self.log(f"🖥️ 対象アプリはディスプレイ {found} に表示されています"
                         f"（部品{counts[found]}個）。操作はこの画面へ送ります。{extra}")
            else:
                self.log(f"🖥️ 対象アプリの表示先がディスプレイ {previous} → {found} "
                         f"に変わりました。{extra}")
        return found

    def _same_display_nodes(self, xml_dump):
        """対象アプリと同じディスプレイのノードだけを返す（番号不明なら全件）"""
        display = getattr(self, "_target_display", None)
        nodes = self.re_node.findall(xml_dump)
        if display is None:
            return nodes
        # display-idが無いノード（古いAndroid）は単一画面とみなして残す
        return [n for n in nodes if self._node_display(n) in (display, None)]

    def _node_display(self, node):
        m = RE_DISPLAY_ID.search(node)
        return m.group(1) if m else None

    def _input_command(self, *args):
        """`input -d <番号> ...` の形にする。番号が分からなければ既定の画面へ送る"""
        display = getattr(self, "_target_display", None)
        prefix = f"input -d {display} " if display is not None else "input "
        return prefix + " ".join(str(a) for a in args)

    # inputコマンドが失敗したことを示す文字列。
    # ⚠️ 終了コードは当てにならない。実測では存在しないディスプレイ番号を
    # 指定しても `input -d 99 tap 1 1` は終了コード0を返し、何も起きないまま
    # 成功したように見える。出力の中身で判断するしかない。
    INPUT_ERROR_HINTS = ("error", "exception", "not found", "usage:", "denied", "failed")

    def _run_input(self, d, *args):
        """`input` を対象アプリのディスプレイへ送り、失敗らしき出力があれば知らせる"""
        command = self._input_command(*args)
        try:
            result = d.shell(command)
        except Exception as e:
            self.log(f"⚠️ 画面操作を送れませんでした（{args[0]}）: "
                     f"{str(e).splitlines()[0][:100]}")
            return False
        output = (getattr(result, "output", result) or "")
        if isinstance(output, str) and any(h in output.lower() for h in self.INPUT_ERROR_HINTS):
            self.log(f"⚠️ 画面操作が失敗した可能性があります: {command} → {output.strip()[:120]}")
            return False
        return True

    def _tap(self, d, x, y):
        """対象アプリのディスプレイをタップする"""
        return self._run_input(d, "tap", int(x), int(y))

    def _swipe(self, d, x1, y1, x2, y2, duration_ms=200):
        """対象アプリのディスプレイをなぞる"""
        return self._run_input(d, "swipe", int(x1), int(y1), int(x2), int(y2), int(duration_ms))

    def _keyevent(self, d, keycode):
        """対象アプリのディスプレイへキーを送る"""
        return self._run_input(d, "keyevent", int(keycode))

    # 対象アプリ名を読み直す間隔（秒）。設定変更には十分速く追従しつつ、
    # 画面1枚あたり100回以上のDB読み出しを避けるための短時間キャッシュ。
    TARGET_PACKAGE_CACHE_SECONDS = 1.0

    def _monitor_target_package(self):
        """
        監視対象アプリのパッケージ名（設定 > 開始時に前面だったアプリ）

        ⚠️ ここを毎回DBから読んではいけない。
        _is_background_noise_node が画面のノード1つごとにこれを呼ぶため、
        素直に実装すると画面1枚の読み取りで100回以上SQLiteへ接続することになる。
        実測では _extract_chat_texts 1回が477msかかり（うち4.75秒/10回がDB接続）、
        毎秒3回動く監視ループがCPUを占有していた。
        設定変更には1秒以内に追従できればよいので、短時間だけ覚えておく。
        """
        now = time.time()
        cache = getattr(self, "_target_package_cache", None)
        if cache and (now - cache[1]) < self.TARGET_PACKAGE_CACHE_SECONDS:
            return cache[0]

        value = ""
        if self.db is not None:
            value = (self.db.get_setting("mumu_target_package", "") or "").strip()
        if not value:
            value = getattr(self, "_foreground_package", "") or ""
        self._target_package_cache = (value, now)
        return value

    def _extract_chat_texts(self, xml_dump, y_min, y_max):
        # ⚠️ まず「対象アプリと同じディスプレイ」だけに絞る。
        # MuMuは複数画面を同時に動かし、ダンプには全部が入ってくる。
        # どれも同じ大きさなので座標が偶然重なり、絞らないと
        # 別画面のランチャーの部品を対象アプリの部品と取り違える。
        nodes = self._same_display_nodes(xml_dump)
        chat_texts = []
        out_of_bounds_texts = []

        # 監視対象アプリ以外（ランチャー・ステータスバー・IME）を除く。
        app_nodes = [n for n in nodes if not self._is_background_noise_node(n)]

        # 文字を読むぶんには、万一すべて除外されてしまった場合に限り
        # 全ノードで読み直す（前面アプリの判定を誤って検知が死ぬのを避けるため）。
        # ⚠️ ただしタップには絶対にこの緩い方を使わないこと。
        # ランチャーだけが映っている画面では全ノードがノイズ判定になり、
        # ここで全ノードに戻すと「設定」アイコンなどを押す対象として復活してしまう。
        # 押し間違えるより、何もしない方が安全。
        scan_nodes = app_nodes if app_nodes else nodes

        for node in scan_nodes:
            text_match = self.re_text.search(node)
            desc_match = self.re_desc.search(node)
            bounds_match = self.re_bounds.search(node)

            t = ""
            if text_match and text_match.group(1).strip():
                t = text_match.group(1)
            elif desc_match and desc_match.group(1).strip():
                t = desc_match.group(1)

            # XMLダンプ内では & < > などが &amp; &lt; &gt; にエスケープされている。
            # 元の文字に戻さないと、これらを含む検知ワードが永久に一致しない。
            if t:
                t = html.unescape(t)

            if t and bounds_match:
                left, top, right, bottom = map(int, bounds_match.groups())

                if (right - left) < 10 or (bottom - top) < 10:
                    continue
                if left < 0 or right < 0:
                    continue

                center_y = (top + bottom) / 2
                if y_min <= center_y <= y_max:
                    chat_texts.append((t, center_y))
                else:
                    out_of_bounds_texts.append(t)
        # ⚠️ 返すのは厳密に絞り込んだ方(app_nodes)。scan_nodes は使わない。
        # 呼び出し側はこれをタップ対象の候補にするため、
        # 「全部除外されたら全ノードに戻す」緩和をここに持ち込むと、
        # ランチャーだけの画面で「設定」アイコン等を押してしまう。
        # 4つ目は絞り込む前の全ノード。ランチャー等が重なっていないかを
        # 座標で確かめるために必要（_blocking_overlay_at 参照）。
        return chat_texts, out_of_bounds_texts, app_nodes, nodes

    # 入力欄とみなす最低幅（画面幅に対する割合）。
    # ⚠️ これが無いと、アイコン（幅100px前後）と入力欄（画面の大半を占める）を区別できず、
    # 「設定」「ギャラリー」などのアイコンをタップして別のアプリを開いてしまう。
    MIN_INPUT_WIDTH_RATIO = 0.3

    def _blocking_overlay_at(self, all_nodes, x, y):
        """
        指定した座標に、対象アプリ以外の押せる部品が重なっていないか調べる。
        重なっていればそのラベルを返す（タップしてはいけない座標）。

        ⚠️ 呼び出し側は、対象アプリと同じディスプレイのノードだけを渡すこと。
        MuMuは画面を4枚（mumuscreen000〜003）同時に動かしており、
        画面ダンプには全ディスプレイのウィンドウが1つの木にまとめて入る。
        どれも720x1280なので座標が偶然重なり、別ディスプレイのランチャーの
        設定アイコン[146,1158][253,1260]がGRAVITYの入力欄(中心173,1209)と
        必ず重なって見える。ディスプレイで絞らずにここへ渡すと、
        正常時でも永久にタップできなくなる。
        """
        for node in all_nodes:
            if not self._is_background_noise_node(node):
                continue
            if not self.re_clickable.search(node):
                continue
            b_match = self.re_bounds.search(node)
            if not b_match:
                continue
            left, top, right, bottom = map(int, b_match.groups())
            if left <= x <= right and top <= y <= bottom:
                return self._node_label(node) or "(名前なし)"
        return ""

    def _find_and_tap_input(self, d, nodes, half_y, all_nodes=None):
        target_x, target_y = None, None
        # 重なり判定には、絞り込む前の全ノードが要る（ランチャー等も見るため）
        all_nodes = all_nodes if all_nodes is not None else nodes

        # ⚠️ 監視対象アプリ以外の部品は絶対に触らない。
        # 画面ダンプにはMuMuのランチャーやステータスバーも含まれており、
        # 除外しないとランチャーの「設定」アイコンなどをタップして
        # 関係のないアプリを勝手に開いてしまう。
        nodes = [n for n in nodes if not self._is_background_noise_node(n)]

        try:
            screen_width = d.window_size()[0] or 0
        except Exception:
            screen_width = 0
        min_width = screen_width * self.MIN_INPUT_WIDTH_RATIO

        for node in nodes:
            t_match = self.re_text.search(node)
            d_match = self.re_desc.search(node)
            b_match = self.re_bounds.search(node)
            if b_match:
                left, top, right, bottom = map(int, b_match.groups())
                if bottom > half_y:
                    t_val = (t_match.group(1) if t_match else "") + (d_match.group(1) if d_match else "")
                    if any(ph in t_val for ph in ["メッセージ", "チャット", "入力", "タップ", "Tap", "一緒に", "コメント", "話そう", "発言"]):
                        target_x, target_y = (left + right) / 2, (top + bottom) / 2
                        self.log(f"👆 画面下部の入力ボタン(「{html.unescape(t_val)[:10]}」)をタップしました。")
                        break

        if not target_x:
            for node in nodes:
                c_match = self.re_class.search(node)
                b_match = self.re_bounds.search(node)
                if c_match and "EditText" in c_match.group(1) and b_match:
                    left, top, right, bottom = map(int, b_match.groups())
                    if bottom > half_y:
                        target_x, target_y = (left + right) / 2, (top + bottom) / 2
                        self.log("👆 画面下部のテキスト入力欄(EditText)をタップしました。")
                        break

        if not target_x:
            # 最後の手段。ここが一番誤爆しやすいので、横に長い要素だけに絞る。
            # 入力欄は画面の大半を占めるのに対し、アイコンやボタンは小さい。
            for node in nodes:
                c_match = self.re_class.search(node)
                cl_match = self.re_clickable.search(node)
                b_match = self.re_bounds.search(node)
                if c_match and "TextView" in c_match.group(1) and cl_match and b_match:
                    left, top, right, bottom = map(int, b_match.groups())
                    if bottom > half_y and (right - left) >= min_width:
                        target_x, target_y = (left + right) / 2, (top + bottom) / 2
                        label = self._node_label(node)
                        self.log(f"👆 画面下部のクリック可能な枠(「{label[:10]}」幅{right - left})をタップしました。")
                        break

        if target_x and target_y:
            blocker = self._blocking_overlay_at(all_nodes, target_x, target_y)
            if blocker:
                self.log(f"🛑 入力欄({int(target_x)},{int(target_y)})に別アプリの「{blocker}」が重なっています。"
                         "押すと関係のないアプリが開くため、タップを中止しました。")
                self.log("💡 対象アプリが実際に画面に表示されているか確認してください"
                         "（前面と報告されていても、ホーム画面が表示されたままのことがあります）。")
                return False
            if not self._tap(d, target_x, target_y):
                # 送れなかったのに成功と答えると、この後の入力が宙に浮く
                return False
            self._check_after_action(d, f"入力欄をタップ({int(target_x)},{int(target_y)})")
            return True

        self.log("⚠️ 入力欄が見つかりませんでした。誤って別のものをタップしないよう、何もしません。")
        return False

    def _is_ime_node(self, node):
        """uiautomator2の入力補助バー(Switch IME / Send / Clear Text)の部品かどうか"""
        p_match = self.re_package.search(node)
        return bool(p_match and p_match.group(1).startswith(UIAUTOMATOR_IME_PACKAGE))

    def _node_label(self, node):
        """要素の表示文字（text と content-desc）を、XMLのエスケープを戻して返す"""
        t_match = self.re_text.search(node)
        d_match = self.re_desc.search(node)
        label = (t_match.group(1) if t_match else "") + (d_match.group(1) if d_match else "")
        return html.unescape(label).strip()

    @staticmethod
    def _normalize_for_compare(text):
        """
        「入力欄に入った文字」と「入れようとした文字」を見比べるための正規化。

        ⚠️ 改行と空白は消してから比べること。アプリ側の入力欄が1行用だと、
        入れた改行が勝手に捨てられたり空白に変わったりする。そのまま比べると
        「入らなかった」と誤判定し、直接入力でもう一度打ち込んで文字が二重になる。
        """
        return re.sub(r"\s+", "", text or "")

    def _input_text_matches(self, d, expected):
        """入力欄に expected の書き出しが入っているか（改行・空白の違いは無視する）"""
        head = self._normalize_for_compare(expected[:15])
        if not head:
            # 空白だけの文字列は比べようがない。入った扱いにして先へ進める
            return True
        return head in self._normalize_for_compare(self._current_input_text(d))

    def _current_input_text(self, d):
        """入力欄(EditText)に今入っている文字を返す。見つからない・空なら空文字。"""
        try:
            xml = d.dump_hierarchy(compressed=True)
        except Exception:
            return ""
        for node in self._same_display_nodes(xml):
            if self._is_ime_node(node):
                continue
            c_match = self.re_class.search(node)
            if not (c_match and "EditText" in c_match.group(1)):
                continue
            t_match = self.re_text.search(node)
            if t_match:
                return html.unescape(t_match.group(1))
        return ""

    def _fill_reply_text(self, d, reply_message):
        """
        返信ワードを入力欄に入れる。

        本命はクリップボード経由の貼り付け。日本語をIMEで1文字ずつ送るより速く、
        変換の途中状態が残らないため確実に狙った文字列が入る。
        ただし機種やアプリによっては貼り付けキーを受け付けないことがあるので、
        画面を見て入ったか確かめ、駄目なら従来どおりの直接入力に切り替える。
        """
        # 一度でも貼り付けが使えないと分かった端末では、以降は試さない。
        # Android 10以降はクリップボードへの書き込みが前面アプリ等に制限されており、
        # uiautomator2の常駐サービス(shell権限)からは SecurityException で必ず失敗する。
        # 毎回試すと1回あたり約1秒を捨てるうえ、長大な例外がログを埋めてしまう。
        if not self._clipboard_paste_available:
            return self._type_reply_text(d, reply_message)

        try:
            d.set_clipboard(reply_message, label="auto_reply")
            time.sleep(0.3)
            self._keyevent(d, ANDROID_KEYCODE_PASTE)
            time.sleep(0.6)
            # 長文は折り返しや省略が起きうるので、先頭部分が入っていれば成功とみなす
            if self._input_text_matches(d, reply_message):
                self.log("📋 返信ワードを貼り付けました。")
                return True
            self._clipboard_paste_available = False
            self.log("⚠️ 貼り付けが反映されなかったため、以降は直接入力で送信します。")
        except Exception as e:
            self._clipboard_paste_available = False
            reason = str(e)
            if "SecurityException" in reason:
                # 端末側の仕様による制限。原因が伝わる一行にまとめる
                reason = "Androidのセキュリティ制限でクリップボードに書き込めません"
            else:
                reason = reason.split("\n")[0][:120]
            self.log(f"ℹ️ このエミュレータでは貼り付けが使えません（{reason}）。以降は直接入力で送信します。")

        return self._type_reply_text(d, reply_message)

    def _type_reply_text(self, d, reply_message):
        """IME経由で直接入力する（貼り付けが使えない端末での本命の入力方法）"""
        try:
            d.send_keys(reply_message)
            time.sleep(0.4)
            self.log("⌨️ キーボード経由で文字を入力しました。")
            return True
        except Exception as e:
            self.log(f"❌ 返信ワードを入力できませんでした: {str(e).split(chr(10))[0][:120]}")
            return False

    def _tap_send_button(self, d):
        """
        アプリ側の「送る」ボタンを探してタップする。

        ⚠️ 2つの引っかけがあるので注意すること。
        　1) uiautomator2の入力補助バーにも「Send」ボタンがあるので除外する
        　2) 入力欄の案内文が「メッセージを送信」なので、「送信」の部分一致だけで探すと
        　   送信ボタンのつもりで入力欄を押してしまう。まず完全一致で探す。
        """
        try:
            xml = d.dump_hierarchy(compressed=True)
        except Exception as e:
            self.log(f"⚠️ 送信ボタンを探せませんでした: {e}")
            return False

        exact_hit, partial_hit = None, None
        for node in self._same_display_nodes(xml):
            # 入力欄の探索と同じく、監視対象アプリ以外の部品には触らない
            if self._is_background_noise_node(node):
                continue
            b_match = self.re_bounds.search(node)
            if not b_match:
                continue
            c_match = self.re_class.search(node)
            if c_match and "EditText" in c_match.group(1):
                continue      # 入力欄そのものは送信ボタンではない

            label = self._node_label(node)
            if not label:
                continue
            bounds = tuple(map(int, b_match.groups()))

            if label in SEND_BUTTON_EXACT_LABELS:
                exact_hit = (label, bounds)
                break
            if (partial_hit is None
                    and any(k in label for k in SEND_BUTTON_PARTIAL_LABELS)
                    and not any(ng in label for ng in SEND_BUTTON_EXCLUDE_WORDS)):
                partial_hit = (label, bounds)

        hit = exact_hit or partial_hit
        if not hit:
            # 見つからない理由を追えるよう、画面に何があったかを残す。
            # 「送信ボタンが無い」のか「別の名前だった」のかを切り分けるため。
            candidates = []
            for node in self._same_display_nodes(xml):
                if self._is_background_noise_node(node):
                    continue
                if not self.re_clickable.search(node):
                    continue
                label = self._node_label(node)
                if label:
                    candidates.append(label[:12])
            if candidates:
                self.log(f"🔎 送信ボタンが見つかりません。画面の押せる要素: {' / '.join(candidates[:10])}")
            else:
                self.log("🔎 送信ボタンが見つかりません。押せる要素が1つもありませんでした。")
            return False

        label, (left, top, right, bottom) = hit
        cx, cy = (left + right) / 2, (top + bottom) / 2
        blocker = self._blocking_overlay_at(self._same_display_nodes(xml), cx, cy)
        if blocker:
            self.log(f"🛑 送信ボタン({int(cx)},{int(cy)})に別アプリの「{blocker}」が重なっています。"
                     "タップを中止しました。")
            return False
        if not self._tap(d, cx, cy):
            return False
        self.log(f"👆 送信ボタン(「{label[:10]}」)をタップしました。")
        self._check_after_action(d, f"送信ボタン「{label[:10]}」をタップ")
        return True

    def _send_reply(self, d, reply_message):
        """入力欄に返信ワードを入れて送信する（入力欄は呼び出し側でタップ済み）"""
        try:
            d.clear_text()
            time.sleep(0.2)
        except Exception:
            pass

        if not self._fill_reply_text(d, reply_message):
            return False

        time.sleep(0.4)
        is_sent = self._tap_send_button(d)

        if not is_sent:
            # 送信ボタンが見当たらないレイアウト向けの保険。
            # 先にEnterを打たないのは、Enterで送信された直後だとボタンが消えてしまい
            # 「送信ボタンが無い＝失敗」と誤判定されるため。
            #
            # 成否は「入力欄が空か」ではなく「入れた文字が消えたか」で判断する。
            # このアプリは空のとき案内文「メッセージを送信」が入力欄の文字として出るため、
            # 空判定にすると送信できていても失敗扱いになってしまう。
            self._keyevent(d, ANDROID_KEYCODE_ENTER)
            time.sleep(0.6)
            self._check_after_action(d, "エンターキー")
            if not self._input_text_matches(d, reply_message):
                is_sent = True
                self.log("↩️ 送信ボタンが見つからないため、エンターキーで送信しました。")

        if is_sent:
            self.log(f" ✉️ 「{reply_message}」を送信しました。")
        else:
            self.log(f"⚠️ 「{reply_message}」を送信できませんでした。入力欄に文字が残っている可能性があります。")

        time.sleep(1.0)
        self._close_keyboard_if_open(d)
        return is_sent

    def _is_keyboard_shown(self, d):
        """
        ソフトキーボードが表示されているかを調べる。
        判断できない場合はFalse（＝BACKを押さない）にして、安全側に倒す。
        """
        try:
            output = d.shell("dumpsys input_method").output
        except Exception:
            return False
        for line in output.splitlines():
            if "mInputShown" in line:
                return "mInputShown=true" in line.replace(" ", "")
        return False

    def _close_keyboard_if_open(self, d):
        """
        キーボードが出ているときだけBACKで閉じる。

        ⚠️ 無条件にBACKを押してはいけない。
        エンターキーで送信した直後はキーボードが既に閉じているため、
        そのBACKはアプリの「戻る」として働き、チャット画面がルートだと
        ホーム画面まで戻ってしまう（＝以後まったく送信できなくなる）。
        """
        if not self._is_keyboard_shown(d):
            self.log("🔽 キーボードは閉じています（BACKは押しません）。")
            return
        self._keyevent(d, ANDROID_KEYCODE_BACK)
        time.sleep(0.3)
        self.log("🔽 キーボードを閉じて待機状態に戻りました。")
        self._check_after_action(d, "BACKキー")

    def _scroll_down(self, d, y_min, y_max, silent=False):
        # エミュレータ自動スクロールがオフの場合は一切スクロールしない（定期分・送信直後分の両方）
        if self.db.get_setting("emulator_auto_scroll", "1") != "1":
            return

        width, height = d.window_size()
        center_x = width // 2

        margin = (y_max - y_min) * 0.2
        start_y = int(y_max - margin)
        end_y = int(y_min + margin)

        if start_y > end_y + 50:
            if not silent:
                self.log("⏬ 画面をスクロールして最新を表示します...")
            try:
                self._swipe(d, center_x, start_y, center_x, end_y, duration_ms=200)
            except Exception as e:
                # スクロールは補助的な操作なので、失敗しても監視自体は続行する。
                # 特にエミュレータで別アプリのウインドウが前面に出ていると
                # 「Injecting to another application requires INJECT_EVENTS permission」
                # (SecurityException) が出るが、これは一時的で監視の続行には支障がない。
                # 以前はこの例外がループのエラー処理まで伝播し、接続断と誤判定されて
                # 毎回フル再接続が走っていた。
                if not silent:
                    self.log(f"⚠️ 画面のスクロールに失敗しました（監視は継続します）: {str(e)[:80]}")
                return
            time.sleep(0.5)
            # 別アプリへ切り替わったかの確認は、silentでも必ず行う。
            # 3秒ごとのこのスクロールが一番回数の多い操作であり、ここを黙らせると
            # 「いつの間にか設定アプリ/ホーム画面」の犯人を名指しできなくなる。
            self._check_after_action(d, "スクロール")

    def _get_cooldown_settings(self):
        """クールダウン機能のオンオフと秒数をDBから取得する"""
        enabled = self.db.get_setting("cooldown_enabled", "1") == "1"
        try:
            seconds = float(normalize_number_text(self.db.get_setting("cooldown_seconds", "10")))
            if seconds < 0:
                seconds = 0.0
        except (TypeError, ValueError):
            seconds = 10.0
        return enabled, seconds

    def _get_runtime_config(self):
        """
        監視ループが毎周回で必要とする「有効キーワード」と「クールダウン設定」をまとめて返す。
        ループは0.3秒間隔で回るため毎回DBに接続すると無駄が大きい。
        CONFIG_CACHE_SECONDSの間はキャッシュを使い回す（設定変更の反映がその分だけ遅れる）。
        """
        now = time.time()
        if self._config_cache is not None and (now - self._config_cache_time) < self.CONFIG_CACHE_SECONDS:
            return self._config_cache

        keywords_map = self.db.get_active_keywords()
        cooldown_enabled, cooldown_seconds = self._get_cooldown_settings()

        # ログのマスク対象外にする語を更新する。
        # 長い語から順に見て、部分一致で短い語が先に当たらないようにする。
        self._log_keep_words = sorted(
            set(keywords_map.keys()) | set(keywords_map.values()),
            key=len, reverse=True
        )

        self._config_cache = (keywords_map, cooldown_enabled, cooldown_seconds)
        self._config_cache_time = now
        return self._config_cache

    def _execute_reply(self, d, nodes, half_y, y_min_internal, y_max_internal, reply_message,
                       failure_count, FAILURE_WARN_THRESHOLD, all_nodes=None):
        """
        入力欄タップ〜送信〜スクロールまでを実行し、(更新後のfailure_count, 送信できたか) を返す。

        送信できたかを呼び出し側に返すのは、同じメッセージへの二重送信を防ぐため。
        成功した行はもう返信済みとして扱い、失敗した行だけ再挑戦させる。
        """
        sent_ok = False
        if self._find_and_tap_input(d, nodes, half_y, all_nodes=all_nodes):
            time.sleep(1.0)
            sent_ok = self._send_reply(d, reply_message)

            if sent_ok:
                failure_count = 0
            else:
                failure_count += 1
                self.log(f"⚠️ 送信ボタンが見つからず失敗としてカウントしました。(連続失敗 {failure_count}回)")

            # 送信の流れで対象アプリが背面に落ちてしまった場合は戻す。
            # 放置すると以後ずっと画面が読めず、何も反応しなくなる。
            self._restore_target_app_if_left(d)

            self._scroll_down(d, y_min_internal, y_max_internal, silent=False)
        else:
            failure_count += 1
            self.log(f"⚠️ 入力欄(EditTextやプレースホルダー)が見つからなかったため、返信をスキップしました。(連続失敗 {failure_count}回)")

        if failure_count >= FAILURE_WARN_THRESHOLD:
            self.log(f"🚨 入力欄・送信ボタンの検出に {failure_count}回連続で失敗しています。アプリのUIレイアウトが変わっていないか確認してください。")
            failure_count = 0

        return failure_count, sent_ok

    def _drain_manual_sends(self, d, nodes, half_y, y_min_internal, y_max_internal,
                            failure_count, FAILURE_WARN_THRESHOLD, all_nodes=None):
        """
        手入力送信の待ち行列を、積まれた順に送り切る。
        戻り値: (更新後のfailure_count, 1件でも送ったか)

        ⚠️ 1件送るごとに画面を読み直すこと。nodes（入力欄や送信ボタンの位置）は
        送信した瞬間に古くなるため、2件目を古いnodesのまま送ると座標を外す。
        """
        sent_any = False
        while self.is_running:
            with self._manual_lock:
                if not self._manual_queue:
                    break
                text = self._manual_queue.pop(0)
                # 送る前に覚える。送信後に覚えると、その間に監視ループが1周して
                # 自分の発言へ自動返信してしまう隙ができる。
                self._recent_manual_texts.append(text)
                while len(self._recent_manual_texts) > self.MAX_RECENT_MANUAL_TEXTS:
                    self._recent_manual_texts.pop(0)

            self.log(f"✍️ 手入力送信します:「{text}」")
            failure_count, sent_ok = self._execute_reply(
                d, nodes, half_y, y_min_internal, y_max_internal, text,
                failure_count, FAILURE_WARN_THRESHOLD, all_nodes=all_nodes
            )
            sent_any = True
            if not sent_ok:
                self.log("⚠️ 手入力送信に失敗しました。入力欄に文字が残っていないか確認してください。")

            with self._manual_lock:
                more = bool(self._manual_queue)
            if not more:
                break

            # 次の1件のために画面を取り直す
            try:
                xml_dump = d.dump_hierarchy(compressed=True)
                self._update_target_display(xml_dump)
                _, _, nodes, all_nodes = self._extract_chat_texts(
                    xml_dump, y_min_internal, y_max_internal)
            except Exception as e:
                self.log(f"⚠️ 画面を読み直せなかったため、残りの手入力は次の周回で送ります: {e}")
                break
            time.sleep(0.5)

        return failure_count, sent_any

    # --- メインループ ---
    def _monitor_loop(self, screen_x1, screen_y1, screen_x2, screen_y2):
        # 準備段階(接続・監視範囲の計算)で例外が起きた場合もfinallyを必ず通すため、
        # 処理全体をtryで囲む。以前は準備段階が外に出ており、ここで例外が起きると
        # スレッドだけが静かに死に、is_runningがTrueのまま残ってUIが「実行中」で固まっていた。
        try:
            self._run_monitor(screen_x1, screen_y1, screen_x2, screen_y2)
        except Exception as e:
            self.log(f"❌ 監視処理が予期しないエラーで停止しました: {e}")
            write_error_log(f"監視スレッドの異常終了: {traceback.format_exc()}")
        finally:
            self.log("🛑 ツールを停止しました。")
            self.is_running = False

    def _run_monitor(self, screen_x1, screen_y1, screen_x2, screen_y2):
        # 前回の監視で覚えたディスプレイ番号は持ち越さない。
        # 対象アプリを変えた場合や、まだ起動しきっていない場合に、
        # 古い画面を相手にしてしまうため。
        self._target_display = None
        try:
            d = self._connect_to_emulator()
        except Exception as e:
            self.log(f"❌ エミュレータ接続エラー: {e}")
            return

        try:
            y_min_internal, y_max_internal, w_height = self._calculate_y_bounds(d, screen_y1, screen_y2)
        except Exception as e:
            self.log(f"❌ 監視範囲の計算に失敗しました: {e}")
            self.log("💡 エミュレータのウインドウが最小化・非表示になっていないか確認してください。")
            return

        half_y = w_height / 2

        self._warn_if_target_app_not_foreground(d)
        self._log_active_keywords()
        self._perform_initial_scan(d, y_min_internal, y_max_internal)
        self.log(" 監視を開始しました... (■ 停止ボタンで終了)")

        last_processed_logs = {}
        # 返信済みのメッセージ本文。画面に残り続ける行へ二重に返信しないための記録。
        # 挿入順を保つdictなので、増えすぎたら古い方から捨てられる。
        replied_logs = {}
        out_of_bounds_warned = {}
        error_count = 0
        reconnect_attempts = 0
        MAX_RECONNECT_ATTEMPTS = 3

        # トリガーごとに「最後に実際に送信した時刻」を記録し、クールダウン設定が有効な場合、
        # 同じトリガーの連続検知が設定秒数未満の間隔になる場合は送信を遅らせる（キューイング）
        last_sent_time = {}
        # 遅延待ち中のトリガー: {trigger_word: (latest_log, reply_message)}
        pending_sends = {}

        # 「入力欄が見つからない」「送信ボタンが見つからない」といった、例外にはならないが
        # 実質的に失敗している操作をカウントする（UI変化やレイアウト崩れの早期発見用）
        failure_count = 0
        FAILURE_WARN_THRESHOLD = 5

        self._last_seen_any_chat = ""

        SCROLL_INTERVAL = 3.0
        last_scroll_time = time.time()

        # 接続断らしきエラーかどうかを文字列で簡易判定するためのキーワード
        CONNECTION_ERROR_HINTS = [
            "connection", "connect", "timeout", "timed out", "refused",
            "closed", "adb", "device", "socket", "broken pipe", "not found"
        ]

        # 上のキーワードに引っかかるが、実際には接続断ではないエラー。
        # 例: swipe失敗時のSecurityExceptionはスタックトレースに "UiDevice.swipe" を含むため
        # "device" に一致してしまい、接続は正常なのに毎回フル再接続が走っていた。
        # こちらを先に判定し、該当する場合は再接続の対象外にする。
        NOT_CONNECTION_ERROR_HINTS = [
            "securityexception", "inject_events", "permission",
            "illegalargumentexception", "nullpointerexception",
        ]

        while self.is_running:
            try:
                # 有効なセットのみ。短時間キャッシュしつつ再読み込みして設定変更に追従する
                keywords_map, cooldown_enabled, cooldown_seconds = self._get_runtime_config()

                xml_dump = d.dump_hierarchy(compressed=True)
                # 対象アプリがどのディスプレイに出ているかを毎回確かめる。
                # MuMuは複数画面を同時に動かすため、ここを間違えると
                # 読み取りはできるのに操作だけ別の画面へ届く。
                self._update_target_display(xml_dump)
                chat_texts, out_of_bounds_texts, nodes, all_nodes = self._extract_chat_texts(
                    xml_dump, y_min_internal, y_max_internal)

                # ダイアログはチャットを覆い隠すので、検知より先に片付ける。
                # 押したら画面が変わるため、次の周回で取り直す。
                if self._auto_dismiss_dialog(d, all_nodes, xml_dump):
                    time.sleep(0.6)
                    continue

                # 手入力送信の待ちがあれば、キーワード判定より先に送る。
                # 人がいま送ろうとしている文を後回しにすると、会話の順序が入れ替わる。
                if self.has_manual_pending():
                    failure_count, manual_sent = self._drain_manual_sends(
                        d, nodes, half_y, y_min_internal, y_max_internal,
                        failure_count, FAILURE_WARN_THRESHOLD, all_nodes=all_nodes
                    )
                    if manual_sent:
                        last_scroll_time = time.time()
                        # 送信で画面が変わっている。古い読み取り結果のまま
                        # キーワード判定へ進まず、次の周回で取り直す。
                        continue

                chat_texts = [item for item in chat_texts if not any(ignore in item[0] for ignore in IGNORE_WORDS)]
                out_of_bounds_texts = [t for t in out_of_bounds_texts if not any(ignore in t for ignore in IGNORE_WORDS)]

                # 画面から流れて消えた行は「返信済み」の記録から外す。
                # 同じ人が入り直した時に、文面が同じというだけで
                # 二度と返信できなくなるのを防ぐ。
                self._forget_replied_off_screen(replied_logs, chat_texts)

                # 検知ワードの有無を素早く判定するための検索用文字列。
                # 生のXMLではなく、エスケープを戻した後のテキストを使う。
                detected_texts_joined = "\n".join([t for t, _ in chat_texts] + out_of_bounds_texts)

                if chat_texts:
                    current_latest = max(chat_texts, key=lambda x: x[1])[0]
                    if current_latest != self._last_seen_any_chat:
                        is_own_reply = any(reply in current_latest for reply in keywords_map.values())
                        if not is_own_reply:
                            # 「検知」だと検知ワードに一致したように読めてしまうため、
                            # 単に画面が変わっただけであることが分かる文言にしている。
                            # 実際に一致したときは「🎯 検知!【ワード】」が出る。
                            self.log(f"👀 画面の文字を読み取りました:「{current_latest}」")
                        self._last_seen_any_chat = current_latest

                # キーワード自動返信をOFFにした（または有効な検知ワードが無くなった）場合、
                # 待機中だった送信も取り消す。「OFFにしたのに少し後から送られた」を防ぐ。
                if not keywords_map and pending_sends:
                    self.log(f"⏸️ 有効な検知ワードが無くなったため、待機中だった送信{len(pending_sends)}件を取り消しました。")
                    pending_sends.clear()

                # 遅延待ち（クールダウン）中の送信をチェックする。
                # 機能がオフになった場合は待機させず、たまっているものを即座に送信する。
                for trigger_word in list(pending_sends.keys()):
                    if not self.is_running:
                        break
                    sent_at = last_sent_time.get(trigger_word, 0)
                    if (not cooldown_enabled) or (time.time() - sent_at >= cooldown_seconds):
                        latest_log, reply_message = pending_sends.pop(trigger_word)
                        if cooldown_enabled:
                            self.log(f"⏰ クールダウン({cooldown_seconds:.0f}秒)が経過したため送信します。【{trigger_word}】ログ:「{latest_log}」")
                        else:
                            self.log(f"⏰ クールダウンがOFFになったため、待機中だった送信を実行します。【{trigger_word}】ログ:「{latest_log}」")
                        failure_count, sent_ok = self._execute_reply(
                            d, nodes, half_y,
                            y_min_internal, y_max_internal, reply_message,
                            failure_count, FAILURE_WARN_THRESHOLD, all_nodes=all_nodes
                        )
                        if sent_ok:
                            self._remember_replied(replied_logs, latest_log)
                        last_sent_time[trigger_word] = time.time()
                        last_scroll_time = time.time()
                        last_processed_logs[trigger_word] = (latest_log, time.time())
                        time.sleep(1)

                for trigger_word, reply_message in list(keywords_map.items()):
                    if not self.is_running:
                        break

                    if trigger_word not in detected_texts_joined:
                        continue

                    # ⚠️ 既にクールダウン待ちの行があるトリガーは、今回は触らない。
                    # 待ち行列は1トリガーにつき1件しか持てないため、ここで次の行を
                    # 拾うと待機中の行を上書きしてしまい、古い人を追い越して
                    # 新しい人へ先に返信してしまう（「順番に送る」が崩れる）。
                    if trigger_word in pending_sends:
                        continue

                    matched_elements = [item for item in chat_texts if trigger_word in item[0]]

                    if not matched_elements:
                        out_of_bounds_matched = [t for t in out_of_bounds_texts if trigger_word in t]
                        if out_of_bounds_matched:
                            latest_out = out_of_bounds_matched[-1]
                            if out_of_bounds_warned.get(trigger_word) != latest_out:
                                self.log(f"⚠️ 【範囲外】で文字を検知しました:「{latest_out}」")
                                self.log("💡 監視範囲がズレているため無視されました。範囲を少し広めに選択し直してみてください。")
                                out_of_bounds_warned[trigger_word] = latest_out
                        continue

                    last_log, last_time = last_processed_logs.get(trigger_word, ("", 0))
                    pending = self._select_pending_replies(
                        matched_elements, replied_logs, reply_message, last_log, last_time)

                    if pending:
                        latest_log = pending[0][0]
                        self.log(f"🎯 検知!【{trigger_word}】ログ:「{latest_log}」")
                        if len(pending) > 1:
                            self.log(f"📥 未返信があと{len(pending) - 1}件あります。順番に処理します。")

                        # クールダウン機能が有効かつ、同じトリガーの前回送信から設定秒数経っていない場合は、
                        # 即座に送信せずキューに入れて後で送る（連続送信の抑制）
                        sent_at = last_sent_time.get(trigger_word)
                        elapsed = time.time() - sent_at if sent_at is not None else None

                        if cooldown_enabled and elapsed is not None and elapsed < cooldown_seconds:
                            remaining = cooldown_seconds - elapsed
                            pending_sends[trigger_word] = (latest_log, reply_message)
                            last_processed_logs[trigger_word] = (latest_log, time.time())
                            self.log(f"⏳ 前回送信から{elapsed:.1f}秒しか経っていないため、あと{remaining:.1f}秒待ってから送信します。")
                        else:
                            failure_count, sent_ok = self._execute_reply(
                                d, nodes, half_y, y_min_internal, y_max_internal,
                                reply_message, failure_count, FAILURE_WARN_THRESHOLD,
                                all_nodes=all_nodes
                            )
                            if sent_ok:
                                self._remember_replied(replied_logs, latest_log)
                            last_sent_time[trigger_word] = time.time()
                            last_scroll_time = time.time()
                            last_processed_logs[trigger_word] = (latest_log, time.time())
                            time.sleep(1)

                # 対象アプリが前面から外れていないか、ときどき見張る。
                # 外れたままだと画面が読めず、検知も送信も静かに空振りし続けるため。
                self._watch_foreground_change(d)

                if time.time() - last_scroll_time > SCROLL_INTERVAL:
                    self._scroll_down(d, y_min_internal, y_max_internal, silent=True)
                    last_scroll_time = time.time()

                time.sleep(0.3)
                error_count = 0
                reconnect_attempts = 0

            except Exception as e:
                error_count += 1
                error_text = str(e).lower()
                looks_like_connection_error = (
                    any(hint in error_text for hint in CONNECTION_ERROR_HINTS)
                    and not any(hint in error_text for hint in NOT_CONNECTION_ERROR_HINTS)
                )

                self.log(f"❌ エラーが発生しました ({error_count}回目): {e}")

                if looks_like_connection_error and reconnect_attempts < MAX_RECONNECT_ATTEMPTS:
                    reconnect_attempts += 1
                    self.log(f"🔄 接続断の可能性があるため、再接続を試みます... ({reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS}回目)")
                    time.sleep(2)
                    try:
                        d = self._connect_to_emulator()
                        y_min_internal, y_max_internal, w_height = self._calculate_y_bounds(d, screen_y1, screen_y2)
                        half_y = w_height / 2
                        self.log("✅ 再接続に成功しました。監視を継続します。")
                        error_count = 0
                        continue
                    except Exception as reconnect_error:
                        self.log(f"❌ 再接続に失敗しました: {reconnect_error}")

                if error_count >= 5:
                    self.log("⚠️ 連続してエラーが発生したため、ツールを自動停止します。エミュレータとの接続状態を確認してください。")
                    self.is_running = False
                time.sleep(2)


# ====================================================
# 🖥️ 3. GUI (CustomTkinter)
# ====================================================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"自動返信Bot アプリケーション  (v{APP_VERSION})")
        self.geometry("800x650")
        ctk.set_appearance_mode("Dark")

        self.db = DatabaseManager()
        self.worker = AutoReplyWorker(self.db, self.append_log)
        self.updater = UpdateManager(self.db, self.append_log)

        # 自動アップデート用の状態。ダウンロードは1度に1つだけ走らせる
        self._update_staging_in_progress = False
        self._auto_update_after_id = None

        # 終了処理に入ったかどうか。繰り返し予約している処理を止めるのに使う
        self._closing = False
        self._pump_after_id = None

        # スマホ連携サーバー。UI構築時に状態を参照するため、先に作っておく
        self.phone_bridge = PhoneBridgeServer(
            self._on_phone_bridge_text, self.append_log,
            list_phrases=self._phone_bridge_phrases,
            save_phrase=self._on_phone_bridge_save_phrase,
            delete_phrase=self._on_phone_bridge_delete_phrase,
            analyze_text=self._on_phone_bridge_analyze,
            speak_query=self._on_phone_bridge_speak_query,
        )
        self._voicevox_process = None
        self._aivisspeech_process = None

        self.last_coords = self._load_last_coords()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.build_ui()
        self.append_log(f"[システム] アプリケーション起動 (v{APP_VERSION})")

        # 過去バージョンでたまった古いログを整理する（DBの肥大化対策）
        removed_logs = self.db.prune_logs()
        if removed_logs:
            self.append_log(f"🧹 古いログ{removed_logs}件を整理しました（最新{self.db.MAX_LOG_ROWS}件を保持）。")

        # 前回終了時に適用済みの準備物が残っていれば片付けてから、表示を最新にする
        if self.updater.read_pending_update() is None:
            self.updater.clear_pending_update()
        self._refresh_version_label()

        # 前回ONのままだった読み上げ関連の機能を復帰させる
        self.after(300, self._restore_speech_features)

        # 起動時に1回、以降はAUTO_UPDATE_CHECK_INTERVAL_HOURSごとに確認する
        # （バックグラウンド・失敗しても無視）
        self.after(1500, self._run_scheduled_update_check)

    def _restore_speech_features(self):
        """前回ONにしていたクリップボード監視・スマホ連携・VOICEVOX/AivisSpeech自動起動を再開する"""
        if self.db.get_setting("voicevox_autostart", "0") == "1":
            self.start_voicevox(silent=True)
        if self.db.get_setting("aivisspeech_autostart", "0") == "1":
            self.start_aivisspeech(silent=True)

        if self.clipboard_watch_var.get():
            self._clipboard_last_text = (self._read_clipboard_text() or "").strip()
            self._watch_clipboard()

        if self.phone_bridge_var.get():
            success, err = self.phone_bridge.start(self.get_phone_bridge_pin(), https=self.get_phone_bridge_https())
            if success:
                self.append_log(f"📱 スマホ連携を開始しました（{self.phone_bridge.get_url()}）。")
            else:
                self.phone_bridge_var.set(False)
                self.append_log(f"⚠️ スマホ連携を開始できませんでした: {err}")
            self._refresh_phone_bridge_info()

    # --- 座標の保存/読込 (settingsテーブルにJSON文字列で保持) ---
    def _load_last_coords(self):
        raw = self.db.get_setting("last_coords")
        if raw:
            try:
                coords = json.loads(raw)
                if isinstance(coords, list) and len(coords) == 4:
                    return tuple(coords)
            except Exception:
                pass
        return None

    def _save_last_coords(self, coords):
        self.db.save_setting("last_coords", json.dumps(list(coords)))

    # --- UI構築 ---
    def build_ui(self):
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_main = self.tabview.add("メイン")
        self.tab_keywords = self.tabview.add("キーワード設定")
        self.tab_timer = self.tabview.add("タイマー")
        self.tab_speech = self.tabview.add("読み上げ")
        self.tab_settings = self.tabview.add("設定")

        self.build_main_tab()
        self.build_keywords_tab()
        self.build_timer_tab()
        self.build_speech_tab()
        self.build_settings_tab()

    # --- メインタブ ---
    def build_main_tab(self):
        btn_frame = ctk.CTkFrame(self.tab_main, fg_color="transparent")
        btn_frame.pack(fill="x", pady=10)

        self.start_btn = ctk.CTkButton(
            btn_frame, text="▶ 範囲選択して開始", fg_color="#1f6aa5", hover_color="#144870",
            command=self.start_monitoring
        )
        self.start_btn.pack(side="left", padx=5, expand=True, fill="x")

        self.start_prev_btn = ctk.CTkButton(
            btn_frame, text="▶ 前回の範囲で開始", fg_color="green", hover_color="darkgreen",
            command=lambda: self.start_monitoring(use_last=True),
            state="normal" if self.last_coords else "disabled"
        )
        self.start_prev_btn.pack(side="left", padx=5, expand=True, fill="x")

        self.stop_btn = ctk.CTkButton(
            btn_frame, text="■ 停止", fg_color="red", hover_color="darkred",
            command=self.stop_monitoring, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=5, expand=True, fill="x")

        # スクロール系オプション（ログ表示欄／エミュレータ本体、それぞれ独立）
        scroll_opts_frame = ctk.CTkFrame(self.tab_main, fg_color="transparent")
        scroll_opts_frame.pack(anchor="e", padx=15, pady=(0, 5))

        self.auto_scroll_var = ctk.BooleanVar(value=True)
        self.auto_scroll_chk = ctk.CTkCheckBox(
            scroll_opts_frame, text="ログを自動スクロール", variable=self.auto_scroll_var
        )
        self.auto_scroll_chk.pack(side="left", padx=(0, 15))

        emulator_scroll_default = self.db.get_setting("emulator_auto_scroll", "1") == "1"
        self.emulator_auto_scroll_var = ctk.BooleanVar(value=emulator_scroll_default)
        self.emulator_auto_scroll_chk = ctk.CTkCheckBox(
            scroll_opts_frame, text="エミュレータを自動スクロール",
            variable=self.emulator_auto_scroll_var,
            command=self.on_emulator_auto_scroll_toggle
        )
        self.emulator_auto_scroll_chk.pack(side="left")

        # アップデート関連（バージョン表示 + 手動確認ボタン）
        update_frame = ctk.CTkFrame(self.tab_main, fg_color="transparent")
        update_frame.pack(fill="x", padx=15, pady=(0, 5))

        self.version_label = ctk.CTkLabel(update_frame, text=f"バージョン: v{APP_VERSION}", text_color="gray")
        self.version_label.pack(side="left")

        self.update_check_btn = ctk.CTkButton(
            update_frame, text="🔄 アップデート確認", width=140,
            fg_color="#555555", hover_color="#3a3a3a",
            command=lambda: self.check_for_updates(silent=False)
        )
        self.update_check_btn.pack(side="right")

        ctk.CTkButton(
            update_frame, text="📋 ログをコピー", width=130,
            fg_color="#555555", hover_color="#3a3a3a",
            command=self.copy_all_log
        ).pack(side="right", padx=(0, 5))

        self.log_textbox = ctk.CTkTextbox(self.tab_main, state="disabled")
        self.log_textbox.pack(fill="both", expand=True, padx=10, pady=10)

        # ログは読み取り専用なので、キーワード欄の右クリックメニュー（切り取り・貼り付けを含む）
        # ではなく、コピー用の専用メニューを用意する
        self.log_context_menu = tk.Menu(self, tearoff=0)
        self.log_context_menu.add_command(label="コピー", command=self.copy_log_selection)
        self.log_context_menu.add_command(label="すべて選択", command=self.select_all_log)
        self.log_context_menu.add_separator()
        self.log_context_menu.add_command(label="ログ全体をコピー", command=self.copy_all_log)
        self.log_context_menu.add_separator()
        self.log_context_menu.add_command(label="表示を消去", command=self.clear_log_display)

        self.log_textbox.bind("<Button-3>", self._show_log_context_menu)
        # TkのTextでは Ctrl+A が「行頭へ移動」なので、全選択として割り当て直す
        for seq in ("<Control-a>", "<Control-A>"):
            self.log_textbox.bind(seq, lambda e: (self.select_all_log(), "break")[1])

    # --- キーワード設定タブ ---
    def build_keywords_tab(self):
        # --- キーワード自動返信のON/OFF（このタブ全体の効き方を決める） ---
        # ⚠️ OFFにしてもセット/ペアごとの☑は書き換えない。OFFの間だけ
        # 「有効キーワードが0件」として扱うので、ONに戻せば以前の組み合わせが
        # そのまま復活する。フラグを直接消すと、戻すときに元の状態が分からなくなる。
        master_frame = ctk.CTkFrame(self.tab_keywords)
        master_frame.pack(fill="x", padx=10, pady=(10, 0))

        self.auto_reply_var = ctk.BooleanVar(
            value=self.db.get_setting(KEYWORD_AUTO_REPLY_SETTING, "1") == "1"
        )
        self.auto_reply_switch = ctk.CTkSwitch(
            master_frame, text="キーワード自動返信", variable=self.auto_reply_var,
            command=self.on_auto_reply_toggle
        )
        self.auto_reply_switch.pack(side="left", padx=10, pady=8)

        # スイッチが下の一覧にどう効くかは見ただけでは分からないため、言葉で添える
        self.auto_reply_hint = ctk.CTkLabel(master_frame, text="", text_color="gray")
        self.auto_reply_hint.pack(side="left", padx=(0, 10))
        self._refresh_auto_reply_hint()

        # --- セット選択・管理エリア ---
        set_frame = ctk.CTkFrame(self.tab_keywords, fg_color="transparent")
        set_frame.pack(fill="x", padx=10, pady=(5, 5))

        ctk.CTkLabel(set_frame, text="セット:").pack(side="left", padx=(0, 5))

        self.keyword_set_var = ctk.StringVar(value="")
        self.keyword_set_menu = ctk.CTkOptionMenu(
            set_frame, variable=self.keyword_set_var, values=[""],
            command=self.on_keyword_set_selected, width=200
        )
        self.keyword_set_menu.pack(side="left", padx=(0, 10))

        self.keyword_set_enabled_var = ctk.BooleanVar(value=True)
        self.keyword_set_enabled_chk = ctk.CTkCheckBox(
            set_frame, text="このセットを有効にする",
            variable=self.keyword_set_enabled_var,
            command=self.on_keyword_set_enabled_toggle
        )
        self.keyword_set_enabled_chk.pack(side="left", padx=(0, 15))

        ctk.CTkButton(set_frame, text="＋新規", width=70,
                      command=self.create_new_keyword_set).pack(side="left", padx=3)
        ctk.CTkButton(set_frame, text="✏️名前変更", width=90,
                      command=self.rename_current_keyword_set).pack(side="left", padx=3)
        ctk.CTkButton(set_frame, text="🗑️セット削除", width=100, fg_color="red", hover_color="darkred",
                      command=self.delete_current_keyword_set).pack(side="left", padx=3)

        ctk.CTkLabel(
            self.tab_keywords,
            text="選択中のセット内で、検知ワードと返信ワードのペアを一覧から選択するか、新しく入力して追加してください。\n"
                 "ペアをダブルクリック（または下の「有効/無効 切替」ボタン）で、ペアごとに動作のオン(☑)／オフ(☐)を切り替えられます。",
        ).pack(pady=(5, 5))

        list_frame = ctk.CTkFrame(self.tab_keywords)
        list_frame.pack(padx=10, pady=5, fill="both", expand=True)

        # CTkにはリストボックスが無いため、標準tkinter Listboxを埋め込む。
        # exportselection=False: 既定のままだと、下の検知ワード欄・返信ワード欄で文字を選択した
        # 瞬間にこの一覧の選択が外れてしまう（Tkは選択をアプリ内で1つしか保持しないため）。
        # ペアを選んでから返信ワードをコピーし、そのあと「削除」を押すと
        # 「未選択です」と言われる、という分かりにくい挙動になっていた。
        self.keyword_listbox = tk.Listbox(list_frame, font=("", 11), bg="#2b2b2b", fg="#dce4ee",
                                           selectbackground="#1f6aa5", highlightthickness=0, bd=0,
                                           exportselection=False)
        y_scroll = tk.Scrollbar(list_frame, command=self.keyword_listbox.yview)
        self.keyword_listbox.config(yscrollcommand=y_scroll.set)
        y_scroll.pack(side="right", fill="y")
        self.keyword_listbox.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)
        self.keyword_listbox.bind("<<ListboxSelect>>", self.on_keyword_select)
        self.keyword_listbox.bind("<Double-Button-1>", self.toggle_selected_keyword_enabled)

        edit_frame = ctk.CTkFrame(self.tab_keywords, fg_color="transparent")
        edit_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(edit_frame, text="検知ワード:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.trigger_entry = ctk.CTkEntry(edit_frame, width=300)
        self.trigger_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ctk.CTkLabel(edit_frame, text="返信ワード:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.reply_entry = ctk.CTkEntry(edit_frame, width=420)
        self.reply_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        # 検知ワード・返信ワード欄で、他アプリからコピーした文字列を貼り付けたり
        # 入力済みの文字列をコピーしたりできるよう、右クリックメニューを用意する
        self.entry_context_menu = tk.Menu(self, tearoff=0)
        self.entry_context_menu.add_command(label="切り取り", command=lambda: self._entry_menu_action("cut"))
        self.entry_context_menu.add_command(label="コピー", command=lambda: self._entry_menu_action("copy"))
        self.entry_context_menu.add_command(label="貼り付け", command=lambda: self._entry_menu_action("paste"))
        self.entry_context_menu.add_separator()
        self.entry_context_menu.add_command(label="全て選択", command=lambda: self._entry_menu_action("select_all"))

        for entry_widget in (self.trigger_entry, self.reply_entry):
            entry_widget.bind("<Button-3>", self._show_entry_context_menu)

        kw_btn_frame = ctk.CTkFrame(edit_frame, fg_color="transparent")
        kw_btn_frame.grid(row=2, column=1, pady=10, sticky="w")

        ctk.CTkButton(kw_btn_frame, text="➕ 追加 / 更新", command=self.add_or_update_keyword, width=120).pack(side="left", padx=5)
        ctk.CTkButton(kw_btn_frame, text="🔀 有効/無効 切替", command=self.toggle_selected_keyword_enabled,
                      width=140).pack(side="left", padx=5)
        ctk.CTkButton(kw_btn_frame, text="🗑️ 削除", fg_color="red", hover_color="darkred",
                      command=self.delete_keyword, width=80).pack(side="left", padx=5)

        # --- 手入力送信（Windowsでコピーした文をそのままエミュレータへ） ---
        # ⚠️ 自動返信のスイッチと同じタブに置いている。手で送る直前に自動返信を
        # 切る、という操作が必ずセットになるため、別タブに離すと片方を忘れて
        # 自分の発言と自動返信が混ざる。
        manual_frame = ctk.CTkFrame(self.tab_keywords)
        manual_frame.pack(fill="x", padx=10, pady=(0, 10))

        manual_header = ctk.CTkFrame(manual_frame, fg_color="transparent")
        manual_header.pack(fill="x", padx=8, pady=(6, 0))

        ctk.CTkLabel(
            manual_header, text="手入力送信", font=ctk.CTkFont(weight="bold")
        ).pack(side="left")

        self.manual_send_hint = ctk.CTkLabel(
            manual_header, text="監視を開始すると送れます。", text_color="gray"
        )
        self.manual_send_hint.pack(side="left", padx=(8, 0))

        self.manual_send_btn = ctk.CTkButton(
            manual_header, text="📨 送信 (Ctrl+Enter)", width=170,
            command=self.send_manual_text, state="disabled"
        )
        self.manual_send_btn.pack(side="right")

        self.manual_send_box = ctk.CTkTextbox(manual_frame, height=60)
        self.manual_send_box.pack(fill="x", padx=8, pady=(4, 8))
        self.manual_send_box.bind("<Button-3>", self._show_entry_context_menu)
        # Enterは改行に使うため、送信はCtrl+Enterに割り当てる
        for seq in ("<Control-Return>", "<Control-KP_Enter>"):
            self.manual_send_box.bind(seq, lambda e: (self.send_manual_text(), "break")[1])

        self.refresh_keyword_set_menu(select_set_id=None)

    # --- キーワードセット管理 ---
    def refresh_keyword_set_menu(self, select_set_id=None):
        """
        セット選択プルダウンの中身をDBの最新状態に合わせて更新する。
        select_set_idを指定すると、そのセットを選択状態にする（省略時は現在の選択を維持、それも無ければ先頭）。
        """
        sets = self.db.get_keyword_sets()
        self._keyword_sets_cache = sets  # 名前⇔id変換用に保持

        if not sets:
            # 万一セットが1つも無い状態（削除しすぎた等）になった場合はデフォルトを作り直す
            self.db.create_keyword_set("デフォルト")
            sets = self.db.get_keyword_sets()
            self._keyword_sets_cache = sets

        names = [s["name"] for s in sets]
        self.keyword_set_menu.configure(values=names)

        target_id = select_set_id
        if target_id is None:
            # 現在選択中のセット名がまだ存在するなら維持、無ければ先頭のセットにする
            current_name = self.keyword_set_var.get()
            current_set = next((s for s in sets if s["name"] == current_name), None)
            target_id = current_set["id"] if current_set else sets[0]["id"]

        target_set = next((s for s in sets if s["id"] == target_id), sets[0])
        self.keyword_set_var.set(target_set["name"])
        self.current_keyword_set_id = target_set["id"]
        self.keyword_set_enabled_var.set(target_set["enabled"])

        self.refresh_keyword_listbox()

    def on_keyword_set_selected(self, selected_name):
        selected_set = next((s for s in self._keyword_sets_cache if s["name"] == selected_name), None)
        if not selected_set:
            return
        self.current_keyword_set_id = selected_set["id"]
        self.keyword_set_enabled_var.set(selected_set["enabled"])
        self.trigger_entry.delete(0, tk.END)
        self.reply_entry.delete(0, tk.END)
        self.refresh_keyword_listbox()

    def on_keyword_set_enabled_toggle(self):
        enabled = self.keyword_set_enabled_var.get()
        success, err = self.db.set_keyword_set_enabled(self.current_keyword_set_id, enabled)
        if success:
            state_text = "有効" if enabled else "無効"
            set_name = self.keyword_set_var.get()
            self.append_log(f"⚙️ セット「{set_name}」を{state_text}にしました。")
            self.refresh_keyword_set_menu(select_set_id=self.current_keyword_set_id)
        else:
            messagebox.showerror("エラー", f"セットの有効/無効切り替えに失敗しました。\n\n詳細: {err}")

    def create_new_keyword_set(self):
        dialog = ctk.CTkInputDialog(text="新しいセットの名前を入力してください:", title="新規セット作成")
        name = dialog.get_input()
        if not name:
            return
        success, err, new_id = self.db.create_keyword_set(name)
        if success:
            self.append_log(f"✅ セット「{name.strip()}」を作成しました。")
            self.refresh_keyword_set_menu(select_set_id=new_id)
        else:
            messagebox.showerror("作成エラー", err)

    def rename_current_keyword_set(self):
        current_name = self.keyword_set_var.get()
        dialog = ctk.CTkInputDialog(text=f"「{current_name}」の新しい名前を入力してください:", title="セット名を変更")
        new_name = dialog.get_input()
        if not new_name:
            return
        success, err = self.db.rename_keyword_set(self.current_keyword_set_id, new_name)
        if success:
            self.append_log(f"✅ セット名を「{current_name}」→「{new_name.strip()}」に変更しました。")
            self.refresh_keyword_set_menu(select_set_id=self.current_keyword_set_id)
        else:
            messagebox.showerror("変更エラー", err)

    def delete_current_keyword_set(self):
        if len(self._keyword_sets_cache) <= 1:
            messagebox.showwarning("削除できません", "最後の1セットは削除できません。少なくとも1つのセットが必要です。")
            return

        current_name = self.keyword_set_var.get()
        keyword_count = len(self.db.get_keywords_in_set(self.current_keyword_set_id))
        if not messagebox.askyesno(
            "確認",
            f"セット「{current_name}」を削除します。\n"
            f"このセットに含まれるキーワード({keyword_count}件)も一緒に削除されます。\n\n"
            "よろしいですか？"
        ):
            return

        success, err = self.db.delete_keyword_set(self.current_keyword_set_id)
        if success:
            self.append_log(f"🗑️ セット「{current_name}」を削除しました。")
            self.refresh_keyword_set_menu(select_set_id=None)
        else:
            messagebox.showerror("削除エラー", err)

    def _show_entry_context_menu(self, event):
        # 右クリックされたウィジェットにフォーカスを移してから、そのウィジェットを対象にメニューを開く
        widget = event.widget
        widget.focus_set()
        self._entry_menu_target = widget
        self.entry_context_menu.tk_popup(event.x_root, event.y_root)

    def _entry_menu_action(self, action):
        widget = getattr(self, "_entry_menu_target", None)
        if widget is None:
            return
        try:
            if action == "cut":
                widget.event_generate("<<Cut>>")
            elif action == "copy":
                widget.event_generate("<<Copy>>")
            elif action == "paste":
                widget.event_generate("<<Paste>>")
            elif action == "select_all":
                # 読み上げ欄は複数行のText、キーワード欄は1行のEntryで、全選択の方法が違う
                if hasattr(widget, "tag_add") and hasattr(widget, "index"):
                    widget.tag_add("sel", "1.0", "end-1c")
                    widget.mark_set("insert", "end-1c")
                    return
                try:
                    widget.select_range(0, "end")
                    widget.icursor("end")
                except AttributeError:
                    # CTkEntryのバージョン差異で直接メソッドが無い場合、内部のtk.Entryを使う
                    inner_entry = getattr(widget, "_entry", None)
                    if inner_entry is not None:
                        inner_entry.select_range(0, "end")
                        inner_entry.icursor("end")
        except Exception:
            pass

    def _refresh_auto_reply_hint(self):
        """スイッチの効き方を言葉で添える（下の一覧との関係が見ただけでは分からないため）"""
        if self.auto_reply_var.get():
            self.auto_reply_hint.configure(
                text="☑ のペアが一致したら自動で返信します。")
        else:
            self.auto_reply_hint.configure(
                text="OFFの間は自動で返信しません（下の☑はそのまま保たれます）。")

    def on_auto_reply_toggle(self):
        """キーワード自動返信のON/OFF。監視は止めず、自動での送信だけを切る"""
        value = "1" if self.auto_reply_var.get() else "0"
        self.db.save_setting(KEYWORD_AUTO_REPLY_SETTING, value)
        self._refresh_auto_reply_hint()
        if value == "1":
            self.append_log("⚙️ キーワード自動返信を ON にしました。")
        else:
            self.append_log("⚙️ キーワード自動返信を OFF にしました。（画面の読み取りと手入力送信は続きます）")

    def send_manual_text(self):
        """入力欄の文字を、監視スレッド経由でエミュレータのアプリへ送る"""
        text = self.manual_send_box.get("1.0", "end-1c")
        accepted, message = self.worker.enqueue_manual_text(text)
        if accepted:
            # 受け付けられたときだけ消す。失敗時に消すと打ち直しになる
            self.manual_send_box.delete("1.0", "end")
            self.append_log(f"📨 {message}")
        else:
            self.append_log(f"⚠️ {message}")

    def _set_manual_send_enabled(self, enabled):
        """監視中だけ送信できるようにする（停止中はエミュレータへの経路が無い）"""
        self.manual_send_btn.configure(state="normal" if enabled else "disabled")
        self.manual_send_hint.configure(text="" if enabled else "監視を開始すると送れます。")

    def on_emulator_auto_scroll_toggle(self):
        value = "1" if self.emulator_auto_scroll_var.get() else "0"
        self.db.save_setting("emulator_auto_scroll", value)
        state_text = "ON" if value == "1" else "OFF"
        self.append_log(f"⚙️ エミュレータ自動スクロールを {state_text} に切り替えました。")

    # ====================================================
    # ⏱️ タイマー／アラーム機能
    # ====================================================
    def build_timer_tab(self):
        self.timer_running = False
        self.timer_end_time = None  # time.time()ベースの終了予定時刻（ずれ防止のため経過秒数のカウントではなくこちらを使う）
        self.timer_after_id = None
        self.timer_remaining_seconds = 0
        self.alarm_stop_flag = False

        # 保存したタイマー一覧を追加して縦に長くなったため、スクロールできるようにしておく
        # （ウィンドウを小さくしてもアラーム設定が画面外に隠れて操作できなくなることがない）
        frame = ctk.CTkScrollableFrame(self.tab_timer, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            frame, text="カウントダウンタイマー",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", pady=(0, 15))

        # 時間入力欄（時・分・秒）
        input_frame = ctk.CTkFrame(frame, fg_color="transparent")
        input_frame.pack(anchor="w", pady=(0, 15))

        # 過去バージョンで全角数字のまま保存された値が残っていることがあるため正規化して表示する
        saved_h = normalize_number_text(self.db.get_setting("timer_hours", "0")) or "0"
        saved_m = normalize_number_text(self.db.get_setting("timer_minutes", "10")) or "0"
        saved_s = normalize_number_text(self.db.get_setting("timer_seconds", "0")) or "0"

        self.timer_hour_entry = ctk.CTkEntry(input_frame, width=60, justify="center")
        self.timer_hour_entry.insert(0, saved_h)
        self.timer_hour_entry.pack(side="left")
        ctk.CTkLabel(input_frame, text="時間").pack(side="left", padx=(5, 15))

        self.timer_minute_entry = ctk.CTkEntry(input_frame, width=60, justify="center")
        self.timer_minute_entry.insert(0, saved_m)
        self.timer_minute_entry.pack(side="left")
        ctk.CTkLabel(input_frame, text="分").pack(side="left", padx=(5, 15))

        self.timer_second_entry = ctk.CTkEntry(input_frame, width=60, justify="center")
        self.timer_second_entry.insert(0, saved_s)
        self.timer_second_entry.pack(side="left")
        ctk.CTkLabel(input_frame, text="秒").pack(side="left", padx=(5, 0))

        # 残り時間の大きな表示
        self.timer_display_label = ctk.CTkLabel(
            frame, text="00:00:00",
            font=ctk.CTkFont(size=48, weight="bold")
        )
        self.timer_display_label.pack(pady=(10, 20))

        # 操作ボタン
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(pady=(0, 15))

        self.timer_start_btn = ctk.CTkButton(
            btn_frame, text="▶ 開始", fg_color="green", hover_color="darkgreen",
            command=self.start_timer, width=100
        )
        self.timer_start_btn.pack(side="left", padx=5)

        self.timer_pause_btn = ctk.CTkButton(
            btn_frame, text="⏸ 一時停止", fg_color="#555555", hover_color="#3a3a3a",
            command=self.pause_timer, width=100, state="disabled"
        )
        self.timer_pause_btn.pack(side="left", padx=5)

        self.timer_reset_btn = ctk.CTkButton(
            btn_frame, text="🔄 リセット", fg_color="gray", hover_color="#444444",
            command=self.reset_timer, width=100
        )
        self.timer_reset_btn.pack(side="left", padx=5)

        # 名前を付けて保存したタイマーの一覧
        self.build_timer_preset_section(frame)

        # 音のオンオフ
        sound_enabled_default = self.db.get_setting("timer_sound_enabled", "1") == "1"
        self.timer_sound_enabled_var = ctk.BooleanVar(value=sound_enabled_default)
        self.timer_sound_chk = ctk.CTkCheckBox(
            frame, text="時間になったら音を鳴らす",
            variable=self.timer_sound_enabled_var,
            command=self.on_timer_sound_toggle
        )
        self.timer_sound_chk.pack(anchor="w")

        self.build_alarm_sound_section(frame)

        # 初期表示を入力欄の値で更新
        self._update_timer_display(self._get_timer_input_seconds())
        self.refresh_timer_preset_listbox()

    # --- 保存したタイマー一覧 ---
    def build_timer_preset_section(self, parent):
        """
        名前を付けて保存したタイマーを一覧表示するエリアを作る。
        一覧をクリックすると上の時・分・秒の入力欄に読み込まれ、ダブルクリックでそのまま開始する。
        """
        self._timer_presets_cache = []
        # Tkは selection_set / delete などプログラム側の操作でも <<ListboxSelect>> を発生させる。
        # 一覧を作り直す間はハンドラを止めておかないと、意図せず読み込み処理が走ってしまう。
        self._suppress_preset_select = False

        section = ctk.CTkFrame(parent)
        section.pack(fill="x", pady=(5, 0))

        ctk.CTkLabel(
            section, text="📋 保存したタイマー一覧",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 2))

        ctk.CTkLabel(
            section,
            text="クリックで上の入力欄に読み込み、ダブルクリックでそのまま開始します。",
            text_color="#9a9a9a"
        ).pack(anchor="w", padx=12, pady=(0, 6))

        list_frame = ctk.CTkFrame(section, fg_color="transparent")
        list_frame.pack(fill="x", padx=12, pady=(0, 8))

        # CTkにはリストボックスが無いため、キーワード一覧と同じく標準tkinter Listboxを埋め込む。
        # exportselection=False: これを付けないと、キーワードタブの一覧を触った瞬間に
        # こちらの選択が解除されてしまう（Tkは既定で選択をアプリ内で1つしか保持しないため）。
        self.timer_preset_listbox = tk.Listbox(
            list_frame, height=5, font=("", 11), bg="#2b2b2b", fg="#dce4ee",
            selectbackground="#1f6aa5", highlightthickness=0, bd=0, exportselection=False
        )
        y_scroll = tk.Scrollbar(list_frame, command=self.timer_preset_listbox.yview)
        self.timer_preset_listbox.config(yscrollcommand=y_scroll.set)
        y_scroll.pack(side="right", fill="y")
        self.timer_preset_listbox.pack(side="left", fill="both", expand=True, pady=2)
        self.timer_preset_listbox.bind("<<ListboxSelect>>", self.on_timer_preset_select)
        self.timer_preset_listbox.bind("<Double-Button-1>", self.start_selected_timer_preset)

        btn_frame = ctk.CTkFrame(section, fg_color="transparent")
        btn_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 10))

        ctk.CTkButton(btn_frame, text="💾 現在の時間を保存", width=150,
                      command=self.save_current_timer_preset).pack(side="left", padx=(0, 5))
        ctk.CTkButton(btn_frame, text="▶ 読み込んで開始", width=130,
                      fg_color="green", hover_color="darkgreen",
                      command=self.start_selected_timer_preset).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="✏️ 名前変更", width=90,
                      command=self.rename_selected_timer_preset).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="🗑️ 削除", width=80,
                      fg_color="red", hover_color="darkred",
                      command=self.delete_selected_timer_preset).pack(side="left", padx=5)

    def refresh_timer_preset_listbox(self, select_preset_id=None):
        """
        一覧の中身をDBの最新状態に合わせて作り直す。
        select_preset_idを指定すると、その行を選択状態にする（保存直後に選んだままにするため）。
        """
        self._suppress_preset_select = True
        try:
            self.timer_preset_listbox.delete(0, tk.END)
            presets = self.db.get_timer_presets()
            self._timer_presets_cache = presets

            if not presets:
                # 空の一覧は「壊れている」ように見えるため、使い方の案内を1行だけ出す
                self.timer_preset_listbox.insert(tk.END, "  （保存したタイマーはありません）")
                self.timer_preset_listbox.itemconfig(0, fg="#7a7a7a")
                return

            for index, preset in enumerate(presets):
                self.timer_preset_listbox.insert(
                    tk.END, f"⏱ {preset['name']}  ─  {format_hms(preset['total_seconds'])}"
                )
                if preset["id"] == select_preset_id:
                    self.timer_preset_listbox.selection_set(index)
                    self.timer_preset_listbox.see(index)
        finally:
            self._suppress_preset_select = False

    def _selected_timer_preset(self):
        """一覧で選択中のタイマー情報を返す（未選択、または空の案内行ならNone）"""
        selection = self.timer_preset_listbox.curselection()
        if not selection:
            return None
        presets = getattr(self, "_timer_presets_cache", [])
        index = selection[0]
        if index >= len(presets):
            return None
        return presets[index]

    def _set_timer_inputs(self, total_seconds):
        """合計秒数を時・分・秒の入力欄に反映する（一覧から読み込むときに使う）"""
        total_seconds = max(0, int(total_seconds))
        for entry, value in (
            (self.timer_hour_entry, total_seconds // 3600),
            (self.timer_minute_entry, (total_seconds % 3600) // 60),
            (self.timer_second_entry, total_seconds % 60),
        ):
            entry.delete(0, tk.END)
            entry.insert(0, str(value))

    def save_current_timer_preset(self):
        """入力欄の時間に名前を付けて保存する。同名があった場合の扱いは下の判断メソッドに任せる。"""
        total_seconds = self._get_timer_input_seconds()
        if total_seconds <= 0:
            messagebox.showwarning("入力エラー", "1秒以上の時間を設定してください。")
            return

        dialog = ctk.CTkInputDialog(
            text=f"保存するタイマーの名前を入力してください:\n（時間: {format_hms(total_seconds)}）",
            title="タイマーを保存"
        )
        name = (dialog.get_input() or "").strip()
        if not name:
            return

        existing = next(
            (p for p in self._timer_presets_cache if p["name"] == name), None
        )
        if existing:
            action, payload = self._resolve_duplicate_preset_name(name, existing, total_seconds)
            if action == "cancel":
                return
            if action == "overwrite":
                success, err = self.db.update_timer_preset(payload, total_seconds)
                if success:
                    self.append_log(
                        f"💾 タイマー「{name}」を{format_hms(total_seconds)}に更新しました。"
                    )
                    self.refresh_timer_preset_listbox(select_preset_id=payload)
                else:
                    messagebox.showerror("保存エラー", f"タイマーの更新に失敗しました。\n\n詳細: {err}")
                return
            name = payload  # "create": 別名で新規保存する

        success, err, new_id = self.db.create_timer_preset(name, total_seconds)
        if success:
            self.append_log(f"💾 タイマー「{name}」({format_hms(total_seconds)}) を保存しました。")
            self.refresh_timer_preset_listbox(select_preset_id=new_id)
        else:
            messagebox.showerror("保存エラー", err)

    def _resolve_duplicate_preset_name(self, name, existing, total_seconds):
        """
        保存しようとした名前が既存のタイマーと重複したときの扱いを決める。

        name          : 入力された名前
        existing      : 同名の既存タイマー {'id':, 'name':, 'total_seconds':}
        total_seconds : 今回保存しようとしている秒数

        戻り値: ("overwrite", 既存のid) → その既存タイマーの時間を書き換える
                ("create", 使う名前)    → その名前で新規保存する
                ("cancel", None)        → 何もしない
        """
        overwrite = messagebox.askyesno(
            "同じ名前のタイマーがあります",
            f"「{name}」は既に保存されています。\n"
            f"　現在: {format_hms(existing['total_seconds'])}\n"
            f"　新しい時間: {format_hms(total_seconds)}\n\n"
            "この時間で上書きしますか？"
        )
        return ("overwrite", existing["id"]) if overwrite else ("cancel", None)

    def on_timer_preset_select(self, event=None):
        """一覧で選ぶだけで入力欄に読み込む（開始はしない）"""
        if self._suppress_preset_select:
            return
        # 動作中・一時停止中に行をクリックしただけで確認ダイアログが出るのは煩わしいので、
        # その場合は選択するだけにとどめる（切り替えはダブルクリックか各ボタンで行う）
        if self.timer_running or self.timer_remaining_seconds > 0:
            return
        preset = self._selected_timer_preset()
        if preset:
            self.apply_timer_preset(preset, start=False)

    def start_selected_timer_preset(self, event=None):
        """一覧のタイマーを読み込んでそのまま開始する（ボタン、またはダブルクリックから呼ばれる）"""
        preset = self._selected_timer_preset()
        if not preset:
            messagebox.showinfo("未選択", "開始するタイマーを一覧から選択してください。")
            return
        self.apply_timer_preset(preset, start=True)

    def apply_timer_preset(self, preset, start=False):
        """
        選んだタイマーを入力欄に読み込む。start=Trueならそのまま開始する。
        動作中・一時停止中の状態が残っているとカウントが混ざるため、必ずリセットしてから読み込む。
        """
        if (self.timer_running or self.timer_remaining_seconds > 0) \
                and not self._confirm_preset_change_while_running(preset):
            return

        self.reset_timer()
        self._set_timer_inputs(preset["total_seconds"])
        self._update_timer_display(preset["total_seconds"])

        if start:
            self.append_log(f"⏱️ 保存したタイマー「{preset['name']}」を開始します。")
            self.start_timer()

    def _confirm_preset_change_while_running(self, preset):
        """動作中／一時停止中のタイマーを捨てて別のタイマーに切り替えて良いか確認する"""
        return messagebox.askyesno(
            "タイマーを切り替えますか？",
            f"現在のタイマー（残り {self.timer_display_label.cget('text')}）を破棄して、\n"
            f"「{preset['name']}」({format_hms(preset['total_seconds'])}) に切り替えます。\n\n"
            "よろしいですか？"
        )

    def rename_selected_timer_preset(self):
        preset = self._selected_timer_preset()
        if not preset:
            messagebox.showinfo("未選択", "名前を変更するタイマーを一覧から選択してください。")
            return
        dialog = ctk.CTkInputDialog(
            text=f"「{preset['name']}」の新しい名前を入力してください:", title="タイマー名を変更"
        )
        new_name = (dialog.get_input() or "").strip()
        if not new_name or new_name == preset["name"]:
            return
        success, err = self.db.rename_timer_preset(preset["id"], new_name)
        if success:
            self.append_log(f"✏️ タイマー名を「{preset['name']}」→「{new_name}」に変更しました。")
            self.refresh_timer_preset_listbox(select_preset_id=preset["id"])
        else:
            messagebox.showerror("変更エラー", err)

    def delete_selected_timer_preset(self):
        preset = self._selected_timer_preset()
        if not preset:
            messagebox.showinfo("未選択", "削除するタイマーを一覧から選択してください。")
            return
        if not messagebox.askyesno(
            "確認",
            f"保存したタイマー「{preset['name']}」({format_hms(preset['total_seconds'])}) を削除します。\n\n"
            "よろしいですか？"
        ):
            return
        success, err = self.db.delete_timer_preset(preset["id"])
        if success:
            self.append_log(f"🗑️ 保存したタイマー「{preset['name']}」を削除しました。")
            self.refresh_timer_preset_listbox()
        else:
            messagebox.showerror("削除エラー", f"タイマーの削除に失敗しました。\n\n詳細: {err}")

    def _get_timer_input_seconds(self):
        """時・分・秒の入力欄から合計秒数を取得する。不正な値は0として扱う。"""
        def parse(entry):
            try:
                v = int(normalize_number_text(entry.get()) or "0")
                return max(0, v)
            except ValueError:
                return 0
        h = parse(self.timer_hour_entry)
        m = parse(self.timer_minute_entry)
        s = parse(self.timer_second_entry)
        return h * 3600 + m * 60 + s

    def _update_timer_display(self, total_seconds):
        self.timer_display_label.configure(text=format_hms(total_seconds))

    # --- アラーム音の設定UI ---
    ALARM_TYPE_LABELS = {
        ALARM_TYPE_BEEP: "ビープ音",
        ALARM_TYPE_ZUNDAMON: "ずんだもん音声",
        ALARM_TYPE_FILE: "音声ファイル",
    }

    def _alarm_type_from_label(self, label):
        for value, text in self.ALARM_TYPE_LABELS.items():
            if text == label:
                return value
        return ALARM_TYPE_BEEP

    def build_alarm_sound_section(self, parent):
        """アラーム音の種類・ずんだもん設定・音声ファイル・音量をまとめたエリアを作る"""
        section = ctk.CTkFrame(parent)
        section.pack(fill="x", pady=(10, 0))

        ctk.CTkLabel(
            section, text="🔔 アラーム音の設定",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 5))

        # --- 音の種類 ---
        type_frame = ctk.CTkFrame(section, fg_color="transparent")
        type_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 5))

        ctk.CTkLabel(type_frame, text="音の種類:").pack(side="left", padx=(0, 8))

        saved_type = self.db.get_setting("alarm_sound_type", ALARM_TYPE_BEEP)
        if saved_type not in self.ALARM_TYPE_LABELS:
            saved_type = ALARM_TYPE_BEEP
        self.alarm_type_var = ctk.StringVar(value=self.ALARM_TYPE_LABELS[saved_type])
        ctk.CTkOptionMenu(
            type_frame, variable=self.alarm_type_var,
            values=list(self.ALARM_TYPE_LABELS.values()),
            command=self.on_alarm_type_change, width=170
        ).pack(side="left")

        # --- ずんだもん設定 ---
        self.zundamon_frame = ctk.CTkFrame(section, fg_color="transparent")

        word_frame = ctk.CTkFrame(self.zundamon_frame, fg_color="transparent")
        word_frame.pack(anchor="w", fill="x", pady=(0, 5))

        ctk.CTkLabel(word_frame, text="読み上げるワード:").pack(side="left", padx=(0, 8))
        self.zundamon_text_entry = ctk.CTkEntry(word_frame, width=330)
        self.zundamon_text_entry.insert(
            0, self.db.get_setting("alarm_zundamon_text", DEFAULT_ZUNDAMON_TEXT)
        )
        self.zundamon_text_entry.pack(side="left")
        # 入力欄から離れた時・Enterを押した時に自動保存する（保存ボタンの押し忘れ防止）
        self.zundamon_text_entry.bind("<FocusOut>", lambda e: self.save_zundamon_text())
        self.zundamon_text_entry.bind("<Return>", lambda e: self.save_zundamon_text(log=True))
        self.zundamon_text_entry.bind("<Button-3>", self._show_entry_context_menu)

        ctk.CTkButton(word_frame, text="💾 保存", width=70,
                      command=lambda: self.save_zundamon_text(log=True)).pack(side="left", padx=(8, 0))

        style_frame = ctk.CTkFrame(self.zundamon_frame, fg_color="transparent")
        style_frame.pack(anchor="w", fill="x", pady=(0, 5))

        # アラームの声も、読み上げと同じくVOICEVOX・AivisSpeechの全キャラから選べる
        speakers = self.get_all_speakers()
        saved_speaker = self.get_zundamon_speaker_id()
        alarm_char, alarm_style = self.find_speaker_by_id(saved_speaker)
        if alarm_char not in speakers:
            alarm_char = next(iter(speakers))
            alarm_style = next(iter(speakers[alarm_char]))

        ctk.CTkLabel(style_frame, text="キャラ:").pack(side="left", padx=(0, 6))
        self.alarm_char_var = ctk.StringVar(value=alarm_char)
        self.alarm_char_menu = ctk.CTkOptionMenu(
            style_frame, variable=self.alarm_char_var, values=sorted(speakers.keys()),
            command=self.on_alarm_char_change, width=150
        )
        self.alarm_char_menu.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(style_frame, text="スタイル:").pack(side="left", padx=(0, 6))
        self.zundamon_style_var = ctk.StringVar(value=alarm_style)
        self.zundamon_style_menu = ctk.CTkOptionMenu(
            style_frame, variable=self.zundamon_style_var,
            values=list(speakers.get(alarm_char, {"ノーマル": 3}).keys()),
            command=self.on_zundamon_style_change, width=130
        )
        self.zundamon_style_menu.pack(side="left")

        ctk.CTkLabel(style_frame, text="VOICEVOX URL:").pack(side="left", padx=(15, 8))
        self.voicevox_url_entry = ctk.CTkEntry(style_frame, width=200)
        self.voicevox_url_entry.insert(0, self.db.get_setting("voicevox_url", DEFAULT_VOICEVOX_URL))
        self.voicevox_url_entry.pack(side="left")
        self.voicevox_url_entry.bind("<FocusOut>", lambda e: self.save_voicevox_url())
        self.voicevox_url_entry.bind("<Return>", lambda e: self.save_voicevox_url())
        self.voicevox_url_entry.bind("<Button-3>", self._show_entry_context_menu)

        ctk.CTkButton(style_frame, text="🔄 接続確認", width=100,
                      command=self.check_voicevox_connection).pack(side="left", padx=(8, 0))

        ctk.CTkLabel(
            self.zundamon_frame,
            text="※ ずんだもん音声にはVOICEVOX（無料）をPCで起動しておく必要があります。\n"
                 "　 VOICEVOXを起動した状態で「接続確認」を押すと、選べるスタイルが最新化されます。",
            justify="left", text_color="gray70"
        ).pack(anchor="w", pady=(0, 5))

        # --- 音声ファイル設定 ---
        self.alarm_file_frame = ctk.CTkFrame(section, fg_color="transparent")

        ctk.CTkLabel(self.alarm_file_frame, text="音声ファイル:").pack(side="left", padx=(0, 8))
        self.alarm_file_label = ctk.CTkLabel(
            self.alarm_file_frame,
            text=self._alarm_file_display_text(), text_color="gray70", anchor="w"
        )
        self.alarm_file_label.pack(side="left", padx=(0, 8))
        ctk.CTkButton(self.alarm_file_frame, text="📂 参照", width=80,
                      command=self.select_alarm_sound_file).pack(side="left")

        # --- 音量スライダー ---
        volume_frame = ctk.CTkFrame(section, fg_color="transparent")
        volume_frame.pack(anchor="w", fill="x", padx=12, pady=(5, 12))

        try:
            saved_volume = int(float(self.db.get_setting("alarm_volume", "50")))
        except (TypeError, ValueError):
            saved_volume = 50
        saved_volume = max(0, min(100, saved_volume))

        ctk.CTkLabel(volume_frame, text="🔊 アラーム音量:").pack(side="left", padx=(0, 8))

        self.alarm_volume_var = ctk.IntVar(value=saved_volume)
        self.alarm_volume_slider = ctk.CTkSlider(
            volume_frame, from_=0, to=100, number_of_steps=100,
            variable=self.alarm_volume_var, command=self.on_alarm_volume_change,
            width=220
        )
        self.alarm_volume_slider.pack(side="left")

        self.alarm_volume_label = ctk.CTkLabel(volume_frame, text=f"{saved_volume}%", width=45)
        self.alarm_volume_label.pack(side="left", padx=(8, 10))

        ctk.CTkButton(volume_frame, text="🔉 試聴", width=70,
                      command=self.test_alarm_sound).pack(side="left")

        self._update_alarm_type_visibility()

    def _alarm_file_display_text(self):
        path = self.get_alarm_sound_file()
        return os.path.basename(path) if path else "（未選択）"

    def _update_alarm_type_visibility(self):
        """選択中の種類に応じて、関係する設定欄だけを表示する"""
        sound_type = self.get_alarm_sound_type()

        self.zundamon_frame.pack_forget()
        self.alarm_file_frame.pack_forget()

        if sound_type == ALARM_TYPE_ZUNDAMON:
            self.zundamon_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 5))
        elif sound_type == ALARM_TYPE_FILE:
            self.alarm_file_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 5))

    def on_alarm_type_change(self, _label=None):
        sound_type = self.get_alarm_sound_type()
        self.db.save_setting("alarm_sound_type", sound_type)
        self._update_alarm_type_visibility()
        self.append_log(f"⚙️ アラーム音を「{self.ALARM_TYPE_LABELS[sound_type]}」に設定しました。")

    def save_zundamon_text(self, log=False):
        text = self.zundamon_text_entry.get().strip()
        if not text:
            text = DEFAULT_ZUNDAMON_TEXT
            self.zundamon_text_entry.delete(0, tk.END)
            self.zundamon_text_entry.insert(0, text)
        if text == self.db.get_setting("alarm_zundamon_text", DEFAULT_ZUNDAMON_TEXT):
            return
        self.db.save_setting("alarm_zundamon_text", text)
        if log:
            self.append_log(f"✅ ずんだもんの読み上げワードを「{text}」に設定しました。")

    def on_alarm_char_change(self, char_name=None):
        """アラームのキャラを変えたら、そのキャラのスタイルにプルダウンを差し替える"""
        styles = self.get_all_speakers().get(self.alarm_char_var.get(), {})
        if not styles:
            return
        names = list(styles.keys())
        self.zundamon_style_menu.configure(values=names)
        if self.zundamon_style_var.get() not in styles:
            self.zundamon_style_var.set(names[0])
        self.on_zundamon_style_change()

    def on_zundamon_style_change(self, _style_name=None):
        speaker_id = self.get_zundamon_speaker_id()
        self.db.save_setting("alarm_zundamon_speaker", str(speaker_id))
        self.append_log(
            f"⚙️ アラームの声を「{self.alarm_char_var.get()} / {self.zundamon_style_var.get()}」に設定しました。"
        )

    def save_voicevox_url(self):
        url = self.get_voicevox_url()
        if url != (self.db.get_setting("voicevox_url", DEFAULT_VOICEVOX_URL) or "").rstrip("/"):
            self.db.save_setting("voicevox_url", url)

    def check_voicevox_connection(self):
        """
        VOICEVOXに接続してキャラ一覧を取り直す。
        読み上げタブの「🔄 キャラ一覧を取得」と同じ処理（取得結果は両方のタブで共有される）。
        """
        self.save_voicevox_url()
        self.refresh_voicevox_speakers()

    def save_aivisspeech_url(self):
        url = self.get_aivisspeech_url()
        if url != (self.db.get_setting("aivisspeech_url", DEFAULT_AIVISSPEECH_URL) or "").rstrip("/"):
            self.db.save_setting("aivisspeech_url", url)

    def check_aivisspeech_connection(self):
        """AivisSpeechに接続してキャラ一覧を取り直す（VOICEVOX版と同じ形）"""
        self.save_aivisspeech_url()
        self.refresh_aivisspeech_speakers()

    def select_alarm_sound_file(self):
        path = filedialog.askopenfilename(
            title="アラームに使う音声ファイルを選択",
            filetypes=[("WAVファイル", "*.wav"), ("すべてのファイル", "*.*")]
        )
        if not path:
            return
        self.db.save_setting("alarm_sound_file", path)
        self.alarm_file_label.configure(text=self._alarm_file_display_text())
        self.append_log(f"✅ アラーム音の音声ファイルを設定しました: {os.path.basename(path)}")

    def on_timer_sound_toggle(self):
        value = "1" if self.timer_sound_enabled_var.get() else "0"
        self.db.save_setting("timer_sound_enabled", value)

    def on_alarm_volume_change(self, value):
        """スライダー操作時。表示を更新し、値をDBに保存する（次回起動時も維持）。"""
        volume = int(float(value))
        self.alarm_volume_label.configure(text=f"{volume}%")

        # ドラッグ中に毎回DBへ書かないよう、少し待ってからまとめて保存する
        pending_id = getattr(self, "_alarm_volume_save_id", None)
        if pending_id is not None:
            try:
                self.after_cancel(pending_id)
            except Exception:
                pass
        self._alarm_volume_save_id = self.after(
            300, lambda: self.db.save_setting("alarm_volume", str(volume))
        )

    def start_timer(self):
        if self.timer_running:
            return

        # 一時停止からの再開でなければ、入力欄から新しく時間を取得する
        if self.timer_end_time is None:
            total_seconds = self._get_timer_input_seconds()
            if total_seconds <= 0:
                messagebox.showwarning("入力エラー", "1秒以上の時間を設定してください。")
                return

            # 次回起動時にも使えるよう、設定した時間を保存する（全角数字は半角に揃えて保存）
            for key, entry in (
                ("timer_hours", self.timer_hour_entry),
                ("timer_minutes", self.timer_minute_entry),
                ("timer_seconds", self.timer_second_entry),
            ):
                value = normalize_number_text(entry.get()) or "0"
                entry.delete(0, tk.END)
                entry.insert(0, value)
                self.db.save_setting(key, value)

            self.timer_remaining_seconds = total_seconds
            self.timer_end_time = time.time() + total_seconds
            self.append_log(f"⏱️ タイマーを開始しました（{total_seconds}秒）")
        else:
            # 一時停止からの再開：残り秒数から終了時刻を再計算する
            self.timer_end_time = time.time() + self.timer_remaining_seconds
            self.append_log("⏱️ タイマーを再開しました。")

        self.timer_running = True
        self.timer_start_btn.configure(state="disabled")
        self.timer_pause_btn.configure(state="normal")
        self._timer_tick()

    def pause_timer(self):
        if not self.timer_running:
            return
        self.timer_running = False
        if self.timer_after_id is not None:
            self.after_cancel(self.timer_after_id)
            self.timer_after_id = None
        # 残り秒数を確定させておく（再開時に使うため）
        self.timer_remaining_seconds = max(0, int(self.timer_end_time - time.time())) if self.timer_end_time else 0
        self.timer_end_time = None
        self.timer_start_btn.configure(state="normal")
        self.timer_pause_btn.configure(state="disabled")
        self.append_log("⏸️ タイマーを一時停止しました。")

    def reset_timer(self):
        self.timer_running = False
        if self.timer_after_id is not None:
            self.after_cancel(self.timer_after_id)
            self.timer_after_id = None
        self.timer_end_time = None
        self.timer_remaining_seconds = 0
        self.timer_start_btn.configure(state="normal")
        self.timer_pause_btn.configure(state="disabled")
        self._update_timer_display(self._get_timer_input_seconds())

    def _timer_tick(self):
        if not self.timer_running or self.timer_end_time is None:
            return

        remaining = self.timer_end_time - time.time()

        if remaining <= 0:
            self._update_timer_display(0)
            self.timer_running = False
            self.timer_end_time = None
            self.timer_remaining_seconds = 0
            self.timer_start_btn.configure(state="normal")
            self.timer_pause_btn.configure(state="disabled")
            self.append_log("🔔 タイマーの時間になりました！")
            self._trigger_alarm()
            return

        self._update_timer_display(remaining)
        self.timer_after_id = self.after(200, self._timer_tick)

    def _build_beep_wav(self, volume_percent, frequency=1000, duration_ms=400, sample_rate=22050):
        """
        指定音量のビープ音をWAVデータ（bytes）として生成する。
        winsound.Beepは音量を変えられないため、自前で波形を作ってPlaySoundで再生する。
        volume_percent: 0〜100。0の場合はNoneを返す（無音）。
        """
        volume_percent = max(0, min(100, int(volume_percent)))
        if volume_percent == 0:
            return None

        # 体感の音量変化が自然になるよう、振幅は2乗カーブで小さくする
        amplitude = int(32767 * (volume_percent / 100.0) ** 2)
        total_samples = int(sample_rate * duration_ms / 1000)
        fade_samples = max(1, int(sample_rate * 0.005))  # 前後5msをフェードしてプチッというノイズを防ぐ

        frames = bytearray()
        for i in range(total_samples):
            gain = 1.0
            if i < fade_samples:
                gain = i / fade_samples
            elif i > total_samples - fade_samples:
                gain = max(0.0, (total_samples - i) / fade_samples)
            value = int(amplitude * gain * math.sin(2 * math.pi * frequency * i / sample_rate))
            frames += struct.pack('<h', value)

        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(bytes(frames))
        return buffer.getvalue()

    def get_alarm_volume(self):
        """現在のアラーム音量(0〜100)を返す。UI未構築時やワーカースレッドからは保存値を読む。"""
        var = getattr(self, "alarm_volume_var", None)
        if var is not None and self._on_main_thread():
            return int(var.get())
        try:
            return int(float(self.db.get_setting("alarm_volume", "50")))
        except (TypeError, ValueError):
            return 50

    def _apply_volume_to_wav(self, wav_data, volume_percent):
        """
        WAVデータ(bytes)の音量を変更したWAVデータを返す。
        16bitモノラル/ステレオのWAVに対応。それ以外の形式やエラー時は元データをそのまま返す。
        """
        volume_percent = max(0, min(100, int(volume_percent)))
        if volume_percent == 100:
            return wav_data
        try:
            with wave.open(io.BytesIO(wav_data), 'rb') as src:
                params = src.getparams()
                frames = src.readframes(src.getnframes())
            if params.sampwidth != 2:
                return wav_data  # 16bit以外は加工せずそのまま鳴らす

            gain = (volume_percent / 100.0) ** 2
            samples = array.array('h')
            samples.frombytes(frames)
            for i, value in enumerate(samples):
                samples[i] = int(max(-32768, min(32767, value * gain)))

            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as dst:
                dst.setnchannels(params.nchannels)
                dst.setsampwidth(params.sampwidth)
                dst.setframerate(params.framerate)
                dst.writeframes(samples.tobytes())
            return buffer.getvalue()
        except Exception:
            return wav_data

    # --- 各アラーム設定の取得（UIが未構築でもDBから読めるようにしておく） ---
    def get_alarm_sound_type(self):
        # _prepare_alarm_wav 経由でワーカースレッドからも呼ばれるため、
        # メインスレッド以外ではウィジェットに触らずDBの保存値を使う（_on_main_thread参照）
        var = getattr(self, "alarm_type_var", None)
        if var is not None and self._on_main_thread():
            return self._alarm_type_from_label(var.get())
        return self.db.get_setting("alarm_sound_type", ALARM_TYPE_BEEP)

    @staticmethod
    def _on_main_thread():
        """
        いまメインスレッドかどうか。UIウィジェットを読んで良いかの判定に使う。

        ⚠️ Tclインタプリタはスレッド安全ではないため、ワーカースレッドから
        ウィジェットやTk変数を読んではいけない。しかも厄介なことに、失敗の仕方が一定しない。
        after() は RuntimeError を投げるが、Variable.get() は例外にならず
        インタプリタのロック待ちで「そのまま止まる」。
        try/exceptでは後者を防げず、読み上げやアラームのスレッドが二度と進まなくなる。

        そのため「例外を受け止める」のではなく「そもそも触らない」方針にしている。
        設定はUI側が変更のたびにDBへ保存しているので、ワーカーからはDBを読めば同じ値が得られる。
        """
        return threading.current_thread() is threading.main_thread()

    def get_zundamon_text(self):
        entry = getattr(self, "zundamon_text_entry", None)
        if entry is not None and self._on_main_thread():
            return entry.get().strip() or DEFAULT_ZUNDAMON_TEXT
        return self.db.get_setting("alarm_zundamon_text", DEFAULT_ZUNDAMON_TEXT)

    # 話者未設定時の既定選択（VOICEVOXのずんだもん・ノーマル）
    DEFAULT_VOICE_SELECTOR = f"{TTS_ENGINE_VOICEVOX}:{DEFAULT_ZUNDAMON_STYLES['ノーマル']}"

    def get_zundamon_speaker_id(self):
        """アラームに使う話者選択("engine:話者ID")。読み上げ用は get_speech_speaker_id"""
        var = getattr(self, "zundamon_style_var", None)
        char_var = getattr(self, "alarm_char_var", None)
        if var is not None and char_var is not None and self._on_main_thread():
            styles = self.get_all_speakers().get(char_var.get(), {})
            if var.get() in styles:
                return styles[var.get()]
        saved = self.db.get_setting("alarm_zundamon_speaker", self.DEFAULT_VOICE_SELECTOR)
        return self._normalize_voice_selector(saved) or self.DEFAULT_VOICE_SELECTOR

    def get_speech_speaker_id(self):
        """
        読み上げに使う話者選択("engine:話者ID")。アラーム用とは別に持つ。
        （アラームは注意を引きたい／読み上げは会話用と、目的が違うため設定を分けている）
        """
        var = getattr(self, "speech_style_var", None)
        if var is not None and self._on_main_thread():
            speakers = self.get_all_speakers()
            char = self.speech_char_var.get()
            style = var.get()
            if char in speakers and style in speakers[char]:
                return speakers[char][style]
        saved = self.db.get_setting("speech_speaker_id", self.DEFAULT_VOICE_SELECTOR)
        return self._normalize_voice_selector(saved) or self.DEFAULT_VOICE_SELECTOR

    def get_speech_volume(self):
        """読み上げの音量(0〜100)。ワーカースレッドからも呼ばれるのでDBフォールバックあり。"""
        var = getattr(self, "speech_volume_var", None)
        if var is not None and self._on_main_thread():
            return int(var.get())
        try:
            return int(float(self.db.get_setting("speech_volume", "50")))
        except (TypeError, ValueError):
            return 50

    def get_voicevox_url(self):
        entry = getattr(self, "voicevox_url_entry", None)
        if entry is not None and self._on_main_thread():
            return entry.get().strip().rstrip("/") or DEFAULT_VOICEVOX_URL
        return (self.db.get_setting("voicevox_url", DEFAULT_VOICEVOX_URL) or DEFAULT_VOICEVOX_URL).rstrip("/")

    def get_alarm_sound_file(self):
        return self.db.get_setting("alarm_sound_file", "") or ""

    # --- VOICEVOX（ずんだもん音声）連携 ---
    def _voicevox_request(self, path, method="GET", data=None, timeout=30):
        url = f"{self.get_voicevox_url()}{path}"
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.read()

    def fetch_voicevox_speakers(self):
        """
        VOICEVOXエンジンから全キャラのスタイル一覧を {キャラ名: {スタイル名: 話者ID}} で返す。
        接続できない場合は例外を投げる（呼び出し側でメッセージ表示）。
        """
        raw = self._voicevox_request("/speakers", timeout=15)
        speakers = json.loads(raw.decode("utf-8"))
        result = {}
        for speaker in speakers:
            name = (speaker.get("name") or "").strip()
            styles = {s["name"]: s["id"] for s in speaker.get("styles", []) if "id" in s}
            if name and styles:
                result[name] = styles
        if not result:
            raise RuntimeError("エンジンから音声が1つも見つかりませんでした。")
        return result

    def get_voicevox_speakers(self):
        """保存済みのキャラ一覧を返す。まだ取得していなければ既定値（ずんだもんのみ）。"""
        cached = getattr(self, "_voicevox_speakers", None)
        if cached:
            return cached
        raw = self.db.get_setting("voicevox_speakers", "")
        if raw:
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict) and loaded:
                    self._voicevox_speakers = {
                        k: {sk: int(sv) for sk, sv in v.items()}
                        for k, v in loaded.items() if isinstance(v, dict)
                    }
                    return self._voicevox_speakers
            except (ValueError, TypeError):
                pass
        self._voicevox_speakers = {k: dict(v) for k, v in DEFAULT_VOICEVOX_SPEAKERS.items()}
        return self._voicevox_speakers

    def find_speaker_by_id(self, voice_selector):
        """
        話者選択("engine:話者ID"。旧形式の裸のIDも受け付ける)から
        (キャラ表示名, スタイル名) を逆引きする。見つからなければ既定値。
        検索はVOICEVOX・AivisSpeechの両方から（get_all_speakers参照）。
        """
        selector = self._normalize_voice_selector(voice_selector)
        if selector is not None:
            for name, styles in self.get_all_speakers().items():
                for style_name, sid in styles.items():
                    if sid == selector:
                        return name, style_name
        return DEFAULT_SPEECH_SPEAKER_NAME, DEFAULT_SPEECH_STYLE_NAME

    def synthesize_zundamon_wav(self, text, speaker_id):
        """
        ずんだもんの読み上げ音声をVOICEVOXで合成してWAVデータ(bytes)を返す。
        同じ内容の再合成を避けるため、結果はメモリ上にキャッシュする。

        ⚠️ 保持件数に上限を設けている。アラームだけで使っていた頃は決まった文しか
        通らなかったが、読み上げ機能では貼り付け・クリップボード・スマホから
        いくらでも違う文が流れてくる。WAVは数秒でも100KB前後あるため、
        上限なしだと長時間の使用でメモリを際限なく食う。
        """
        cache_key = (self.get_voicevox_url(), speaker_id, text)
        cache = getattr(self, "_zundamon_wav_cache", None)
        if cache is None:
            cache = self._zundamon_wav_cache = {}
        if cache_key in cache:
            return cache[cache_key]

        query_path = f"/audio_query?text={urllib.parse.quote(text)}&speaker={speaker_id}"
        query_json = self._voicevox_request(query_path, method="POST", data=b"")
        wav_data = self._voicevox_request(
            f"/synthesis?speaker={speaker_id}", method="POST", data=query_json, timeout=60
        )

        # 古いものから捨てる（dictは挿入順を保つのでそのまま先頭が最古）
        while len(cache) >= MAX_SPEECH_WAV_CACHE:
            try:
                del cache[next(iter(cache))]
            except (StopIteration, KeyError, RuntimeError):
                break   # 別スレッドが同時に触った場合は次回に任せる
        cache[cache_key] = wav_data
        return wav_data

    # --- AivisSpeech連携 ---
    # ⚠️ AivisSpeechはVOICEVOXと同じAPI形式（/speakers, /audio_query, /synthesis）の
    # ローカルエンジンだが、既定のポートが違う別プロセスなので、URL・キャラ一覧・
    # WAVキャッシュはVOICEVOXとは完全に分けて持つ。上のVOICEVOX用の各メソッドと
    # 1対1で対応している（コメントの重複は避け、違いがある部分だけ補足する）。
    def get_aivisspeech_url(self):
        entry = getattr(self, "aivisspeech_url_entry", None)
        if entry is not None and self._on_main_thread():
            return entry.get().strip().rstrip("/") or DEFAULT_AIVISSPEECH_URL
        return (self.db.get_setting("aivisspeech_url", DEFAULT_AIVISSPEECH_URL) or DEFAULT_AIVISSPEECH_URL).rstrip("/")

    def _aivisspeech_request(self, path, method="GET", data=None, timeout=30):
        url = f"{self.get_aivisspeech_url()}{path}"
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.read()

    def fetch_aivisspeech_speakers(self):
        """AivisSpeechエンジンから全キャラのスタイル一覧を {キャラ名: {スタイル名: 話者ID}} で返す。"""
        raw = self._aivisspeech_request("/speakers", timeout=15)
        speakers = json.loads(raw.decode("utf-8"))
        result = {}
        for speaker in speakers:
            name = (speaker.get("name") or "").strip()
            styles = {s["name"]: s["id"] for s in speaker.get("styles", []) if "id" in s}
            if name and styles:
                result[name] = styles
        if not result:
            raise RuntimeError("エンジンから音声が1つも見つかりませんでした。")
        return result

    def get_aivisspeech_speakers(self):
        """
        保存済みのAivisSpeechキャラ一覧を返す。まだ一度も取得していなければ空。

        ⚠️ VOICEVOXと違い、既定値（ハードコードされた話者ID）は用意しない。
        AivisSpeechはユーザーが入れる音声モデルによってキャラ構成が変わるため、
        実際に接続して取得するまでは「選べるキャラが無い」のが正直な状態。
        当て推量のIDを既定値にすると、確認もせず合成に失敗する原因になる。
        """
        cached = getattr(self, "_aivisspeech_speakers", None)
        if cached is not None:
            return cached
        raw = self.db.get_setting("aivisspeech_speakers", "")
        if raw:
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict) and loaded:
                    self._aivisspeech_speakers = {
                        k: {sk: int(sv) for sk, sv in v.items()}
                        for k, v in loaded.items() if isinstance(v, dict)
                    }
                    return self._aivisspeech_speakers
            except (ValueError, TypeError):
                pass
        self._aivisspeech_speakers = {}
        return self._aivisspeech_speakers

    def synthesize_aivisspeech_wav(self, text, speaker_id):
        """AivisSpeechで読み上げ音声を合成してWAVデータ(bytes)を返す。挙動はVOICEVOX版と同じ。"""
        cache_key = (self.get_aivisspeech_url(), speaker_id, text)
        cache = getattr(self, "_aivisspeech_wav_cache", None)
        if cache is None:
            cache = self._aivisspeech_wav_cache = {}
        if cache_key in cache:
            return cache[cache_key]

        query_path = f"/audio_query?text={urllib.parse.quote(text)}&speaker={speaker_id}"
        query_json = self._aivisspeech_request(query_path, method="POST", data=b"")
        wav_data = self._aivisspeech_request(
            f"/synthesis?speaker={speaker_id}", method="POST", data=query_json, timeout=60
        )

        while len(cache) >= MAX_SPEECH_WAV_CACHE:
            try:
                del cache[next(iter(cache))]
            except (StopIteration, KeyError, RuntimeError):
                break
        cache[cache_key] = wav_data
        return wav_data

    # --- VOICEVOX / AivisSpeech をまとめて扱う層 ---
    # ⚠️ 話者の選択は "engine:話者ID" の文字列（例: "voicevox:3"）で表す。
    # 裸の数値（旧バージョンがDBに保存した形式）は voicevox とみなして読み替える。
    def _normalize_voice_selector(self, raw):
        """"3" や "voicevox:3" を "voicevox:3" の形に正規化する。読めなければNone。"""
        text = str(raw).strip() if raw is not None else ""
        if not text:
            return None
        if ":" in text:
            engine, _, sid = text.partition(":")
            if engine in TTS_ENGINES and sid.lstrip("-").isdigit():
                return f"{engine}:{sid}"
            return None
        if text.lstrip("-").isdigit():
            return f"{TTS_ENGINE_VOICEVOX}:{text}"
        return None

    def _split_voice_selector(self, raw):
        """話者選択を (エンジン名, 話者ID(int)) に分解する。読めなければVOICEVOXの既定値。"""
        selector = self._normalize_voice_selector(raw)
        if selector is None:
            selector = f"{TTS_ENGINE_VOICEVOX}:{DEFAULT_ZUNDAMON_STYLES['ノーマル']}"
        engine, _, sid = selector.partition(":")
        return engine, int(sid)

    def get_all_speakers(self):
        """
        VOICEVOXとAivisSpeech、両方のキャラをまとめた一覧を返す。
        {表示名: {スタイル名: "engine:話者ID"}}

        AivisSpeech側のキャラ名には印を付けて区別する。VOICEVOX側の表示名は
        AivisSpeech対応前と同じ無印のまま（既存の保存設定・表示への影響を避けるため）。
        """
        combined = {}
        for name, styles in self.get_voicevox_speakers().items():
            combined[name] = {style: f"{TTS_ENGINE_VOICEVOX}:{sid}" for style, sid in styles.items()}

        suffix = f"（{TTS_ENGINES[TTS_ENGINE_AIVISSPEECH]['label']}）"
        for name, styles in self.get_aivisspeech_speakers().items():
            display_name = f"{name}{suffix}"
            while display_name in combined:      # 名前が衝突した場合の保険
                display_name += "_"
            combined[display_name] = {style: f"{TTS_ENGINE_AIVISSPEECH}:{sid}" for style, sid in styles.items()}
        return combined

    def synthesize_voice_wav(self, text, voice_selector):
        """
        話者選択("engine:話者ID")に従って、正しいエンジンで音声を合成する。
        アラーム・読み上げのどちらも、実際の合成はここを通す。
        """
        engine, speaker_id = self._split_voice_selector(voice_selector)
        if engine == TTS_ENGINE_AIVISSPEECH:
            return self.synthesize_aivisspeech_wav(text, speaker_id)
        return self.synthesize_zundamon_wav(text, speaker_id)

    def _engine_request(self, engine, path, method="GET", data=None, timeout=30):
        """エンジン名に応じて、正しいエンジンへHTTPリクエストを投げる"""
        if engine == TTS_ENGINE_AIVISSPEECH:
            return self._aivisspeech_request(path, method=method, data=data, timeout=timeout)
        return self._voicevox_request(path, method=method, data=data, timeout=timeout)

    # --- アクセント解析（スマホの解析ページ用） ---
    def analyze_accent(self, text, voice_selector=None):
        """
        文を今の声のエンジンに解析させ、アクセント句・モーラの構造を返す。

        戻り値: {"engine":..., "speaker":..., "kana":..., "query":<audio_query全体>,
                 "phrases":[{"surface":..., "accent":..., "moras":[...]}]}

        「どういうものなのか」を見せるのが目的なので、エンジンが返した
        audio_query をそのまま query に入れて持ち回る。合成し直すときに
        同じものを送り返せば、解析結果と実際に喋る音がずれない。
        """
        selector = self._normalize_voice_selector(voice_selector) or self.get_speech_speaker_id()
        engine, speaker_id = self._split_voice_selector(selector)

        raw = self._engine_request(
            engine, f"/audio_query?text={urllib.parse.quote(text)}&speaker={speaker_id}",
            method="POST", data=b"", timeout=30)
        query = json.loads(raw.decode("utf-8"))
        return {
            "engine": engine,
            "engine_label": TTS_ENGINES[engine]["label"],
            "selector": selector,
            "kana": query.get("kana") or "",
            "phrases": self._summarize_accent_phrases(query.get("accent_phrases") or []),
            "query": query,
        }

    @staticmethod
    def _summarize_accent_phrases(accent_phrases):
        """画面に出しやすい形（表記・アクセント核の位置・モーラ一覧）に整える"""
        result = []
        for phrase in accent_phrases:
            moras = phrase.get("moras") or []
            result.append({
                "surface": "".join(m.get("text", "") for m in moras),
                "accent": phrase.get("accent", 0),
                "moras": [m.get("text", "") for m in moras],
                "pause": bool(phrase.get("pause_mora")),
            })
        return result

    def synthesize_from_query(self, query, voice_selector, recalculate=True):
        """
        編集済みの audio_query から音声を合成する。

        ⚠️ accent の数値を書き換えただけでは音は変わらない。
        moras には既にピッチ(pitch)が入っており、/synthesis はそちらを見るため、
        accent だけ直しても元のままの音が返ってくる（実測で確認済み）。
        アクセントを変えたら必ず /mora_data に通してピッチを計算し直すこと。
        """
        engine, speaker_id = self._split_voice_selector(voice_selector)

        if recalculate and query.get("accent_phrases"):
            try:
                raw = self._engine_request(
                    engine, f"/mora_data?speaker={speaker_id}", method="POST",
                    data=json.dumps(query["accent_phrases"]).encode("utf-8"), timeout=30)
                query = dict(query, accent_phrases=json.loads(raw.decode("utf-8")))
            except Exception:
                # 再計算できなくても、元のクエリで喋れるだけは喋らせる
                pass

        return self._engine_request(
            engine, f"/synthesis?speaker={speaker_id}", method="POST",
            data=json.dumps(query).encode("utf-8"), timeout=60)

    # --- 再生 ---
    def _play_wav_bytes(self, wav_data, volume_percent):
        """
        WAVデータを鳴らす。出力デバイスが選ばれていればそこへ、
        選ばれていなければWindowsの既定デバイスへ流す。
        """
        if not wav_data:
            return False

        device = self.get_audio_output_device()
        if device:
            if self._play_wav_to_device(wav_data, volume_percent, device):
                return True
            # 選んだデバイスで鳴らせなかった場合は、黙って無音にせず既定へ落とす。
            # （デバイスを抜いた・名前が変わった等でも、とりあえず音は出る）
            self._warn_output_device_once(device)

        if winsound is None:
            return False
        try:
            winsound.PlaySound(self._apply_volume_to_wav(wav_data, volume_percent), winsound.SND_MEMORY)
            return True
        except Exception:
            return False

    def _play_wav_to_device(self, wav_data, volume_percent, device_name):
        """
        指定した出力デバイスへWAVを流す。鳴らせたらTrue。

        ⚠️ 書き込んだだけでは再生は終わらない。
        RawOutputStream.write() は再生完了を待たずに返る（実測: 4.2秒の音声で0.04秒）。
        そのまま閉じると途中で切れるため、音の長さぶん待ってから閉じること。
        """
        if sounddevice is None:
            return False
        index = self._resolve_output_device_index(device_name)
        if index is None:
            return False
        try:
            adjusted = self._apply_volume_to_wav(wav_data, volume_percent)
            with wave.open(io.BytesIO(adjusted), "rb") as w:
                channels, sampwidth, framerate = w.getnchannels(), w.getsampwidth(), w.getframerate()
                frame_count = w.getnframes()
                frames = w.readframes(frame_count)
            if sampwidth != 2 or not frames:
                return False        # 16bit以外は扱わない（winsound側に任せる）

            stream = sounddevice.RawOutputStream(
                samplerate=framerate, channels=channels, dtype="int16", device=index)
            try:
                stream.start()
                stream.write(frames)
                time.sleep(frame_count / float(framerate) + 0.2)
            finally:
                stream.stop()
                stream.close()
            return True
        except Exception:
            return False

    def _warn_output_device_once(self, device_name):
        """出力デバイスで鳴らせなかったことを、同じ相手につき1度だけ知らせる"""
        if getattr(self, "_warned_output_device", None) == device_name:
            return
        self._warned_output_device = device_name
        self._post_to_ui(lambda: self.append_log(
            f"⚠️ 出力デバイス「{device_name}」で鳴らせませんでした。"
            "既定のデバイスで鳴らします（設定を選び直してください）。"))

    # --- 出力デバイスの選択 ---
    # ⚠️ 保存するのはデバイス名。番号(index)は機器の抜き差しや再起動で
    # ずれるため、番号で覚えると気付かないうちに別のデバイスへ鳴らしてしまう。
    #
    # ⚠️ ホストAPIは MME を使う。DirectSound を使ってはいけない。
    # 実測(2026-08-13):
    #   ・DirectSoundで CABLE Input へ再生 -> CABLE Output に届く信号は peak=1（無音）
    #   ・MMEで        CABLE Input へ再生 -> CABLE Output に peak=15002 で届く
    #   ・DirectSoundの録音は read() が即座に無音を返し続ける（実時間の5781倍）
    #   ・MMEの録音は正常（1秒でおよそ44100フレーム）
    # DirectSoundは「ストリームを開けて、書き込めて、時間もかかる」ため
    # 例外も出ず成功しているように見えるのに、音だけが届かない。
    # MMEは名前が31文字で切れるが、それは表示上の都合にすぎない。
    # 実際に音が通ることを優先する。
    #
    # WASAPI と WDM-KS は音声エンジンの出力(24000Hz)を
    # 「Invalid sample rate」で拒否するため使えない。
    AUDIO_HOST_API = "MME"
    AUDIO_OUTPUT_DEFAULT_LABEL = "既定のデバイス（Windowsの設定に従う）"

    def list_output_devices(self):
        """選べる出力デバイス名の一覧を返す（先頭は既定を表す項目）"""
        names = [self.AUDIO_OUTPUT_DEFAULT_LABEL]
        if sounddevice is None:
            return names
        try:
            host_apis = sounddevice.query_hostapis()
            for device in sounddevice.query_devices():
                if device.get("max_output_channels", 0) <= 0:
                    continue
                if host_apis[device["hostapi"]]["name"] != self.AUDIO_HOST_API:
                    continue
                name = (device.get("name") or "").strip()
                if name and name not in names:
                    names.append(name)
        except Exception:
            pass
        return names

    def _resolve_output_device_index(self, device_name):
        """デバイス名から今の番号を引く。見つからなければNone"""
        return self._resolve_device_index(device_name, want_output=True)

    def _resolve_device_index(self, device_name, want_output):
        """
        デバイス名から今の番号を引く（入力・出力の共通処理）。

        ⚠️ 完全一致だけで探してはいけない。
        以前のバージョンは DirectSound の完全な名前を保存していたが、
        今は MME を使っており、MMEはデバイス名を31文字で切る
        （例: 'CABLE Input (VB-Audio Virtual Cable)' -> 'CABLE Input (VB-Audio Virtual C'）。
        完全一致だけだと、更新した瞬間に保存済みの設定が全部「見つからない」になる。
        前方一致でも拾えるようにして、設定を引き継げるようにしておく。
        """
        if sounddevice is None or not device_name:
            return None
        key = "max_output_channels" if want_output else "max_input_channels"
        try:
            host_apis = sounddevice.query_hostapis()
            fallback = None
            for index, device in enumerate(sounddevice.query_devices()):
                if device.get(key, 0) <= 0:
                    continue
                if host_apis[device["hostapi"]]["name"] != self.AUDIO_HOST_API:
                    continue
                name = (device.get("name") or "").strip()
                if name == device_name:
                    return index
                # 保存値(長い)が、今の名前(切れている)で始まっているか
                if fallback is None and name and device_name.startswith(name):
                    fallback = index
            return fallback
        except Exception:
            return None

    @staticmethod
    def _match_saved_device(saved, devices, default_label):
        """
        保存されている名前を、今の一覧の表記に合わせる。

        ⚠️ 完全一致だけで判定すると、DirectSound時代に保存した長い名前が
        MMEの切り詰められた名前と一致せず、更新した瞬間に設定が
        「見つからない」扱いになって既定へ戻ってしまう。前方一致でも拾う。
        """
        if not saved or saved == default_label:
            return default_label
        if saved in devices:
            return saved
        for name in devices:
            if name != default_label and name and saved.startswith(name):
                return name
        return default_label

    def get_audio_output_device(self):
        """
        選ばれている出力デバイス名。既定を使う場合は空文字。
        ワーカースレッドからも呼ばれるのでDBを読む（_on_main_thread参照）。
        """
        name = (self.db.get_setting("audio_output_device", "") or "").strip()
        return "" if name == self.AUDIO_OUTPUT_DEFAULT_LABEL else name

    # --- 入力デバイス（マイク）の選択 ---
    # ⚠️ 出力側と同じく、保存するのはデバイス名。番号は抜き差しでずれる。
    AUDIO_INPUT_DEFAULT_LABEL = "既定のマイク（Windowsの設定に従う）"

    def list_input_devices(self):
        """選べる入力デバイス名の一覧を返す（先頭は既定を表す項目）"""
        names = [self.AUDIO_INPUT_DEFAULT_LABEL]
        if sounddevice is None:
            return names
        try:
            host_apis = sounddevice.query_hostapis()
            for device in sounddevice.query_devices():
                if device.get("max_input_channels", 0) <= 0:
                    continue
                if host_apis[device["hostapi"]]["name"] != self.AUDIO_HOST_API:
                    continue
                name = (device.get("name") or "").strip()
                if name and name not in names:
                    names.append(name)
        except Exception:
            pass
        return names

    def _resolve_input_device_index(self, device_name):
        """入力デバイス名から今の番号を引く。名前が空なら既定(None)を返す"""
        return self._resolve_device_index(device_name, want_output=False)

    def get_audio_input_device(self):
        """選ばれている入力デバイス名。既定を使う場合は空文字。"""
        name = (self.db.get_setting("audio_input_device", "") or "").strip()
        return "" if name == self.AUDIO_INPUT_DEFAULT_LABEL else name

    def measure_input_level(self, seconds=1.0):
        """
        マイクが拾えているか確かめるため、少しだけ録って音の大きさ(0〜100)を返す。
        録れなければ (None, 理由) を返す。
        """
        if sounddevice is None:
            return None, "この環境ではマイクを扱えません。"
        name = self.get_audio_input_device()
        index = self._resolve_input_device_index(name)
        if name and index is None:
            return None, f"マイク「{name}」が見つかりません。"
        try:
            channels, rate = self._input_stream_format(index)
            captured = bytearray()
            with sounddevice.RawInputStream(
                    samplerate=rate, channels=channels, dtype="int16", device=index) as stream:
                deadline = time.time() + seconds
                while time.time() < deadline:
                    data, _overflowed = stream.read(1024)
                    captured += bytes(data)
        except Exception as e:
            return None, f"マイクを開けませんでした（{str(e).splitlines()[-1][:80]}）。"

        if not captured:
            return None, "マイクから何も録れませんでした。"
        samples = array.array("h")
        samples.frombytes(bytes(captured[: len(captured) // 2 * 2]))
        peak = max((abs(v) for v in samples), default=0)
        return int(peak / 32767 * 100), ""

    def _input_stream_format(self, index):
        """その入力デバイスで使うチャンネル数とサンプリングレートを決める"""
        channels, rate = 1, 44100
        try:
            info = sounddevice.query_devices(index if index is not None else None, "input")
            channels = min(2, max(1, int(info.get("max_input_channels", 1))))
            rate = int(info.get("default_samplerate") or 44100)
        except Exception:
            pass
        return channels, rate

    # --- マイクの音を出力先へ流す（パススルー） ---
    # ⚠️ 出力先がスピーカーだと、スピーカーの音をマイクが拾って
    # ハウリングする。VB-CABLE等の仮想デバイスへ流す使い方を想定している。
    def is_input_passthrough_running(self):
        thread = getattr(self, "_passthrough_thread", None)
        return thread is not None and thread.is_alive()

    def start_input_passthrough(self):
        """マイクの音を、選んでいる出力先へ流し続ける。戻り値: (開始できたか, 理由)"""
        if self.is_input_passthrough_running():
            return True, ""
        if sounddevice is None:
            return False, "この環境ではマイクを扱えません。"

        in_name = self.get_audio_input_device()
        in_index = self._resolve_input_device_index(in_name)
        if in_name and in_index is None:
            return False, f"マイク「{in_name}」が見つかりません。"

        out_name = self.get_audio_output_device()
        out_index = self._resolve_output_device_index(out_name)
        if not out_name:
            return False, ("出力先が「既定のデバイス」のままです。\n"
                           "スピーカーへ流すとハウリングするため、"
                           "VB-CABLE等の出力先を選んでから使ってください。")
        if out_index is None:
            return False, f"出力先「{out_name}」が見つかりません。"

        self._passthrough_stop = threading.Event()
        stop_event = self._passthrough_stop

        def run():
            try:
                channels, rate = self._input_stream_format(in_index)
                with sounddevice.RawInputStream(
                        samplerate=rate, channels=channels, dtype="int16",
                        device=in_index, blocksize=1024) as source, \
                     sounddevice.RawOutputStream(
                        samplerate=rate, channels=channels, dtype="int16",
                        device=out_index, blocksize=1024) as sink:
                    while not stop_event.is_set():
                        data, _overflowed = source.read(1024)
                        sink.write(data)
            except Exception as e:
                message = f"⚠️ マイクの転送が止まりました（{str(e).splitlines()[-1][:80]}）。"
                self._post_to_ui(lambda: self.append_log(message))
                self._post_to_ui(self._sync_passthrough_ui)

        self._passthrough_thread = threading.Thread(target=run, daemon=True)
        self._passthrough_thread.start()
        return True, ""

    def stop_input_passthrough(self):
        event = getattr(self, "_passthrough_stop", None)
        if event is not None:
            event.set()
        thread = getattr(self, "_passthrough_thread", None)
        if thread is not None:
            thread.join(timeout=2)
        self._passthrough_thread = None

    def _play_beep_once(self, volume_percent):
        """指定音量でビープ音を1回鳴らす（再生が終わるまでブロックする）"""
        if winsound is None:
            return False
        wav_data = self._build_beep_wav(volume_percent)
        if wav_data is None:
            return False
        try:
            winsound.PlaySound(wav_data, winsound.SND_MEMORY)
            return True
        except Exception:
            # WAV再生に失敗した環境では、音量調整なしの従来のビープにフォールバックする
            try:
                winsound.Beep(1000, 400)
                return True
            except Exception:
                return False

    def _prepare_alarm_wav(self):
        """
        現在の設定に応じて、鳴らすWAVデータ(bytes)を用意して返す。
        (wav_data, error_message) を返し、wav_dataがNoneならビープ音で代替する。
        """
        sound_type = self.get_alarm_sound_type()

        if sound_type == ALARM_TYPE_ZUNDAMON:
            voice_selector = self.get_zundamon_speaker_id()
            try:
                return self.synthesize_voice_wav(self.get_zundamon_text(), voice_selector), None
            except Exception as e:
                engine, _ = self._split_voice_selector(voice_selector)
                return None, (
                    f"音声の生成に失敗しました（{e}）。\n"
                    f"{TTS_ENGINES[engine]['label']}が起動しているか確認してください。ビープ音で代替します。"
                )

        if sound_type == ALARM_TYPE_FILE:
            path = self.get_alarm_sound_file()
            if not path or not os.path.exists(path):
                return None, "音声ファイルが見つかりません。ビープ音で代替します。"
            try:
                with open(path, "rb") as f:
                    return f.read(), None
            except Exception as e:
                return None, f"音声ファイルを読み込めませんでした（{e}）。ビープ音で代替します。"

        return None, None  # ビープ音

    def _play_alarm_once(self, wav_data, volume_percent):
        """用意済みのWAV（無ければビープ音）を1回鳴らす"""
        if wav_data:
            if self._play_wav_bytes(wav_data, volume_percent):
                return True
        return self._play_beep_once(volume_percent)

    def test_alarm_sound(self):
        """「試聴」ボタン用。現在の設定・音量で1回だけ鳴らす。"""
        volume = self.get_alarm_volume()
        if volume == 0:
            messagebox.showinfo("音量0", "音量が0のため音は鳴りません。スライダーを上げてください。")
            return

        def run():
            wav_data, error = self._prepare_alarm_wav()
            if error:
                self.after(0, lambda: messagebox.showwarning("アラーム音", error))
            self._play_alarm_once(wav_data, volume)

        threading.Thread(target=run, daemon=True).start()

    def _trigger_alarm(self):
        """タイマー終了時にアラーム音を鳴らし、確認ダイアログを表示する"""
        self.alarm_stop_flag = False

        if self.timer_sound_enabled_var.get() and winsound is not None:
            volume = self.get_alarm_volume()

            def alarm_loop():
                # 音声の用意は1回だけ行い、ダイアログが閉じられるまで繰り返し鳴らす
                wav_data, error = self._prepare_alarm_wav()
                if error:
                    self.append_log(f"⚠️ {error}")
                while not self.alarm_stop_flag:
                    if not self._play_alarm_once(wav_data, volume):
                        break
                    time.sleep(0.3)

            if volume > 0:
                threading.Thread(target=alarm_loop, daemon=True).start()

        def show_alarm_dialog():
            dialog = ctk.CTkToplevel(self)
            dialog.title("タイマー")
            dialog.geometry("320x150")
            dialog.grab_set()
            dialog.attributes("-topmost", True)

            ctk.CTkLabel(
                dialog, text="⏰ 設定した時間になりました！",
                font=ctk.CTkFont(size=16, weight="bold")
            ).pack(pady=(25, 15))

            def on_ok():
                self.alarm_stop_flag = True
                dialog.destroy()

            ctk.CTkButton(dialog, text="OK", command=on_ok, width=100).pack(pady=5)
            dialog.protocol("WM_DELETE_WINDOW", on_ok)

        self.after(0, show_alarm_dialog)

    # --- 設定タブ（送信クールダウン） ---
    def build_settings_tab(self):
        # ⚠️ 中身を tab_settings へ直接置かないこと。
        # エミュレータ・自動OK・クールダウン・GitHub・自動更新・ローカル更新と
        # 区画が増えて縦に長くなっており、素のフレームだと下がはみ出したまま
        # スクロールできず、画面外の設定を操作できなくなる。
        # タイマータブ・読み上げタブと同じくスクロール枠で包む。
        self.settings_scroll = ctk.CTkScrollableFrame(self.tab_settings, fg_color="transparent")
        self.settings_scroll.pack(fill="both", expand=True)

        self.build_emulator_section(self.settings_scroll)
        self.build_auto_ok_section(self.settings_scroll)

        frame = ctk.CTkFrame(self.settings_scroll, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=(10, 20))

        ctk.CTkLabel(
            frame,
            text="連続送信を抑制する設定です。同じ検知ワードが短時間に連続した場合、\n設定した秒数が経過するまで送信を遅らせます。",
            justify="left"
        ).pack(anchor="w", pady=(0, 15))

        cooldown_enabled_default = self.db.get_setting("cooldown_enabled", "1") == "1"
        self.cooldown_enabled_var = ctk.BooleanVar(value=cooldown_enabled_default)
        self.cooldown_enabled_chk = ctk.CTkCheckBox(
            frame, text="送信間隔（クールダウン）を有効にする",
            variable=self.cooldown_enabled_var,
            command=self.on_cooldown_enabled_toggle
        )
        self.cooldown_enabled_chk.pack(anchor="w", pady=(0, 15))

        seconds_frame = ctk.CTkFrame(frame, fg_color="transparent")
        seconds_frame.pack(anchor="w", pady=(0, 10))

        ctk.CTkLabel(seconds_frame, text="最短送信間隔（秒）:").pack(side="left", padx=(0, 10))
        self.cooldown_seconds_entry = ctk.CTkEntry(seconds_frame, width=100)
        self.cooldown_seconds_entry.insert(0, normalize_number_text(self.db.get_setting("cooldown_seconds", "10")) or "10")
        self.cooldown_seconds_entry.pack(side="left")
        self.cooldown_seconds_entry.bind("<Button-3>", self._show_entry_context_menu)

        ctk.CTkButton(
            frame, text="💾 保存", command=self.save_cooldown_settings, width=120
        ).pack(anchor="w", pady=(15, 0))

        # --- GitHub連携（更新の取得元リポジトリ） ---
        github_separator = ctk.CTkFrame(self.settings_scroll, height=2, fg_color="gray30")
        github_separator.pack(fill="x", padx=20, pady=(20, 15))

        github_frame = ctk.CTkFrame(self.settings_scroll, fg_color="transparent")
        github_frame.pack(fill="x", padx=20, pady=(0, 5))

        ctk.CTkLabel(
            github_frame, text="GitHub連携（アップデートの取得元）",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", pady=(0, 5))

        ctk.CTkLabel(
            github_frame,
            text="アップデートを取得するリポジトリです。変更するとexeを作り直さずに配布元を切り替えられます。\n"
                 "「owner/repo」のほか、GitHubのURLをそのまま貼り付けても構いません。\n"
                 "⚠️ 未認証でアクセスするため、publicリポジトリである必要があります。",
            justify="left", text_color="gray70"
        ).pack(anchor="w", pady=(0, 10))

        repo_input_frame = ctk.CTkFrame(github_frame, fg_color="transparent")
        repo_input_frame.pack(anchor="w", fill="x", pady=(0, 8))

        ctk.CTkLabel(repo_input_frame, text="リポジトリ:").pack(side="left", padx=(0, 8))

        current_owner, current_repo = self.updater.get_repository()
        self.github_repo_entry = ctk.CTkEntry(repo_input_frame, width=320)
        self.github_repo_entry.insert(0, f"{current_owner}/{current_repo}")
        self.github_repo_entry.pack(side="left")
        self.github_repo_entry.bind("<Button-3>", self._show_entry_context_menu)
        self.github_repo_entry.bind("<Return>", lambda e: self.save_github_repository())

        ctk.CTkButton(repo_input_frame, text="💾 保存", width=70,
                      command=self.save_github_repository).pack(side="left", padx=(8, 0))

        self.github_test_btn = ctk.CTkButton(
            repo_input_frame, text="🔗 接続テスト", width=110,
            fg_color="#555555", hover_color="#3a3a3a",
            command=self.test_github_connection
        )
        self.github_test_btn.pack(side="left", padx=(5, 0))

        ctk.CTkButton(
            repo_input_frame, text="↩️ 既定に戻す", width=110,
            fg_color="#555555", hover_color="#3a3a3a",
            command=self.reset_github_repository
        ).pack(side="left", padx=(5, 0))

        self.github_status_label = ctk.CTkLabel(github_frame, text="", justify="left")
        self.github_status_label.pack(anchor="w")

        # --- 自動アップデート ---
        auto_update_separator = ctk.CTkFrame(self.settings_scroll, height=2, fg_color="gray30")
        auto_update_separator.pack(fill="x", padx=20, pady=(20, 15))

        auto_update_frame = ctk.CTkFrame(self.settings_scroll, fg_color="transparent")
        auto_update_frame.pack(fill="x", padx=20, pady=(0, 5))

        ctk.CTkLabel(
            auto_update_frame, text="自動アップデート",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", pady=(0, 5))

        self.auto_update_enabled_var = ctk.BooleanVar(value=self.is_auto_update_enabled())
        ctk.CTkCheckBox(
            auto_update_frame,
            text="新しいバージョンを自動でダウンロードし、終了時に適用する",
            variable=self.auto_update_enabled_var,
            command=self.on_auto_update_toggle
        ).pack(anchor="w", pady=(0, 8))

        ctk.CTkLabel(
            auto_update_frame,
            text=f"起動時と、その後{AUTO_UPDATE_CHECK_INTERVAL_HOURS}時間ごとに新しいバージョンを確認します。\n"
                 "見つかった場合は裏でダウンロードするだけなので、監視や作業は中断されません。\n"
                 "実際の差し替えはアプリを閉じたときに行われ、次に起動すると新しいバージョンになっています。\n"
                 "OFFにすると、これまでどおり確認ダイアログが出るだけになります。",
            justify="left", text_color="gray70"
        ).pack(anchor="w")

        # --- ローカルzipからのアップデート（動作確認・デバッグ用） ---
        separator = ctk.CTkFrame(self.settings_scroll, height=2, fg_color="gray30")
        separator.pack(fill="x", padx=20, pady=(20, 20))

        local_update_frame = ctk.CTkFrame(self.settings_scroll, fg_color="transparent")
        local_update_frame.pack(fill="x", padx=20, pady=(0, 20))

        ctk.CTkLabel(
            local_update_frame,
            text="アップデート（開発者向け）",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", pady=(0, 5))

        ctk.CTkLabel(
            local_update_frame,
            text="GitHubに公開せず、手元のzipファイルを直接指定してアップデートを適用できます。\n"
                 "動作確認やデバッグ用の機能です。zipの中身はGitHub配布時と同じ構成\n"
                 "（exeを含むフォルダ一式）にしてください。",
            justify="left", text_color="gray70"
        ).pack(anchor="w", pady=(0, 10))

        ctk.CTkButton(
            local_update_frame, text="📂 ローカルzipから更新", width=180,
            fg_color="#555555", hover_color="#3a3a3a",
            command=self._start_local_update
        ).pack(anchor="w")

    # ====================================================
    # 🗣️ 読み上げタブ
    # ====================================================
    def build_speech_tab(self):
        self._speech_queue = queue.Queue(maxsize=MAX_SPEECH_QUEUE_SIZE)
        self._speech_thread = None
        self._speech_thread_lock = threading.Lock()
        self._speech_history = []
        self._speech_phrases_cache = []
        self._clipboard_last_text = None
        self._clipboard_after_id = None
        # ワーカースレッドからの画面更新依頼を受け取る伝言板（_post_to_ui参照）
        self._ui_queue = queue.Queue()
        self._pump_ui_queue()

        frame = ctk.CTkScrollableFrame(self.tab_speech, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=20, pady=15)

        ctk.CTkLabel(
            frame, text="ずんだもんに読み上げてもらう",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", pady=(0, 3))

        ctk.CTkLabel(
            frame,
            text="マイクで話せないときに、打った文をキャラの声で流すための機能です。\n"
                 "読み上げにはVOICEVOXまたはAivisSpeechの起動が必要です"
                 "（声の選択は下の「🎤 読み上げの声」にあります）。",
            justify="left", text_color="gray70"
        ).pack(anchor="w", pady=(0, 10))

        # --- VOICEVOXの起動 ---
        # ⚠️ VOICEVOXのURL設定はタイマータブ側にあるが、あちらはアラーム種類が
        # 「ずんだもん」のときしか表示されない。読み上げは種類に関係なくVOICEVOXが要るため、
        # 起動まわりの操作はこのタブにも独立して置く。
        voicevox_section = ctk.CTkFrame(frame)
        voicevox_section.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            voicevox_section, text="🟢 VOICEVOXの起動",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 5))

        voicevox_path_frame = ctk.CTkFrame(voicevox_section, fg_color="transparent")
        voicevox_path_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 5))

        ctk.CTkLabel(voicevox_path_frame, text="VOICEVOXの場所:").pack(side="left", padx=(0, 8))
        self.voicevox_path_label = ctk.CTkLabel(
            voicevox_path_frame, text=self._voicevox_path_display_text(),
            text_color="gray70", anchor="w"
        )
        self.voicevox_path_label.pack(side="left", padx=(0, 8))
        ctk.CTkButton(voicevox_path_frame, text="📂 場所を選択", width=110,
                      command=self.select_voicevox_exe).pack(side="left", padx=(0, 5))
        ctk.CTkButton(voicevox_path_frame, text="▶ 今すぐ起動", width=110,
                      fg_color="green", hover_color="darkgreen",
                      command=lambda: self.start_voicevox(silent=False)).pack(side="left", padx=5)

        self.voicevox_autostart_var = ctk.BooleanVar(
            value=self.db.get_setting("voicevox_autostart", "0") == "1"
        )
        ctk.CTkCheckBox(
            voicevox_section, text="このツールの起動と同時にVOICEVOXも起動する",
            variable=self.voicevox_autostart_var,
            command=self.on_voicevox_autostart_toggle
        ).pack(anchor="w", padx=12, pady=(0, 5))

        self.voicevox_status_label = ctk.CTkLabel(
            voicevox_section, text="", justify="left", text_color="gray70"
        )
        self.voicevox_status_label.pack(anchor="w", padx=12, pady=(0, 10))

        # --- AivisSpeechの起動 ---
        # VOICEVOXと同じAPI形式の別エンジン。両方インストールしておいて、
        # アラーム・読み上げのキャラごとにどちらのエンジンを使うか選べる。
        aivisspeech_section = ctk.CTkFrame(frame)
        aivisspeech_section.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            aivisspeech_section, text="🟣 AivisSpeechの起動",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 5))

        aivisspeech_path_frame = ctk.CTkFrame(aivisspeech_section, fg_color="transparent")
        aivisspeech_path_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 5))

        ctk.CTkLabel(aivisspeech_path_frame, text="AivisSpeechの場所:").pack(side="left", padx=(0, 8))
        self.aivisspeech_path_label = ctk.CTkLabel(
            aivisspeech_path_frame, text=self._aivisspeech_path_display_text(),
            text_color="gray70", anchor="w"
        )
        self.aivisspeech_path_label.pack(side="left", padx=(0, 8))
        ctk.CTkButton(aivisspeech_path_frame, text="📂 場所を選択", width=110,
                      command=self.select_aivisspeech_exe).pack(side="left", padx=(0, 5))
        ctk.CTkButton(aivisspeech_path_frame, text="▶ 今すぐ起動", width=110,
                      fg_color="green", hover_color="darkgreen",
                      command=lambda: self.start_aivisspeech(silent=False)).pack(side="left", padx=5)

        self.aivisspeech_autostart_var = ctk.BooleanVar(
            value=self.db.get_setting("aivisspeech_autostart", "0") == "1"
        )
        ctk.CTkCheckBox(
            aivisspeech_section, text="このツールの起動と同時にAivisSpeechも起動する",
            variable=self.aivisspeech_autostart_var,
            command=self.on_aivisspeech_autostart_toggle
        ).pack(anchor="w", padx=12, pady=(0, 5))

        aivisspeech_url_frame = ctk.CTkFrame(aivisspeech_section, fg_color="transparent")
        aivisspeech_url_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 5))

        ctk.CTkLabel(aivisspeech_url_frame, text="AivisSpeech URL:").pack(side="left", padx=(0, 8))
        self.aivisspeech_url_entry = ctk.CTkEntry(aivisspeech_url_frame, width=200)
        self.aivisspeech_url_entry.insert(0, self.db.get_setting("aivisspeech_url", DEFAULT_AIVISSPEECH_URL))
        self.aivisspeech_url_entry.pack(side="left")
        self.aivisspeech_url_entry.bind("<FocusOut>", lambda e: self.save_aivisspeech_url())
        self.aivisspeech_url_entry.bind("<Return>", lambda e: self.save_aivisspeech_url())
        self.aivisspeech_url_entry.bind("<Button-3>", self._show_entry_context_menu)

        ctk.CTkButton(aivisspeech_url_frame, text="🔄 接続確認", width=100,
                      command=self.check_aivisspeech_connection).pack(side="left", padx=(8, 5))
        ctk.CTkButton(aivisspeech_url_frame, text="🔄 キャラ一覧を取得", width=150,
                      command=self.refresh_aivisspeech_speakers).pack(side="left")

        self.aivisspeech_status_label = ctk.CTkLabel(
            aivisspeech_section, text="", justify="left", text_color="gray70"
        )
        self.aivisspeech_status_label.pack(anchor="w", padx=12, pady=(0, 10))

        self.build_speech_voice_section(frame)

        # --- 貼り付け欄 ---
        self.speech_textbox = ctk.CTkTextbox(frame, height=110)
        self.speech_textbox.pack(fill="x", pady=(0, 8))
        # LINEなど他アプリからコピーした文をここに貼り付けて使う想定なので、
        # キーワード欄と同じ右クリックメニュー（切り取り/コピー/貼り付け）を付ける
        self.speech_textbox.bind("<Button-3>", self._show_entry_context_menu)
        # Ctrl+Enterで送信。改行を打ちながら書けるよう、Enter単体では送信しない
        self.speech_textbox.bind("<Control-Return>", lambda e: (self.speak_textbox_content(), "break")[1])

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(anchor="w", fill="x", pady=(0, 5))

        ctk.CTkButton(btn_frame, text="🔊 読み上げ (Ctrl+Enter)", width=190,
                      fg_color="green", hover_color="darkgreen",
                      command=self.speak_textbox_content).pack(side="left", padx=(0, 5))
        ctk.CTkButton(btn_frame, text="📋 クリップボードを読み上げ", width=190,
                      command=self.speak_clipboard_once).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="🧹 消去", width=70,
                      fg_color="gray", hover_color="#444444",
                      command=lambda: self.speech_textbox.delete("1.0", tk.END)).pack(side="left", padx=5)

        self.speech_queue_label = ctk.CTkLabel(frame, text="読み上げ待ち: なし", text_color="gray70")
        self.speech_queue_label.pack(anchor="w", pady=(0, 10))

        self.build_speech_history_section(frame)
        self.build_speech_phrase_section(frame)

        # --- クリップボード自動監視 ---
        clip_section = ctk.CTkFrame(frame)
        clip_section.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            clip_section, text="📋 クリップボード自動読み上げ",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 3))

        self.clipboard_watch_var = ctk.BooleanVar(
            value=self.db.get_setting("clipboard_watch_enabled", "0") == "1"
        )
        ctk.CTkCheckBox(
            clip_section, text="文字をコピーしたら自動で読み上げる",
            variable=self.clipboard_watch_var,
            command=self.on_clipboard_watch_toggle
        ).pack(anchor="w", padx=12, pady=(0, 5))

        ctk.CTkLabel(
            clip_section,
            text="LINEなどでメッセージをコピーすると、そのまま読み上げます。\n"
                 "ONの間はコピーした内容がすべて読み上げられるので、必要なときだけお使いください。",
            justify="left", text_color="gray70"
        ).pack(anchor="w", padx=12, pady=(0, 10))

        self.build_phone_bridge_section(frame)

    def build_speech_history_section(self, parent):
        """直前に読み上げた文の一覧。選んで「もう一度読み上げ」できる。"""
        section = ctk.CTkFrame(parent)
        section.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            section, text="🕘 読み上げた履歴",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 2))

        ctk.CTkLabel(
            section,
            text="ダブルクリックでもう一度読み上げます。履歴はアプリを閉じると消えるので、"
                 "また使う文は「⭐ 定型文に保存」しておいてください。",
            justify="left", text_color="gray70"
        ).pack(anchor="w", padx=12, pady=(0, 6))

        list_frame = ctk.CTkFrame(section, fg_color="transparent")
        list_frame.pack(fill="x", padx=12, pady=(0, 8))

        self.speech_history_listbox = tk.Listbox(
            list_frame, height=5, font=("", 11), bg="#2b2b2b", fg="#dce4ee",
            selectbackground="#1f6aa5", highlightthickness=0, bd=0, exportselection=False
        )
        y_scroll = tk.Scrollbar(list_frame, command=self.speech_history_listbox.yview)
        self.speech_history_listbox.config(yscrollcommand=y_scroll.set)
        y_scroll.pack(side="right", fill="y")
        self.speech_history_listbox.pack(side="left", fill="both", expand=True, pady=2)
        self.speech_history_listbox.bind("<Double-Button-1>", lambda e: self.replay_selected_history())

        btn_frame = ctk.CTkFrame(section, fg_color="transparent")
        btn_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 10))

        ctk.CTkButton(btn_frame, text="🔊 もう一度読み上げ", width=160,
                      fg_color="green", hover_color="darkgreen",
                      command=self.replay_selected_history).pack(side="left", padx=(0, 5))
        ctk.CTkButton(btn_frame, text="⭐ 定型文に保存", width=140,
                      command=self.save_selected_history_as_phrase).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="🧹 履歴を消去", width=110,
                      fg_color="gray", hover_color="#444444",
                      command=self.clear_speech_history).pack(side="left", padx=5)

        self._refresh_speech_history_listbox()

    def build_speech_phrase_section(self, parent):
        """よく使う文を保存しておき、ワンクリックで読み上げられるようにする一覧"""
        section = ctk.CTkFrame(parent)
        section.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            section, text="⭐ 保存した定型文",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 2))

        ctk.CTkLabel(
            section,
            text="よく使う文を保存しておくと、ダブルクリックですぐ読み上げられます。\n"
                 "ここに保存した文はスマホ側の画面にも並び、タップするだけで読み上げられます。",
            justify="left", text_color="gray70"
        ).pack(anchor="w", padx=12, pady=(0, 6))

        list_frame = ctk.CTkFrame(section, fg_color="transparent")
        list_frame.pack(fill="x", padx=12, pady=(0, 8))

        self.speech_phrase_listbox = tk.Listbox(
            list_frame, height=5, font=("", 11), bg="#2b2b2b", fg="#dce4ee",
            selectbackground="#1f6aa5", highlightthickness=0, bd=0, exportselection=False
        )
        y_scroll = tk.Scrollbar(list_frame, command=self.speech_phrase_listbox.yview)
        self.speech_phrase_listbox.config(yscrollcommand=y_scroll.set)
        y_scroll.pack(side="right", fill="y")
        self.speech_phrase_listbox.pack(side="left", fill="both", expand=True, pady=2)
        self.speech_phrase_listbox.bind("<Double-Button-1>", lambda e: self.speak_selected_phrase())

        btn_frame = ctk.CTkFrame(section, fg_color="transparent")
        btn_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 10))

        ctk.CTkButton(btn_frame, text="🔊 読み上げ", width=110,
                      fg_color="green", hover_color="darkgreen",
                      command=self.speak_selected_phrase).pack(side="left", padx=(0, 5))
        ctk.CTkButton(btn_frame, text="⭐ 入力中の文を保存", width=160,
                      command=self.save_textbox_as_phrase).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="✏️ 入力欄に取り込む", width=150,
                      command=self.load_phrase_into_textbox).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="🗑️ 削除", width=80,
                      fg_color="red", hover_color="darkred",
                      command=self.delete_selected_phrase).pack(side="left", padx=5)

        self._refresh_speech_phrase_listbox()

    # --- 履歴 ---
    def _add_speech_history(self, text):
        """読み上げた文を履歴に積む（既にある文は増やさず、最新の位置へ動かす）"""
        history = self._speech_history
        if text in history:
            history.remove(text)
        history.insert(0, text)
        del history[MAX_SPEECH_HISTORY:]
        self._refresh_speech_history_listbox()

    def _refresh_speech_history_listbox(self):
        self.speech_history_listbox.delete(0, tk.END)
        if not self._speech_history:
            self.speech_history_listbox.insert(tk.END, "  （まだ読み上げていません）")
            self.speech_history_listbox.itemconfig(0, fg="#7a7a7a")
            return
        for text in self._speech_history:
            self.speech_history_listbox.insert(tk.END, f"  {text}")

    def _selected_history_text(self):
        selection = self.speech_history_listbox.curselection()
        if not selection or not self._speech_history:
            return None
        index = selection[0]
        if index >= len(self._speech_history):
            return None
        return self._speech_history[index]

    def replay_selected_history(self):
        text = self._selected_history_text()
        if not text:
            messagebox.showinfo("未選択", "もう一度読み上げる文を履歴から選択してください。")
            return
        self.request_speech(text, source="履歴")

    def save_selected_history_as_phrase(self):
        text = self._selected_history_text()
        if not text:
            messagebox.showinfo("未選択", "定型文に保存する文を履歴から選択してください。")
            return
        self._save_phrase(text)

    def clear_speech_history(self):
        self._speech_history.clear()
        self._refresh_speech_history_listbox()

    # --- 定型文 ---
    def _refresh_speech_phrase_listbox(self, select_phrase_id=None):
        self.speech_phrase_listbox.delete(0, tk.END)
        phrases = self.db.get_speech_phrases()
        self._speech_phrases_cache = phrases

        if not phrases:
            self.speech_phrase_listbox.insert(tk.END, "  （保存した定型文はありません）")
            self.speech_phrase_listbox.itemconfig(0, fg="#7a7a7a")
            return

        for index, phrase in enumerate(phrases):
            self.speech_phrase_listbox.insert(tk.END, f"⭐ {phrase['text']}")
            if phrase["id"] == select_phrase_id:
                self.speech_phrase_listbox.selection_set(index)
                self.speech_phrase_listbox.see(index)

    def _selected_phrase(self):
        selection = self.speech_phrase_listbox.curselection()
        if not selection:
            return None
        phrases = getattr(self, "_speech_phrases_cache", [])
        index = selection[0]
        if index >= len(phrases):
            return None
        return phrases[index]

    def _save_phrase(self, text):
        success, err, phrase_id = self.db.create_speech_phrase(text)
        if not success:
            messagebox.showerror("保存エラー", f"定型文の保存に失敗しました。\n\n詳細: {err}")
            return
        self._refresh_speech_phrase_listbox(select_phrase_id=phrase_id)
        if err == "already":
            self.append_log(f"ℹ️ 「{text}」は既に定型文に保存されています。")
        else:
            self.append_log(f"⭐ 定型文に保存しました:「{text}」")

    def save_textbox_as_phrase(self):
        text = self.speech_textbox.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("入力なし", "上の入力欄に保存したい文を入力してください。")
            return
        self._save_phrase(text)

    def speak_selected_phrase(self):
        phrase = self._selected_phrase()
        if not phrase:
            messagebox.showinfo("未選択", "読み上げる定型文を一覧から選択してください。")
            return
        self.request_speech(phrase["text"], source="定型文")

    def load_phrase_into_textbox(self):
        phrase = self._selected_phrase()
        if not phrase:
            messagebox.showinfo("未選択", "取り込む定型文を一覧から選択してください。")
            return
        self.speech_textbox.delete("1.0", tk.END)
        self.speech_textbox.insert("1.0", phrase["text"])

    def delete_selected_phrase(self):
        phrase = self._selected_phrase()
        if not phrase:
            messagebox.showinfo("未選択", "削除する定型文を一覧から選択してください。")
            return
        if not messagebox.askyesno("確認", f"定型文「{phrase['text']}」を削除します。\n\nよろしいですか？"):
            return
        success, err = self.db.delete_speech_phrase(phrase["id"])
        if success:
            self._refresh_speech_phrase_listbox()
            self.append_log(f"🗑️ 定型文を削除しました:「{phrase['text']}」")
        else:
            messagebox.showerror("削除エラー", f"定型文の削除に失敗しました。\n\n詳細: {err}")

    def build_speech_voice_section(self, parent):
        """読み上げに使う声（キャラ・スタイル）と音量の設定エリア"""
        section = ctk.CTkFrame(parent)
        section.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            section, text="🎤 読み上げの声",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 3))

        ctk.CTkLabel(
            section,
            text="VOICEVOXやAivisSpeechに入っているキャラから選べます。アラーム音の声とは別に設定できます。",
            justify="left", text_color="gray70"
        ).pack(anchor="w", padx=12, pady=(0, 8))

        speakers = self.get_all_speakers()
        saved_id = self.get_speech_speaker_id()
        char_name, style_name = self.find_speaker_by_id(saved_id)
        if char_name not in speakers:
            char_name = next(iter(speakers))
            style_name = next(iter(speakers[char_name]))

        voice_frame = ctk.CTkFrame(section, fg_color="transparent")
        voice_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(voice_frame, text="キャラ:").pack(side="left", padx=(0, 6))
        self.speech_char_var = ctk.StringVar(value=char_name)
        self.speech_char_menu = ctk.CTkOptionMenu(
            voice_frame, variable=self.speech_char_var, values=sorted(speakers.keys()),
            command=self.on_speech_char_change, width=170
        )
        self.speech_char_menu.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(voice_frame, text="スタイル:").pack(side="left", padx=(0, 6))
        self.speech_style_var = ctk.StringVar(value=style_name)
        self.speech_style_menu = ctk.CTkOptionMenu(
            voice_frame, variable=self.speech_style_var,
            values=list(speakers.get(char_name, {"ノーマル": 3}).keys()),
            command=self.on_speech_style_change, width=140
        )
        self.speech_style_menu.pack(side="left", padx=(0, 12))

        ctk.CTkButton(voice_frame, text="🔄 キャラ一覧を取得", width=150,
                      command=self.refresh_voicevox_speakers).pack(side="left", padx=(0, 5))

        vol_frame = ctk.CTkFrame(section, fg_color="transparent")
        vol_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 10))

        ctk.CTkLabel(vol_frame, text="音量:").pack(side="left", padx=(0, 8))
        saved_volume = self.get_speech_volume()
        self.speech_volume_var = ctk.IntVar(value=saved_volume)
        ctk.CTkSlider(
            vol_frame, from_=0, to=100, number_of_steps=100,
            variable=self.speech_volume_var, command=self.on_speech_volume_change, width=220
        ).pack(side="left", padx=(0, 8))
        self.speech_volume_label = ctk.CTkLabel(vol_frame, text=f"{saved_volume}%", width=45)
        self.speech_volume_label.pack(side="left", padx=(0, 12))

        ctk.CTkButton(vol_frame, text="🔊 試聴", width=90,
                      command=self.test_speech_voice).pack(side="left")

        self.build_audio_output_section(section)

    def build_audio_output_section(self, parent):
        """読み上げ・アラームを鳴らす出力デバイスを選ぶエリア"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(anchor="w", fill="x", padx=12, pady=(0, 10))

        ctk.CTkLabel(row, text="出力先:").pack(side="left", padx=(0, 8))

        devices = self.list_output_devices()
        saved = self._match_saved_device(
            (self.db.get_setting("audio_output_device", "") or "").strip(),
            devices, self.AUDIO_OUTPUT_DEFAULT_LABEL)
        # 名前が切り詰められた分（旧バージョンからの引き継ぎ）は、
        # 今の表記に置き換えて保存し直す
        if saved != self.AUDIO_OUTPUT_DEFAULT_LABEL:
            self.db.save_setting("audio_output_device", saved)
        self.audio_output_var = ctk.StringVar(value=saved)
        self.audio_output_menu = ctk.CTkOptionMenu(
            row, variable=self.audio_output_var, values=devices,
            command=self.on_audio_output_change, width=290)
        self.audio_output_menu.pack(side="left", padx=(0, 8))

        ctk.CTkButton(row, text="🔄", width=36,
                      command=self.refresh_output_devices).pack(side="left", padx=(0, 8))

        if sounddevice is None:
            # 出せない理由を黙って隠さない
            ctk.CTkLabel(
                row, text="※ この環境では出力先を選べません（既定のデバイスに鳴ります）",
                text_color="#d08a4a").pack(side="left")
        else:
            ctk.CTkLabel(
                row, text="※ VB-CABLE等を選ぶと、その先へ声を流せます",
                text_color="gray70").pack(side="left")

        self.build_audio_input_section(parent)

    def build_audio_input_section(self, parent):
        """マイク（入力デバイス）を選ぶエリア"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(anchor="w", fill="x", padx=12, pady=(0, 4))

        ctk.CTkLabel(row, text="マイク:").pack(side="left", padx=(0, 8))

        devices = self.list_input_devices()
        saved = self._match_saved_device(
            (self.db.get_setting("audio_input_device", "") or "").strip(),
            devices, self.AUDIO_INPUT_DEFAULT_LABEL)
        if saved != self.AUDIO_INPUT_DEFAULT_LABEL:
            self.db.save_setting("audio_input_device", saved)
        self.audio_input_var = ctk.StringVar(value=saved)
        self.audio_input_menu = ctk.CTkOptionMenu(
            row, variable=self.audio_input_var, values=devices,
            command=self.on_audio_input_change, width=290)
        self.audio_input_menu.pack(side="left", padx=(0, 8))

        ctk.CTkButton(row, text="🔄", width=36,
                      command=self.refresh_input_devices).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="🎙️ 拾えるか確認", width=130,
                      command=self.check_input_level).pack(side="left")

        pass_row = ctk.CTkFrame(parent, fg_color="transparent")
        pass_row.pack(anchor="w", fill="x", padx=12, pady=(0, 10))

        self.input_passthrough_var = ctk.BooleanVar(value=False)
        self.input_passthrough_check = ctk.CTkCheckBox(
            pass_row, text="マイクの音を出力先へ流す",
            variable=self.input_passthrough_var,
            command=self.on_input_passthrough_toggle)
        self.input_passthrough_check.pack(side="left", padx=(0, 10))

        self.input_status_label = ctk.CTkLabel(pass_row, text="", text_color="gray70")
        self.input_status_label.pack(side="left")

        if sounddevice is None:
            self.input_passthrough_check.configure(state="disabled")
            self._set_input_status("※ この環境ではマイクを扱えません", "#d08a4a")
        else:
            self._set_input_status("※ 自分の声と読み上げを、同じ出力先にまとめられます")

    def _set_input_status(self, text, color="gray70"):
        self.input_status_label.configure(text=text, text_color=color)

    def _sync_passthrough_ui(self):
        """転送が止まったときに、チェックの状態を実態に合わせる"""
        if not self.is_input_passthrough_running():
            self.input_passthrough_var.set(False)
            self._set_input_status("※ マイクの転送は止まっています")

    def refresh_input_devices(self):
        devices = self.list_input_devices()
        self.audio_input_menu.configure(values=devices)
        if self.audio_input_var.get() not in devices:
            self.audio_input_var.set(self.AUDIO_INPUT_DEFAULT_LABEL)
            self.db.save_setting("audio_input_device", "")
            self.append_log("ℹ️ 選んでいたマイクが見つからないため、既定に戻しました。")
        self.append_log(f"🔄 マイクの一覧を更新しました（{len(devices) - 1}件）。")

    def on_audio_input_change(self, name=None):
        chosen = self.audio_input_var.get()
        if chosen == self.AUDIO_INPUT_DEFAULT_LABEL:
            self.db.save_setting("audio_input_device", "")
            self.append_log("⚙️ マイクを既定のデバイスにしました。")
        else:
            self.db.save_setting("audio_input_device", chosen)
            self.append_log(f"⚙️ マイクを「{chosen}」にしました。")
        # 転送中にマイクを変えたら、新しいマイクで開き直す
        if self.is_input_passthrough_running():
            self.stop_input_passthrough()
            started, reason = self.start_input_passthrough()
            if not started:
                self.input_passthrough_var.set(False)
                self._set_input_status(f"⚠️ {reason.splitlines()[0]}", "#d08a4a")

    def check_input_level(self):
        """マイクが拾えているかを、実際に少し録って確かめる"""
        self._set_input_status("マイクを確認しています...")
        self.update_idletasks()

        def run():
            level, reason = self.measure_input_level()
            if level is None:
                self._post_to_ui(lambda: self._set_input_status(f"⚠️ {reason}", "#d08a4a"))
                self._post_to_ui(lambda: self.append_log(f"⚠️ マイクの確認: {reason}"))
                return
            if level < 2:
                text, color = f"音を拾えていません（音量 {level}%）。話しながらもう一度お試しください。", "#d08a4a"
            else:
                text, color = f"✅ 拾えています（音量 {level}%）", "#4a9e4a"
            self._post_to_ui(lambda: self._set_input_status(text, color))
            self._post_to_ui(lambda: self.append_log(f"🎙️ マイクの確認: 音量 {level}%"))

        threading.Thread(target=run, daemon=True).start()

    def on_input_passthrough_toggle(self):
        if self.input_passthrough_var.get():
            started, reason = self.start_input_passthrough()
            if not started:
                self.input_passthrough_var.set(False)
                self._set_input_status(f"⚠️ {reason.splitlines()[0]}", "#d08a4a")
                messagebox.showwarning("マイクの転送", reason)
                return
            out = self.get_audio_output_device()
            self._set_input_status(f"🔴 転送中 → {out}", "#4a9e4a")
            self.append_log(f"🔴 マイクの音を「{out}」へ流し始めました。")
        else:
            self.stop_input_passthrough()
            self._set_input_status("※ 自分の声と読み上げを、同じ出力先にまとめられます")
            self.append_log("⏹️ マイクの転送を止めました。")

    def refresh_output_devices(self):
        """つなぎ直した機器を拾い直す"""
        devices = self.list_output_devices()
        self.audio_output_menu.configure(values=devices)
        if self.audio_output_var.get() not in devices:
            self.audio_output_var.set(self.AUDIO_OUTPUT_DEFAULT_LABEL)
            self.db.save_setting("audio_output_device", "")
            self.append_log("ℹ️ 選んでいた出力先が見つからないため、既定のデバイスに戻しました。")
        self.append_log(f"🔄 出力先の一覧を更新しました（{len(devices) - 1}件）。")

    def on_audio_output_change(self, name=None):
        chosen = self.audio_output_var.get()
        if chosen == self.AUDIO_OUTPUT_DEFAULT_LABEL:
            self.db.save_setting("audio_output_device", "")
            self.append_log("⚙️ 出力先を既定のデバイスにしました。")
        else:
            self.db.save_setting("audio_output_device", chosen)
            self.append_log(f"⚙️ 出力先を「{chosen}」にしました。")
        # 選び直したら、前の機器で出した警告は忘れる
        self._warned_output_device = None

    def on_speech_char_change(self, char_name=None):
        """キャラを変えたら、そのキャラが持つスタイルにプルダウンを差し替える"""
        speakers = self.get_all_speakers()
        styles = speakers.get(self.speech_char_var.get(), {})
        if not styles:
            return
        names = list(styles.keys())
        self.speech_style_menu.configure(values=names)
        if self.speech_style_var.get() not in styles:
            self.speech_style_var.set(names[0])
        self.on_speech_style_change()

    def on_speech_style_change(self, style_name=None):
        speakers = self.get_all_speakers()
        char = self.speech_char_var.get()
        style = self.speech_style_var.get()
        speaker_id = speakers.get(char, {}).get(style)
        if speaker_id is None:
            return
        self.db.save_setting("speech_speaker_id", str(speaker_id))
        self.append_log(f"⚙️ 読み上げの声を「{char} / {style}」に設定しました。")

    def on_speech_volume_change(self, value):
        volume = int(float(value))
        self.speech_volume_label.configure(text=f"{volume}%")
        # ドラッグ中に毎回DBへ書かないよう、少し待ってからまとめて保存する
        pending_id = getattr(self, "_speech_volume_save_id", None)
        if pending_id is not None:
            try:
                self.after_cancel(pending_id)
            except Exception:
                pass
        self._speech_volume_save_id = self.after(
            300, lambda: self.db.save_setting("speech_volume", str(volume))
        )

    def refresh_voicevox_speakers(self):
        """VOICEVOXから全キャラを取り直してプルダウンに反映する"""
        self.append_log("🔄 VOICEVOXからキャラ一覧を取得しています...")

        def run():
            try:
                speakers = self.fetch_voicevox_speakers()
            except Exception as e:
                message = (
                    f"VOICEVOXからキャラ一覧を取得できませんでした。\n\n"
                    f"URL: {self.get_voicevox_url()}\n詳細: {e}\n\n"
                    "VOICEVOXを起動してから、もう一度お試しください。"
                )
                self._post_to_ui(lambda: messagebox.showerror("取得できません", message))
                self._post_to_ui(lambda: self.append_log("⚠️ キャラ一覧を取得できませんでした。"))
                return
            self._post_to_ui(lambda: self._apply_voicevox_speakers(speakers))

        threading.Thread(target=run, daemon=True).start()

    def refresh_aivisspeech_speakers(self):
        """AivisSpeechから全キャラを取り直してプルダウンに反映する（VOICEVOX版と同じ形）"""
        self.append_log("🔄 AivisSpeechからキャラ一覧を取得しています...")

        def run():
            try:
                speakers = self.fetch_aivisspeech_speakers()
            except Exception as e:
                message = (
                    f"AivisSpeechからキャラ一覧を取得できませんでした。\n\n"
                    f"URL: {self.get_aivisspeech_url()}\n詳細: {e}\n\n"
                    "AivisSpeechを起動してから、もう一度お試しください。"
                )
                self._post_to_ui(lambda: messagebox.showerror("取得できません", message))
                self._post_to_ui(lambda: self.append_log("⚠️ キャラ一覧を取得できませんでした。"))
                return
            self._post_to_ui(lambda: self._apply_aivisspeech_speakers(speakers))

        threading.Thread(target=run, daemon=True).start()

    def _refresh_voice_dropdowns(self):
        """
        キャラ選択プルダウン(アラーム/読み上げ)を、いま分かっている全エンジンの
        キャラ(get_all_speakers)で作り直す。

        ⚠️ どちらか一方のエンジンだけを取得し直した場合でも、必ずここを通して
        「取得済みの全エンジン分」で作り直すこと。取得した側の一覧だけで
        プルダウンを差し替えると、もう一方のエンジンの選択肢が消えてしまう。
        """
        speakers = self.get_all_speakers()
        names = sorted(speakers.keys())
        # 読み上げタブとアラーム（タイマータブ）は同じキャラ一覧を共有する
        for char_var, char_menu, on_change in (
            (getattr(self, "speech_char_var", None), getattr(self, "speech_char_menu", None),
             self.on_speech_char_change),
            (getattr(self, "alarm_char_var", None), getattr(self, "alarm_char_menu", None),
             self.on_alarm_char_change),
        ):
            if char_var is None or char_menu is None:
                continue
            char_menu.configure(values=names)
            if names and char_var.get() not in speakers:
                char_var.set(names[0])
            on_change()

    def _apply_voicevox_speakers(self, speakers):
        """取得したVOICEVOXのキャラ一覧を保存し、両方のプルダウンに反映する"""
        self._voicevox_speakers = speakers
        self.db.save_setting("voicevox_speakers", json.dumps(speakers, ensure_ascii=False))
        # 合成結果のキャッシュは話者IDごとなので捨てなくてよいが、
        # スタイル構成が変わった可能性があるため念のため空にする
        self._zundamon_wav_cache = {}
        self._refresh_voice_dropdowns()

        total_styles = sum(len(v) for v in speakers.values())
        self.append_log(f"✅ VOICEVOXから{len(speakers)}キャラ・{total_styles}スタイルを読み込みました。")
        messagebox.showinfo(
            "取得しました",
            f"{len(speakers)}キャラ・{total_styles}スタイルを読み込みました。\n"
            "「キャラ」と「スタイル」から選んでください。"
        )

    def _apply_aivisspeech_speakers(self, speakers):
        """取得したAivisSpeechのキャラ一覧を保存し、両方のプルダウンに反映する"""
        self._aivisspeech_speakers = speakers
        self.db.save_setting("aivisspeech_speakers", json.dumps(speakers, ensure_ascii=False))
        self._aivisspeech_wav_cache = {}
        self._refresh_voice_dropdowns()

        total_styles = sum(len(v) for v in speakers.values())
        self.append_log(f"✅ AivisSpeechから{len(speakers)}キャラ・{total_styles}スタイルを読み込みました。")
        messagebox.showinfo(
            "取得しました",
            f"{len(speakers)}キャラ・{total_styles}スタイルを読み込みました。\n"
            "「キャラ」と「スタイル」から選んでください。"
        )

    def test_speech_voice(self):
        """現在の声・音量で試聴する"""
        if self.get_speech_volume() == 0:
            messagebox.showinfo("音量0", "音量が0のため音は鳴りません。スライダーを上げてください。")
            return
        char = self.speech_char_var.get()
        self.request_speech(f"{char}の声で読み上げます。", source="試聴")

    def build_phone_bridge_section(self, parent):
        """スマホから文字を送って読み上げさせるための設定エリア"""
        section = ctk.CTkFrame(parent)
        section.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            section, text="📱 スマホから送って読み上げ",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 3))

        ctk.CTkLabel(
            section,
            text="ONにすると、同じWi-Fiにいるスマホのブラウザから文を送れるようになります。\n"
                 "スマホで打った文が、そのままPCのずんだもんの声で流れます。\n"
                 "⚠️ 同じネットワークの人が音を出せてしまわないよう、送信には暗証番号が必要です。",
            justify="left", text_color="gray70"
        ).pack(anchor="w", padx=12, pady=(0, 8))

        self.phone_bridge_var = ctk.BooleanVar(
            value=self.db.get_setting("phone_bridge_enabled", "0") == "1"
        )
        ctk.CTkCheckBox(
            section, text="スマホからの受け取りを有効にする",
            variable=self.phone_bridge_var,
            command=self.on_phone_bridge_toggle
        ).pack(anchor="w", padx=12, pady=(0, 8))

        # ⚠️ スマホのブラウザでマイク（音声認識）を使うには「安全なページ(https)」が要る。
        # 平文HTTPだとブラウザがマイクを開かせてくれないため、この切り替えを用意する。
        self.phone_bridge_https_var = ctk.BooleanVar(
            value=self.db.get_setting("phone_bridge_https", "0") == "1"
        )
        https_check = ctk.CTkCheckBox(
            section, text="HTTPSで配信する（スマホのマイクで話すために必要）",
            variable=self.phone_bridge_https_var,
            command=self.on_phone_bridge_https_toggle
        )
        https_check.pack(anchor="w", padx=12, pady=(0, 4))
        if x509 is None:
            https_check.configure(state="disabled")
            ctk.CTkLabel(
                section, text="※ この環境ではHTTPSを使えません（証明書を作る部品がありません）",
                text_color="#d08a4a", justify="left"
            ).pack(anchor="w", padx=12, pady=(0, 6))

        self.phone_bridge_info_label = ctk.CTkLabel(
            section, text="", justify="left", font=ctk.CTkFont(size=13)
        )
        self.phone_bridge_info_label.pack(anchor="w", padx=12, pady=(0, 5))

        phone_btn_frame = ctk.CTkFrame(section, fg_color="transparent")
        phone_btn_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 10))

        ctk.CTkButton(phone_btn_frame, text="🔢 暗証番号を作り直す", width=160,
                      fg_color="#555555", hover_color="#3a3a3a",
                      command=self.regenerate_phone_bridge_pin).pack(side="left", padx=(0, 5))
        ctk.CTkButton(phone_btn_frame, text="📋 URLをコピー", width=130,
                      fg_color="#555555", hover_color="#3a3a3a",
                      command=self.copy_phone_bridge_url).pack(side="left", padx=5)

        self._refresh_phone_bridge_info()

    # ====================================================
    # 🗣️ 読み上げ（ずんだもん）
    # ====================================================
    def _ensure_speech_worker(self):
        """
        読み上げ専用のワーカースレッドを（まだ無ければ）起こす。

        貼り付け欄・クリップボード・スマホの3系統から同時に要求が来るため、
        1本のキューに集約して順番に処理する。winsoundの再生は終わるまでブロックするので、
        ここを通さずに各所から直接鳴らすと音が重なったり、UIが固まったりする。

        ⚠️ スマホ連携のサーバーはリクエストごとに別スレッドで動くため、この関数は
        複数スレッドから同時に呼ばれうる。ロックなしだと「まだ無い」と判断した2本が
        それぞれワーカーを起こし、同じキューを2本で食い合って音が重なってしまう。
        （＝キューで直列化した意味がなくなる）
        """
        with self._speech_thread_lock:
            if self._speech_thread is not None and self._speech_thread.is_alive():
                return
            self._speech_thread = threading.Thread(target=self._speech_worker, daemon=True)
            self._speech_thread.start()

    def _post_to_ui(self, callback):
        """
        ワーカースレッドからUIスレッドへ処理を渡す。

        ⚠️ ここで self.after() を直接呼んではいけない。after()の内部で行う
        Tclへの登録は、メインスレッド以外から呼ぶと例外になるか、
        Tclインタプリタのロック待ちで「そのまま止まる」かのどちらかになる。
        止まった場合、読み上げワーカーは次の1件に進めず、以後まったく喋らなくなる。

        そこで、ワーカーはTkにいっさい触れず、ただのキューに用件を置くだけにする。
        取り出して実行するのはメインスレッド側(_pump_ui_queue)の仕事。
        """
        self._ui_queue.put(callback)

    # UI更新の失敗を記録する種類の上限。
    # 同じ失敗が毎周回で起きてもファイルを溢れさせないための歯止め。
    MAX_UI_ERROR_KINDS = 20

    def _record_ui_callback_error(self, detail):
        """UI更新の失敗を残す（同じ内容は1度だけ／ループは止めない）"""
        seen = getattr(self, "_ui_error_seen", None)
        if seen is None:
            seen = self._ui_error_seen = {}
        key = (detail.strip().splitlines() or ["unknown"])[-1][:200]
        seen[key] = seen.get(key, 0) + 1
        if seen[key] != 1 or len(seen) > self.MAX_UI_ERROR_KINDS:
            return
        write_error_log(f"UI更新の処理に失敗しました:\n{detail}")
        # 画面にも一度だけ知らせる。ここでの失敗が再帰しないよう印を立てる。
        if not getattr(self, "_ui_error_notified", False):
            self._ui_error_notified = True
            try:
                self.append_log(
                    "⚠️ 画面の更新処理でエラーが発生しました。"
                    f"詳細は {os.path.basename(ERROR_LOG_FILE)} を確認してください。")
            except Exception:
                pass

    def _pump_ui_queue(self):
        """
        ワーカーから届いた用件をメインスレッドで実行する。
        起動中はずっと回り続けるため、1件の失敗でループが途切れないようにする。
        """
        try:
            while True:
                try:
                    callback = self._ui_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    callback()
                except Exception:
                    # ⚠️ 握りつぶすだけにしてはいけない。
                    # ここはワーカーからUIへの用件が すべて 通る一本道なので、
                    # 何も残さないと「ログが出ない」「読み上げ履歴が増えない」
                    # といった症状の手掛かりが完全に消える。
                    # ループは止めず、同じ内容は1度だけ記録する。
                    self._record_ui_callback_error(traceback.format_exc())
        finally:
            # 終了処理に入っていたら予約し直さない（破棄後の発火を避ける）
            if not getattr(self, "_closing", False):
                try:
                    self._pump_after_id = self.after(120, self._pump_ui_queue)
                except tk.TclError:
                    pass

    def request_speech(self, text, source=""):
        """
        読み上げを依頼する。どのスレッドから呼んでもよい。
        戻り値: 受け付けたらTrue、待ち行列が一杯で捨てたらFalse。
        """
        text = (text or "").strip()
        if not text:
            return False
        text = text[:MAX_SPEECH_TEXT_LENGTH]

        self._ensure_speech_worker()
        try:
            self._speech_queue.put_nowait((text, source))
        except queue.Full:
            # 連打や誤送信で延々と喋り続けないよう、溢れた分は捨てる
            self._post_to_ui(lambda: self.append_log("⚠️ 読み上げの待ち行列が一杯のため、1件を破棄しました。"))
            return False

        label = f"[{source}] " if source else ""
        self._post_to_ui(lambda: self.append_log(f"🗣️ 読み上げ: {label}「{text}」"))
        self._post_to_ui(lambda: self._add_speech_history(text))
        self._post_to_ui(self._refresh_speech_queue_label)
        return True

    def _speech_worker(self):
        """
        キューから1件ずつ取り出して、合成→再生を最後まで行う。
        このスレッドが死ぬと以後まったく喋らなくなるため、
        1件の失敗が全体を巻き込まないよう、必ず握りつぶして次へ進む。
        """
        while True:
            text, _source = self._speech_queue.get()
            voice_selector = self.get_speech_speaker_id()
            try:
                # 読み上げはアラームとは別の声・音量を使う
                wav_data = self.synthesize_voice_wav(text, voice_selector)
                self._play_wav_bytes(wav_data, self.get_speech_volume())
            except Exception as e:
                # エンジン未起動などで失敗しても、ワーカーごと止めてはいけない
                engine, _ = self._split_voice_selector(voice_selector)
                message = (
                    f"⚠️ 読み上げに失敗しました（{e}）。"
                    f"{TTS_ENGINES[engine]['label']}が起動しているか確認してください。"
                )
                self._post_to_ui(lambda m=message: self.append_log(m))
            finally:
                # ここで例外が漏れるとワーカーごと止まり、以後まったく喋らなくなる
                try:
                    self._speech_queue.task_done()
                except Exception:
                    pass
                self._post_to_ui(self._refresh_speech_queue_label)

    def _refresh_speech_queue_label(self):
        waiting = self._speech_queue.qsize()
        self.speech_queue_label.configure(
            text=f"読み上げ待ち: {waiting}件" if waiting else "読み上げ待ち: なし"
        )

    def speak_textbox_content(self):
        """貼り付け欄の内容を読み上げる。読み上げたら欄は空にして、次の文をすぐ打てるようにする。"""
        text = self.speech_textbox.get("1.0", tk.END).strip()
        if not text:
            return
        if self.request_speech(text, source="手入力"):
            self.speech_textbox.delete("1.0", tk.END)

    def _read_clipboard_text(self):
        """クリップボードの文字列を取り出す（画像など文字以外が入っている場合はNone）"""
        try:
            return self.clipboard_get()
        except tk.TclError:
            return None

    def speak_clipboard_once(self):
        text = (self._read_clipboard_text() or "").strip()
        if not text:
            messagebox.showinfo("クリップボード", "クリップボードに文字が入っていません。")
            return
        # 手動で押した分は、自動監視が同じ内容を二重に読まないよう記憶しておく
        self._clipboard_last_text = text
        self.request_speech(text, source="クリップボード")

    def on_clipboard_watch_toggle(self):
        enabled = self.clipboard_watch_var.get()
        self.db.save_setting("clipboard_watch_enabled", "1" if enabled else "0")
        if enabled:
            # ONにした瞬間に、既にコピー済みの内容を読み上げてしまわないようにする
            self._clipboard_last_text = (self._read_clipboard_text() or "").strip()
            self._watch_clipboard()
            self.append_log("⚙️ クリップボードの自動読み上げを ON にしました。")
        else:
            if self._clipboard_after_id is not None:
                self.after_cancel(self._clipboard_after_id)
                self._clipboard_after_id = None
            self.append_log("⚙️ クリップボードの自動読み上げを OFF にしました。")

    def _watch_clipboard(self):
        """クリップボードを定期的に見て、内容が変わっていたら読み上げる"""
        if getattr(self, "_closing", False) or not self.clipboard_watch_var.get():
            self._clipboard_after_id = None
            return
        text = (self._read_clipboard_text() or "").strip()
        if text and text != self._clipboard_last_text:
            self._clipboard_last_text = text
            self.request_speech(text, source="クリップボード")
        self._clipboard_after_id = self.after(700, self._watch_clipboard)

    # --- VOICEVOXの自動起動 ---
    def get_voicevox_exe_path(self):
        return self.db.get_setting("voicevox_exe_path", "") or ""

    def is_voicevox_ready(self, timeout=2):
        """VOICEVOXエンジンが応答するか（＝すでに起動しているか）を確かめる"""
        try:
            self._voicevox_request("/version", timeout=timeout)
            return True
        except Exception:
            return False

    def select_voicevox_exe(self):
        path = filedialog.askopenfilename(
            title="VOICEVOXの実行ファイル(VOICEVOX.exe)を選択",
            filetypes=[("実行ファイル", "*.exe"), ("すべてのファイル", "*.*")]
        )
        if not path:
            return
        self.db.save_setting("voicevox_exe_path", path)
        self.voicevox_path_label.configure(text=self._voicevox_path_display_text())
        self.append_log(f"✅ VOICEVOXの場所を設定しました: {os.path.basename(path)}")

    def _voicevox_path_display_text(self):
        path = self.get_voicevox_exe_path()
        return os.path.basename(path) if path else "未設定"

    def on_voicevox_autostart_toggle(self):
        enabled = self.voicevox_autostart_var.get()
        self.db.save_setting("voicevox_autostart", "1" if enabled else "0")
        self.append_log(f"⚙️ VOICEVOXの同時起動を {'ON' if enabled else 'OFF'} にしました。")
        if enabled and not self.get_voicevox_exe_path():
            messagebox.showinfo(
                "VOICEVOXの場所",
                "VOICEVOXの実行ファイルの場所を設定してください。\n"
                "「📂 場所を選択」から VOICEVOX.exe を指定します。"
            )

    def start_voicevox(self, silent=False):
        """
        VOICEVOXを起動する。すでに起動していれば何もしない。
        起動には時間がかかるため、待ち受けは必ずワーカースレッドで行う。
        """
        path = self.get_voicevox_exe_path()
        if not path or not os.path.exists(path):
            message = (
                "VOICEVOXの場所が設定されていません。「📂 場所を選択」から指定してください。"
                if not path else
                f"設定されたVOICEVOXが見つかりません: {path}"
            )
            self._set_voicevox_status(f"⚠️ {message}", "#d08a4a")
            self.append_log(f"⚠️ {message}")
            if not silent:
                messagebox.showwarning("VOICEVOX", message)
            return

        self._set_voicevox_status("VOICEVOXの状態を確認しています...", "gray70")

        # 起動待ちは最大90秒ループするため、画面更新は必ず_post_to_ui経由で行う。
        # ここで直接 self.after() を呼ぶと、Tclのロック待ちでこのスレッドが止まり、
        # 起動が終わっても画面がいつまでも「確認中」のままになりうる。
        def run():
            if self.is_voicevox_ready():
                self._post_to_ui(lambda: self._on_voicevox_ready(already_running=True))
                return

            try:
                # 別プロセスとして起動し、こちらの終了に巻き込まれないようにする
                self._voicevox_process = subprocess.Popen([path], cwd=os.path.dirname(path) or None)
            except Exception as e:
                # except節を抜けると変数eは消える。_post_to_uiのlambdaは後からメインスレッドで
                # 実行されるため、lambda内でeを参照するとNameErrorになり、
                # 肝心の失敗理由が表示されない。先に文字列へ組み立てておく。
                message = f"起動に失敗しました: {e}"
                self._post_to_ui(lambda: self._on_voicevox_failed(message, silent))
                return

            self._post_to_ui(lambda: self._set_voicevox_status(
                "VOICEVOXを起動しています...（初回は時間がかかります）", "gray70"))

            # エンジンが応答を返せるようになるまで待つ。
            # プロセスが立ち上がっただけでは合成できないため、/version が通るまでを「起動完了」とする。
            deadline = time.time() + VOICEVOX_STARTUP_TIMEOUT_SECONDS
            while time.time() < deadline:
                if self.is_voicevox_ready():
                    self._post_to_ui(lambda: self._on_voicevox_ready(already_running=False))
                    return
                time.sleep(2)

            self._post_to_ui(lambda: self._on_voicevox_failed(
                f"{VOICEVOX_STARTUP_TIMEOUT_SECONDS}秒待っても応答がありませんでした。", silent))

        threading.Thread(target=run, daemon=True).start()

    def _on_voicevox_ready(self, already_running):
        if already_running:
            self._set_voicevox_status("✅ VOICEVOXは既に起動しています。", "#4a9e4a")
            self.append_log("✅ VOICEVOXは既に起動していました。")
        else:
            self._set_voicevox_status("✅ VOICEVOXの起動が完了しました。", "#4a9e4a")
            self.append_log("✅ VOICEVOXを起動しました。読み上げが使えます。")

    def _on_voicevox_failed(self, message, silent):
        self._set_voicevox_status(f"⚠️ {message}", "#d08a4a")
        self.append_log(f"⚠️ VOICEVOX: {message}")
        if not silent:
            messagebox.showwarning("VOICEVOX", message)

    def _set_voicevox_status(self, text, color="gray70"):
        self.voicevox_status_label.configure(text=text, text_color=color)

    # --- AivisSpeechの自動起動 ---
    # ⚠️ VOICEVOXの起動処理と1対1で対応している（同じ罠・同じ対策も含めて）。
    # 特に start_aivisspeech の except節: 節を抜けると変数eは消えるため、
    # _post_to_ui に渡すlambdaの中でeを直接参照するとNameErrorになり、
    # 肝心の失敗理由が表示されない。VOICEVOX版と同じく、先に文字列へ組み立てておく。
    def get_aivisspeech_exe_path(self):
        return self.db.get_setting("aivisspeech_exe_path", "") or ""

    def is_aivisspeech_ready(self, timeout=2):
        """AivisSpeechエンジンが応答するか（＝すでに起動しているか）を確かめる"""
        try:
            self._aivisspeech_request("/version", timeout=timeout)
            return True
        except Exception:
            return False

    def select_aivisspeech_exe(self):
        path = filedialog.askopenfilename(
            title="AivisSpeechの実行ファイル(AivisSpeech.exe)を選択",
            filetypes=[("実行ファイル", "*.exe"), ("すべてのファイル", "*.*")]
        )
        if not path:
            return
        self.db.save_setting("aivisspeech_exe_path", path)
        self.aivisspeech_path_label.configure(text=self._aivisspeech_path_display_text())
        self.append_log(f"✅ AivisSpeechの場所を設定しました: {os.path.basename(path)}")

    def _aivisspeech_path_display_text(self):
        path = self.get_aivisspeech_exe_path()
        return os.path.basename(path) if path else "未設定"

    def on_aivisspeech_autostart_toggle(self):
        enabled = self.aivisspeech_autostart_var.get()
        self.db.save_setting("aivisspeech_autostart", "1" if enabled else "0")
        self.append_log(f"⚙️ AivisSpeechの同時起動を {'ON' if enabled else 'OFF'} にしました。")
        if enabled and not self.get_aivisspeech_exe_path():
            messagebox.showinfo(
                "AivisSpeechの場所",
                "AivisSpeechの実行ファイルの場所を設定してください。\n"
                "「📂 場所を選択」から AivisSpeech.exe を指定します。"
            )

    def start_aivisspeech(self, silent=False):
        """
        AivisSpeechを起動する。すでに起動していれば何もしない。
        起動には時間がかかるため、待ち受けは必ずワーカースレッドで行う。
        """
        path = self.get_aivisspeech_exe_path()
        if not path or not os.path.exists(path):
            message = (
                "AivisSpeechの場所が設定されていません。「📂 場所を選択」から指定してください。"
                if not path else
                f"設定されたAivisSpeechが見つかりません: {path}"
            )
            self._set_aivisspeech_status(f"⚠️ {message}", "#d08a4a")
            self.append_log(f"⚠️ {message}")
            if not silent:
                messagebox.showwarning("AivisSpeech", message)
            return

        self._set_aivisspeech_status("AivisSpeechの状態を確認しています...", "gray70")

        def run():
            if self.is_aivisspeech_ready():
                self._post_to_ui(lambda: self._on_aivisspeech_ready(already_running=True))
                return

            try:
                self._aivisspeech_process = subprocess.Popen([path], cwd=os.path.dirname(path) or None)
            except Exception as e:
                message = f"起動に失敗しました: {e}"
                self._post_to_ui(lambda: self._on_aivisspeech_failed(message, silent))
                return

            self._post_to_ui(lambda: self._set_aivisspeech_status(
                "AivisSpeechを起動しています...（初回は時間がかかります）", "gray70"))

            deadline = time.time() + AIVISSPEECH_STARTUP_TIMEOUT_SECONDS
            while time.time() < deadline:
                if self.is_aivisspeech_ready():
                    self._post_to_ui(lambda: self._on_aivisspeech_ready(already_running=False))
                    return
                time.sleep(2)

            self._post_to_ui(lambda: self._on_aivisspeech_failed(
                f"{AIVISSPEECH_STARTUP_TIMEOUT_SECONDS}秒待っても応答がありませんでした。", silent))

        threading.Thread(target=run, daemon=True).start()

    def _on_aivisspeech_ready(self, already_running):
        if already_running:
            self._set_aivisspeech_status("✅ AivisSpeechは既に起動しています。", "#4a9e4a")
            self.append_log("✅ AivisSpeechは既に起動していました。")
        else:
            self._set_aivisspeech_status("✅ AivisSpeechの起動が完了しました。", "#4a9e4a")
            self.append_log("✅ AivisSpeechを起動しました。読み上げが使えます。")

    def _on_aivisspeech_failed(self, message, silent):
        self._set_aivisspeech_status(f"⚠️ {message}", "#d08a4a")
        self.append_log(f"⚠️ AivisSpeech: {message}")
        if not silent:
            messagebox.showwarning("AivisSpeech", message)

    def _set_aivisspeech_status(self, text, color="gray70"):
        self.aivisspeech_status_label.configure(text=text, text_color=color)

    # --- スマホ連携 ---
    def get_phone_bridge_pin(self):
        """暗証番号を返す。まだ無ければ作って保存する（毎回入力し直さずに済むように）。"""
        pin = (self.db.get_setting("phone_bridge_pin", "") or "").strip()
        if not pin.isdigit() or len(pin) != 6:
            pin = PhoneBridgeServer.generate_pin()
            self.db.save_setting("phone_bridge_pin", pin)
        return pin

    def get_phone_bridge_https(self):
        """HTTPSで配信する設定か（証明書を作る部品が無ければ常にFalse）"""
        if x509 is None:
            return False
        return self.db.get_setting("phone_bridge_https", "0") == "1"

    def on_phone_bridge_https_toggle(self):
        enabled = self.phone_bridge_https_var.get()
        self.db.save_setting("phone_bridge_https", "1" if enabled else "0")
        self.append_log(f"⚙️ スマホ連携のHTTPSを {'ON' if enabled else 'OFF'} にしました。")
        # 配信方式が変わるので、動いていれば開き直す
        if self.phone_bridge.is_running():
            self.phone_bridge.stop()
            success, err = self.phone_bridge.start(self.get_phone_bridge_pin(),
                                                   https=self.get_phone_bridge_https())
            if not success:
                self.phone_bridge_https_var.set(False)
                self.db.save_setting("phone_bridge_https", "0")
                self.phone_bridge.start(self.get_phone_bridge_pin(), https=False)
                messagebox.showwarning("HTTPSにできません", err)
                self.append_log(f"⚠️ HTTPSにできなかったため、通常の配信に戻しました: {err}")
        self._refresh_phone_bridge_info()

    def _refresh_phone_bridge_info(self):
        if self.phone_bridge.is_running():
            bridge = self.phone_bridge
            if bridge.use_https and bridge.cert_is_trusted:
                extra = "\n　　🔒 正規の証明書です（警告は出ません）。スマホのマイクが使えます。"
            elif bridge.use_https:
                extra = ("\n　　🔒 自分で作った証明書のため、初回だけスマホに警告が出ます。"
                         "\n　　　　「詳細」→「アクセスする」で進んでください。以降は出ません。")
            else:
                extra = ("\n　　ℹ️ 通常の配信です。スマホのマイクで話す機能を使うには、"
                         "\n　　　　上の「HTTPSで配信する」をONにしてください。")
            self.phone_bridge_info_label.configure(
                text=f"✅ 受け取り中です。スマホのブラウザで下のURLを開いてください。\n"
                     f"　　URL: {bridge.get_url()}\n"
                     f"　　暗証番号: {self.get_phone_bridge_pin()}{extra}",
                text_color="#4a9e4a"
            )
        else:
            self.phone_bridge_info_label.configure(
                text="停止中です。チェックを入れると受け取りを開始します。", text_color="gray70"
            )

    def on_phone_bridge_toggle(self):
        enabled = self.phone_bridge_var.get()
        if enabled:
            success, err = self.phone_bridge.start(self.get_phone_bridge_pin(), https=self.get_phone_bridge_https())
            if not success:
                self.phone_bridge_var.set(False)
                self.db.save_setting("phone_bridge_enabled", "0")
                self._refresh_phone_bridge_info()
                messagebox.showerror("開始できません", err)
                self.append_log(f"❌ スマホ連携を開始できませんでした: {err}")
                return
            self.append_log(f"📱 スマホ連携を開始しました（{self.phone_bridge.get_url()}）。")
        else:
            self.phone_bridge.stop()
            self.append_log("📱 スマホ連携を停止しました。")

        self.db.save_setting("phone_bridge_enabled", "1" if enabled else "0")
        self._refresh_phone_bridge_info()

    def regenerate_phone_bridge_pin(self):
        """暗証番号を作り直す。動作中なら、その場から新しい番号だけを受け付けるようにする。"""
        pin = PhoneBridgeServer.generate_pin()
        self.db.save_setting("phone_bridge_pin", pin)
        if self.phone_bridge.is_running():
            self.phone_bridge.pin = pin
        self._refresh_phone_bridge_info()
        self.append_log("🔢 スマホ連携の暗証番号を作り直しました。スマホ側で入れ直してください。")

    def copy_phone_bridge_url(self):
        url = self.phone_bridge.get_url()
        # Windowsのクリップボードは一度に1つのアプリしか掴めない。
        # 他のアプリが操作中だと一瞬失敗することがあるため、落とさず知らせる。
        try:
            self.clipboard_clear()
            self.clipboard_append(url)
        except tk.TclError:
            self.append_log(f"⚠️ クリップボードを使用できませんでした。URL: {url}")
            messagebox.showinfo("URL", f"コピーできませんでした。手で入力してください。\n\n{url}")
            return
        # 自動監視がこのURLを読み上げてしまわないようにしておく
        self._clipboard_last_text = url
        self.append_log(f"📋 スマホ連携のURLをコピーしました: {url}")

    def _on_phone_bridge_text(self, text):
        """
        スマホから文字が届いたときにサーバースレッドから呼ばれる。
        戻り値はそのままスマホ側の表示に使われる（Falseなら「混み合っています」）。
        """
        return self.request_speech(text, source="スマホ")

    def _phone_bridge_phrases(self):
        """
        スマホ画面に並べる定型文を返す。サーバースレッドから呼ばれるため、
        UIのリストではなくDBを直接読む（_on_main_thread参照）。
        """
        return [p["text"] for p in self.db.get_speech_phrases()]

    def _on_phone_bridge_save_phrase(self, text):
        """スマホから「⭐」で保存されたときにサーバースレッドから呼ばれる"""
        success, _err, _phrase_id = self.db.create_speech_phrase(text)
        if success:
            self._post_to_ui(self._refresh_speech_phrase_listbox)
            self._post_to_ui(lambda: self.append_log(f"⭐ スマホから定型文を保存しました:「{text}」"))
        return success

    def _on_phone_bridge_delete_phrase(self, text):
        """スマホから「×」で削除されたときにサーバースレッドから呼ばれる"""
        target = next(
            (p for p in self.db.get_speech_phrases() if p["text"] == text), None
        )
        if not target:
            return False
        success, _err = self.db.delete_speech_phrase(target["id"])
        if success:
            self._post_to_ui(self._refresh_speech_phrase_listbox)
            self._post_to_ui(lambda: self.append_log(f"🗑️ スマホから定型文を削除しました:「{text}」"))
        return success

    # --- スマホの「声の解析」ページ用 ---
    # ⚠️ どちらもサーバースレッドから呼ばれる。UIウィジェットには触らないこと。
    def _on_phone_bridge_analyze(self, text):
        """スマホから届いた文を解析して、アクセント構造を返す。失敗したら (None, 理由)"""
        try:
            result = self.analyze_accent(text)
        except Exception as e:
            engine, _ = self._split_voice_selector(self.get_speech_speaker_id())
            reason = (f"{TTS_ENGINES[engine]['label']}に解析させられませんでした"
                      f"（{str(e).splitlines()[0][:80]}）。起動しているか確認してください。")
            self._post_to_ui(lambda: self.append_log(f"⚠️ スマホの解析: {reason}"))
            return None, reason
        self._post_to_ui(lambda: self.append_log(f"🔍 スマホから解析しました:「{text}」→ {result['kana'] or '(読みなし)'}"))
        return result, ""

    def _on_phone_bridge_speak_query(self, query, label=""):
        """
        スマホで編集されたアクセントのまま喋らせる。

        読み上げキュー(request_speech)は「文字から合成する」作りなので通せない。
        ここは編集済みクエリからWAVを作り、同じ再生経路に流す。
        """
        selector = self.get_speech_speaker_id()
        try:
            wav_data = self.synthesize_from_query(query, selector)
        except Exception as e:
            engine, _ = self._split_voice_selector(selector)
            reason = (f"{TTS_ENGINES[engine]['label']}で合成できませんでした"
                      f"（{str(e).splitlines()[0][:80]}）。")
            self._post_to_ui(lambda: self.append_log(f"⚠️ スマホの解析: {reason}"))
            return False, reason

        volume = self.get_speech_volume()
        # 再生は音が鳴り終わるまで戻らないため、スマホを待たせないよう別スレッドで行う
        threading.Thread(
            target=lambda: self._play_wav_bytes(wav_data, volume), daemon=True).start()
        shown = label or "(編集したアクセント)"
        self._post_to_ui(lambda: self.append_log(f"🗣️ スマホの解析から読み上げました:「{shown}」"))
        return True, ""

    # --- GitHub連携 ---
    def _set_github_status(self, text, color="gray70"):
        self.github_status_label.configure(text=text, text_color=color)

    def save_github_repository(self):
        """入力されたリポジトリを検証して保存する。取得元が変わるので準備済みの更新は破棄する。"""
        owner, repo, err = parse_github_repository(self.github_repo_entry.get())
        if err:
            self._set_github_status(f"⚠️ {err}", "#d08a4a")
            messagebox.showwarning("入力エラー", err)
            return

        old_owner, old_repo = self.updater.get_repository()
        self.db.save_setting("github_owner", owner)
        self.db.save_setting("github_repo", repo)

        # 入力を正規化した形（URLで貼られた場合は owner/repo）に整えて表示し直す
        self.github_repo_entry.delete(0, tk.END)
        self.github_repo_entry.insert(0, f"{owner}/{repo}")

        if (owner, repo) != (old_owner, old_repo):
            # 別のリポジトリから落としたファイルを、切り替え後の配布元のものとして
            # 適用してしまわないよう、準備済みの更新は捨てる
            if self.updater.read_pending_update():
                self.append_log("🧹 取得元が変わったため、ダウンロード済みの更新ファイルを破棄しました。")
            self.updater.clear_pending_update()
            self._refresh_version_label()

        self.append_log(f"⚙️ アップデートの取得元を {owner}/{repo} に設定しました。")
        self._set_github_status(f"✅ {owner}/{repo} を保存しました。", "#4a9e4a")

    def reset_github_repository(self):
        """出荷時の既定リポジトリに戻す"""
        self.db.save_setting("github_owner", "")
        self.db.save_setting("github_repo", "")
        self.github_repo_entry.delete(0, tk.END)
        self.github_repo_entry.insert(0, f"{GITHUB_OWNER}/{GITHUB_REPO}")
        self.updater.clear_pending_update()
        self._refresh_version_label()
        self.append_log(f"⚙️ アップデートの取得元を既定 ({GITHUB_OWNER}/{GITHUB_REPO}) に戻しました。")
        self._set_github_status(f"✅ 既定の {GITHUB_OWNER}/{GITHUB_REPO} に戻しました。", "#4a9e4a")

    def test_github_connection(self):
        """
        入力中のリポジトリに実際に問い合わせて、更新の取得元として使えるかを確かめる。
        保存しなくても試せるようにしてあるので、打ち間違いをその場で発見できる。
        """
        owner, repo, err = parse_github_repository(self.github_repo_entry.get())
        if err:
            self._set_github_status(f"⚠️ {err}", "#d08a4a")
            return

        self.github_test_btn.configure(state="disabled", text="確認中...")
        self._set_github_status(f"{owner}/{repo} に接続しています...", "gray70")

        def run():
            release = self.updater.fetch_latest_release(owner=owner, repo=repo)
            self.after(0, lambda: self._on_github_test_done(owner, repo, release))

        threading.Thread(target=run, daemon=True).start()

    def _on_github_test_done(self, owner, repo, release):
        self.github_test_btn.configure(state="normal", text="🔗 接続テスト")

        if release is None:
            self._set_github_status(
                f"❌ {owner}/{repo} からリリース情報を取得できませんでした。\n"
                "リポジトリ名の誤り、private設定、ネットワーク未接続などが考えられます（詳細はログ）。",
                "#c05a5a"
            )
            return

        tag = release.get("tag_name", "") or "(タグ名なし)"
        # 接続できただけでは不十分。zipアセットが無いリリースは、更新の段階になって
        # 初めて「zipが見つかりません」で失敗するため、ここで一緒に確かめておく。
        asset = self.updater.find_zip_asset(release)
        if not asset:
            self._set_github_status(
                f"⚠️ {owner}/{repo} に接続できました（最新: {tag}）。\n"
                "ただしリリースにzipファイルが無いため、このままでは更新を適用できません。",
                "#d08a4a"
            )
            return

        self._set_github_status(
            f"✅ {owner}/{repo} に接続できました。\n"
            f"最新リリース: {tag} / 配布ファイル: {asset.get('name', '')}",
            "#4a9e4a"
        )

    # --- ダイアログの自動OK ---
    def build_auto_ok_section(self, parent):
        section = ctk.CTkFrame(parent)
        section.pack(fill="x", padx=20, pady=(10, 0))

        ctk.CTkLabel(
            section, text="✅ ダイアログの自動OK",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 3))

        ctk.CTkLabel(
            section,
            text="「当選者」のように、目印の文言を含むダイアログが出たらOKを自動で押します。\n"
                 "⚠️ 目印が画面にあるときだけ押します。目印なしで「OK」を押すことはありません\n"
                 "　（購入確認や規約同意など、押してはいけないダイアログを避けるため）。",
            justify="left", text_color="gray70"
        ).pack(anchor="w", padx=12, pady=(0, 8))

        self.auto_ok_var = ctk.BooleanVar(
            value=self.db.get_setting("auto_ok_enabled", "0") == "1"
        )
        ctk.CTkCheckBox(
            section, text="目印を含むダイアログのOKを自動で押す",
            variable=self.auto_ok_var,
            command=self.on_auto_ok_toggle
        ).pack(anchor="w", padx=12, pady=(0, 8))

        kw_frame = ctk.CTkFrame(section, fg_color="transparent")
        kw_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(kw_frame, text="目印の文言:").pack(side="left", padx=(0, 8))
        self.auto_ok_keywords_entry = ctk.CTkEntry(kw_frame, width=280)
        self.auto_ok_keywords_entry.insert(
            0, self.db.get_setting("auto_ok_keywords", DEFAULT_AUTO_OK_KEYWORDS) or DEFAULT_AUTO_OK_KEYWORDS
        )
        self.auto_ok_keywords_entry.pack(side="left", padx=(0, 5))
        self.auto_ok_keywords_entry.bind("<Button-3>", self._show_entry_context_menu)
        self.auto_ok_keywords_entry.bind("<Return>", lambda e: self.save_auto_ok_keywords())
        ctk.CTkButton(kw_frame, text="💾 保存", width=70,
                      command=self.save_auto_ok_keywords).pack(side="left", padx=(0, 5))
        ctk.CTkButton(kw_frame, text="↩️ 既定に戻す", width=110,
                      fg_color="#555555", hover_color="#3a3a3a",
                      command=self.reset_auto_ok_keywords).pack(side="left")

        ctk.CTkLabel(
            section,
            text="カンマ区切りで複数指定できます（例: 当選者,選ばれました）。\n"
                 f"押す対象のボタン: {' / '.join(AUTO_OK_BUTTON_LABELS[:5])} など",
            justify="left", text_color="gray70"
        ).pack(anchor="w", padx=12, pady=(0, 10))

    def on_auto_ok_toggle(self):
        enabled = self.auto_ok_var.get()
        self.db.save_setting("auto_ok_enabled", "1" if enabled else "0")
        self.append_log(f"⚙️ ダイアログの自動OKを {'ON' if enabled else 'OFF'} にしました。")
        if enabled:
            words = self.db.get_setting("auto_ok_keywords", DEFAULT_AUTO_OK_KEYWORDS)
            self.append_log(f"　 目印:「{words}」を含むダイアログだけが対象です。")

    def save_auto_ok_keywords(self):
        text = self.auto_ok_keywords_entry.get().strip()
        words = [w.strip() for w in text.split(",") if w.strip()]
        if not words:
            messagebox.showwarning(
                "入力エラー",
                "目印の文言を1つ以上入れてください。\n"
                "空にすると、どのダイアログを押してよいか判断できません。"
            )
            return
        cleaned = ",".join(words)
        self.db.save_setting("auto_ok_keywords", cleaned)
        self.auto_ok_keywords_entry.delete(0, tk.END)
        self.auto_ok_keywords_entry.insert(0, cleaned)
        self.append_log(f"⚙️ 自動OKの目印を「{cleaned}」に設定しました。")

    def reset_auto_ok_keywords(self):
        self.db.save_setting("auto_ok_keywords", DEFAULT_AUTO_OK_KEYWORDS)
        self.auto_ok_keywords_entry.delete(0, tk.END)
        self.auto_ok_keywords_entry.insert(0, DEFAULT_AUTO_OK_KEYWORDS)
        self.append_log(f"⚙️ 自動OKの目印を既定「{DEFAULT_AUTO_OK_KEYWORDS}」に戻しました。")

    # --- エミュレータ(MuMu) ---
    def build_emulator_section(self, parent):
        """MuMuの場所・対象アプリ・自動起動の設定エリア"""
        section = ctk.CTkFrame(parent)
        section.pack(fill="x", padx=20, pady=(20, 0))

        ctk.CTkLabel(
            section, text="📱 エミュレータ(MuMu)",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 3))

        ctk.CTkLabel(
            section,
            text="MuMu本体と、監視したいアプリの起動をこのツールから行えます。\n"
                 "接続先(adbのポート)もMuMuに直接問い合わせるため、手で設定する必要はありません。",
            justify="left", text_color="gray70"
        ).pack(anchor="w", padx=12, pady=(0, 8))

        # MuMuManager.exe の場所
        path_frame = ctk.CTkFrame(section, fg_color="transparent")
        path_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(path_frame, text="MuMuの場所:").pack(side="left", padx=(0, 8))
        self.mumu_path_label = ctk.CTkLabel(path_frame, text="", text_color="gray70", anchor="w")
        self.mumu_path_label.pack(side="left", padx=(0, 8))
        ctk.CTkButton(path_frame, text="📂 参照", width=80,
                      command=self.select_mumu_manager).pack(side="left", padx=(0, 5))

        # 対象アプリ
        app_frame = ctk.CTkFrame(section, fg_color="transparent")
        app_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(app_frame, text="監視するアプリ:").pack(side="left", padx=(0, 8))
        self.mumu_app_var = ctk.StringVar(value="")
        self.mumu_app_menu = ctk.CTkOptionMenu(
            app_frame, variable=self.mumu_app_var, values=[""],
            command=self.on_mumu_app_selected, width=240
        )
        self.mumu_app_menu.pack(side="left", padx=(0, 5))
        ctk.CTkButton(app_frame, text="🔄 一覧を取得", width=120,
                      command=self.refresh_mumu_apps).pack(side="left", padx=5)

        self.mumu_auto_launch_var = ctk.BooleanVar(
            value=self.db.get_setting("mumu_auto_launch", "0") == "1"
        )
        ctk.CTkCheckBox(
            section, text="監視を開始するとき、MuMuと上のアプリを自動で起動する",
            variable=self.mumu_auto_launch_var,
            command=self.on_mumu_auto_launch_toggle
        ).pack(anchor="w", padx=12, pady=(0, 6))

        btn_frame = ctk.CTkFrame(section, fg_color="transparent")
        btn_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 6))
        ctk.CTkButton(btn_frame, text="▶ 今すぐ起動", width=120,
                      fg_color="green", hover_color="darkgreen",
                      command=self.launch_mumu_now).pack(side="left", padx=(0, 5))
        ctk.CTkButton(btn_frame, text="🔌 接続を確認", width=120,
                      fg_color="#555555", hover_color="#3a3a3a",
                      command=self.check_mumu_connection).pack(side="left", padx=5)

        self.mumu_status_label = ctk.CTkLabel(section, text="", justify="left", text_color="gray70")
        self.mumu_status_label.pack(anchor="w", padx=12, pady=(0, 10))

        self._mumu_apps = {}
        self._refresh_mumu_path_label()
        self._restore_saved_mumu_app()

    def _set_mumu_status(self, text, color="gray70"):
        self.mumu_status_label.configure(text=text, text_color=color)

    def _refresh_mumu_path_label(self):
        path = self.worker.mumu.resolve_manager_path()
        if path:
            saved = self.db.get_setting("mumu_manager_path", "") or ""
            suffix = "" if saved else "（自動検出）"
            self.mumu_path_label.configure(text=os.path.basename(path) + suffix, text_color="gray70")
        else:
            self.mumu_path_label.configure(text="見つかりません", text_color="#d08a4a")

    def _restore_saved_mumu_app(self):
        """保存済みのパッケージを、一覧を取らずに表示だけ戻す"""
        package = self.db.get_setting("mumu_target_package", "") or ""
        name = self.db.get_setting("mumu_target_name", "") or package
        if package:
            label = f"{name} ({package})"
            self.mumu_app_menu.configure(values=[label])
            self.mumu_app_var.set(label)
            self._mumu_apps = {label: package}

    def select_mumu_manager(self):
        path = filedialog.askopenfilename(
            title="MuMuManager.exe を選択",
            filetypes=[("MuMuManager", "MuMuManager.exe"), ("実行ファイル", "*.exe")]
        )
        if not path:
            return
        self.db.save_setting("mumu_manager_path", path)
        self.worker.mumu.manager_path = path
        # 別のMuMuを指定したなら、番号は覚え直す
        self.worker.mumu.forget_index_cache()
        self._refresh_mumu_path_label()
        self.append_log(f"✅ MuMuの場所を設定しました: {path}")

    def refresh_mumu_apps(self):
        """MuMuにインストール済みのアプリ一覧を取得してプルダウンに入れる"""
        if not self.worker.mumu.is_available():
            self._set_mumu_status("⚠️ MuMuManager.exeが見つかりません。「📂 参照」で指定してください。", "#d08a4a")
            return
        self._set_mumu_status("アプリ一覧を取得しています...", "gray70")

        def run():
            active, apps = self.worker.mumu.list_apps(
                self.db.get_setting("mumu_instance_index", "") or None
            )
            self._post_to_ui(lambda: self._on_mumu_apps(active, apps))

        threading.Thread(target=run, daemon=True).start()

    def _on_mumu_apps(self, active, apps):
        if not apps:
            self._set_mumu_status("⚠️ アプリ一覧を取得できませんでした。MuMuが起動しているか確認してください。", "#d08a4a")
            return
        # 自動化の補助として入っているATX自身は監視対象になりえないので除く
        apps = {pkg: name for pkg, name in apps.items() if not pkg.startswith(UIAUTOMATOR_IME_PACKAGE)}
        self._mumu_apps = {f"{name} ({pkg})": pkg for pkg, name in sorted(apps.items(), key=lambda kv: kv[1])}
        labels = list(self._mumu_apps.keys())
        self.mumu_app_menu.configure(values=labels)

        saved = self.db.get_setting("mumu_target_package", "") or ""
        prefer = saved or active
        chosen = next((lb for lb, pkg in self._mumu_apps.items() if pkg == prefer), labels[0])
        self.mumu_app_var.set(chosen)
        self.on_mumu_app_selected(chosen)

        note = f"（現在起動中: {active}）" if active else ""
        self._set_mumu_status(f"✅ アプリ{len(labels)}件を読み込みました。{note}", "#4a9e4a")

    def on_mumu_app_selected(self, label):
        package = self._mumu_apps.get(label, "")
        if not package:
            return
        self.db.save_setting("mumu_target_package", package)
        self.db.save_setting("mumu_target_name", label.rsplit(" (", 1)[0])
        self.append_log(f"⚙️ 監視するアプリを「{label}」に設定しました。")

    def on_mumu_auto_launch_toggle(self):
        enabled = self.mumu_auto_launch_var.get()
        self.db.save_setting("mumu_auto_launch", "1" if enabled else "0")
        self.append_log(f"⚙️ MuMuの自動起動を {'ON' if enabled else 'OFF'} にしました。")
        if enabled and not (self.db.get_setting("mumu_target_package", "") or ""):
            self._set_mumu_status("ℹ️ 「🔄 一覧を取得」で監視するアプリを選んでおいてください。", "gray70")

    def launch_mumu_now(self):
        """設定タブの「▶ 今すぐ起動」。MuMuと対象アプリを起動する。"""
        if not self.worker.mumu.is_available():
            self._set_mumu_status("⚠️ MuMuManager.exeが見つかりません。「📂 参照」で指定してください。", "#d08a4a")
            return
        package = self.db.get_setting("mumu_target_package", "") or ""
        self._set_mumu_status("MuMuを起動しています...（初回は時間がかかります）", "gray70")

        def run():
            success, message = self.worker.mumu.launch(
                index=self.db.get_setting("mumu_instance_index", "") or None,
                package=package,
            )
            self._post_to_ui(lambda: self._set_mumu_status(
                ("✅ " if success else "⚠️ ") + message, "#4a9e4a" if success else "#d08a4a"))
            self._post_to_ui(lambda: self.append_log(("✅ MuMu: " if success else "⚠️ MuMu: ") + message))

        threading.Thread(target=run, daemon=True).start()

    def check_mumu_connection(self):
        """MuMuに問い合わせて、接続先と起動状態を確認する"""
        if not self.worker.mumu.is_available():
            self._set_mumu_status("⚠️ MuMuManager.exeが見つかりません。「📂 参照」で指定してください。", "#d08a4a")
            return
        self._set_mumu_status("MuMuの状態を確認しています...", "gray70")

        def run():
            # 番号は決め打ちしない。保存値が無ければ resolve_index が自動検出する
            index = self.db.get_setting("mumu_instance_index", "") or None
            instances = self.worker.mumu.list_instances()
            if not instances:
                self._post_to_ui(lambda: self._set_mumu_status(
                    "⚠️ MuMuのインスタンスが見つかりません。"
                    "MuMuを一度手動で起動して、端末が作成されているか確認してください。", "#d08a4a"))
                return
            resolved = self.worker.mumu.resolve_index(index)
            info = self.worker.mumu.get_info(resolved)
            ready = self.worker.mumu.is_android_ready(info)
            address = self.worker.mumu.get_adb_address(info)
            found = "／".join(f"{k}:{v.get('name', '')}" for k, v in instances.items())
            if ready and address:
                text = f"✅ 起動中です（インスタンス {resolved}）。接続先: {address}"
                color = "#4a9e4a"
            elif info:
                text = (f"⚠️ インスタンス {resolved} は検出できましたが、まだ起動しきっていません"
                        f"（{info.get('player_state') or 'Android未起動'}）。\n"
                        f"　　「▶ 今すぐ起動」を押すか、MuMuを起動してください。")
                color = "#d08a4a"
            else:
                text = (f"⚠️ MuMuの状態を取得できませんでした。\n"
                        f"　　見つかったインスタンス: {found}")
                color = "#d08a4a"
            self._post_to_ui(lambda: self._set_mumu_status(text, color))

        threading.Thread(target=run, daemon=True).start()

    def on_auto_update_toggle(self):
        enabled = self.auto_update_enabled_var.get()
        self.db.save_setting("auto_update_enabled", "1" if enabled else "0")
        self.append_log(f"⚙️ 自動アップデートを {'ON' if enabled else 'OFF'} に切り替えました。")
        if not enabled:
            # OFFにした以上、勝手に適用されないよう準備済みのものは破棄する
            if self.updater.read_pending_update():
                self.append_log("🧹 ダウンロード済みの更新ファイルを破棄しました。")
            self.updater.clear_pending_update()
        self._refresh_version_label()

    def on_cooldown_enabled_toggle(self):
        value = "1" if self.cooldown_enabled_var.get() else "0"
        self.db.save_setting("cooldown_enabled", value)
        state_text = "ON" if value == "1" else "OFF"
        self.append_log(f"⚙️ 送信クールダウンを {state_text} に切り替えました。")

    def save_cooldown_settings(self):
        # 日本語入力のままだと全角数字が入りうるので半角に正規化してから解釈する
        raw = normalize_number_text(self.cooldown_seconds_entry.get())
        try:
            seconds = float(raw)
            if seconds < 0:
                raise ValueError("負の値は指定できません。")
        except ValueError:
            messagebox.showwarning("入力エラー", "最短送信間隔には0以上の数値を入力してください。")
            return

        # 入力欄も正規化後の値に揃えておく
        self.cooldown_seconds_entry.delete(0, tk.END)
        self.cooldown_seconds_entry.insert(0, str(seconds))

        self.db.save_setting("cooldown_seconds", str(seconds))
        self.append_log(f"✅ 送信クールダウンを {seconds:.1f}秒 に設定しました。")

    def refresh_keyword_listbox(self):
        self.keyword_listbox.delete(0, tk.END)
        self._keyword_rows = []
        set_id = getattr(self, "current_keyword_set_id", None)
        if set_id is None:
            return
        rows = self.db.get_keywords_in_set(set_id)
        self._keyword_rows = rows
        for index, row in enumerate(rows):
            mark = "☑" if row["enabled"] else "☐"
            self.keyword_listbox.insert(tk.END, f"{mark} {row['trigger']}  ➔  {row['reply']}")
            # 無効なペアはグレー表示にして、ひと目で区別できるようにする
            if not row["enabled"]:
                self.keyword_listbox.itemconfig(index, fg="#7a7a7a")

    def _selected_keyword_row(self):
        """一覧で選択中のペア情報を返す（未選択ならNone）"""
        selection = self.keyword_listbox.curselection()
        if not selection:
            return None
        rows = getattr(self, "_keyword_rows", [])
        index = selection[0]
        if index >= len(rows):
            return None
        return rows[index]

    def on_keyword_select(self, event):
        row = self._selected_keyword_row()
        if row:
            self.trigger_entry.delete(0, tk.END)
            self.trigger_entry.insert(0, row["trigger"])
            self.reply_entry.delete(0, tk.END)
            self.reply_entry.insert(0, row["reply"])

    def toggle_selected_keyword_enabled(self, event=None):
        """選択中のペアの有効/無効を切り替える（ボタン、またはダブルクリックから呼ばれる）"""
        row = self._selected_keyword_row()
        if not row:
            messagebox.showinfo("未選択", "有効/無効を切り替えるペアを一覧から選択してください。")
            return
        new_state = not row["enabled"]
        success, err = self.db.set_keyword_enabled(
            self.current_keyword_set_id, row["trigger"], new_state
        )
        if success:
            selected_index = self.keyword_listbox.curselection()
            self.refresh_keyword_listbox()
            # 切り替え後も同じ行を選択したままにする（連続で切り替えやすいように）
            if selected_index:
                self.keyword_listbox.selection_set(selected_index[0])
            state_text = "有効" if new_state else "無効"
            self.append_log(f"⚙️ ペア「{row['trigger']}」➔「{row['reply']}」を{state_text}にしました。")
        else:
            messagebox.showerror("エラー", f"有効/無効の切り替えに失敗しました。\n\n詳細: {err}")

    def add_or_update_keyword(self):
        k = self.trigger_entry.get().strip()
        v = self.reply_entry.get().strip()
        if k and v:
            success, err = self.db.upsert_keyword(self.current_keyword_set_id, k, v)
            if success:
                self.refresh_keyword_listbox()
                self.trigger_entry.delete(0, tk.END)
                self.reply_entry.delete(0, tk.END)
                set_name = self.keyword_set_var.get()
                self.append_log(f"✅ セット「{set_name}」にキーワードを保存しました:「{k}」➔「{v}」")
            else:
                messagebox.showerror("保存エラー", f"キーワードの保存に失敗しました。\n\n詳細: {err}")
        else:
            messagebox.showwarning("入力不足", "検知ワードと返信ワードの両方を入力してください。")

    def delete_keyword(self):
        row = self._selected_keyword_row()
        if not row:
            messagebox.showinfo("未選択", "削除するペアを一覧から選択してください。")
            return
        k = row["trigger"]
        success, err = self.db.delete_keyword(self.current_keyword_set_id, k)
        if success:
            self.refresh_keyword_listbox()
            self.trigger_entry.delete(0, tk.END)
            self.reply_entry.delete(0, tk.END)
            self.append_log(f"🗑️ キーワードを削除しました:「{k}」")
        else:
            messagebox.showerror("削除エラー", f"キーワードの削除に失敗しました。\n\n詳細: {err}")

    # --- ログ ---
    def append_log(self, message):
        def update_gui():
            if self.winfo_exists():
                self.log_textbox.configure(state="normal")
                self.log_textbox.insert("end", message + "\n")

                lines = int(self.log_textbox.index('end-1c').split('.')[0])
                if lines > 1000:
                    self.log_textbox.delete("1.0", f"{lines - 1000}.0")

                self.log_textbox.configure(state="disabled")
                if self.auto_scroll_var.get():
                    self.log_textbox.yview("end")
        # ⚠️ ワーカースレッドから after() を直接呼ばない。
        # mainloopが回っている間は通るが、起動直後や終了処理中は
        # RuntimeError("main thread is not in main loop") になり、
        # そのログ行は画面に出ないまま消える（DBには残るので気付きにくい）。
        # 監視スレッドはこの append_log を毎周回で呼ぶため、そちらは
        # _post_to_ui の伝言板を経由してメインスレッドで実行させる。
        #
        # ⚠️ メインスレッドからの分まで伝言板に回してはいけない。
        # 伝言板は120msごとにしか掃き出さないため、「ログを出した直後に
        # ログ欄を読む」処理（ログのコピー等）が古い内容を見てしまう。
        if self._on_main_thread() or getattr(self, "_ui_queue", None) is None:
            try:
                self.after(0, update_gui)
            except Exception:
                pass
            return
        try:
            self._post_to_ui(update_gui)
        except Exception:
            pass

    # --- ログのコピー ---
    def _log_inner_widget(self):
        """選択操作は内部のtk.Textに対して行う（CTkTextboxが全ての操作を中継しないため）"""
        return getattr(self.log_textbox, "_textbox", self.log_textbox)

    def _show_log_context_menu(self, event):
        self.log_context_menu.tk_popup(event.x_root, event.y_root)

    def select_all_log(self):
        widget = self._log_inner_widget()
        try:
            widget.tag_remove("sel", "1.0", "end")
            widget.tag_add("sel", "1.0", "end-1c")
            widget.focus_set()
        except tk.TclError:
            pass

    def _copy_text_to_clipboard(self, text, what):
        """
        文字列をクリップボードへ入れる。

        クリップボードの自動読み上げがONのとき、自分でコピーした内容まで
        ずんだもんが読み上げてしまわないよう、監視側にも「これは既知」と伝えておく。
        """
        if not text:
            self.append_log("ℹ️ コピーする内容がありません。")
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except tk.TclError:
            # Windowsのクリップボードは他アプリが掴んでいると一時的に失敗する
            self.append_log("⚠️ クリップボードを使用できませんでした。少し待ってからもう一度お試しください。")
            return
        # 自動読み上げの監視は前後の空白を落として比較しているので、こちらも同じ形で覚える。
        # 生のまま覚えるとログ末尾の改行だけで別物と判定され、ログ全体が読み上げられてしまう。
        self._clipboard_last_text = text.strip()
        self.append_log(f"📋 {what}をコピーしました（{len(text)}文字）。")

    def copy_log_selection(self):
        """選択部分をコピーする。選択が無ければログ全体をコピーする。"""
        widget = self._log_inner_widget()
        try:
            text = widget.get("sel.first", "sel.last")
        except tk.TclError:
            text = ""
        if text:
            self._copy_text_to_clipboard(text, "選択したログ")
        else:
            self.copy_all_log()

    def copy_all_log(self):
        widget = self._log_inner_widget()
        try:
            text = widget.get("1.0", "end-1c")
        except tk.TclError:
            text = ""
        self._copy_text_to_clipboard(text, "ログ全体")

    def clear_log_display(self):
        """画面のログ表示だけを消す（DBに保存された監視ログはそのまま）"""
        widget = self._log_inner_widget()
        try:
            widget.configure(state="normal")
            widget.delete("1.0", tk.END)
            widget.configure(state="disabled")
        except tk.TclError:
            return
        self.append_log("🧹 ログの表示を消去しました。")

    # --- 監視制御 ---
    def start_monitoring(self, use_last=False):
        # 停止直後はスレッドがまだ後片付け中のことがある。その状態で開始すると
        # 監視が二重に走って同じ返信が2回送られてしまうため、ここで弾く。
        if self.worker.is_running or self.worker.is_alive():
            self.append_log("⚠️ 前回の監視がまだ終了していません。数秒待ってからもう一度お試しください。")
            return

        if use_last and self.last_coords:
            self.append_log("\n--- 前回と同じ範囲で開始 ---")
            self._begin_monitoring(self.last_coords)
            return

        self.append_log("\n--- 範囲選択モード ---")
        self.append_log("エミュレータの【監視したいチャットエリア】をマウスでドラッグして囲んでください。")
        self.append_log("💡 やめる場合は Esc キーを押してください。")

        # 以前はここでtime.sleepしており、その間UIが固まっていた。
        # ウインドウを隠した後の描画はafterで待ち、メインスレッドは止めない。
        self.withdraw()
        self.update_idletasks()
        self.after(300, self._open_screen_selector)

    def _open_screen_selector(self):
        selector = ScreenSelector(self)
        coords = selector.get_coordinates()  # wait_window（内部でイベントループが回るのでUIは固まらない）

        self.deiconify()
        self.lift()

        if not coords:
            self.append_log(selector.error_message or "❌ 範囲選択がキャンセルされました。")
            return

        self.last_coords = coords
        self._save_last_coords(coords)
        self.start_prev_btn.configure(state="normal")
        self._begin_monitoring(coords)

    def _begin_monitoring(self, coords):
        screen_x1, screen_y1, screen_x2, screen_y2 = coords
        self.append_log(f"✅ 選択された画面座標: 左上({screen_x1}, {screen_y1}) -> 右下({screen_x2}, {screen_y2})")

        if not self.worker.start(screen_x1, screen_y1, screen_x2, screen_y2):
            self.append_log("⚠️ 前回の監視がまだ終了していないため、開始できませんでした。")
            return

        self.start_btn.configure(state="disabled")
        self.start_prev_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_manual_send_enabled(True)
        self._watch_worker_state()

    def stop_monitoring(self):
        self.worker.stop()
        self.stop_btn.configure(state="disabled")

    def _watch_worker_state(self):
        # workerが自動停止（エラー等）した場合にボタン状態を復帰させる。
        # is_runningだけでなくスレッドの終了も待たないと、後片付け中に再開できてしまう。
        if not self.winfo_exists():
            return
        if self.worker.is_running or self.worker.is_alive():
            self.after(500, self._watch_worker_state)
        else:
            self.start_btn.configure(state="normal")
            self.start_prev_btn.configure(state="normal" if self.last_coords else "disabled")
            self.stop_btn.configure(state="disabled")
            self._set_manual_send_enabled(False)

    # ====================================================
    # 🔄 アップデート機能
    # ====================================================
    # --- 自動アップデート ---
    def is_auto_update_enabled(self):
        """自動アップデートがONか。UIより先に呼ばれる可能性があるためDBを正とする"""
        return self.db.get_setting("auto_update_enabled", "1") == "1"

    def _can_apply_update(self):
        """
        更新を実際に適用できる状態か。
        .pyで直接動かしている開発環境では差し替える対象のexeが無いため、
        ダウンロードしても無駄になる（＝自動アップデートは動かさない）。
        """
        return bool(getattr(sys, 'frozen', False))

    def _run_scheduled_update_check(self):
        """定期チェックの本体。実行後、必ず次回の予約を入れ直す（自動アップデートOFFでも継続）"""
        if getattr(self, "_closing", False):
            return
        try:
            if self.is_auto_update_enabled():
                self.check_for_updates(silent=True)
        finally:
            if not getattr(self, "_closing", False):
                interval_ms = AUTO_UPDATE_CHECK_INTERVAL_HOURS * 60 * 60 * 1000
                try:
                    self._auto_update_after_id = self.after(
                        interval_ms, self._run_scheduled_update_check)
                except tk.TclError:
                    pass

    def _stage_update_in_background(self, release_data):
        """新バージョンを裏でダウンロードし、終了時に適用できる状態にしておく"""
        latest_tag = release_data.get("tag_name", "")

        if not self._can_apply_update():
            self.append_log("ℹ️ 開発環境（.py実行）のため、自動ダウンロードは行いません。")
            return
        if self._update_staging_in_progress:
            return
        # 既に同じ（またはより新しい）バージョンを準備済みなら、同じものを再ダウンロードしない
        pending = self.updater.read_pending_update()
        if pending and not self.updater.is_newer(latest_tag, pending["version"]):
            return

        self._update_staging_in_progress = True
        self.append_log(f"⬇️ {latest_tag} をバックグラウンドでダウンロードしています...")

        def worker_task():
            success, err = self.updater.stage_update(release_data, os.path.basename(sys.executable))
            self.after(0, lambda: self._on_update_staged(latest_tag, success, err))

        threading.Thread(target=worker_task, daemon=True).start()

    def _on_update_staged(self, latest_tag, success, err):
        self._update_staging_in_progress = False
        if success:
            self.append_log(
                f"✅ {latest_tag} の準備が完了しました。アプリを終了するときに自動で適用されます。"
            )
        else:
            # 失敗しても作業の邪魔はしない。次回のチェックで再挑戦される。
            self.append_log(f"⚠️ 自動アップデートの準備に失敗しました: {err}")
        self._refresh_version_label()

    def _refresh_version_label(self):
        """バージョン表示に、適用待ちの更新があることを添える（ダイアログを出さない代わりの通知）"""
        pending = self.updater.read_pending_update()
        if pending:
            self.version_label.configure(
                text=f"バージョン: v{APP_VERSION} → 終了時に {pending['version']} を適用します",
                text_color="#4a9e4a"
            )
        else:
            self.version_label.configure(
                text=f"バージョン: v{APP_VERSION}", text_color="gray"
            )

    def _apply_pending_update_on_exit(self):
        """
        終了時に、準備済みの新バージョンがあれば差し替えスクリプトを起動する。
        戻り値: Trueなら更新処理を開始した（呼び出し側はdestroyせず、そのままプロセスを終える）
        """
        if not self.is_auto_update_enabled() or not self._can_apply_update():
            return False
        pending = self.updater.read_pending_update()
        if not pending:
            return False

        # バックアップのzip作成に数秒かかるため、固まったように見えないよう一言出しておく
        notice = ctk.CTkToplevel(self)
        notice.title("アップデート")
        notice.geometry("380x90")
        notice.resizable(False, False)
        ctk.CTkLabel(
            notice, text=f"{pending['version']} を適用しています...\nこのまま少しお待ちください。"
        ).pack(expand=True, padx=20, pady=20)
        notice.update()

        backup_root_dir = os.path.join(os.path.expanduser("~"), "AutoReplyTool_Backups")
        self.updater.backup_current_installation(backup_root_dir)

        launched = self.updater.create_update_batch_and_launch(
            pending["source_dir"], BASE_DIR, sys.executable,
            cleanup_dirs=[PENDING_UPDATE_DIR], relaunch=False
        )
        if not launched:
            # スクリプトを起動できなかった場合は、準備物を残したまま普通に終了する
            # （次回の終了時にもう一度試せる）
            try:
                notice.destroy()
            except Exception:
                pass
            write_error_log("終了時アップデートの適用スクリプトを起動できませんでした。")
            return False

        # スクリプト側が現プロセスの終了を待っているため、少し待ってから終了する
        time.sleep(1)
        os._exit(0)

    def check_for_updates(self, silent=True):
        """
        GitHub Releasesを確認する。
        silent=True: 起動時・定期の自動チェック。新バージョンが無ければ何も表示しない。
        silent=False: 手動ボタンからの実行。結果を必ずダイアログ/ログで通知する。
        """
        if not silent:
            self.update_check_btn.configure(state="disabled", text="確認中...")
            self.append_log("🔄 アップデートを確認しています...")

        def worker_task():
            release_data = self.updater.fetch_latest_release()
            self.after(0, lambda: self._on_update_check_done(release_data, silent))

        threading.Thread(target=worker_task, daemon=True).start()

    def _on_update_check_done(self, release_data, silent):
        if not silent:
            self.update_check_btn.configure(state="normal", text="🔄 アップデート確認")

        if release_data is None:
            if not silent:
                messagebox.showwarning("アップデート確認", "アップデート情報の取得に失敗しました。\nネットワーク接続をご確認ください。")
            return

        latest_tag = release_data.get("tag_name", "")
        if not latest_tag:
            if not silent:
                messagebox.showinfo("アップデート確認", "リリース情報が見つかりませんでした。")
            return

        if self.updater.is_newer(latest_tag, APP_VERSION):
            self.append_log(f"🆕 新しいバージョンが見つかりました: {latest_tag} (現在: v{APP_VERSION})")
            # 自動アップデートがONの定期チェックでは、ダイアログで作業を止めずに
            # 裏でダウンロードだけ済ませておく。手動ボタンからのときは今すぐ適用したいはずなので、
            # 従来どおり確認ダイアログを出す。
            if silent and self.is_auto_update_enabled():
                self._stage_update_in_background(release_data)
            else:
                self._show_update_dialog(release_data)
        else:
            self.append_log(f"✅ 現在のバージョンは最新です (v{APP_VERSION})")
            if not silent:
                messagebox.showinfo("アップデート確認", f"現在のバージョン (v{APP_VERSION}) は最新です。")

    def _show_update_dialog(self, release_data):
        latest_tag = release_data.get("tag_name", "不明")
        release_notes = release_data.get("body", "").strip() or "(リリースノートはありません)"

        # リリースノートが長すぎる場合はダイアログが肥大化しないよう適度に切る
        if len(release_notes) > 1500:
            release_notes = release_notes[:1500] + "\n...(以下省略)"

        dialog = ctk.CTkToplevel(self)
        dialog.title("アップデートのお知らせ")
        dialog.geometry("500x400")
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text=f"新しいバージョン {latest_tag} が利用可能です。\n(現在: v{APP_VERSION})",
            font=ctk.CTkFont(weight="bold")
        ).pack(pady=(15, 10), padx=15)

        notes_box = ctk.CTkTextbox(dialog, width=460, height=220)
        notes_box.pack(padx=15, pady=5, fill="both", expand=True)
        notes_box.insert("1.0", release_notes)
        notes_box.configure(state="disabled")

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=15)

        def on_update_click():
            dialog.destroy()
            self._start_update_process(release_data)

        def on_later_click():
            dialog.destroy()

        ctk.CTkButton(btn_frame, text="今すぐ更新する", fg_color="green", hover_color="darkgreen",
                      command=on_update_click, width=140).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="後で", fg_color="gray", hover_color="#444444",
                      command=on_later_click, width=100).pack(side="left", padx=10)

    def _start_update_process(self, release_data):
        if not getattr(sys, 'frozen', False):
            messagebox.showwarning(
                "アップデート不可",
                "現在は開発環境（.py実行）のため、自動アップデートは適用できません。\n"
                "exe化されたバージョンで実行してください。"
            )
            return

        asset = self.updater.find_zip_asset(release_data)
        if not asset:
            messagebox.showerror("アップデート失敗", "リリースにzipファイルが見つかりませんでした。")
            return

        download_url = asset.get("browser_download_url")
        if not download_url:
            messagebox.showerror("アップデート失敗", "ダウンロードURLが取得できませんでした。")
            return

        # 進捗表示用の簡易ダイアログ
        progress_dialog = ctk.CTkToplevel(self)
        progress_dialog.title("アップデート中")
        progress_dialog.geometry("400x120")
        progress_dialog.grab_set()
        progress_dialog.protocol("WM_DELETE_WINDOW", lambda: None)  # 更新中は閉じさせない

        status_label = ctk.CTkLabel(progress_dialog, text="ダウンロードを準備しています...")
        status_label.pack(pady=(20, 10))
        progress_bar = ctk.CTkProgressBar(progress_dialog, width=320)
        progress_bar.pack(pady=10)
        progress_bar.set(0)

        self.update_check_btn.configure(state="disabled")

        def progress_callback(downloaded, total):
            ratio = downloaded / total if total else 0
            self.after(0, lambda: progress_bar.set(ratio))
            self.after(0, lambda: status_label.configure(text=f"ダウンロード中... {downloaded // 1024}KB / {total // 1024}KB"))

        def worker_task():
            try:
                tmp_dir = tempfile.mkdtemp(prefix="auto_reply_update_")
                zip_path = os.path.join(tmp_dir, asset.get("name", "update.zip"))

                self.after(0, lambda: self.append_log(f"⬇️ 新しいバージョンをダウンロードしています: {asset.get('name')}"))
                success, err = self.updater.download_asset(download_url, zip_path, progress_callback=progress_callback)

                if not success:
                    self.after(0, lambda: self._on_update_failed(progress_dialog, f"ダウンロードに失敗しました: {err}"))
                    return

                self._apply_update_from_zip(zip_path, tmp_dir, progress_dialog, status_label)

            except Exception as e:
                # eはexcept節を抜けると消えるため、lambdaに渡す前に文字列化しておく
                message = f"予期しないエラー: {e}"
                self.after(0, lambda: self._on_update_failed(progress_dialog, message))

        threading.Thread(target=worker_task, daemon=True).start()

    def _start_local_update(self):
        """
        ローカルのzipファイルを選択し、GitHubを経由せず直接アップデートを適用する（動作確認・デバッグ用）。
        """
        if not getattr(sys, 'frozen', False):
            messagebox.showwarning(
                "アップデート不可",
                "現在は開発環境（.py実行）のため、自動アップデートは適用できません。\n"
                "exe化されたバージョンで実行してください。"
            )
            return

        zip_path = filedialog.askopenfilename(
            title="アップデート用のzipファイルを選択",
            filetypes=[("ZIPファイル", "*.zip")]
        )
        if not zip_path:
            return

        if not messagebox.askyesno(
            "確認",
            f"以下のzipファイルでアップデートを適用します。よろしいですか？\n\n{zip_path}\n\n"
            "適用前に現在のアプリ一式は自動でバックアップされます。"
        ):
            return

        self.append_log(f"📂 ローカルzipからのアップデートを開始します: {zip_path}")

        progress_dialog = ctk.CTkToplevel(self)
        progress_dialog.title("アップデート中")
        progress_dialog.geometry("400x120")
        progress_dialog.grab_set()
        progress_dialog.protocol("WM_DELETE_WINDOW", lambda: None)  # 更新中は閉じさせない

        status_label = ctk.CTkLabel(progress_dialog, text="準備しています...")
        status_label.pack(pady=(20, 10))
        progress_bar = ctk.CTkProgressBar(progress_dialog, width=320)
        progress_bar.pack(pady=10)
        progress_bar.set(1.0)  # ローカルファイルなのでダウンロード待ちが無く、即座に満タン表示

        def worker_task():
            try:
                tmp_dir = tempfile.mkdtemp(prefix="auto_reply_local_update_")
                self._apply_update_from_zip(zip_path, tmp_dir, progress_dialog, status_label)
            except Exception as e:
                # eはexcept節を抜けると消えるため、lambdaに渡す前に文字列化しておく
                message = f"予期しないエラー: {e}"
                self.after(0, lambda: self._on_update_failed(progress_dialog, message))

        threading.Thread(target=worker_task, daemon=True).start()

    def _apply_update_from_zip(self, zip_path, tmp_dir, progress_dialog, status_label):
        """
        zipファイル(zip_path)から、展開→exe検索→バックアップ→差し替え・再起動までを行う共通処理。
        GitHubからダウンロードした場合と、ローカルのzipを直接指定した場合の両方から呼ばれる。
        tmp_dirは、このアップデート処理で作った一時フォルダ（後片付け対象）。
        """
        self.after(0, lambda: status_label.configure(text="ファイルを展開しています..."))
        extract_dir = os.path.join(tmp_dir, "extracted")
        success, err = self.updater.extract_zip(zip_path, extract_dir)

        if not success:
            self.after(0, lambda: self._on_update_failed(progress_dialog, f"zipの展開に失敗しました: {err}"))
            return

        target_exe_path = sys.executable
        exe_name = os.path.basename(target_exe_path)
        source_dir = self.updater.find_exe_in_extracted(extract_dir, exe_name)

        if not source_dir:
            self.after(0, lambda: self._on_update_failed(
                progress_dialog,
                f"zip内に「{exe_name}」が見つかりませんでした。zipの中身をご確認ください。"
            ))
            return

        self.after(0, lambda: status_label.configure(text="バックアップを作成しています..."))
        backup_root_dir = os.path.join(os.path.expanduser("~"), "AutoReplyTool_Backups")
        self.updater.backup_current_installation(backup_root_dir)

        self.after(0, lambda: status_label.configure(text="再起動して更新を適用します..."))
        self.after(0, lambda: self.append_log("🔁 更新を適用するため、アプリを再起動します。"))

        target_dir = BASE_DIR
        launched = self.updater.create_update_batch_and_launch(
            source_dir, target_dir, target_exe_path, cleanup_dirs=[tmp_dir]
        )

        if not launched:
            self.after(0, lambda: self._on_update_failed(progress_dialog, "更新プロセスの起動に失敗しました。"))
            return

        # batファイル側が現プロセスの終了を待っているため、少し待ってから終了する
        time.sleep(1)
        self.after(0, lambda: os._exit(0))

    def _on_update_failed(self, progress_dialog, message):
        try:
            progress_dialog.destroy()
        except Exception:
            pass
        self.update_check_btn.configure(state="normal")
        self.append_log(f"❌ アップデートに失敗しました: {message}")
        messagebox.showerror("アップデート失敗", message)

    def on_closing(self):
        if self.worker.is_running:
            if not messagebox.askokcancel("確認", "現在ツールが実行中です。\n終了してもよろしいですか？"):
                return
            self.worker.stop()
        # 待ち受けポートを掴んだままにしないよう、確実に閉じる
        self.phone_bridge.stop()
        # マイクの転送も止める。開いたままだと音声デバイスを掴み続けてしまう
        self.stop_input_passthrough()
        self._cancel_scheduled_jobs()
        self._check_thread_and_destroy()

    def _cancel_scheduled_jobs(self):
        """
        終了前に、繰り返し予約している処理を止める。
        止めないと、破棄済みのウィジェットに対して発火してTclエラーが出る。
        """
        self._closing = True
        for attr in ("_clipboard_after_id", "_auto_update_after_id", "_pump_after_id"):
            job_id = getattr(self, attr, None)
            if job_id is None:
                continue
            try:
                self.after_cancel(job_id)
            except Exception:
                pass
            setattr(self, attr, None)

    def _check_thread_and_destroy(self):
        if self.worker.is_alive():
            self.after(100, self._check_thread_and_destroy)
            return
        # 監視スレッドが完全に止まってから更新を適用する。
        # 監視中にファイルを差し替えると、動いているコードと中身が食い違うことになる。
        if self._apply_pending_update_on_exit():
            return  # 適用処理側でプロセスを終了する
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    # exe(--windowed)では例外が起きても画面に何も出ずに終了してしまうため、
    # 内容をerror_log.txtに記録し、ダイアログでも通知する。
    try:
        main()
    except Exception:
        error_detail = traceback.format_exc()
        write_error_log("=== 起動時に予期しないエラーが発生しました ===")
        write_error_log(error_detail)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "起動エラー",
                "アプリの起動中にエラーが発生しました。\n\n"
                f"{error_detail[-1000:]}\n\n"
                f"詳細は次のファイルに保存されました:\n{ERROR_LOG_FILE}"
            )
            root.destroy()
        except Exception:
            pass
        sys.exit(1)
