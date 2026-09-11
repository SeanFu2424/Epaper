#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Roadbook V1 —— 渲染核心（PC 预览器 和 ESP32 固件 共用同一套规则）

V1 只有 5 种事件：
    turn / glu / climb / danger / finish

排版铁律（改这里 = 预览和屏幕一起改）：
    公里数永远左对齐，事件永远右对齐。
    爬坡是唯一允许占两行的事件。

为什么箭头要自制位图：
    FreeSans9pt7b 只覆盖 ASCII 0x20-0x7E，
    ↰ ↱ ← → ↙ ↘ 全部在 U+2190 以上，字体里根本没有，画出来是空白。
    所以 8 个方向的箭头在这里用数学方法画成 16x16 的 1-bit 位图，
    PC 端和 ESP32 端用的是同一份数据（roadbook_gen.py 会导出成 C 数组）。
"""

import json
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
ARROW_BYTES = ARROW * ARROW // 8


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

EVENT_TYPES = (TYPE_TURN, TYPE_GLU, TYPE_CLIMB, TYPE_DANGER, TYPE_FINISH)


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


def pack_bitmap(px, size=ARROW):
    """打包成字节：row-major，MSB 在左 —— 和 GxEPD2 的 drawBitmap 一致"""
    out = bytearray()
    row = 0
    for i, v in enumerate(px):
        if v:
            row |= 0x80 >> (i & 7)
        if (i & 7) == 7:
            out.append(row)
            row = 0
    return bytes(out)


# ----------------------------------------------------------------------
# 事件 -> 行
# ----------------------------------------------------------------------
def fmt_km(km):
    """公里数格式。KM_SUFFIX 默认空串（12pt 大字放不下 ' km'，见常量区注释）"""
    return "%.1f%s" % (float(km), KM_SUFFIX)


def event_rows(ev):
    """把一个事件拆成 1~2 行。每行返回 dict：
         left  : 左列文字（公里数，可能为空）
         right : 右列文字（None 表示画箭头）
         arrow : 方向名（仅 turn）
    """
    t = ev.get("type", "").strip().lower()
    if t not in EVENT_TYPES:
        raise ValueError("未知事件类型 %r，V1 只有：%s" % (t, ", ".join(EVENT_TYPES)))

    km = fmt_km(ev["km"])

    if t == TYPE_TURN:
        return [{"left": km, "right": None, "arrow": norm_dir(ev.get("dir")), "sub": False}]
    if t == TYPE_GLU:
        return [{"left": km, "right": "GLU", "arrow": None, "sub": False}]
    if t == TYPE_DANGER:
        return [{"left": km, "right": "DANGER", "arrow": None, "sub": False}]
    if t == TYPE_FINISH:
        return [{"left": km, "right": "FINISH", "arrow": None, "sub": False}]
    if t == TYPE_CLIMB:
        r1 = "CLM %.*f" % (1, float(ev.get("length", 0)))
        r2 = "+%dm %.*f%%" % (int(float(ev.get("elev", 0))),
                              1, float(ev.get("grade", 0)))
        # 第二行左列 = 爬坡结束公里数（22.6 + 3.1 = 25.7），缩进表示从属于上面那行
        end_km = float(ev["km"]) + float(ev.get("length", 0))
        return [{"left": km, "right": r1, "arrow": None, "sub": False},
                {"left": fmt_km(end_km), "right": r2, "arrow": None, "sub": True}]
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
