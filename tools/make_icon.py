# -*- coding: utf-8 -*-
"""
アプリのアイコン files/app_icon.ico を描き直す。

図柄: 黒地にクリーム色の輪のある惑星、右下に白い吹き出し（2026-10-11 本人がD案「惑星が主役」を選んだ。
いったんA案「クリームの吹き出しの中に惑星」を選んだ後でDに変えた）。
色は GRAVITY の画面に合わせている（黒の地、右下の「+」ボタンなどのクリーム色）。
⚠️ 16pxでは右下の吹き出しの「…」が読めなくなる。案を選ぶ時点で本人に伝えたうえでの選択。

使い方:
    python tools/make_icon.py            # files/app_icon.ico を上書きする
    python tools/make_icon.py 見本.png   # あわせて、各サイズを並べた見本を書き出す

⚠️ Windowsはショートカットのアイコンを覚えておくので、描き直しても古い絵のまま見えることがある。
   そのときは `ie4uinit.exe -show` でアイコンの覚えを更新する。
"""
import os
import sys
from PIL import Image, ImageDraw

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_PATH = os.path.join(_ROOT, "files", "app_icon.ico")

S = 1024  # 大きく描いてから縮める
BLACK = (17, 17, 17, 255)
CREAM = (246, 217, 162, 255)
WHITE = (255, 255, 255, 255)
# 入れるサイズ。16〜24はタスクバーや一覧、32〜48はデスクトップ、256は大きい表示
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def _bubble(d, box, color):
    """しっぽが右下にある吹き出し"""
    x1, y1, x2, y2 = box
    d.rounded_rectangle(box, radius=int((y2 - y1) * 0.42), fill=color)
    d.polygon([(x2 - 120, y2 - 50), (x2 - 40, y2 + 130), (x2 - 330, y2 - 50)], fill=color)


def _planet(diameter, color, ring_width, angle=-22):
    """輪のある惑星。輪の上半分は惑星の後ろ、下半分は手前に描く"""
    empty = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    c, r = S // 2, diameter // 2
    body = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(body).ellipse([c - r, c - r, c + r, c + r], fill=color)
    ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    rw, rh = int(r * 1.75), int(r * 0.55)
    ImageDraw.Draw(ring).ellipse([c - rw, c - rh, c + rw, c + rh], outline=color, width=ring_width)
    lower = Image.new("L", (S, S), 0)
    ImageDraw.Draw(lower).rectangle([0, c, S, S], fill=255)
    front = Image.composite(ring, empty, lower)
    back = Image.composite(empty, ring, lower)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.alpha_composite(back.rotate(angle, resample=Image.BILINEAR, center=(c, c)))
    out.alpha_composite(body)
    out.alpha_composite(front.rotate(angle, resample=Image.BILINEAR, center=(c, c)))
    return out


def draw(size):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=230, fill=BLACK)
    img.alpha_composite(_planet(470, CREAM, 58), (-40, -60))
    # 右下の吹き出し。黒で縁取り、惑星の輪と重なっても形が読めるようにする
    _bubble(d, [520, 600, 930, 840], BLACK)
    _bubble(d, [550, 625, 900, 815], WHITE)
    for i in range(3):
        cx = 640 + i * 85
        d.ellipse([cx - 30, 690, cx + 30, 750], fill=BLACK)
    return img.resize((size, size), Image.LANCZOS)


def main():
    images = [draw(s) for s in SIZES]
    images[-1].save(ICON_PATH, format="ICO", sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    print(f"書き出した: {ICON_PATH}（{', '.join(map(str, SIZES))}px）")
    if len(sys.argv) > 1:
        sheet = Image.new("RGBA", (sum(SIZES) + 20 * len(SIZES) + 20, 600), (255, 255, 255, 255))
        ImageDraw.Draw(sheet).rectangle([0, 300, sheet.width, 600], fill=(36, 36, 36, 255))
        x = 20
        for s, im in zip(SIZES, images):
            sheet.alpha_composite(im, (x, 20))
            sheet.alpha_composite(im, (x, 320))
            x += s + 20
        sheet.save(sys.argv[1])
        print(f"見本: {sys.argv[1]}")


if __name__ == "__main__":
    main()
