# -*- coding: utf-8 -*-
"""
調べる（2026-10-16 本人「なにか代わりに調べてくれる時、調べるからちょっと待っててねみたいな一言あればいいかも」「チャットの中の話ね」）。
本人の決定: 調べる先は Wikipedia と天気 / 「待って」の一言は、下書きを見せる設定でも確かめずに送る。

- Wikipedia（日本語版の MediaWiki API。1回の問い合わせで、いちばん合う記事の見出しと冒頭の説明）
  … 言葉・作品・有名な人・出来事・場所の説明。文章は CC BY-SA 4.0 → 答えに「Wikipediaによると」と添えさせる
  ⚠️ User-Agent にアプリ名と連絡先（公開リポジトリの URL）を入れる（Wikimedia の User-Agent の決まり。無い・ありふれたものは 403）
- 天気（Open-Meteo。キー不要。非営利なら無料・1日1万回まで。データは CC BY 4.0）… 地名を緯度経度にして、今と3日分の予報
  ⚠️ 日本語の地名はそのままだと外れる（実測 2026-10-16:「東京」は見つからない・「横浜」は青森県の村）。
     「市・都・府・県」を付けた形も探し、人口のいちばん多い場所を選ぶ
- ⚠️ Gemini の Google 検索（googleSearch）は使わない: 規約で、検索結果は検索候補と一緒に、質問した本人へそのまま見せる必要がある。
     GRAVITY のチャット・声ではできない（2026-10-16 規約を確認）。無料枠でも使えない
- ⚠️ 調べる言葉はルームの人の発言から来る（外の文字）。長さを切って URL に入れる（urlencode）。返ってきた文も外の文字（データ）
- ウェブ検索・ニュース（Tavily。2026-10-23 本人「チャット欄で調べて欲しいことに対して…代わりに調べて」→ 選んだのは
  「ニュース・最新の話題」「ふつうのウェブ検索」・「Tavilyで作る」）。無料で毎月1,000回・カード不要。キーは本人が作って保存する
  … キーを保存したときだけ使える（無ければ選ばせない）。調べる言葉は Tavily（アメリカの会社）に送られる
  ⚠️ キーは Authorization の見出しで送る（URL に入れない・持ち続けない）。返ってきた文はどのサイトの文か分からないので、
     区切り記号（<<< >>>）を消してから渡す
  ⚠️ Google の Custom Search は新しく使えない（2027年1月に終わる）・Brave は申し込みにカードが要る（2026-10-23 調べ）
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

TOOL_WIKIPEDIA = "wikipedia"
TOOL_WEATHER = "weather"
TOOL_WEB = "web"
TOOL_NEWS = "news"
BASIC_TOOLS = (TOOL_WIKIPEDIA, TOOL_WEATHER)
SEARCH_TOOLS = (TOOL_WEB, TOOL_NEWS)          # 検索のキーを保存したときだけ使える
TOOLS = BASIC_TOOLS + SEARCH_TOOLS
TOOL_LABELS = {TOOL_WIKIPEDIA: "Wikipedia", TOOL_WEATHER: "天気", TOOL_WEB: "ウェブ検索", TOOL_NEWS: "ニュース"}

WIKIPEDIA_API = "https://ja.wikipedia.org/w/api.php"
GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_API = "https://api.open-meteo.com/v1/forecast"
SEARCH_API = "https://api.tavily.com/search"
SEARCH_KEY_ID = "tavily"                 # api_keys に保存する名前（settings の ai_api_key.tavily）
SEARCH_KEY_ENV = "TAVILY_API_KEY"
SEARCH_RESULTS = 5
SEARCH_NEWS_DAYS = 7
MAX_SNIPPET_CHARS = 220
MAX_SEARCH_TEXT_CHARS = 1200
# Tavily が返す番号 → わけ（docs: 429 は回数が速すぎる・432 はプランの回数を超えた）
SEARCH_ERRORS = {400: "検索の頼み方が合わなかった", 401: "検索のキーが使えない（設定タブで保存し直す）",
                 403: "検索のキーが使えない（設定タブで保存し直す）", 429: "検索が混んでいる（少し待つ）",
                 432: "検索の今月の無料の回数を使い切った", 433: "検索の回数の上限を超えた"}
MAX_QUERY_CHARS = 60
MAX_EXTRACT_CHARS = 500
PLACE_SUFFIXES = ("市", "都", "府", "県")
BIG_PLACE = 100000          # これより人口の多い場所が見つかれば、「市」などを付けて探し直さない

# WMO の天気の番号（Open-Meteo の weather_code）
WEATHER_WORDS = {0: "快晴", 1: "晴れ", 2: "晴れ時々くもり", 3: "くもり", 45: "霧", 48: "霧（霧氷）",
                 51: "弱い霧雨", 53: "霧雨", 55: "強い霧雨", 56: "着氷性の霧雨", 57: "強い着氷性の霧雨",
                 61: "弱い雨", 63: "雨", 65: "強い雨", 66: "着氷性の雨", 67: "強い着氷性の雨",
                 71: "弱い雪", 73: "雪", 75: "強い雪", 77: "霧雪", 80: "弱いにわか雨", 81: "にわか雨", 82: "激しいにわか雨",
                 85: "にわか雪", 86: "強いにわか雪", 95: "雷雨", 96: "雷雨（ひょう）", 99: "激しい雷雨（ひょう）"}
DAY_LABELS = ("今日", "明日", "あさって")


@dataclass
class LookupResult:
    ok: bool
    tool: str
    query: str
    text: str = ""        # AI に渡す中身（見つからなければ空）
    source: str = ""      # 出典（例: Wikipedia「富士山」）
    note: str = ""        # うまくいかなかったわけ（見つからない・つながらない など）


class Lookup:
    def __init__(self, user_agent, fetch=None, timeout=8.0, search_key=None, post=None):
        self.user_agent = user_agent
        self.timeout = timeout
        self._fetch = fetch or self._fetch_json     # (url) -> dict。テストでは にせもの
        self._post = post or self._post_json        # (url, body, headers) -> dict。テストでは にせもの
        self._search_key = search_key               # () -> 検索のキー（無ければ None）。使う直前に読む

    def available_tools(self):
        """今使える調べ方。検索のキーが無ければ、ウェブ検索・ニュースは出さない"""
        return TOOLS if self._has_search_key() else BASIC_TOOLS

    def _has_search_key(self):
        try:
            return bool(self._search_key and self._search_key())
        except Exception:
            return False

    def run(self, tool, query, cancel=None):
        """調べる。失敗しても例外にせず、LookupResult(ok=False, note=わけ) を返す"""
        query = " ".join((query or "").split())[:MAX_QUERY_CHARS]
        if tool not in TOOLS:
            return LookupResult(False, tool or "", query, note="調べられない種類")
        if not query:
            return LookupResult(False, tool, query, note="何を調べるかが分からない")
        try:
            if tool == TOOL_WIKIPEDIA:
                return self.wikipedia(query)
            if tool in SEARCH_TOOLS:
                return self.search(tool, query)
            return self.weather(query, cancel)
        except urllib.error.HTTPError as e:
            note = SEARCH_ERRORS.get(e.code) if tool in SEARCH_TOOLS else None
            return LookupResult(False, tool, query, note=note or f"つながらなかった（HTTP {e.code}）")
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
            return LookupResult(False, tool, query, note=f"つながらなかった（{type(e).__name__}）")

    # --- Wikipedia ---
    def wikipedia(self, query):
        params = {"action": "query", "format": "json", "formatversion": "2", "redirects": "1",
                  "generator": "search", "gsrsearch": query, "gsrlimit": "1",
                  "prop": "extracts|info", "exintro": "1", "explaintext": "1", "exchars": str(MAX_EXTRACT_CHARS),
                  "inprop": "url"}
        data = self._fetch(WIKIPEDIA_API + "?" + urllib.parse.urlencode(params))
        pages = (data.get("query") or {}).get("pages") or []
        page = pages[0] if pages else {}
        title, extract = page.get("title") or "", " ".join((page.get("extract") or "").split())
        if not title or not extract:
            return LookupResult(False, TOOL_WIKIPEDIA, query, note="Wikipediaに合う記事が見つからなかった")
        return LookupResult(True, TOOL_WIKIPEDIA, query, text=f"記事の見出し: {title}\n{extract[:MAX_EXTRACT_CHARS]}",
                            source=f"Wikipedia「{title}」")

    # --- 天気 ---
    def find_place(self, name, cancel=None):
        """地名 → いちばん合いそうな場所（人口の多い順）。見つからなければ None"""
        candidates = []
        variants = [name] + [name + s for s in PLACE_SUFFIXES if not name.endswith(s)]
        for i, variant in enumerate(variants):
            if cancel is not None and cancel.cancelled:
                break
            if i == 1 and any((r.get("population") or 0) >= BIG_PLACE for r in candidates):
                break           # そのままの名前で大きな町が見つかった（「パリ」「名古屋市」など）
            params = {"name": variant, "count": "10", "language": "ja", "format": "json"}
            candidates += self._fetch(GEOCODING_API + "?" + urllib.parse.urlencode(params)).get("results") or []
        candidates = [r for r in candidates if "latitude" in r and "longitude" in r]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.get("population") or 0)

    def weather(self, query, cancel=None):
        place = self.find_place(query, cancel)
        if place is None:
            return LookupResult(False, TOOL_WEATHER, query, note=f"「{query}」という場所が見つからなかった")
        params = {"latitude": place["latitude"], "longitude": place["longitude"],
                  "current": "temperature_2m,weather_code",
                  "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                  "timezone": place.get("timezone") or "auto", "forecast_days": "3"}
        data = self._fetch(FORECAST_API + "?" + urllib.parse.urlencode(params))
        where = "・".join(x for x in (place.get("admin1"), place.get("country")) if x and x != place.get("name"))
        lines = [f"場所: {place.get('name')}" + (f"（{where}）" if where else "")]
        current = data.get("current") or {}
        if "temperature_2m" in current:
            lines.append(f"今: {current['temperature_2m']:.0f}℃・{WEATHER_WORDS.get(current.get('weather_code'), '不明')}")
        daily = data.get("daily") or {}
        for i, day in enumerate(daily.get("time") or []):
            label = DAY_LABELS[i] if i < len(DAY_LABELS) else ""
            month_day = f"{int(day[5:7])}/{int(day[8:10])}" if len(day) >= 10 else day
            word = WEATHER_WORDS.get(_at(daily, "weather_code", i), "不明")
            high, low = _at(daily, "temperature_2m_max", i), _at(daily, "temperature_2m_min", i)
            rain = _at(daily, "precipitation_probability_max", i)
            parts = [f"{month_day}（{label}）: {word}"]
            if high is not None and low is not None:
                parts.append(f"最高{high:.0f}℃・最低{low:.0f}℃")
            if rain is not None:
                parts.append(f"降水確率{rain:.0f}%")
            lines.append(" ".join(parts))
        return LookupResult(True, TOOL_WEATHER, query, text="\n".join(lines), source="天気（Open-Meteo）")

    # --- ウェブ検索・ニュース（Tavily） ---
    def search(self, tool, query):
        key = self._search_key() if self._search_key else None
        if not key:
            return LookupResult(False, tool, query, note="ウェブ検索のキーが保存されていない")
        body = {"query": query, "topic": "news" if tool == TOOL_NEWS else "general", "search_depth": "basic",
                "max_results": SEARCH_RESULTS, "include_answer": False, "include_images": False}
        if tool == TOOL_NEWS:
            body["days"] = SEARCH_NEWS_DAYS
        data = self._post(SEARCH_API, body, {"Authorization": f"Bearer {key}"})
        key = None
        lines, sites, size = [], [], 0
        for r in data.get("results") or []:
            title = _plain(r.get("title"))
            content = _plain(r.get("content"))[:MAX_SNIPPET_CHARS]
            if not title and not content:
                continue
            site = _site(r.get("url"))
            head = "・".join(x for x in (site, _plain(r.get("published_date"))[:32]) if x)
            line = f"- {title}" + (f"（{head}）" if head else "") + (f": {content}" if content else "")
            if lines and size + len(line) > MAX_SEARCH_TEXT_CHARS:
                break
            lines.append(line[:MAX_SEARCH_TEXT_CHARS])
            size += len(line)
            if site and site not in sites:
                sites.append(site)
        label = TOOL_LABELS[tool]
        if not lines:
            return LookupResult(False, tool, query, note=f"{label}で見つからなかった")
        return LookupResult(True, tool, query, text="\n".join(lines),
                            source=f"{label}（{'・'.join(sites[:3])}）" if sites else label)

    # --- 通信 ---
    def _fetch_json(self, url):
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, url, body, headers):
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers={"User-Agent": self.user_agent, "Accept": "application/json",
                                                  "Content-Type": "application/json", **headers})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def _at(daily, key, i):
    values = daily.get(key) or []
    return values[i] if i < len(values) else None


def _plain(value):
    """外のサイトの文を1行にして、区切り記号（<<< >>>）を消す"""
    return " ".join(str(value or "").replace("<<<", "").replace(">>>", "").split())


def _site(url):
    """URL → サイト名（www. を外したホスト名）。URL そのものは AI に渡さない"""
    try:
        host = urllib.parse.urlsplit(str(url or "")).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def user_agent(app_name, version, contact_url):
    """Wikimedia の決まりに合う User-Agent（アプリ名/版 (連絡先; bot) ライブラリ）"""
    return f"{app_name}/{version} ({contact_url}; bot) Python-urllib/{sys.version_info[0]}.{sys.version_info[1]}"
