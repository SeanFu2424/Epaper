#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Roadbook V1 —— 渲染核心（PC 预览器 和 ESP32 固件 共用同一套规则）

V1 只有 6 种事件：
    turn / glu / climb / danger / finish / halfway

排版铁律（改这里 = 预览和屏幕一起改）：
    公里数永远左对齐，事件永远右对齐。
    爬坡是唯一允许占两行的事件；第二行 = 结束公里数（缩进）+ 难度星级。
    没有文字也没有位图能画 ★（字体只覆盖 ASCII），所以星级是自制位图。

为什么箭头要自制位图：
    FreeSans9pt7b 只覆盖 ASCII 0x20-0x7E，
    ↰ ↱ ← → ↙ ↘ 全部在 U+2190 以上，字体里根本没有，画出来是空白。
    所以 8 个方向的箭头在这里用数学方法画成 16x16 的 1-bit 位图，
    PC 端和 ESP32 端用的是同一份数据（roadbook_gen.py 会导出成 C 数组）。
"""

import json
import math
import os

# ----------------------------------------------------------------------
# 屏幕与模板参数（固件里是同一组 #define）
# ----------------------------------------------------------------------
SCREEN_W = 200
SCREEN_H = 200
MARGIN = 6             # 左右边距
SUB_INDENT = 8         # 爬坡第二行的缩进（视觉上从属于上面那行）
                       # ⚠️ 必须和 02_Roadbook.ino 的 SUB_INDENT 一致

# ---- 版式：200px 高的四段结构 ----
#
#     0 ─ 16   页眉（路名 + 页码）        基线 y=16
#    16 ─ 22   页眉横线                    y=22
#    22 ─ 162  正文区（自适应行距）        基线 y=38..162
#   162 ─ 174  页脚横线                    y=174
#   174 ─ 200  状态栏（左=时间 / 右=电量） 基线 y=190
#
# 正文区高度 124px 中塞 6 行 -> 行距 24（字体 yAdvance=22，余 2px）：
# 9pt 字形墨高只有 11px，行距 24 意味着行间白 13px，视觉不挤。
# 加页脚状态栏的代价就是正文区少了 28px，行距从 30 收紧到 24，仍可用。
HEADER_Y = 16          # 页眉基线
HEADER_LINE_Y = 22     # 页眉横线

BODY_TOP = 38          # 正文区顶部（第一行基线能到的最高位置）
BODY_BOTTOM = 162      # 最后一行基线的下限
                       # 实测：正文墨迹底 = 基线 +1px。162 -> 距离页脚横线(174)
                       # 最紧的一页还剩 11px；再往下就会贴线（试过 166，只剩 7px）
GAP_MIN = 24           # 最小行距（字体 yAdvance=22，必须 > 22 才不重叠）
GAP_MAX = 38           # 最大行距（内容少时最多散到这么开，再散就难看了）
MAX_ROWS = 6           # 一页最多几个"行"（爬坡算 2 行）

FOOT_LINE_Y = 174      # 页脚横线
FOOT_Y = 190           # 状态栏基线（9pt：数字无下伸部，墨迹底 = 基线）

KM_SUFFIX = " km"      # 公里数后缀（9pt 下 "108.9 km" 也放得下）

ARROW = 16             # 箭头位图边长
ARROW_BYTES = ARROW * ((ARROW + 7) // 8)

# ---- 爬坡星级（代替原来的 "+237m 6.1%"）----
# ★ 在 U+2605，字体里没有（只覆盖 ASCII 0x20-0x7E），
#   所以和箭头一样用数学方法画成 1-bit 位图，PC 与 ESP32 共用同一份数据。
STAR = 13              # 单颗星位图边长（12px 尖角糊成一团；13px 是 9pt 字高附近的甜点）
STAR_GAP = 0           # 星与星的间距。0 = 紧贴。
                       # 爬坡第二行 = 结束公里数(含 .0) + 坡度% + 5星，右列很宽；
                       # 5星 gap=2 时和左列只差 -1px（撞），gap=1 仍只有 3px（太贴），
                       # gap=0 余 7px。13px 的星本身有约 1px 留白，gap=0 视觉上仍分得清颗数。
STAR_MAX = 5
STAR_INNER = 0.45      # 内半径/外半径。标准五角星是 0.382（很尖），
                       # 但 13px 下尖角会糊，0.45 更饱满、更认得出是星星
STAR_BYTES = STAR * ((STAR + 7) // 8)


def body_region():
    """正文区可用高度"""
    return BODY_BOTTOM - BODY_TOP


def layout(rows, gap=None):
    """给定本页行数，算出怎么排版。返回 (首行基线, 行距)

    gap=None 时行距自适应：行少就撑开（上限 GAP_MAX），行多就压紧（下限 GAP_MIN），
    整块再垂直居中 —— 这样事件少的页不会在底下空一大块。

    所有行等距——包括爬坡的第二行。别想着"爬坡两行挤紧一点"：
    一旦两行不等距，实际占用的高度就和这里的假设对不上，底部又会空出一块
    （这个坑踩过）。爬坡的归属感靠"第二行缩进"来体现。

    固件里是同一个公式（02_Roadbook.ino 的 computeLayout），改这边记得改那边。
    """
    rows = max(1, int(rows))
    avail = body_region()
    if rows <= 1:
        return BODY_TOP + avail // 2, GAP_MAX   # 只有一行就垂直居中
    if gap is None:
        gap = max(GAP_MIN, min(GAP_MAX, avail // (rows - 1)))
    gap = max(1, int(gap))
    if gap * (rows - 1) > avail:                # 放不下就压回去（宁可挤，不可溢出）
        gap = avail // (rows - 1)
    block = gap * (rows - 1)                    # 首行到末行基线的距离
    top = BODY_TOP + (avail - block) // 2       # 整块垂直居中
    return top, gap

# ----------------------------------------------------------------------
# 8 个方向（屏幕坐标系：y 向下）
# ----------------------------------------------------------------------
DIRS = {
    "up":         (0.0, -1.0),
    "up_right":   (0.7071, -0.7071),
    "right":      (1.0, 0.0),
    "down_right": (0.7071, 0.7071),
    "down":       (0.0, 1.0),
    "down_left":  (-0.7071, 0.7071),
    "left":       (-1.0, 0.0),
    "up_left":    (-0.7071, -0.7071),
}

# 手写 JSON 时可以用简写
DIR_ALIAS = {
    "u": "up", "ur": "up_right", "r": "right", "dr": "down_right",
    "d": "down", "dl": "down_left", "l": "left", "ul": "up_left",
    "^": "up", ">": "right", "v": "down", "<": "left",
}

TYPE_TURN = "turn"
TYPE_GLU = "glu"
TYPE_CLIMB = "climb"
TYPE_DANGER = "danger"
TYPE_FINISH = "finish"
TYPE_HALFWAY = "halfway"   # 中点提示
TYPE_CP = "cp"             # 固定补给点（GPX 航点，骑手人工标的真实补给点）

EVENT_TYPES = (TYPE_TURN, TYPE_GLU, TYPE_CLIMB, TYPE_DANGER, TYPE_FINISH,
               TYPE_HALFWAY, TYPE_CP)


def cp_label(ev):
    """CP 的右列文字：优先用显式 label，否则按序号拼 'CP1' / 'CP2' ...

    为什么补给点要分 cp / glu 两种：
        cp  = GPX 里作者自己标的固定补给点（有人有店，必须停），编号 CP1..CPn
        glu = 按时间/里程推算出来的"该吃胶了"的提醒（不一定有店）
    两者语义不同，屏幕上也不能混 —— 看到 CP 是"这里有补给"，看到 GLU 是"该吃了"。
    """
    lab = (ev.get("label") or "").strip()
    if lab:
        return lab
    n = ev.get("n")
    return "CP%d" % int(n) if n else "CP"


def arrow_of(ev, t):
    """这一行要不要画箭头；不画返回 None。

    turn 事件看 dir；其它事件看 arrow —— 那是"同一个点既要补给又要拐弯"
    被合并成一行时留下的（见 gpx_to_roadbook.merge_same_km）。
    """
    d = ev.get("dir") if t == TYPE_TURN else ev.get("arrow")
    return norm_dir(d) if d else None


def norm_dir(d):
    """把 'r' / 'right' 之类归一化成标准方向名"""
    if d is None:
        return "right"
    d = str(d).strip().lower()
    d = DIR_ALIAS.get(d, d)
    if d not in DIRS:
        raise ValueError("未知方向 %r，可用：%s" % (d, ", ".join(sorted(DIRS))))
    return d


# ----------------------------------------------------------------------
# 箭头位图：数学方法画，PC 和 ESP32 得到完全一样的点
# ----------------------------------------------------------------------
def _in_arrow(lx, ly):
    """箭头局部坐标判定（箭头指向 +X 方向）"""
    if -7.0 <= lx <= 2.0 and abs(ly) <= 1.6:        # 尾巴
        return True
    if -1.0 <= lx <= 7.0:                            # 三角箭头头部
        half = 4.6 * (7.0 - lx) / 8.0
        return abs(ly) <= half
    return False


def make_arrow(dx, dy, size=ARROW, ss=4):
    """画一个方向的箭头。返回 list[size*size]，1 = 黑点。ss = 超采样倍数"""
    c = (size - 1) / 2.0
    need = (ss * ss + 1) // 2
    px = []
    for y in range(size):
        for x in range(size):
            hits = 0
            for sy in range(ss):
                for sx in range(ss):
                    ox = x + (sx + 0.5) / ss - c
                    oy = y + (sy + 0.5) / ss - c
                    lx = ox * dx + oy * dy      # 旋转到箭头局部坐标
                    ly = -ox * dy + oy * dx
                    if _in_arrow(lx, ly):
                        hits += 1
            px.append(1 if hits >= need else 0)
    return px


def arrows_all():
    return dict((name, make_arrow(*vec)) for name, vec in DIRS.items())


# ----------------------------------------------------------------------
# 星级位图：五角星，顶点朝上
# ----------------------------------------------------------------------
def _star_verts(size, inner=STAR_INNER):
    """五角星 10 个顶点。inner = 内半径/外半径（0.382 是标准五角星比例）

    五角星的重心不在外接圆圆心（上方有个尖角、下方是两个钝角），
    所以最后按实际包围盒竖直居中 —— 否则星星看上去会偏上。
    """
    c = (size - 1) / 2.0
    R = size / 2.0
    r = R * inner
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5      # 从正上方开始，每 36°
        rad = R if i % 2 == 0 else r
        pts.append((c + rad * math.cos(ang), c + rad * math.sin(ang)))
    ys = [p[1] for p in pts]
    dy = c - (min(ys) + max(ys)) / 2.0
    return [(x, y + dy) for x, y in pts]


def _in_poly(x, y, poly):
    """射线法判断点是否在多边形内"""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def make_star(size=STAR, ss=6):
    """画一颗五角星。返回 list[size*size]，1 = 黑点"""
    poly = _star_verts(size)
    need = (ss * ss + 1) // 2
    px = []
    for y in range(size):
        for x in range(size):
            hits = 0
            for sy in range(ss):
                for sx in range(ss):
                    if _in_poly(x + (sx + 0.5) / ss, y + (sy + 0.5) / ss, poly):
                        hits += 1
            px.append(1 if hits >= need else 0)
    return px


def star_width(n, size=STAR, gap=STAR_GAP):
    """n 颗星的总宽（px）"""
    n = max(0, int(n))
    return n * size + (n - 1) * gap if n else 0


def pack_bitmap(px, size=ARROW):
    """打包成字节：row-major，MSB 在左 —— 和 GxEPD2 的 drawBitmap 一致

    ⚠️ 每行必须补齐到整字节：Adafruit_GFX / GxEPD2 的 drawBitmap 是按
    ceil(width/8) 字节一行来取的。边长是 8 的倍数时（16px 的箭头）
    补不补一样，所以箭头一直没暴露这个问题；12x12 的星星不补行就会整体错位
    （PC 预览看不出来，因为预览用的是未打包的像素 —— 只有烧进板子才会发现）。
    """
    stride = (size + 7) // 8
    out = bytearray()
    for j in range(size):
        row = bytearray(stride)
        for i in range(size):
            if px[j * size + i]:
                row[i >> 3] |= 0x80 >> (i & 7)
        out.extend(row)
    return bytes(out)


# ----------------------------------------------------------------------
# 事件 -> 行
# ----------------------------------------------------------------------
def fmt_km(km):
    """公里数格式。KM_SUFFIX 默认空串（12pt 大字放不下 ' km'，见常量区注释）"""
    return "%.1f%s" % (float(km), KM_SUFFIX)


# ---- 爬坡难度星级（规则抄 dincalculator 官网，不是拍脑袋）----
#   1★ 温和   3-4%
#   2★ 中等
#   3★ 扎实   5-7% 且 2km+
#   4★ 难     7-9% 且 3km+
#   5★ 残酷   9%+  或 7km+
def climb_stars(grade, length_km):
    g = float(grade or 0)
    L = float(length_km or 0)
    if g >= 9.0 or L >= 7.0:
        return 5
    if g >= 7.0 and L >= 3.0:
        return 4
    if g >= 5.0 and L >= 2.0:
        return 3
    if g >= 4.0:
        return 2
    return 1


def event_rows(ev):
    """把一个事件拆成 1~2 行。每行返回 dict：
         left  : 左列文字（公里数，可能为空）
         right : 右列文字（None 表示画箭头或星级）
         arrow : 方向名（仅 turn）
         stars : 星级（仅爬坡第二行），0 = 不画
         sub   : True = 缩进（从属于上一行）
    """
    t = ev.get("type", "").strip().lower()
    if t not in EVENT_TYPES:
        raise ValueError("未知事件类型 %r，V1 只有：%s" % (t, ", ".join(EVENT_TYPES)))

    km = fmt_km(ev["km"])
    arw = arrow_of(ev, t)

    if t == TYPE_TURN:
        return [{"left": km, "right": None, "arrow": arw, "stars": 0, "sub": False}]
    if t == TYPE_GLU:
        return [{"left": km, "right": "GLU", "arrow": arw, "stars": 0, "sub": False}]
    if t == TYPE_CP:
        return [{"left": km, "right": cp_label(ev), "arrow": arw,
                 "stars": 0, "sub": False}]
    if t == TYPE_DANGER:
        return [{"left": km, "right": "DANGER", "arrow": arw, "stars": 0, "sub": False}]
    if t == TYPE_FINISH:
        return [{"left": km, "right": "FINISH", "arrow": arw, "stars": 0, "sub": False}]
    if t == TYPE_HALFWAY:
        return [{"left": km, "right": "HALFWAY", "arrow": arw, "stars": 0, "sub": False}]
    if t == TYPE_CLIMB:
        stars = int(ev.get("stars") or 0) or climb_stars(ev.get("grade"),
                                                         ev.get("length"))
        stars = max(1, min(STAR_MAX, stars))
        r1 = "CLM %.*f" % (1, float(ev.get("length", 0)))
        # 第二行左列 = 爬坡结束公里数（22.6 + 3.1 = 25.7），缩进表示从属于上面那行。
        # ⚠️ 这里**不带 " km" 单位** —— 单位第一行已经给了。
        #    原因：三位数公里数("136.2 km"=72px) + 间距 + 坡度%("5.5%"=40px)
        #    + 5 颗星(65px) = 181px，而可用宽度只有 188 - 8(缩进) = 180px，差 1px 就粘连。
        #    省略单位省 20px，且**不损失任何数字精度**（小数点照留，坡度照留一位小数）。
        #    试过的其他方案都不如这个：缩小星星（13px 已是可辨认下限，12px 就糊）、
        #    加速度整数（丢精度）、减缩进（视觉上"从属感"会消失）。
        end_km = float(ev["km"]) + float(ev.get("length", 0))
        end_km_str = "%.1f" % end_km
        grade = ev.get("grade")
        grade_txt = "%.1f%%" % float(grade) if grade not in (None, "") else None
        return [{"left": km, "right": r1, "arrow": None, "stars": 0, "sub": False},
                {"left": end_km_str, "right": grade_txt, "arrow": None,
                 "stars": stars, "sub": True}]
    raise ValueError(t)


def rows_of(ev):
    """这个事件占几行"""
    return 2 if ev.get("type", "").strip().lower() == TYPE_CLIMB else 1


# ----------------------------------------------------------------------
# 分页：爬坡不跨页
# ----------------------------------------------------------------------
def paginate(events, max_rows=MAX_ROWS):
    pages, cur, n = [], [], 0
    for ev in events:
        r = rows_of(ev)
        if cur and n + r > max_rows:
            pages.append(cur)
            cur, n = [], 0
        cur.append(ev)
        n += r
    if cur or not pages:
        pages.append(cur)
    return pages


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    evs = data.get("events", [])
    for e in evs:
        if "type" not in e or "km" not in e:
            raise ValueError("事件缺少 type 或 km：%r" % e)
    return data
