#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
01_Paging 排版预览器 —— 上传前先在电脑上看到屏幕长什么样。

原理
----
不去"模拟"排版，而是把固件里那套东西原样搬到电脑上跑：

  1. 排版参数（边距、行高、每页行数、标题、页脚…）直接从 01_Paging.ino 里
     读 #define，正文直接从 SAMPLE_TEXT 里抠出来
     -> 改固件，预览跟着变，两边永远不会对不上
  2. 折行算法 1:1 照搬 C 里那份（同样按字体的 xAdvance 精确测宽）
  3. 每个字符的像素从 Arduino 库里的字体头文件里读出来
     FreeSans9pt7b.h  -> 正文和页眉
     glcdfont.c       -> 页脚用的 5x7 内置字体
     按 Adafruit_GFX::drawChar 的同一套位图规则画点
     -> 预览图和屏幕上显示的是同一张图，不是"大概像"

用法
----
    python tools/preview_paging.py
    python tools/preview_paging.py --scale 4 --out 01_Paging/preview
    python tools/preview_paging.py --dump-lines      # 顺便打印每行怎么折的

输出
----
    <out>/page_01.png ... page_NN.png     每页单独一张（放大 4 倍好肉眼看）
    <out>/contact_sheet.png               全部页拼成一张

对账
----
脚本最后会打印一行：

    layout: 96 lines -> 11 pages  maxw=186/188 over=0  chk=0x----

烧录后串口 115200 会打印一模一样的一行。两行对上了，就说明
电脑上看到的就是屏幕上显示的。
"""

import argparse
import os
import re
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("缺 Pillow。先装： python -m pip install Pillow")


# ----------------------------------------------------------------------
# 解析固件源文件
# ----------------------------------------------------------------------
def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_defines(src):
    """把 #define NAME value 读成 dict。字符串宏读成 str，其余尽力转 int。"""
    out = {}
    for m in re.finditer(r'^\s*#define\s+(\w+)\s+(.+?)\s*(?://.*)?$', src, re.M):
        name, raw = m.group(1), m.group(2).strip()
        if '"' in raw:
            sm = re.search(r'"((?:[^"\\]|\\.)*)"', raw)
            out[name] = unescape(sm.group(1)) if sm else raw
            continue
        try:
            out[name] = int(raw, 0)
        except ValueError:
            # 不是数字但是个合法标识符（比如 BODY_FONT  FreeSans9pt7b）就当字符串存
            if re.fullmatch(r'[A-Za-z_]\w*', raw):
                out[name] = raw
    return out


def unescape(s):
    return re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t', 'r': '\r',
                                       '"': '"', '\\': '\\'}.get(m.group(1), m.group(1)), s)


def extract_c_string(src, varname):
    """抠出 static const char *NAME = "..."; 拼成的整段文本。"""
    m = re.search(re.escape(varname) + r'\s*=\s*(.*?);\s*\n', src, re.S)
    if not m:
        sys.exit("在 .ino 里找不到 %s" % varname)
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
    if not parts:
        sys.exit("%s 里没有字符串字面量" % varname)
    return unescape("".join(parts))


# ----------------------------------------------------------------------
# 解析字体（Adafruit GFX 自定义字体 + 内置 5x7）
# ----------------------------------------------------------------------
class GfxFont:
    """对应 Adafruit_GFX 的 GFXfont。每个字形 6 个数：
    bitmapOffset, width, height, xAdvance, xOffset, yOffset
    """

    def __init__(self, bits, glyphs, first, last, y_advance, name=""):
        self.bits = bits
        self.glyphs = glyphs
        self.first = first
        self.last = last
        self.y_advance = y_advance
        self.name = name

    def advance(self, s):
        """一串文字的前进宽度（= 固件里 textWidth() 算的东西）"""
        w = 0
        for ch in s:
            o = ord(ch)
            if self.first <= o <= self.last:
                w += self.glyphs[o - self.first][3]
        return w

    def bounds(self, s, x, y):
        """复刻 Adafruit_GFX::getTextBounds，返回 (x1, y1, w, h)"""
        minx, miny, maxx, maxy = x, y, x, y
        cx = x
        for ch in s:
            o = ord(ch)
            if not (self.first <= o <= self.last):
                continue
            _off, gw, gh, adv, xo, yo = self.glyphs[o - self.first]
            gx, gy = cx + xo, y + yo
            if gw > 0:
                minx = min(minx, gx)
                miny = min(miny, gy)
                maxx = max(maxx, gx + gw - 1)
                maxy = max(maxy, gy + gh - 1)
            cx += adv
        return minx, miny, maxx - minx + 1, maxy - miny + 1


def parse_gfx_font(path):
    src = read_text(path)
    m = re.search(r'Bitmaps\s*\[\s*\]\s*PROGMEM\s*=\s*\{(.*?)\};', src, re.S)
    if not m:
        sys.exit("解析不了位图数组: %s" % path)
    bits = bytes(int(h, 16) for h in re.findall(r'0x([0-9A-Fa-f]{2})', m.group(1)))

    m = re.search(r'Glyphs\s*\[\s*\]\s*PROGMEM\s*=\s*\{(.*?)\};', src, re.S)
    if not m:
        sys.exit("解析不了字形表: %s" % path)
    glyphs = []
    for row in re.findall(r'\{([^{}]*)\}', m.group(1)):
        vals = [v.strip() for v in row.split(',')]
        if len(vals) != 6 or not vals[0]:
            continue
        try:
            glyphs.append([int(v, 0) for v in vals])
        except ValueError:
            continue

    m = re.search(r'const\s+GFXfont\s+\w+\s+PROGMEM\s*=\s*\{[^,]*,[^,]*,\s*'
                  r'(0x[0-9A-Fa-f]+|\d+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)\s*,\s*(\d+)',
                  src)
    if not m:
        sys.exit("解析不了 GFXfont 结构: %s" % path)
    first, last, yadv = int(m.group(1), 0), int(m.group(2), 0), int(m.group(3))
    if len(glyphs) != last - first + 1:
        sys.exit("字形数量对不上：期望 %d，实际 %d（%s）"
                 % (last - first + 1, len(glyphs), path))
    return GfxFont(bits, glyphs, first, last, yadv, os.path.basename(path))


def parse_glcd_font(path):
    """解析 glcdfont.c 里的 5x7 内置字体：256 个字符 x 5 列"""
    src = read_text(path)
    m = re.search(r'font\s*\[\s*\]\s*PROGMEM\s*=\s*\{(.*?)\};', src, re.S)
    if not m:
        sys.exit("解析不了 glcdfont: %s" % path)
    data = bytes(int(h, 16) for h in re.findall(r'0x([0-9A-Fa-f]{2})', m.group(1)))
    if len(data) < 256 * 5:
        sys.exit("glcdfont 数据不够：只有 %d 字节" % len(data))
    return data


# ----------------------------------------------------------------------
# 画布：语义和 Adafruit_GFX 一致，color 0 = 黑，1 = 白
# ----------------------------------------------------------------------
class Canvas:
    def __init__(self, w, h, glcd):
        self.w, self.h = w, h
        self.glcd = glcd
        self.buf = bytearray(w * h)      # 1 = 黑
        self.cx = self.cy = 0
        self.font = None                 # None = 内置 5x7

    def fill(self, color):
        self.buf[:] = bytes([1 if color == 0 else 0]) * (self.w * self.h)

    def px(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.buf[y * self.w + x] = 1 if color == 0 else 0

    def hline(self, x, y, w, color):
        for i in range(w):
            self.px(x + i, y, color)

    def set_font(self, font):
        self.font = font

    def cursor(self, x, y):
        self.cx, self.cy = x, y

    def write_char(self, ch, color=0):
        if self.font is None:
            c = ord(ch) & 0xFF
            for i in range(5):                       # 5 列
                line = self.glcd[c * 5 + i]
                for j in range(8):                   # 8 行，LSB 在上
                    if (line >> j) & 1:
                        self.px(self.cx + i, self.cy + j, color)
            self.cx += 6                             # 固定步进 6
        else:
            o = ord(ch)
            if not (self.font.first <= o <= self.font.last):
                return
            off, gw, gh, adv, xo, yo = self.font.glyphs[o - self.font.first]
            x0, y0 = self.cx + xo, self.cy + yo
            for dy in range(gh):
                for dx in range(gw):
                    bit = off * 8 + dy * gw + dx
                    if self.font.bits[bit >> 3] & (0x80 >> (bit & 7)):
                        self.px(x0 + dx, y0 + dy, color)
            self.cx += adv

    def print(self, s, color=0):
        for ch in s:
            self.write_char(ch, color)

    def to_image(self):
        img = Image.new("L", (self.w, self.h), 255)
        px = img.load()
        for y in range(self.h):
            row = y * self.w
            for x in range(self.w):
                if self.buf[row + x]:
                    px[x, y] = 0
        return img


# ----------------------------------------------------------------------
# 折行：1:1 照搬固件里那份算法
# ----------------------------------------------------------------------
def fit_chars(s, maxw, font):
    k, w = 0, 0
    while k < len(s):
        o = ord(s[k])
        adv = font.glyphs[o - font.first][3] if font.first <= o <= font.last else 0
        if w + adv > maxw:
            break
        w += adv
        k += 1
    return k if k > 0 else 1


def wrap_text(text, P, font):
    line_len = P["LINE_LEN"]
    maxw = P["BODY_MAX_W"]
    lines = []

    def push(s):
        if len(lines) >= P["MAX_LINES"]:
            return
        s = s[:line_len - 1].rstrip(" ")
        lines.append(s)

    paras = text.split("\n")
    if paras and paras[-1] == "":        # 末尾那个 \n 不产生空行（和 C 一致）
        paras.pop()

    for par in paras:
        if par == "":
            push("")
            continue
        i, n = 0, len(par)
        while i < n:
            while i < n and par[i] == " ":
                i += 1
            if i >= n:
                break
            start, last_fit, j = i, -1, i
            while j < n:
                while j < n and par[j] != " ":
                    j += 1
                seg = par[start:j][:line_len - 1]
                if font.advance(seg) <= maxw:
                    last_fit = j
                else:
                    break
                j += 1                      # 跳过空格，看下一个词
            if last_fit < 0:
                last_fit = start + fit_chars(par[start:], maxw, font)
            push(par[start:last_fit])
            i = last_fit
    return lines


def checksum(lines):
    chk = 0
    for ln in lines:
        for ch in ln:
            chk = (chk * 31 + ord(ch)) & 0xFFFF
        chk = (chk * 31 + 0xFF) & 0xFFFF
    return chk


# ----------------------------------------------------------------------
# 渲染
# ----------------------------------------------------------------------
def ink_bottom(c, y0, y1):
    """扫 [y0, y1) 区间里黑点的最低 y 坐标；没有内容返回 None。
    用来查正文有没有压到页脚那条线（178）上。"""
    for y in range(y1 - 1, y0 - 1, -1):
        row = y * c.w
        if any(c.buf[row:row + c.w]):
            return y
    return None


def render_page(idx, page_count, lines, P, f_body, c):
    c.fill(1)                                # fillScreen(GxEPD_WHITE)
    c.set_font(f_body)

    # 页眉
    c.cursor(P["BODY_X"], 16)
    c.print(P["RB_TITLE"])
    pbuf = "%d/%d" % (idx + 1, page_count)
    x1, _y1, bw, _bh = f_body.bounds(pbuf, 0, 0)
    c.cursor(P["EPD_W"] - P["BODY_X"] - bw - x1, 16)
    c.print(pbuf)
    c.hline(4, 22, P["EPD_W"] - 8, 0)

    # 正文
    y = P["BODY_TOP_Y"]
    for i in range(P["LINES_PER_PAGE"]):
        li = idx * P["LINES_PER_PAGE"] + i
        if li >= len(lines):
            break
        c.cursor(P["BODY_X"], y)
        c.print(lines[li])
        y += P["LINE_H"]

    # 正文墨迹最低点（还没画页脚线，正好量正文占了多少）
    body_bottom = ink_bottom(c, 24, 178)

    # 页脚（内置 5x7）
    c.hline(4, 178, P["EPD_W"] - 8, 0)
    c.set_font(None)
    c.cursor(P["BODY_X"], 186)
    c.print(P["RB_FOOTER"])
    c.set_font(f_body)
    return body_bottom


def render_off(P, f_big, c):
    c.fill(1)
    c.set_font(f_big)
    x1, y1, bw, bh = f_big.bounds("OFF", 0, 0)
    c.cursor((P["EPD_W"] - bw) // 2 - x1, (P["EPD_H"] - bh) // 2 - y1)
    c.print("OFF")


def label_scale(img, scale):
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="01_Paging 排版预览器")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--ino", default=os.path.join(root, "01_Paging", "01_Paging.ino"))
    ap.add_argument("--out", default=os.path.join(root, "01_Paging", "preview"))
    ap.add_argument("--libs", default=os.path.join(os.path.expanduser("~"),
                                                   "Documents", "Arduino", "libraries"))
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--dump-lines", action="store_true")
    ap.add_argument("--font", help="临时试字体，只改预览不动固件，如 FreeSans12pt7b")
    ap.add_argument("--line-h", type=int, help="临时试行高，只改预览不动固件")
    ap.add_argument("--lpp", type=int, help="临时试每页几行，只改预览不动固件")
    args = ap.parse_args()

    src = read_text(args.ino)
    macros = parse_defines(src)
    text = extract_c_string(src, "SAMPLE_TEXT")

    # 字体从 .ino 的 BODY_FONT / BIG_FONT 读；--font 可以临时覆盖来试效果
    gfx = os.path.join(args.libs, "Adafruit_GFX_Library")
    body_name = args.font or macros.get("BODY_FONT", "FreeSans9pt7b")
    big_name = macros.get("BIG_FONT", "FreeMonoBold18pt7b")
    font_path = os.path.join(gfx, "Fonts", body_name + ".h")
    big_path = os.path.join(gfx, "Fonts", big_name + ".h")
    glcd_path = os.path.join(gfx, "glcdfont.c")
    for p in (args.ino, font_path, big_path, glcd_path):
        if not os.path.exists(p):
            sys.exit("找不到文件：%s\n用 --libs 指定 Arduino libraries 目录" % p)

    f_body = parse_gfx_font(font_path)
    f_big = parse_gfx_font(big_path)
    glcd = parse_glcd_font(glcd_path)

    P = {
        "EPD_W": macros["EPD_W"],
        "EPD_H": macros["EPD_H"],
        "MAX_LINES": macros["MAX_LINES"],
        "LINE_LEN": macros["LINE_LEN"],
        "BODY_X": macros["BODY_X"],
        "BODY_MAX_W": macros["BODY_MAX_W"],
        "BODY_TOP_Y": macros["BODY_TOP_Y"],
        "LINE_H": macros["LINE_H"],
        "LINES_PER_PAGE": macros["LINES_PER_PAGE"],
        "RB_TITLE": macros.get("RB_TITLE", "ROADBOOK"),
        "RB_FOOTER": macros.get("RB_FOOTER", ""),
    }
    if args.line_h:
        P["LINE_H"] = args.line_h
    if args.lpp:
        P["LINES_PER_PAGE"] = args.lpp

    lines = wrap_text(text, P, f_body)
    page_count = max(1, (len(lines) + P["LINES_PER_PAGE"] - 1) // P["LINES_PER_PAGE"])

    # 自检
    widths = [f_body.advance(l) for l in lines]
    over = [i for i, w in enumerate(widths) if w > P["BODY_MAX_W"]]
    maxw = max(widths) if widths else 0

    trial = "  [试排模式：不会改固件]" if (args.font or args.line_h or args.lpp) else ""
    print("源文本: %d 字符" % len(text))
    print("字体:   %s（%d 个字形 0x%02X-0x%02X，字体自然行高 yAdvance=%dpx）"
          % (body_name, len(f_body.glyphs), f_body.first, f_body.last,
             f_body.y_advance))
    print("排版:   行高 LINE_H=%d  每页 %d 行  左边距 %d  正文宽 %d  首行基线 %d%s"
          % (P["LINE_H"], P["LINES_PER_PAGE"], P["BODY_X"],
             P["BODY_MAX_W"], P["BODY_TOP_Y"], trial))
    print("layout: %d lines -> %d pages  maxw=%d/%d over=%d  chk=0x%04X"
          % (len(lines), page_count, maxw, P["BODY_MAX_W"], len(over), checksum(lines)))
    if over:
        print("!! 有 %d 行超宽，会和下一行重叠：" % len(over))
        for i in over:
            print("   第 %d 行 (%dpx): %s" % (i, widths[i], lines[i]))

    # ---- 行重叠检查（第 1 步踩过的大坑：LINE_H 小于字体实际高度就会压行）----
    def ink_extent(s):
        """这行字的墨迹相对基线的上下范围 (top, bottom)，top 一般为负"""
        top = bot = 0
        for ch in s:
            o = ord(ch)
            if not (f_body.first <= o <= f_body.last):
                continue
            _off, gw, gh, _adv, _xo, yo = f_body.glyphs[o - f_body.first]
            if gh > 0:
                top = min(top, yo)
                bot = max(bot, yo + gh - 1)
        return top, bot

    ext = [ink_extent(l) for l in lines]
    min_gap, min_i = 9999, -1          # 相邻两行之间最小的垂直空隙（负数=重叠）
    for i in range(len(lines) - 1):
        if (i + 1) % P["LINES_PER_PAGE"] == 0:      # 跨页的两行不算
            continue
        gap = P["LINE_H"] + ext[i + 1][0] - ext[i][1] - 1
        if gap < min_gap:
            min_gap, min_i = gap, i
    if min_i >= 0:
        if min_gap < 0:
            print("!! 行 %d 和行 %d 在垂直方向重叠 %dpx（LINE_H=%d 太小）"
                  % (min_i + 1, min_i + 2, -min_gap, P["LINE_H"]))
            print("   这字体的自然行高是 %dpx，把 LINE_H 调到 %d 以上，或减小每页行数"
                  % (f_body.y_advance, f_body.y_advance))
        else:
            print("行距 OK：最紧的一处（第 %d/%d 行）还剩 %dpx 空隙"
                  % (min_i + 1, min_i + 2, min_gap))

    if args.dump_lines:
        print()
        for pg in range(page_count):
            print("===== PAGE %d/%d =====" % (pg + 1, page_count))
            for i in range(P["LINES_PER_PAGE"]):
                li = pg * P["LINES_PER_PAGE"] + i
                if li >= len(lines):
                    break
                print("  %3dpx |%s|" % (widths[li], lines[li]))

    # 渲染
    os.makedirs(args.out, exist_ok=True)
    c = Canvas(P["EPD_W"], P["EPD_H"], glcd)
    pages = []
    body_bottom = 0
    for idx in range(page_count):
        bb = render_page(idx, page_count, lines, P, f_body, c)
        if bb and bb > body_bottom:
            body_bottom = bb
        img = c.to_image()
        pages.append(img)
        label_scale(img, args.scale).save(
            os.path.join(args.out, "page_%02d.png" % (idx + 1)))

    render_off(P, f_big, c)
    label_scale(c.to_image(), args.scale).save(os.path.join(args.out, "page_off.png"))

    # 拼版
    sc = args.scale
    cell_w, cell_h = P["EPD_W"] * sc, P["EPD_H"] * sc
    cols = min(6, page_count + 1)
    rows = (page_count + 1 + cols - 1) // cols
    pad, top = 10, 16
    sheet = Image.new("L", (cols * (cell_w + pad) + pad,
                            rows * (cell_h + top + pad) + pad), 200)
    d = ImageDraw.Draw(sheet)
    for i, img in enumerate(pages + [c.to_image()]):
        r, cc = divmod(i, cols)
        x = pad + cc * (cell_w + pad)
        y = pad + r * (cell_h + top + pad)
        t = "OFF" if i == page_count else "%d/%d" % (i + 1, page_count)
        d.text((x + 2, y + 2), t, fill=0)
        sheet.paste(label_scale(img, sc), (x, y + top))
    sheet.save(os.path.join(args.out, "contact_sheet.png"))

    if body_bottom:
        if body_bottom >= 174:
            print("!! 正文快压到页脚线了：墨迹最低 y=%d，页脚线在 178（只剩 %dpx）"
                  % (body_bottom, 178 - body_bottom))
            print("   把 LINES_PER_PAGE 减 1，或 LINE_H 调小，或 BODY_TOP_Y 往上挪")
        else:
            print("正文最低墨迹 y=%d（页脚线 178，还剩 %dpx 空隙）"
                  % (body_bottom, 178 - body_bottom))

    print()
    print("已输出到 %s" % args.out)
    print("  每页单图 page_01.png ... page_%02d.png + page_off.png" % page_count)
    print("  拼版图   contact_sheet.png")
    print()
    print("把上面那行 layout: 和烧录后串口打印的对比，一致就说明电脑上看到的=屏幕上显示的")


if __name__ == "__main__":
    main()
