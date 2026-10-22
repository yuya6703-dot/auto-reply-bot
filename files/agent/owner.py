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
CMD_DELEGATE = "delegate"            # 代わりに伝えて（2026-10-23）
CMD_DELEGATE_END = "delegate_end"    # 戻った・もう伝えなくていい
DEFAULT_MUTE_MINUTES = 30
MAX_MUTE_MINUTES = 360
DEFAULT_DELEGATE_MINUTES = 60

# オーナーの代わりに伝える（2026-10-23 本人「チャットで（AIの名前）に代わりとして頼んだ時にそれを実行してくれたりしたら助かる…
# 俺が音声ルームでチャットに対して反応できない時のために…新規でルーム入ってきた人に対してルームオーナーはこのような状況なので
# 反応できないです。みたいなことを伝えてくれるとか」。実物 10/22: 「トイレ行くからさ、マイクのミュートするんだけど、俺がいない時に
# 代わりに主が話せない理由も伝えといて」）。⚠️ なりすましもありうるので、AI がするのは「頼まれた状況を伝える」ことだけ
_DELEGATE = re.compile(r"(代わりに|かわりに|代理で|伝えといて|伝えておいて|伝えてあげて|伝えてて|言っといて|言っておいて|"
                       r"説明しといて|説明しておいて)")
_DELEGATE_END = re.compile(r"(ただいま|戻った|もどった|戻ってきた|もどってきた|伝えなくていい|言わなくていい|伝えなくて大丈夫|"
                           r"代わりはもういい|かわりはもういい)")

_UNMUTE = re.compile(r"(もういいよ|もう大丈夫|話していいよ|喋っていいよ|しゃべっていいよ|戻っていいよ|もどっていいよ|戻ってきて|"
                     r"もどってきて|ミュート解除)")
# 頼む形のときだけ合図にする（2026-10-22 本人「静かにしてって言ってないのにそう言ったと認識してる」）。言葉を含むだけで合図にしていて、
# 「そもそもミュートしてるのに」「なんで静かにしてるん」「マイクのミュートするんだけど、…伝えといて」で静かになった（実際に3回）。
# ⚠️ 後ろに る・た・な(い)・ま(す)・ん・っ(て)・いる/いた/いま が続く形は、様子・否定・言われたことの話なので合図にしない。
#    「ミュート」だけ（名詞。マイクのミュートの話が多い）も合図にしない（「ミュートして」「ミュートにして」は合図）
_MUTE = re.compile(r"(静かにして|しずかにして|黙って|だまって|ミュートして|ミュートにして|喋らないで|しゃべらないで|お口チャック)"
                   r"(?!る|た|な|ま|ん|っ|いる|いた|いま)")
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


def mute_minutes(text, default=DEFAULT_MUTE_MINUTES):
    """「10分」「1時間」「ずっと」→ 分。書いていなければ default（静かにするは30分）。上限6時間"""
    m = _HOURS.search(text)
    if m:
        minutes = int(m.group(1)) * 60
    else:
        m = _MINUTES.search(text)
        minutes = int(m.group(1)) if m else (MAX_MUTE_MINUTES if _LONG.search(text) else default)
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


def parse_command(text, call_names, muted=False, delegating=False):
    """
    オーナーの発言から合図を読む。(種類, 値) か None（AI に呼びかけていなければ None）。
    muted は今静かにしているか。⚠️ 静かにしていないときの「もういいよ」「もう大丈夫？」は合図にしない（ふつうの会話として AI が判断する。
    合図にすると、静かにしていないのに「戻ったよ！」と返していた）。
    delegating は今オーナーの代わりに伝えているか（そのときだけ「ただいま」「もういいよ」で終わる）
    """
    text = _norm(text)
    if not text or not mentions_name(text, call_names):
        return None
    if _UNMUTE.search(text) and not _MUTE.search(text.replace("ミュート解除", "")) and muted:
        return CMD_UNMUTE, None
    if delegating and (_DELEGATE_END.search(text) or _UNMUTE.search(text)):
        return CMD_DELEGATE_END, None
    if _UNMUTE.search(text) and not _MUTE.search(text.replace("ミュート解除", "")):
        return None
    if _MUTE.search(text):
        return CMD_MUTE, mute_minutes(text)
    if _DELEGATE.search(text):
        return CMD_DELEGATE, mute_minutes(text, DEFAULT_DELEGATE_MINUTES)
    m = _REMEMBER.search(text)
    if m:
        content = strip_names(text[:m.start()], call_names)
        if content:
            return CMD_REMEMBER, content
    return None
