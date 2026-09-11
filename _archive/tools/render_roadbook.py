# -*- coding: utf-8 -*-
"""
路书渲染器（V1 · PC 端渲染）

输入：路书 JSON
输出：
  out/roadbook.bin      直接拷进 SD 卡的设备端数据文件
  out/pages/pXXX.png    每页预览（放大 scale 倍）
  out/contact_sheet.png 全部页面的拼版预览
  out/manifest.json     页码索引（调试用）

用法：
  python tools/render_roadbook.py samples/roadbook_sample.json
  python tools/render_roadbook.py roadbook.json --out out --scale 4 --polarity white1

数据流：JSON -> (Pillow 绘制 200x200 灰度) -> 阈值化 -> 打包 1-bit -> bin
设备端只负责"读字节 -> 刷屏"，不含任何字体和排版代码。
"""
import argparse
import json
import os
import struct
import zlib

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- 字体

FONT_CANDIDATES = [
    # Windows
    ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc"),
    ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simhei.ttf"),
    # macOS
    ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/PingFang.ttc"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
    # Linux
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
     "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
     "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
]

_font_cache = {}


def font(size, bold=False):
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    idx = 0 if bold else 1
    for pair in FONT_CANDIDATES:
        path = pair[idx]
        if os.path.exists(path):
            try:
                f = ImageFont.truetype(path, size)
                _font_cache[key] = f
                return f
            except OSError:
                continue
    f = ImageFont.load_default()
    _font_cache[key] = f
    return f


# ---------------------------------------------------------------- 文本工具

def text_w(draw, s, f):
    return draw.textbbox((0, 0), s, font=f)[2]


def wrap(draw, s, f, max_w, max_lines=99):
    """按字宽换行，中文逐字断行，英文按空格断词。"""
    lines, cur = [], ""
    for ch in s:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        test = cur + ch
        if text_w(draw, test, f) > max_w and cur:
            lines.append(cur)
            cur = ch.lstrip() if ch == " " else ch
        else:
            cur = test
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines[:max_lines]


def ellipsis(draw, s, f, max_w):
    if text_w(draw, s, f) <= max_w:
        return s
    out = ""
    for ch in s:
        if text_w(draw, out + ch + "…", f) > max_w:
            break
        out += ch
    return out + "…"


# ---------------------------------------------------------------- 图标（全部单色自绘）

def _icon_box(size):
    """返回一张 size×size 的白底灰度图 + draw 对象，供图标绘制。"""
    img = Image.new("L", (size, size), 255)
    return img, ImageDraw.Draw(img)


def icon(kind, size=32):
    """返回 size×size 的灰度图（255=白，0=黑）。"""
    img, d = _icon_box(size)
    s = size
    m = max(1, round(s * 0.04))  # 线宽基准

    if kind == "climb":                       # 山峰
        d.polygon([(s * 0.5, s * 0.08), (s * 0.95, s * 0.92), (s * 0.05, s * 0.92)], fill=0)
        d.polygon([(s * 0.52, s * 0.34), (s * 0.72, s * 0.58), (s * 0.36, s * 0.58)], fill=255)
    elif kind == "feed":                      # 水滴
        d.polygon([(s * 0.5, s * 0.06), (s * 0.86, s * 0.58), (s * 0.14, s * 0.58)], fill=0)
        d.ellipse([s * 0.14, s * 0.42, s * 0.86, s * 0.96], fill=0)
    elif kind == "sprint":                    # 闪电
        d.polygon([(s * 0.58, s * 0.04), (s * 0.26, s * 0.54), (s * 0.46, s * 0.54),
                   (s * 0.38, s * 0.96), (s * 0.76, s * 0.42), (s * 0.54, s * 0.42),
                   (s * 0.66, s * 0.04)], fill=0)
    elif kind == "danger":                    # 感叹号三角
        d.polygon([(s * 0.5, s * 0.06), (s * 0.96, s * 0.92), (s * 0.04, s * 0.92)], fill=255,
                  outline=0, width=max(2, m))
        d.rectangle([s * 0.45, s * 0.34, s * 0.55, s * 0.62], fill=0)
        d.rectangle([s * 0.45, s * 0.70, s * 0.55, s * 0.80], fill=0)
    elif kind == "turn":                      # 右转箭头
        d.rectangle([s * 0.08, s * 0.42, s * 0.58, s * 0.60], fill=0)
        d.polygon([(s * 0.50, s * 0.18), (s * 0.96, s * 0.51), (s * 0.50, s * 0.84)], fill=0)
    elif kind == "finish":                    # 格子旗
        d.rectangle([s * 0.06, s * 0.10, s * 0.16, s * 0.94], fill=0)
        c = 3
        cell = s * 0.78 / c
        for r in range(c):
            for cc in range(c):
                if (r + cc) % 2 == 0:
                    x0 = s * 0.18 + cc * cell
                    y0 = s * 0.10 + r * cell
                    d.rectangle([x0, y0, x0 + cell, y0 + cell], fill=0)
        d.rectangle([s * 0.18, s * 0.10, s * 0.96, s * 0.88], outline=0, width=max(1, m // 2))
    elif kind == "start":                     # 起点旗 + 播放三角
        d.polygon([(s * 0.20, s * 0.14), (s * 0.20, s * 0.86), (s * 0.72, s * 0.50)], fill=0)
        d.rectangle([s * 0.80, s * 0.18, s * 0.90, s * 0.94], fill=0)
        d.polygon([(s * 0.88, s * 0.22), (s * 0.88, s * 0.50), (s * 0.99, s * 0.34)], fill=0)
    else:                                     # 兜底：圆点
        d.ellipse([s * 0.2, s * 0.2, s * 0.8, s * 0.8], outline=0, width=max(2, m))
    return img


# ---------------------------------------------------------------- 页面骨架

class Page:
    W = 200
    H = 200

    def __init__(self):
        self.img = Image.new("L", (self.W, self.H), 255)
        self.d = ImageDraw.Draw(self.img)

    def text(self, xy, s, f, anchor=None, fill=0):
        self.d.text(xy, s, font=f, fill=fill, anchor=anchor)

    def hline(self, y, x0=None, x1=None, w=1):
        self.d.line([(x0 if x0 is not None else 2, y), (x1 if x1 is not None else self.W - 2, y)],
                    fill=0, width=w)

    def paste_icon(self, kind, x, y, size):
        im = icon(kind, size)
        self.img.paste(im, (int(x), int(y)))

    def header(self, route, page_no, total_pages, at_km=None, total_km=None):
        d, f = self.d, font(11)
        d.text((3, 2), ellipsis(d, route, f, 96), font=f, fill=0)
        right = "%d/%d" % (page_no, total_pages)
        d.text((self.W - 3, 2), right, font=f, fill=0, anchor="ra")
        if at_km is not None:
            mid = "%.1f / %.1f km" % (at_km, total_km)
            d.text((self.W / 2, 2), mid, font=f, fill=0, anchor="ma")
        self.hline(17)

    def footer(self, left, right="NEXT ▶"):
        f = font(11)
        self.d.text((3, self.H - 13), left, font=f, fill=0)
        self.d.text((self.W - 3, self.H - 13), right, font=f, fill=0, anchor="ra")
        self.hline(self.H - 16)

    def progress(self, y, cards, cur_idx, total_km):
        """全程进度条：外框 + 已完成填充 + 每个事件一个刻度。"""
        x0, x1, h = 4, self.W - 4, 7
        self.d.rectangle([x0, y, x1, y + h], outline=0, width=1)
        cur = cards[cur_idx] if cards else None
        if cur is not None and total_km > 0:
            frac = min(1.0, max(0.0, cur["at_km"] / total_km))
            fx = x0 + (x1 - x0 - 2) * frac
            if fx > x0 + 1:
                self.d.rectangle([x0 + 1, y + 1, fx, y + h - 1], fill=0)
        for i, c in enumerate(cards):
            if total_km <= 0:
                break
            fx = x0 + 1 + (x1 - x0 - 3) * min(1.0, c["at_km"] / total_km)
            top = y - 3 if i == cur_idx else y + h
            self.d.line([(fx, top), (fx, y + h if i == cur_idx else y + h + 3)], fill=0, width=1)


# ---------------------------------------------------------------- 三种板式

def page_cover(rb, page_no, total_pages):
    p = Page()
    p.header(rb.get("route", "路书"), page_no, total_pages)
    f1, f2, f3 = font(20, True), font(36, True), font(12)
    p.d.text((Page.W / 2, 22), ellipsis(p.d, rb.get("route", "路书"), f1, 190),
             font=f1, fill=0, anchor="mt")
    p.text((Page.W / 2, 70), "%.1f" % rb.get("total_km", 0), f2, anchor="mt")
    p.text((Page.W / 2, 112), "公里 · 全程", f3, anchor="mt")
    p.hline(128)
    cards = rb["cards"]
    n_feed = sum(1 for c in cards if c["type"] == "feed")
    n_climb = sum(1 for c in cards if c["type"] == "climb")
    p.text((Page.W / 2, 142), "关键点 %d · 补给 %d · 爬坡 %d" % (len(cards), n_feed, n_climb),
           f3, anchor="ma")
    if rb.get("date"):
        p.text((Page.W / 2, 160), str(rb["date"]), f3, anchor="ma")
    p.footer("Stem Notes", "按 NEXT 开始 ▶")
    return p


def page_l1(rb, idx, page_no, total_pages):
    """L1 主页面：下一个关键点还有多远。"""
    cards, total = rb["cards"], rb.get("total_km", 0)
    c = cards[idx]
    p = Page()
    p.header(rb.get("route", "路书"), page_no, total_pages, c["at_km"], total)
    p.progress(22, cards, idx, total)

    # 巨型距离（到下一个事件）
    nxt = cards[idx + 1] if idx + 1 < len(cards) else None
    gap = (nxt["at_km"] - c["at_km"]) if nxt else 0.0
    fbig, fkm = font(40, True), font(14)
    p.text((4, 34), "%.1f" % gap, fbig)
    wbig = text_w(p.d, "%.1f" % gap, fbig)
    p.text((4 + wbig + 3, 62), "km", fkm)

    # 类型标签（右上角）
    ftag = font(11)
    label = {"start": "起点", "finish": "终点", "climb": "爬坡", "feed": "补给",
             "sprint": "冲刺", "danger": "危险", "turn": "转弯"}.get(c["type"], "提示")
    p.d.rectangle([Page.W - 40, 34, Page.W - 4, 50], outline=0, width=1)
    p.text((Page.W - 22, 42), label, ftag, anchor="ma")

    p.paste_icon(c["type"], 150, 56, 40)

    # 标题 + 副标题
    ft, fs = font(18, True), font(12)
    y = 88
    for line in wrap(p.d, c.get("title", ""), ft, 190, 2):
        p.text((4, y), line, ft)
        y += 21
    for line in wrap(p.d, c.get("sub", ""), fs, 190, 2):
        p.text((4, y), line, fs)
        y += 15

    # 底部：接下来 3 个事件
    p.hline(150)
    up = cards[idx + 1: idx + 4]
    if up:
        for i, u in enumerate(up):
            cx = 34 + i * 66
            p.paste_icon(u["type"], cx - 9, 156, 18)
            p.text((cx, 178), "%.1f" % (u["at_km"] - c["at_km"]), font(10), anchor="mt")
    else:
        p.text((Page.W / 2, 174), "全程结束", ftag, anchor="ma")
    return p


def page_l2(rb, idx, page_no, total_pages):
    """L2 未来列表：从这个点往后还有什么。"""
    cards, total = rb["cards"], rb.get("total_km", 0)
    c = cards[idx]
    p = Page()
    p.header(rb.get("route", "路书"), page_no, total_pages)
    fh = font(13, True)
    p.text((4, 22), "剩余关键点", fh)
    p.text((Page.W - 4, 22), "%.1f km" % max(0.0, total - c["at_km"]), font(11), anchor="ra")
    p.hline(38)

    up = cards[idx + 1:]
    frow, fkm = font(12), font(11)
    y = 42
    for u in up[:7]:
        p.paste_icon(u["type"], 4, y + 1, 14)
        name = ellipsis(p.d, u.get("title", ""), frow, 118)
        p.text((23, y + 2), name, frow)
        p.text((Page.W - 4, y + 3), "%.1f" % (u["at_km"] - c["at_km"]), fkm, anchor="ra")
        y += 17
        p.hline(y - 1, 3, Page.W - 3)
    if not up:
        p.text((Page.W / 2, 100), "后面没有关键点", frow, anchor="ma")
    p.footer("L2 列表", "NEXT ▶ 详情")
    return p


def page_l3(rb, idx, page_no, total_pages):
    """L3 事件详情。"""
    cards, total = rb["cards"], rb.get("total_km", 0)
    c = cards[idx]
    p = Page()
    p.header(rb.get("route", "路书"), page_no, total_pages)
    p.paste_icon(c["type"], 4, 22, 26)
    ft = font(16, True)
    p.text((35, 23), ellipsis(p.d, c.get("title", ""), ft, 160), ft)
    p.text((35, 43), "%.1f km 处" % c["at_km"], font(11))
    p.hline(58)

    fk, fv = font(11), font(13, True)
    rows = list(c.get("detail") or [])
    if not rows and c.get("sub"):
        rows = ["说明", c["sub"]]
    y = 64
    for i in range(0, len(rows) - 1, 2):
        k, v = rows[i], rows[i + 1]
        p.text((4, y + 2), k, fk)
        p.text((Page.W - 4, y), ellipsis(p.d, str(v), fv, 110), fv, anchor="ra")
        y += 16
        p.hline(y - 1, 3, Page.W - 3)
        if y > 170:
            break
    nxt = cards[idx + 1] if idx + 1 < len(cards) else None
    if nxt:
        p.footer("距下一关键点 %.1f km" % (nxt["at_km"] - c["at_km"]), "NEXT ▶")
    else:
        p.footer("全程终点", "NEXT ▶")
    return p


# ---------------------------------------------------------------- 打包

def pack1bit(p: Page, black_is_1=True) -> bytes:
    """阈值化后打包成 1-bit 位图，MSB 在前，每行 width/8 字节（无行填充）。"""
    g = p.img.point(lambda v: 255 if v >= 128 else 0)
    px = g.load()
    W, H = Page.W, Page.H
    row_bytes = W // 8
    out = bytearray(row_bytes * H)
    for y in range(H):
        base = y * row_bytes
        for x in range(W):
            black = px[x, y] < 128
            bit = 1 if (black == black_is_1) else 0
            if bit:
                out[base + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(out)


HEADER_FMT = "<2sBBHHHIH"  # magic, version, flags, width, height, count, crc32, reserved
HEADER_SIZE = 16


def write_bin(path, pages_bits, width, height, black_is_1):
    payload = b"".join(pages_bits)
    flags = 0x01 if black_is_1 else 0x00
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    head = struct.pack(HEADER_FMT, b"RB", 1, flags, width, height, len(pages_bits), crc, 0)
    with open(path, "wb") as f:
        f.write(head)
        f.write(payload)
    return len(payload) + HEADER_SIZE


# ---------------------------------------------------------------- 主流程

def build_pages(rb, mode):
    """返回 [(label, Page)]。"""
    cards = rb["cards"]
    out = []
    if mode == "cycle":
        # 封面 + 每个事件 [L1, L2, L3]
        seq = []
        for i in range(len(cards)):
            seq.append(("L1", i))
            seq.append(("L2", i))
            seq.append(("L3", i))
    else:
        seq = [("OV", 0)]
        for i in range(len(cards)):
            seq.append(("L1", i))
            seq.append(("L3", i))

    total = 1 + len(seq)
    out.append(("cover", page_cover(rb, 1, total)))
    for n, (kind, i) in enumerate(seq, start=2):
        if kind == "L1":
            out.append(("L1#%d" % cards[i]["id"], page_l1(rb, i, n, total)))
        elif kind == "L2":
            out.append(("L2#%d" % cards[i]["id"], page_l2(rb, i, n, total)))
        elif kind == "L3":
            out.append(("L3#%d" % cards[i]["id"], page_l3(rb, i, n, total)))
        else:
            out.append(("OV", page_l2(rb, i, n, total)))
    return out


def main():
    ap = argparse.ArgumentParser(description="路书 JSON -> 1-bit 位图 bin（SD 卡用）")
    ap.add_argument("json")
    ap.add_argument("--out", default="out")
    ap.add_argument("--width", type=int, default=200)
    ap.add_argument("--height", type=int, default=200)
    ap.add_argument("--scale", type=int, default=3, help="预览图放大倍数")
    ap.add_argument("--mode", choices=["cycle", "simple"], default="cycle",
                    help="cycle=每事件 L1/L2/L3 三层轮转；simple=总览 + 每事件 L1/L3")
    ap.add_argument("--polarity", choices=["black1", "white1"], default="black1",
                    help="位图中 1 表示黑(black1)还是白(white1)，需与固件一致")
    args = ap.parse_args()

    Page.W, Page.H = args.width, args.height

    with open(args.json, "r", encoding="utf-8") as f:
        rb = json.load(f)
    rb["cards"].sort(key=lambda c: c.get("at_km", 0))

    pages = build_pages(rb, args.mode)
    black_is_1 = (args.polarity == "black1")

    os.makedirs(os.path.join(args.out, "pages"), exist_ok=True)
    bits = []
    manifest = []
    for i, (label, p) in enumerate(pages):
        b = pack1bit(p, black_is_1)
        assert len(b) == Page.W * Page.H // 8, "位图大小异常"
        bits.append(b)
        p.img.point(lambda v: 255 if v >= 128 else 0).convert("1") \
            .resize((Page.W * args.scale, Page.H * args.scale), Image.NEAREST) \
            .save(os.path.join(args.out, "pages", "p%03d_%s.png" % (i, label.replace("#", "-"))))
        manifest.append({"index": i, "label": label, "bytes": len(b)})

    bin_path = os.path.join(args.out, "roadbook.bin")
    size = write_bin(bin_path, bits, Page.W, Page.H, black_is_1)

    # 拼版预览
    cols = 6
    rows = (len(pages) + cols - 1) // cols
    sheet = Image.new("L", (cols * (Page.W + 8) + 8, rows * (Page.H + 8) + 8), 200)
    for i, (label, p) in enumerate(pages):
        im = p.img.point(lambda v: 255 if v >= 128 else 0)
        x = 8 + (i % cols) * (Page.W + 8)
        y = 8 + (i // cols) * (Page.H + 8)
        sheet.paste(im, (x, y))
    sheet.convert("1").save(os.path.join(args.out, "contact_sheet.png"))

    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"route": rb.get("route"), "pages": len(pages),
                   "page_bytes": Page.W * Page.H // 8,
                   "polarity": args.polarity, "items": manifest},
                  f, ensure_ascii=False, indent=2)

    print("页面数    : %d" % len(pages))
    print("单页      : %d 字节" % (Page.W * Page.H // 8))
    print("输出 bin  : %s (%.1f KB)" % (bin_path, size / 1024.0))
    print("预览      : %s/pages/  拼版: %s/contact_sheet.png" % (args.out, args.out))
    print("极性      : 1 = %s" % ("黑" if black_is_1 else "白"))


if __name__ == "__main__":
    main()
