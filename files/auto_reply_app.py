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

try:
    import winsound  # Windows標準ライブラリ。アラーム音の再生に使用（Windows以外では利用不可）
except ImportError:
    winsound = None

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
APP_VERSION = "1.2.0"  # リリースするたびにこの値を上げ、同じ番号でタグ(例: v1.2.0)をpushしてください

# GitHubリポジトリ情報（owner/repo）
# ⚠️ アプリの更新確認は「未認証」でGitHub APIを叩くため、ここで指定するリポジトリは
# public である必要がある。private だと利用者側では常に404になり、更新を検知できない。
GITHUB_OWNER = "yuya6703-dot"
GITHUB_REPO = "auto-reply-bot"
GITHUB_API_LATEST_RELEASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

# 絶対に反応させない（無視する）ワードのリスト
IGNORE_WORDS = [
    "がマイクをもらいました"
]

DEFAULT_KEYWORDS = {
    "が音声ルームに参加しました": "よろしくお願いします！"
}

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
_QUOTED_TEXT_RE = re.compile(r'「([^」]*)」')


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
        """
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
    def __init__(self, log_callback=None):
        self.log_callback = log_callback or (lambda msg: None)

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

    def fetch_latest_release(self, timeout=10):
        """
        GitHub Releases APIから最新リリース情報を取得する。
        戻り値: dict{tag_name, name, body, assets:[{name, browser_download_url}, ...]} または None（取得失敗時）
        """
        try:
            req = urllib.request.Request(
                GITHUB_API_LATEST_RELEASE,
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
                self.log("ℹ️ リリースがまだ公開されていません。")
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

    def create_update_batch_and_launch(self, source_dir, target_dir, target_exe_path, cleanup_dirs=None):
        """
        展開済みの新しいアプリ一式(source_dir)を、現在のインストール先(target_dir)へ上書きコピーし、
        再起動するためのPowerShellスクリプトを作成・実行する。
        実行中のexeは自分自身のフォルダを直接上書きできないため、外部スクリプトに処理を委譲してから終了する。

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
    Write-Host "Update failed. The previous version will be started."
    Start-Sleep -Seconds 5
}} else {{
    Write-Host "Update applied successfully."
}}

Start-Process -FilePath '{target_exe_q}'

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


# ====================================================
# 🤖 2. 監視ワーカー (uiautomator2 + XML解析 + 自動返信)
# ====================================================
class AutoReplyWorker:
    def __init__(self, db: DatabaseManager, log_callback):
        self.db = db
        self.log_callback = log_callback
        self.is_running = False
        self.thread = None

        self.re_node = re.compile(r'<node\s+([^>]+)>')
        self.re_text = re.compile(r'text="([^"]+)"')
        self.re_desc = re.compile(r'content-desc="([^"]+)"')
        self.re_bounds = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
        self.re_class = re.compile(r'class="([^"]+)"')
        self.re_clickable = re.compile(r'clickable="true"')

        self._last_seen_any_chat = ""

        # 監視ループから毎回DBを読むと0.3秒ごとに何度も接続することになるため、
        # 短時間だけ結果を保持する（設定変更への追従はこの秒数だけ遅れる）
        self._config_cache = None
        self._config_cache_time = 0.0
        self.CONFIG_CACHE_SECONDS = 1.0

        # ログ保存時にマスクせず残す語（自分で登録した検知ワード・返信ワード）。
        # 設定を読み込むたびに最新化される。
        self._log_keep_words = []

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

    # --- エミュレータ接続 ---
    def _connect_to_emulator(self):
        self.log("🔄 エミュレータの検出を試みています...")
        try:
            adb.connect("127.0.0.1:7555")
        except Exception:
            pass
        try:
            adb.connect("127.0.0.1:16384")
        except Exception:
            pass

        device_list = adb.device_list()
        if not device_list:
            raise Exception("接続可能なエミュレータが見つかりません。起動しているか確認してください。")

        target_serial = device_list[0].serial
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

    def _perform_initial_scan(self, d, y_min, y_max):
        self.log("🔍 [テスト] 監視範囲内から読み取れる文字を調べています...")
        try:
            xml_dump = d.dump_hierarchy(compressed=True)
            chat_texts, _, _ = self._extract_chat_texts(xml_dump, y_min, y_max)

            dumped_texts = []
            for t, _ in chat_texts:
                if t.strip() and t not in dumped_texts:
                    dumped_texts.append(t)

            if dumped_texts:
                self.log("📋 監視範囲内で以下の文字を認識しました（最初の15件）:")
                for t in dumped_texts[:15]:
                    self.log(f" - {t}")
            else:
                self.log("⚠️ 監視範囲内から文字を全く読み取れませんでした。範囲がずれているか、画像化されています。")
        except Exception as e:
            self.log(f"⚠️ 文字スキャン中にエラーまたはタイムアウト: {e}")
            self.log("💡 アプリの構造が複雑すぎるか、読み取りがブロックされています。")

    def _extract_chat_texts(self, xml_dump, y_min, y_max):
        nodes = self.re_node.findall(xml_dump)
        chat_texts = []
        out_of_bounds_texts = []

        for node in nodes:
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
        return chat_texts, out_of_bounds_texts, nodes

    def _find_and_tap_input(self, d, nodes, half_y):
        target_x, target_y = None, None

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
                        self.log(f"👆 画面下部の入力ボタン(「{t_val[:10]}」)をタップしました。")
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
            for node in nodes:
                c_match = self.re_class.search(node)
                cl_match = self.re_clickable.search(node)
                b_match = self.re_bounds.search(node)
                if c_match and "TextView" in c_match.group(1) and cl_match and b_match:
                    left, top, right, bottom = map(int, b_match.groups())
                    if bottom > half_y:
                        target_x, target_y = (left + right) / 2, (top + bottom) / 2
                        self.log("👆 画面下部のクリック可能な枠(TextView)をタップしました。")
                        break

        if target_x and target_y:
            d.click(target_x, target_y)
            return True
        return False

    def _send_reply(self, d, reply_message):
        try:
            d.clear_text()
            time.sleep(0.2)
        except Exception:
            pass

        d.send_keys(reply_message)
        self.log("⌨️ キーボード経由で文字を入力しました。")

        time.sleep(0.5)
        d.press("enter")
        time.sleep(0.5)

        send_xml = d.dump_hierarchy(compressed=True)
        is_sent = False
        for node in self.re_node.findall(send_xml):
            t_match = self.re_text.search(node)
            d_match = self.re_desc.search(node)
            b_match = self.re_bounds.search(node)
            if b_match:
                t_val = (t_match.group(1) if t_match else "") + (d_match.group(1) if d_match else "")
                if any(sb in t_val for sb in ["送信", "送る", "Send", "send"]):
                    left, top, right, bottom = map(int, b_match.groups())
                    d.click((left + right) / 2, (top + bottom) / 2)
                    self.log("👆 送信ボタンをタップしました。")
                    is_sent = True
                    break

        if is_sent:
            self.log(f" ✉️ 「{reply_message}」を送信しました。")
        else:
            self.log(f"⚠️ 送信ボタンが見つかりませんでした。(エンターキーのみで「{reply_message}」の送信を試みました)")

        time.sleep(1.0)
        d.press("back")
        self.log("🔽 キーボードを閉じて待機状態に戻りました。")
        return is_sent

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
                d.swipe(center_x, start_y, center_x, end_y, duration=0.2)
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

    def _execute_reply(self, d, nodes, half_y, y_min_internal, y_max_internal, reply_message, failure_count, FAILURE_WARN_THRESHOLD):
        """入力欄タップ〜送信〜スクロールまでを実行し、更新後のfailure_countを返す"""
        if self._find_and_tap_input(d, nodes, half_y):
            time.sleep(1.0)
            sent_ok = self._send_reply(d, reply_message)

            if sent_ok:
                failure_count = 0
            else:
                failure_count += 1
                self.log(f"⚠️ 送信ボタンが見つからず失敗としてカウントしました。(連続失敗 {failure_count}回)")

            self._scroll_down(d, y_min_internal, y_max_internal, silent=False)
        else:
            failure_count += 1
            self.log(f"⚠️ 入力欄(EditTextやプレースホルダー)が見つからなかったため、返信をスキップしました。(連続失敗 {failure_count}回)")

        if failure_count >= FAILURE_WARN_THRESHOLD:
            self.log(f"🚨 入力欄・送信ボタンの検出に {failure_count}回連続で失敗しています。アプリのUIレイアウトが変わっていないか確認してください。")
            failure_count = 0

        return failure_count

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

        self._perform_initial_scan(d, y_min_internal, y_max_internal)
        self.log(" 監視を開始しました... (■ 停止ボタンで終了)")

        last_processed_logs = {}
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
                chat_texts, out_of_bounds_texts, nodes = self._extract_chat_texts(xml_dump, y_min_internal, y_max_internal)

                chat_texts = [item for item in chat_texts if not any(ignore in item[0] for ignore in IGNORE_WORDS)]
                out_of_bounds_texts = [t for t in out_of_bounds_texts if not any(ignore in t for ignore in IGNORE_WORDS)]

                # 検知ワードの有無を素早く判定するための検索用文字列。
                # 生のXMLではなく、エスケープを戻した後のテキストを使う。
                detected_texts_joined = "\n".join([t for t, _ in chat_texts] + out_of_bounds_texts)

                if chat_texts:
                    current_latest = max(chat_texts, key=lambda x: x[1])[0]
                    if current_latest != self._last_seen_any_chat:
                        is_own_reply = any(reply in current_latest for reply in keywords_map.values())
                        if not is_own_reply:
                            self.log(f"👀 文字検知:「{current_latest}」")
                        self._last_seen_any_chat = current_latest

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
                        failure_count = self._execute_reply(
                            d, nodes, half_y,
                            y_min_internal, y_max_internal, reply_message,
                            failure_count, FAILURE_WARN_THRESHOLD
                        )
                        last_sent_time[trigger_word] = time.time()
                        last_scroll_time = time.time()
                        last_processed_logs[trigger_word] = (latest_log, time.time())
                        time.sleep(1)

                for trigger_word, reply_message in list(keywords_map.items()):
                    if not self.is_running:
                        break

                    if trigger_word not in detected_texts_joined:
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

                    latest_item = max(matched_elements, key=lambda x: x[1])
                    latest_log = latest_item[0]

                    if reply_message in latest_log:
                        last_processed_logs[trigger_word] = (latest_log, time.time())
                        continue

                    last_log, last_time = last_processed_logs.get(trigger_word, ("", 0))

                    if last_log != latest_log or (time.time() - last_time) > 15:
                        self.log(f"🎯 検知!【{trigger_word}】ログ:「{latest_log}」")

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
                            failure_count = self._execute_reply(
                                d, nodes, half_y, y_min_internal, y_max_internal,
                                reply_message, failure_count, FAILURE_WARN_THRESHOLD
                            )
                            last_sent_time[trigger_word] = time.time()
                            last_scroll_time = time.time()
                            last_processed_logs[trigger_word] = (latest_log, time.time())
                            time.sleep(1)

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
        self.updater = UpdateManager(self.append_log)

        self.last_coords = self._load_last_coords()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.build_ui()
        self.append_log(f"[システム] アプリケーション起動 (v{APP_VERSION})")

        # 過去バージョンでたまった古いログを整理する（DBの肥大化対策）
        removed_logs = self.db.prune_logs()
        if removed_logs:
            self.append_log(f"🧹 古いログ{removed_logs}件を整理しました（最新{self.db.MAX_LOG_ROWS}件を保持）。")

        # 起動時に自動でアップデートを確認する（バックグラウンド・失敗しても無視）
        self.after(1500, lambda: self.check_for_updates(silent=True))

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
        self.tab_settings = self.tabview.add("設定")

        self.build_main_tab()
        self.build_keywords_tab()
        self.build_timer_tab()
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

        self.log_textbox = ctk.CTkTextbox(self.tab_main, state="disabled")
        self.log_textbox.pack(fill="both", expand=True, padx=10, pady=10)

    # --- キーワード設定タブ ---
    def build_keywords_tab(self):
        # --- セット選択・管理エリア ---
        set_frame = ctk.CTkFrame(self.tab_keywords, fg_color="transparent")
        set_frame.pack(fill="x", padx=10, pady=(10, 5))

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

        # CTkにはリストボックスが無いため、標準tkinter Listboxを埋め込む
        self.keyword_listbox = tk.Listbox(list_frame, font=("", 11), bg="#2b2b2b", fg="#dce4ee",
                                           selectbackground="#1f6aa5", highlightthickness=0, bd=0)
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

        frame = ctk.CTkFrame(self.tab_timer, fg_color="transparent")
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
        total_seconds = max(0, int(total_seconds))
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        self.timer_display_label.configure(text=f"{h:02d}:{m:02d}:{s:02d}")

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

        ctk.CTkLabel(style_frame, text="声のスタイル:").pack(side="left", padx=(0, 8))

        # 保存済みのスタイル一覧があればそれを使う（前回エンジンから取得した内容）
        self._zundamon_styles = dict(DEFAULT_ZUNDAMON_STYLES)
        saved_styles_json = self.db.get_setting("alarm_zundamon_styles", "")
        if saved_styles_json:
            try:
                loaded = json.loads(saved_styles_json)
                if isinstance(loaded, dict) and loaded:
                    self._zundamon_styles = {k: int(v) for k, v in loaded.items()}
            except (ValueError, TypeError):
                pass

        saved_speaker = self.get_zundamon_speaker_id()
        current_style_name = next(
            (name for name, sid in self._zundamon_styles.items() if sid == saved_speaker),
            next(iter(self._zundamon_styles))
        )
        self.zundamon_style_var = ctk.StringVar(value=current_style_name)
        self.zundamon_style_menu = ctk.CTkOptionMenu(
            style_frame, variable=self.zundamon_style_var,
            values=list(self._zundamon_styles.keys()),
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

    def on_zundamon_style_change(self, _style_name=None):
        speaker_id = self.get_zundamon_speaker_id()
        self.db.save_setting("alarm_zundamon_speaker", str(speaker_id))
        self.append_log(f"⚙️ ずんだもんの声を「{self.zundamon_style_var.get()}」に設定しました。")

    def save_voicevox_url(self):
        url = self.get_voicevox_url()
        if url != (self.db.get_setting("voicevox_url", DEFAULT_VOICEVOX_URL) or "").rstrip("/"):
            self.db.save_setting("voicevox_url", url)

    def check_voicevox_connection(self):
        """VOICEVOXに接続して、ずんだもんのスタイル一覧を取得し直す"""
        self.save_voicevox_url()

        def run():
            try:
                styles = self.fetch_zundamon_styles()
            except Exception as e:
                # except節を抜けると変数eは削除される。lambdaはafter()で後から実行されるため、
                # lambda内でeを参照するとNameErrorになり、肝心のエラーダイアログが出ない。
                # 先に文字列へ組み立てておく。
                message = (
                    f"VOICEVOXに接続できませんでした。\n\n"
                    f"URL: {self.get_voicevox_url()}\n詳細: {e}\n\n"
                    "VOICEVOXを起動してから、もう一度お試しください。"
                )
                self.after(0, lambda: messagebox.showerror("接続できません", message))
                return
            self.after(0, lambda: self._apply_zundamon_styles(styles))

        threading.Thread(target=run, daemon=True).start()

    def _apply_zundamon_styles(self, styles):
        """取得したスタイル一覧をプルダウンに反映し、次回起動用にDBへ保存する"""
        self._zundamon_styles = styles
        names = list(styles.keys())
        self.zundamon_style_menu.configure(values=names)

        current = self.zundamon_style_var.get()
        if current not in styles:
            self.zundamon_style_var.set(names[0])
        self.db.save_setting("alarm_zundamon_styles", json.dumps(styles, ensure_ascii=False))
        self.db.save_setting("alarm_zundamon_speaker", str(self.get_zundamon_speaker_id()))
        self._zundamon_wav_cache = {}  # スタイル一覧が変わったのでキャッシュを捨てる
        self.append_log(f"✅ VOICEVOXに接続しました（ずんだもんのスタイル{len(names)}件）。")
        messagebox.showinfo("接続成功", f"VOICEVOXに接続できました。\nずんだもんのスタイル{len(names)}件を読み込みました。")

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
        """現在のアラーム音量(0〜100)を返す。UI未構築時は保存値を読む。"""
        var = getattr(self, "alarm_volume_var", None)
        if var is not None:
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
        var = getattr(self, "alarm_type_var", None)
        if var is not None:
            return self._alarm_type_from_label(var.get())
        return self.db.get_setting("alarm_sound_type", ALARM_TYPE_BEEP)

    def get_zundamon_text(self):
        entry = getattr(self, "zundamon_text_entry", None)
        if entry is not None:
            return entry.get().strip() or DEFAULT_ZUNDAMON_TEXT
        return self.db.get_setting("alarm_zundamon_text", DEFAULT_ZUNDAMON_TEXT)

    def get_zundamon_speaker_id(self):
        var = getattr(self, "zundamon_style_var", None)
        styles = getattr(self, "_zundamon_styles", DEFAULT_ZUNDAMON_STYLES)
        if var is not None and var.get() in styles:
            return styles[var.get()]
        try:
            return int(self.db.get_setting("alarm_zundamon_speaker", str(DEFAULT_ZUNDAMON_STYLES["ノーマル"])))
        except (TypeError, ValueError):
            return DEFAULT_ZUNDAMON_STYLES["ノーマル"]

    def get_voicevox_url(self):
        entry = getattr(self, "voicevox_url_entry", None)
        if entry is not None:
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

    def fetch_zundamon_styles(self):
        """
        VOICEVOXエンジンからずんだもんのスタイル一覧を取得して {スタイル名: 話者ID} で返す。
        接続できない場合は例外を投げる（呼び出し側でメッセージ表示）。
        """
        raw = self._voicevox_request("/speakers", timeout=10)
        speakers = json.loads(raw.decode("utf-8"))
        styles = {}
        for speaker in speakers:
            if "ずんだもん" not in speaker.get("name", ""):
                continue
            for style in speaker.get("styles", []):
                styles[style["name"]] = style["id"]
        if not styles:
            raise RuntimeError("エンジンからずんだもんの音声が見つかりませんでした。")
        return styles

    def synthesize_zundamon_wav(self, text, speaker_id):
        """
        ずんだもんの読み上げ音声をVOICEVOXで合成してWAVデータ(bytes)を返す。
        同じ内容の再合成を避けるため、結果はメモリ上にキャッシュする。
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

        cache[cache_key] = wav_data
        return wav_data

    # --- 再生 ---
    def _play_wav_bytes(self, wav_data, volume_percent):
        if winsound is None or not wav_data:
            return False
        try:
            winsound.PlaySound(self._apply_volume_to_wav(wav_data, volume_percent), winsound.SND_MEMORY)
            return True
        except Exception:
            return False

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
            try:
                return self.synthesize_zundamon_wav(self.get_zundamon_text(), self.get_zundamon_speaker_id()), None
            except Exception as e:
                return None, (
                    f"ずんだもん音声の生成に失敗しました（{e}）。\n"
                    "VOICEVOXが起動しているか確認してください。ビープ音で代替します。"
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
        frame = ctk.CTkFrame(self.tab_settings, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=20)

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

        # --- ローカルzipからのアップデート（動作確認・デバッグ用） ---
        separator = ctk.CTkFrame(self.tab_settings, height=2, fg_color="gray30")
        separator.pack(fill="x", padx=20, pady=(10, 20))

        local_update_frame = ctk.CTkFrame(self.tab_settings, fg_color="transparent")
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
        try:
            self.after(0, update_gui)
        except Exception:
            pass

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

    # ====================================================
    # 🔄 アップデート機能
    # ====================================================
    def check_for_updates(self, silent=True):
        """
        GitHub Releasesを確認する。
        silent=True: 起動時の自動チェック。新バージョンが無ければ何も表示しない。
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
        self._check_thread_and_destroy()

    def _check_thread_and_destroy(self):
        if self.worker.is_alive():
            self.after(100, self._check_thread_and_destroy)
        else:
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
