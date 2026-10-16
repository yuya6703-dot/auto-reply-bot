# -*- coding: utf-8 -*-
"""
オーナーの合図（2026-10-16 本人「1から6まで」の2）。オーナーがチャットで AI に呼びかけて、静かにさせる・戻す・覚えさせる。
AI を呼ばずに規則で見る（速い・費用がかからない）。

⚠️ オーナーは表示名でしか見分けられない（GRAVITY では誰でも同じ名前にできる＝なりすませる）。だから合図は、悪用されても困らないものだけ:
   - 静かにする・戻る … 止める・止めをやめるだけ（静かにする長さには上限がある）
   - 覚えて … 「（オーナーから）」と付けたふつうの記憶にする（確かなこととして扱うメモにはしない）。一覧で見て消せる。
     繊細な事柄は覚えない。「会話を覚える」がOFFなら覚えない
⚠️ AI に呼びかけていない発言は合図にしない（「静かにしてって言われた」のような話を取り違えない）
"""
import re
import unicodedata

from .events import name_matches
from .gate import _CUT_MENTION, mentions_name

CMD_MUTE = "mute"
CMD_UNMUTE = "unmute"
CMD_REMEMBER = "remember"
DEFAULT_MUTE_MINUTES = 30
MAX_MUTE_MINUTES = 360

_UNMUTE = re.compile(r"(もういいよ|もう大丈夫|話していいよ|喋っていいよ|しゃべっていいよ|戻っていいよ|もどっていいよ|戻ってきて|"
                     r"もどってきて|ミュート解除)")
_MUTE = re.compile(r"(静かにして|しずかにして|黙って|だまって|ミュート|喋らないで|しゃべらないで|お口チャック)")
_REMEMBER = re.compile(r"[、,\s]*(?:って|と)?(?:覚えておいて|覚えといて|覚えてて|覚えて|おぼえておいて|おぼえといて|おぼえてて|おぼえて)"
                       r"(?:ね|ください|くれる|おいて|お願い)?[。！!？?〜~\s]*$")
_MINUTES = re.compile(r"(\d{1,3})\s*分")
_HOURS = re.compile(r"(\d{1,2})\s*時間")
_LONG = re.compile(r"(ずっと|しばらく)")
_EDGE = re.compile(r"^[\s、,，。.：:・!！?？〜~]+|[\s、,，。.：:・〜~]+$")


def _norm(text):
    return unicodedata.normalize("NFKC", text or "").strip()


def is_owner(event, config):
    """オーナーの発言か（表示名で見る。⚠️ なりすましは防げない）"""
    return bool(event.speaker) and not event.is_self and any(name_matches(event.speaker, owner)
                                                             for owner in config.owner_name_list)


def mute_minutes(text):
    """「10分」「1時間」「ずっと」→ 分。書いていなければ30分。上限6時間"""
    m = _HOURS.search(text)
    if m:
        minutes = int(m.group(1)) * 60
    else:
        m = _MINUTES.search(text)
        minutes = int(m.group(1)) if m else (MAX_MUTE_MINUTES if _LONG.search(text) else DEFAULT_MUTE_MINUTES)
    return max(1, min(MAX_MUTE_MINUTES, minutes))


def strip_names(text, names):
    """呼びかけ（名前・@名前・切れたメンション）と、端の句読点を除く"""
    text = _CUT_MENTION.sub("", text)
    for name in sorted((_norm(n) for n in names if n), key=len, reverse=True):
        text = text.replace("@" + name.lstrip("@"), "").replace(name, "")
    previous = None
    while previous != text:
        previous, text = text, _EDGE.sub("", text)
    return text.strip()


def parse_command(text, call_names):
    """オーナーの発言から合図を読む。(種類, 値) か None（AI に呼びかけていなければ None）"""
    text = _norm(text)
    if not text or not mentions_name(text, call_names):
        return None
    if _UNMUTE.search(text) and not _MUTE.search(text.replace("ミュート解除", "")):
        return CMD_UNMUTE, None
    if _MUTE.search(text):
        return CMD_MUTE, mute_minutes(text)
    m = _REMEMBER.search(text)
    if m:
        content = strip_names(text[:m.start()], call_names)
        if content:
            return CMD_REMEMBER, content
    return None
