#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Roadbook 预览器 —— 不烧录，在电脑上看 200x200 屏幕长什么样。

版式（200x200，四段结构）：
    ┌────────────────────┐  y=0
    │ NANJING LOOP   1/3 │  页眉（路名 + 页码）      基线 y=16
    │ ────────────────── │  页眉横线                y=22
    │                    │
    │ 22.6 km      CLM 3.1│  正文（自适应行距）      基线 y=38..166
    │   25.7 km  +180m 5.4%│
    │ 31.0 km      DANGER │
    │ 40.5 km         GLU │
    │                    │
    │ ────────────────── │  页脚横线                y=174
    │ 14:32          87% │  状态栏（时间 / 电量）    基线 y=190
    └────────────────────┘  y=200

用法：
    python tools/preview_roadbook.py 02_Roadbook/sample.json
    python tools/preview_roadbook.py sample.json --font FreeSansBold9pt7b
    python tools/preview_roadbook.py sample.json --time 06:41 --batt 62%

输出：
    <out>/page_01.png ...     每页一张（放大 4 倍）
    <out>/contact_sheet.png   全部页拼版
    <out>/arrows.png          8 个方向箭头的位图图例

自检（任何一条报警都别烧录）：
    左右列有没有撞上 / 有没有压到页脚横线
"""

import argparse
import os
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("缺 Pillow。先装： python -m pip install Pillow")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roadbook as rb
import preview_paging as pp


def draw_arrow(c, px, x, y, size=rb.ARROW):
    """把 16x16 位图画到画布上（1 = 黑）"""
    for j in range(size):
        for i in range(size):
            if px[j * size + i]:
                c.px(x + i, y + j, 0)


def render_page(c, idx, page_count, events, name, f, arrows, warn,
                gap, foot_left, foot_right):
    c.fill(1)

    # ---- 页眉：左路名，右页码 ----
    c.set_font(f)
    c.cursor(rb.MARGIN, rb.HEADER_Y)
    c.print(name)
    pbuf = "%d/%d" % (idx + 1, page_count)
    x1, _y1, bw, _bh = f.bounds(pbuf, 0, 0)
    c.cursor(rb.SCREEN_W - rb.MARGIN - bw - x1, rb.HEADER_Y)
    c.print(pbuf)
    c.hline(rb.MARGIN, rb.HEADER_LINE_Y, rb.SCREEN_W - 2 * rb.MARGIN, 0)

    # ---- 正文：自适应行距，整块垂直居中 ----
    n_rows = sum(rb.rows_of(e) for e in events)
    top, gap = rb.layout(n_rows, gap)
    y = top
    last_bottom = 0
    for ev in events:
        for row in rb.event_rows(ev):
            lx = rb.MARGIN + (rb.SUB_INDENT if row.get("sub") else 0)

            # 左列：公里数
            c.cursor(lx, y)
            c.print(row["left"])

            if row["arrow"]:
                px = arrows[row["arrow"]]
                draw_arrow(c, px, rb.SCREEN_W - rb.MARGIN - rb.ARROW,
                           y - rb.ARROW + 2)
                right_w = rb.ARROW
            elif row["right"]:
                x1, _y1, bw, _bh = f.bounds(row["right"], 0, 0)
                right_w = bw + x1
                c.cursor(rb.SCREEN_W - rb.MARGIN - bw - x1, y)
                c.print(row["right"])
            else:
                right_w = 0

            # 左右列有没有撞上
            if row["left"]:
                _x1, _y1, lw, _lh = f.bounds(row["left"], 0, 0)
                gapx = (rb.SCREEN_W - rb.MARGIN - right_w) - (lx + lw)
                if gapx < 4:
                    warn.append("第 %d 页：'%s' 和 '%s' 只差 %dpx，快撞上了"
                                % (idx + 1, row["left"],
                                   row["right"] or "箭头", gapx))

            # 这一行墨迹的最低点（用实际字形的 yOffset+height）
            _x, oy, _w, oh = f.bounds(row["left"] or row["right"] or "A", 0, 0)
            last_bottom = max(last_bottom, y + max(0, oy + oh))
            y += gap

    if last_bottom > rb.FOOT_LINE_Y - 2:
        warn.append("第 %d 页：正文压到页脚横线了（最低 %d，横线 %d）"
                    % (idx + 1, last_bottom, rb.FOOT_LINE_Y))

    # ---- 页脚：横线 + 左时间 / 右电量 ----
    c.hline(rb.MARGIN, rb.FOOT_LINE_Y, rb.SCREEN_W - 2 * rb.MARGIN, 0)
    c.cursor(rb.MARGIN, rb.FOOT_Y)
    c.print(foot_left)
    if foot_right:
        x1, _y1, bw, _bh = f.bounds(foot_right, 0, 0)
        c.cursor(rb.SCREEN_W - rb.MARGIN - bw - x1, rb.FOOT_Y)
        c.print(foot_right)

    return top, gap, last_bottom


def render_arrows(arrows, scale=4):
    """把 8 个方向箭头画成一张图例（返回原始尺寸，由调用方放大）"""
    n = len(rb.DIRS)
    cell = rb.ARROW + 12
    img = Image.new("L", (n * cell, cell), 255)
    d = ImageDraw.Draw(img)
    for i, name in enumerate(sorted(rb.DIRS)):
        x = i * cell + 6
        for j in range(rb.ARROW):
            for k in range(rb.ARROW):
                if arrows[name][j * rb.ARROW + k]:
                    d.point((x + k, 6 + j), fill=0)
        d.text((x, cell - 9), name[:4], fill=0)
    return img


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="Roadbook 预览器")
    ap.add_argument("json", nargs="?",
                    default=os.path.join(root, "02_Roadbook", "sample.json"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--libs", default=os.path.join(os.path.expanduser("~"),
                                                   "Documents", "Arduino", "libraries"))
    ap.add_argument("--font", default="FreeSansBold9pt7b",
                    help="字体（页眉/正文/页脚统一用这一个）")
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--rows", type=int, default=rb.MAX_ROWS, help="一页最多几行")
    ap.add_argument("--gap", type=int, default=None,
                    help="固定行距；不给就自适应（%d~%d）" % (rb.GAP_MIN, rb.GAP_MAX))
    ap.add_argument("--time", default="14:32", help="状态栏左侧时间（示例值）")
    ap.add_argument("--batt", default="87%", help="状态栏右侧电量（示例值）")
    args = ap.parse_args()

    if not os.path.exists(args.json):
        sys.exit("找不到路书文件：%s" % args.json)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.json)),
                                   "preview")

    gfx = os.path.join(args.libs, "Adafruit_GFX_Library")
    font_path = os.path.join(gfx, "Fonts", args.font + ".h")
    glcd_path = os.path.join(gfx, "glcdfont.c")
    for p in (font_path, glcd_path):
        if not os.path.exists(p):
            sys.exit("找不到：%s" % p)

    f = pp.parse_gfx_font(font_path)
    glcd = pp.parse_glcd_font(glcd_path)
    arrows = rb.arrows_all()

    data = rb.load(args.json)
    name = data.get("name", "ROADBOOK")
    events = data.get("events", [])
    pages = rb.paginate(events, args.rows)

    print("路书:   %s" % name)
    print("事件:   %d 个 -> %d 页   每页最多 %d 行" % (len(events), len(pages), args.rows))
    print("字体:   %s (yAdvance=%d)" % (args.font, f.y_advance))
    print("版式:   正文区 y=%d..%d（%dpx）  页脚横线 y=%d  状态栏基线 y=%d"
          % (rb.BODY_TOP, rb.BODY_BOTTOM, rb.body_region(),
             rb.FOOT_LINE_Y, rb.FOOT_Y))
    print("状态栏: 左 '%s'   右 '%s'   （示例值，接上 RTC/ADC 后是真实数据）"
          % (args.time, args.batt))

    os.makedirs(out, exist_ok=True)
    c = pp.Canvas(rb.SCREEN_W, rb.SCREEN_H, glcd)
    warn = []
    imgs = []
    for i, evs in enumerate(pages):
        c.fill(1)
        top, gap_used, last_bottom = render_page(
            c, i, len(pages), evs, name, f, arrows, warn,
            args.gap, args.time, args.batt)
        img = c.to_image()
        imgs.append(img)
        pp.label_scale(img, args.scale).save(os.path.join(out, "page_%02d.png" % (i + 1)))
        n_rows = sum(rb.rows_of(e) for e in evs)
        slack = rb.FOOT_LINE_Y - last_bottom
        print("  第 %d 页：%d 事件 / %d 行   首行基线 %d  行距 %d  距页脚线 %dpx"
              % (i + 1, len(evs), n_rows, top, gap_used, slack))

    fa = render_arrows(arrows)
    pp.label_scale(fa, args.scale).save(os.path.join(out, "arrows.png"))

    # 拼版（最后一格放箭头图例）
    sc = args.scale
    cw, ch = rb.SCREEN_W * sc, rb.SCREEN_H * sc
    cells = imgs + [fa]
    cols = min(4, len(cells))
    rows = (len(cells) + cols - 1) // cols
    pad, top_pad = 10, 16
    sheet = Image.new("L", (cols * (cw + pad) + pad,
                            rows * (ch + top_pad + pad) + pad), 200)
    d = ImageDraw.Draw(sheet)
    for i, img in enumerate(cells):
        r, cc = divmod(i, cols)
        x, y = pad + cc * (cw + pad), pad + r * (ch + top_pad + pad)
        t = "ARROWS (not to scale)" if i == len(imgs) else "%d/%d" % (i + 1, len(pages))
        d.text((x + 2, y + 2), t, fill=0)
        sheet.paste(pp.label_scale(img, sc), (x, y + top_pad))
    sheet.save(os.path.join(out, "contact_sheet.png"))

    for w in warn:
        print("!! " + w)
    if not warn:
        print("自检:   全部通过（左右列没撞 / 没压页脚线）")
    print()
    print("已输出到 %s" % out)


if __name__ == "__main__":
    main()
