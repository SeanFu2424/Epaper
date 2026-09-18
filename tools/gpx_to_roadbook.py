#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPX -> 路书 JSON（阶段 A：离线纯几何，不联网）

把一条 GPX 压缩成模板要的事件：turn / glu / climb / danger / halfway / finish / **cp**。

链路：
    GPX -->【本脚本】--> 路书 JSON --> roadbook_gen.py --> roadbook.h --> 墨水屏
                                    --> preview_roadbook.py --> 电脑上看效果

用法：
    python tools/gpx_to_roadbook.py "在覆卮山燃烧.gpx" --name FUZHISHAN --pages 6
    python tools/gpx_to_roadbook.py x.gpx --max-turns 5 --out 02_Roadbook/x.json

参数起始值来源（不是拍脑袋）：
    爬坡 >=4% 且 >=300m      <- dincalculator 官网（真实产品在跑）
    爬坡星级 1~5★            <- dincalculator 官网难度分级
    转弯角度/聚类/最小间距    <- nbareil/gpx-to-markdown（开源项目默认值）
    补给间隔 12~15km         <- dincalculator 官网 route card 的实际密度

🔴 补给分两种，语义完全不同，**不是二选一**（用户 2026-09-18 明确）：
    CP1..CPn  「固定补给点」= GPX 自带航点，骑手人工标的，有人有店必须停
    GLU       「该吃胶了」  = 规则估算的提醒，不一定有店
    → 两者都出现在同一张路书上；GLU 与 CP 同点时 GLU 丢弃（真实补给点优先）

明确不做：
    water  —— 补水提示已按用户要求去掉，只保留 GLU
    danger —— GPX 是纯几何轨迹，推不出"哪里有危险"，留给人工加
    路名   —— GPX 里没有路名，要路名得叠路网数据（BRouter，阶段 B）
"""

import argparse
import bisect
import json
import math
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roadbook as rb          # 星级规则只有一份（roadbook.climb_stars）

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

GPX_NS = "{http://www.topografix.com/GPX/1/1}"

# ======================================================================
# 基础几何
# ======================================================================
R_EARTH = 6371000.0


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH * math.asin(math.sqrt(a))


def bearing(lat1, lon1, lat2, lon2):
    """方位角，度。正北=0，顺时针增大（东=90）"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def smooth(xs, w):
    """滑动平均（窗口 w 点）。w<=1 原样返回。"""
    if w <= 1:
        return list(xs)
    n = len(xs)
    half = w // 2
    out = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out.append(sum(xs[lo:hi]) / (hi - lo))
    return out


# ======================================================================
# 解析
# ======================================================================
def parse_gpx(path):
    """返回 (pts, meta)。pts = [(lat, lon, ele), ...]

    meta["waypoints"] = [(lat, lon, name, sym), ...]
    航点是"人工标的提示点"（Strava/规划器导出时常带，<sym> 是图标种类）。
    补给点如果 GPX 里已经标了，就用真实的，不要再让算法瞎猜。
    """
    tree = ET.parse(path)
    root = tree.getroot()
    pts, n_time = [], 0
    for tp in root.iter(GPX_NS + "trkpt"):
        lat = float(tp.get("lat"))
        lon = float(tp.get("lon"))
        e = tp.find(GPX_NS + "ele")
        ele = float(e.text) if e is not None and e.text else 0.0
        if tp.find(GPX_NS + "time") is not None:
            n_time += 1
        pts.append((lat, lon, ele))

    waypoints = []
    for w in root.iter(GPX_NS + "wpt"):
        nm = w.find(GPX_NS + "name")
        sy = w.find(GPX_NS + "sym")
        waypoints.append((
            float(w.get("lat")), float(w.get("lon")),
            (nm.text or "").strip() if nm is not None else "",
            (sy.text or "").strip() if sy is not None else "",
        ))

    nm = root.find(GPX_NS + "metadata/" + GPX_NS + "name")
    meta = {
        "name": (nm.text or "").strip() if nm is not None else "",
        "n_time": n_time,
        "n_wpt": len(waypoints),
        "n_rtept": sum(1 for _ in root.iter(GPX_NS + "rtept")),
        "waypoints": waypoints,
    }
    return pts, meta


def project_waypoints(pts, dists, waypoints, max_off_m=300.0):
    """把航点投影到轨迹上，算出各自的里程（km）。

    做法：找轨迹上离航点最近的一个点，取它的累积里程。
    （严格说应该投影到"最近线段"上，但对"找它在第几公里"这个用途，
    最近点已经足够 —— 轨迹点密度约 50m，误差远小于 1km 的路书精度。）

    max_off_m: 航点离轨迹超过这个距离就认为"它不在路线上"（比如另存的兴趣点），
    丢弃并报告。Strava 正常导出的补给点偏差是 0~5m。
    """
    out = []
    for lat, lon, nm, sy in waypoints:
        best_i, best_d = 0, float("inf")
        for i, (plat, plon, _e) in enumerate(pts):
            dd = haversine(lat, lon, plat, plon)
            if dd < best_d:
                best_d, best_i = dd, i
        if best_d > max_off_m:
            out.append({"km": None, "name": nm, "sym": sy, "off_m": best_d})
            continue
        out.append({"km": round(dists[best_i] / 1000.0, 1), "name": nm,
                    "sym": sy, "off_m": best_d})
    return out


def cumulative(pts):
    """每点里程（米）"""
    d = [0.0]
    for i in range(1, len(pts)):
        d.append(d[-1] + haversine(pts[i - 1][0], pts[i - 1][1],
                                   pts[i][0], pts[i][1]))
    return d


def resample_idx(dists, step_m):
    """沿距离每 step_m 米取一个点的下标"""
    out, nxt = [], 0.0
    for i, d in enumerate(dists):
        if d >= nxt:
            out.append(i)
            nxt = d + step_m
    if out and out[-1] != len(dists) - 1:
        out.append(len(dists) - 1)
    return out


# ======================================================================
# 爬坡检测
# ======================================================================
def detect_climbs(dists, eles, min_grade=4.0, min_len_m=300.0,
                  win_m=250.0, merge_gap_m=150.0, min_gain_m=20.0):
    """返回爬坡段列表。

    做法：对每个点算"向前 win_m 米"的平均坡度 -> 标记 >= min_grade 的点
    -> 连续段（允许 merge_gap_m 的小间断）-> 过滤太短/爬升太小的。
    """
    n = len(dists)
    if n < 3:
        return []

    grades = [0.0] * n
    j = 0
    for i in range(n):
        if j < i:
            j = i
        while j + 1 < n and dists[j + 1] - dists[i] <= win_m:
            j += 1
        dd = dists[j] - dists[i]
        grades[i] = (eles[j] - eles[i]) / dd * 100.0 if dd > 1e-6 else 0.0

    raw = []
    i = 0
    while i < n:
        if grades[i] < min_grade:
            i += 1
            continue
        a = b = i
        k = i
        while k < n:
            if grades[k] >= min_grade:
                b = k
                k += 1
                continue
            # 找 merge_gap_m 内有没有重新上坡
            nxt = k
            while nxt < n and dists[nxt] - dists[k] <= merge_gap_m:
                if grades[nxt] >= min_grade:
                    break
                nxt += 1
            if nxt < n and dists[nxt] - dists[k] <= merge_gap_m:
                k = nxt
            else:
                break
        raw.append((a, b))
        i = b + 1

    out = []
    for (a, b) in raw:
        e = b
        while e + 1 < n and dists[e + 1] - dists[b] <= win_m:
            e += 1
        length_m = dists[e] - dists[a]
        if length_m < min_len_m:
            continue
        gain = eles[e] - eles[a]
        if gain < min_gain_m:
            continue
        out.append({
            "km": dists[a] / 1000.0,
            "length_km": length_m / 1000.0,
            "elev_m": int(round(gain)),
            "grade": round(gain / length_m * 100.0, 1),
        })
    return out


# ======================================================================
# 转弯检测
# ======================================================================
DIR_UP = "up"
NAV_DIRS = {
    (0, 22): "up", (22, 67): "up_right", (67, 112): "right", (112, 157): "down_right",
}


def turn_dir(delta):
    """delta: -180..180，正 = 右转（顺时针）。返回模板用的方向名，直行返回 None

    骑行路书里"掉头"几乎没有意义，所以 >157 也归到急转，不产生 down。
    """
    a = abs(delta)
    if a < 25.0:
        return None
    if a < 65.0:
        return "up_right" if delta > 0 else "up_left"
    if a < 120.0:
        return "right" if delta > 0 else "left"
    return "down_right" if delta > 0 else "down_left"


def detect_turns(dists, pts, min_angle=45.0, cluster_m=200.0, step_m=60.0):
    """step_m 是方位角基线长度：太短（30m）会被 GPS 噪声放大成假角度，
    60m 起步更稳。"""
    idx = resample_idx(dists, step_m)
    if len(idx) < 3:
        return []
    cands = []
    for k in range(1, len(idx) - 1):
        i0, i1, i2 = idx[k - 1], idx[k], idx[k + 1]
        b1 = bearing(pts[i0][0], pts[i0][1], pts[i1][0], pts[i1][1])
        b2 = bearing(pts[i1][0], pts[i1][1], pts[i2][0], pts[i2][1])
        d = (b2 - b1 + 180.0) % 360.0 - 180.0
        if abs(d) >= min_angle:
            cands.append({"km": dists[i1] / 1000.0, "delta": d})
    # 聚类：cluster_m 内的合并，取角度最大的那个
    clusters = []
    for c in cands:
        if clusters and (c["km"] - clusters[-1][-1]["km"]) * 1000.0 < cluster_m:
            clusters[-1].append(c)
        else:
            clusters.append([c])
    out = []
    for cl in clusters:
        best = max(cl, key=lambda x: abs(x["delta"]))
        d = turn_dir(best["delta"])
        if d:
            out.append({"km": best["km"], "dir": d, "angle": abs(best["delta"])})
    return out


def select_turns(turns, budget, min_spacing_km=3.0):
    """角度大的优先，且彼此至少隔 min_spacing_km"""
    if budget <= 0:
        return []
    chosen = []
    for t in sorted(turns, key=lambda t: -t["angle"]):
        if len(chosen) >= budget:
            break
        if any(abs(t["km"] - c["km"]) < min_spacing_km for c in chosen):
            continue
        chosen.append(t)
    return sorted(chosen, key=lambda t: t["km"])


# ======================================================================
# 补给点
# ======================================================================
# 屏幕上补给分两种，语义完全不同，不能混：
#
#   CP1..CPn  「固定补给点」—— GPX 里作者人工标的航点，有人有店，必须停。
#             km 是真实的，不参与估算，只做"别和爬坡撞"的微调。
#   GLU       「该吃胶了」—— 没有航点可依据时，按里程/时间推出来的提醒。
#             骑手看到 CP 是"这里有补给"，看到 GLU 是"该吃了"，两码事。
#
# 所以本文件的逻辑是：CP 全部来自 wpt；GLU 一律走规则估算（不再二选一）。
# ======================================================================
# 时间轴：把"距离-高程"剖面换算成"骑到这里花了多少分钟"
# ======================================================================
# 为什么需要它：GLU（该吃胶了）本质是**生理节律** —— 每 30~45 分钟补一次，
# 而不是每 13 公里补一次。按里程铺的结果是"平路补太勤、爬坡补太晚"：
# 同样 13 km，平路 25 分钟就到了，8% 的陡坡要骑 1 小时。
#
# 坡度 -> 速度 经验表（km/h）。⚠️ 这是**通用业余长途骑行的经验值，不是实测**，
# 用途只是让"同一条路上各段速度不一样"这件事成立（爬坡慢、平路快）。
# 如果你的实际速度不同，用 --speed-scale 整体缩放（0.8 = 比表里慢 20%）。
V_GRADE_TABLE = (
    (-99.0, -3.0, 42.0), (-3.0, -1.0, 38.0), (-1.0, 0.5, 32.0),
    (0.5, 1.5, 28.0), (1.5, 2.5, 25.0), (2.5, 3.5, 22.0),
    (3.5, 4.5, 20.0), (4.5, 5.5, 18.0), (5.5, 6.5, 16.0),
    (6.5, 7.5, 14.5), (7.5, 8.5, 13.0), (8.5, 10.0, 11.5), (10.0, 99.0, 10.0),
)


def grade_speed(grade_pct, scale=1.0):
    """给定坡度（%），返回经验速度（km/h）"""
    for lo, hi, v in V_GRADE_TABLE:
        if lo <= grade_pct < hi:
            return v * scale
    return 10.0 * scale


def time_axis(dists, eles, step_m=25.0, win_m=125.0, scale=1.0):
    """距离-高程剖面 -> 时间轴。

    返回 (grid_km, cum_min)：两者等长，下标 i 表示"骑到 grid_km[i] 公里时
    累计花了 cum_min[i] 分钟"。用 km_at_min() 可以把时间反算成公里数。

    流程：按 step_m 等距重采样高程 -> ±win_m 中心窗口算坡度 -> 查表得速度
          -> 用相邻两点的平均速度累加时间。
    """
    total_m = dists[-1]
    n = int(total_m / step_m)
    grid_m = [i * step_m for i in range(n + 1)]

    def interp(xs, ys, x):
        i = bisect.bisect_left(xs, x)
        if i <= 0:
            return ys[0]
        if i >= len(xs):
            return ys[-1]
        x0, x1 = xs[i - 1], xs[i]
        if x1 == x0:
            return ys[i]
        return ys[i - 1] + (x - x0) / (x1 - x0) * (ys[i] - ys[i - 1])

    eg = [interp(dists, eles, x) for x in grid_m]

    w = max(1, int(round(win_m / step_m)))
    grade = [0.0] * len(grid_m)
    for i in range(1, len(grid_m) - 1):
        a, b = max(0, i - w), min(len(grid_m) - 1, i + w)
        dd = grid_m[b] - grid_m[a]
        if dd > 0:
            grade[i] = (eg[b] - eg[a]) / dd * 100.0
    if len(grid_m) > 1:
        grade[0] = grade[1]
        grade[-1] = grade[-2]

    cum_min = [0.0] * len(grid_m)
    t = 0.0
    for i in range(1, len(grid_m)):
        v = (grade_speed(grade[i - 1], scale) + grade_speed(grade[i], scale)) / 2.0
        t += (step_m / 1000.0) / v * 60.0
        cum_min[i] = t
    grid_km = [x / 1000.0 for x in grid_m]
    return grid_km, cum_min


def km_at_min(grid_km, cum_min, tmin):
    """时间（分钟）-> 公里数（线性插值）。时间轴是单调的，二分即可。"""
    lo, hi = 0, len(cum_min) - 1
    if tmin <= cum_min[0]:
        return grid_km[0]
    if tmin >= cum_min[-1]:
        return grid_km[-1]
    while lo < hi:
        mid = (lo + hi) // 2
        if cum_min[mid] < tmin:
            lo = mid + 1
        else:
            hi = mid
    if lo == 0:
        return grid_km[0]
    t0, t1 = cum_min[lo - 1], cum_min[lo]
    k0, k1 = grid_km[lo - 1], grid_km[lo]
    if t1 == t0:
        return k1
    return k0 + (tmin - t0) / (t1 - t0) * (k1 - k0)


def _frame_minutes(km_list, dists, eles, scale=1.0):
    """把一串公里数换算成"出发后第几小时几分"，并显示相邻两点的实际间隔。

    只是命令行报表用：让"按时间铺"这件事可核对 —— 避让爬坡/CP 之后，
    间隔会偏离设定值，一眼能看出来。
    """
    if not km_list:
        return "(无)"
    grid_km, cum_min = time_axis(dists, eles, scale=scale)

    def min_of(km):
        lo, hi = 0, len(grid_km) - 1
        if km <= grid_km[0]:
            return cum_min[0]
        if km >= grid_km[-1]:
            return cum_min[-1]
        while lo < hi:
            mid = (lo + hi) // 2
            if grid_km[mid] < km:
                lo = mid + 1
            else:
                hi = mid
        k0, k1 = grid_km[lo - 1], grid_km[lo]
        t0, t1 = cum_min[lo - 1], cum_min[lo]
        if k1 == k0:
            return t1
        return t0 + (km - k0) / (k1 - k0) * (t1 - t0)

    ts = [min_of(k) for k in km_list]
    txt = "  ".join("%dh%02d" % (t // 60, t % 60) for t in ts)
    if len(ts) < 2:
        return txt
    gaps = " ".join("%.0f" % (ts[i] - ts[i - 1]) for i in range(1, len(ts)))
    return "%s   （相邻间隔 %s 分钟）" % (txt, gaps)


def fuel_cands_km(total_km, args, interval, taxis=None):
    """算出 GLU 的"目标公里数"候选列表（还没做避让）。

    --fuel-mode km   ：从 interval 公里开始，每 interval 公里一个
    --fuel-mode time ：从 interval 分钟开始，每 interval 分钟一个
                       （interval 的单位随模式变成分钟）
    taxis = time_axis() 的返回值。传进来是为了避免在"页数不够就放大间隔"
    的循环里反复重算时间轴。
    返回 (候选公里数列表, 模型全程时间分钟；km 模式为 None)
    """
    tail = args.fuel_tail
    cands, t_mov = [], None

    if args.fuel_mode == "time":
        grid_km, cum_min = taxis
        t_mov = cum_min[-1]
        t = interval
        while t <= t_mov:
            k = km_at_min(grid_km, cum_min, t)
            if k > total_km - tail:
                break
            cands.append(round(k, 1))
            t += interval
    else:
        k = interval
        while k <= total_km - tail:
            cands.append(round(k, 1))
            k += interval
    return cands, t_mov


def place_fuel(total_km, climbs, busy, cp_km, cands_km, spread_km=5.0,
               step_km=0.4, min_gap_km=7.0, edge_gap_km=1.2,
               cp_gap_km=3.0, tail_km=4.0, in_climb=False):
    """在一串"目标公里数"上铺 GLU 提醒，落点要避开：

    · **爬坡区间**（含前后 edge_gap_km 余量）—— 默认是硬禁区。爬坡块占两行、
      第二行写的是"结束公里数"，中间插一个更小的公里数会被读成倒挂。
    · busy（转弯 / 中点 / 终点等已占用位置）前后 edge_gap_km
    · cp_km 前后 cp_gap_km —— 已经到真实补给点了，不用再提醒吃胶

    in_climb=True 时**放行爬坡区间**（只躲开坡的起点/终点各 0.6km，
    免得和爬坡块那两个数字挤在一起）。此时落在坡内的 GLU 会被上层标成
    sub（缩进显示），读起来是"这块坡里面，第 x 公里处吃胶"。
    ⚠️ 代价：屏幕上的公里数顺序会出现"48.6 之后跟 45.2"，靠缩进表达从属。

    某个目标点放不下时，在 ±spread_km 内按 step_km 找最近的空位；
    再找不到就放弃这个点（宁缺毋滥，别硬挤）。
    """
    climb_ranges = [(c["km"], c["km"] + c["length_km"]) for c in climbs]

    def free(x):
        for a, b in climb_ranges:
            if in_climb:
                if abs(x - a) < 0.6 or abs(x - b) < 0.6:
                    return False
            elif a - edge_gap_km <= x <= b + edge_gap_km:
                return False
        for x0 in busy:
            if abs(x - x0) < edge_gap_km:
                return False
        for x0 in cp_km:
            if abs(x - x0) < cp_gap_km:
                return False
        return True

    cands = []
    for k in cands_km:
        n = int(round(spread_km / step_km))
        hit = None
        for i in range(n + 1):
            for s in ((0,) if i == 0 else (-i, i)):
                x = round(k + s * step_km, 1)
                if x < 1.5 or x > total_km - tail_km:
                    continue
                if free(x):
                    hit = x
                    break
            if hit is not None:
                break
        if hit is not None:
            cands.append(hit)

    out = []
    for c in sorted(set(cands)):
        if out and c - out[-1] < min_gap_km:
            continue
        out.append(c)
    return out


def merge_same_km(events, climbs, notes):
    """同一个公里数上的多个事件合并成一行（用户 2026-09-18 要求）。

    合并规则：
      1. 先处理"和爬坡结束公里数撞上"的：爬坡第二行印的就是结束公里数，
         同点再来一行同样的数字，屏幕上像重复 -> 把非爬坡事件顺延 0.4 km。
      2. 同一公里数剩下的按优先级取一个主事件，其余附着或丢弃：
           转弯  -> 变成主事件的 arrow 字段（显示成 "CP2 ↙"）
           GLU   -> 遇到同点的 CP 直接丢弃（有真实补给点就不用再提醒吃胶）
      3. 爬坡永远独立占两行，不参与合并。
    """
    # ---- 1) 撞爬坡结束公里数 ----
    ends = dict((round(c["km"] + c["length_km"], 1), round(c["km"], 1)) for c in climbs)
    for e in events:
        if e["type"] == "climb":
            continue
        for _ in range(8):
            k = round(e["km"], 1)
            if k not in ends:
                break
            e["km"] = round(e["km"] + 0.4, 1)
            notes.append("%.1f -> %.1f km（撞上爬坡[起 %.1f]的结束公里数，顺延）"
                         % (k, e["km"], ends[k]))

    # ---- 2) 同公里数分组 ----
    groups = {}
    order = []
    for e in events:
        k = round(e["km"], 1)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(e)

    out = []
    PRIO = {"cp": 4, "halfway": 3, "finish": 2, "glu": 1, "turn": 0, "climb": 9}
    for k in order:
        g = groups[k]
        if len(g) == 1 or any(x["type"] == "climb" for x in g):
            out.extend(sorted(g, key=lambda x: -PRIO.get(x["type"], 0)))
            continue
        head = max(g, key=lambda x: PRIO.get(x["type"], 0))
        rest = [x for x in g if x is not head]
        for x in rest:
            if x["type"] == "turn" and "arrow" not in head:
                head["arrow"] = x["dir"]
                notes.append("%.1f km：转角 %s 并入同一行" % (k, x["dir"]))
            elif x["type"] == "glu":
                notes.append("%.1f km：GLU 与 %s 同点，去掉（真实补给点优先）"
                             % (k, head["type"].upper()))
            else:
                out.append(x)      # 实在合并不了就留着（例如同点两个 CP）
        out.append(head)
    out.sort(key=lambda e: e["km"])
    return out


def order_sub_after_climb(events):
    """把"坡内提醒"（sub=1）挪到它所属的爬坡事件**紧后面**。

    tools/roadbook.py 的 event_blocks() 和固件的 buildPages() 都是靠
    「爬坡后面紧跟若干 sub 事件」来切块的 —— 顺序不对就会切错块
    （表现是坡内提醒跑到爬坡块外面，屏幕上又是数字倒挂）。

    按公里数排序本来就已经满足（坡内提醒的公里数必然大于爬坡起点），
    但合并 / 顺延之后不保证，所以这里显式重排一次，把它变成结构性保证。
    """
    n = len(events)
    placed = [False] * n
    out = []
    for i, c in enumerate(events):
        if placed[i]:
            continue
        placed[i] = True
        if c["type"] != "climb":
            out.append(c)
            continue
        a = float(c["km"])
        b = a + float(c.get("length", 0))
        inner = []
        for j in range(i + 1, n):
            e = events[j]
            if placed[j] or e["type"] == "climb" or not e.get("sub"):
                continue
            if a < float(e["km"]) < b:
                inner.append(j)
        inner.sort(key=lambda j: float(events[j]["km"]))
        out.append(c)
        for j in inner:
            placed[j] = True
            out.append(events[j])
    # 兜底：万一有事件没被走到（例如同号），按原顺序补上
    for i, e in enumerate(events):
        if not placed[i]:
            out.append(e)
    return out


def check_row_order(events, max_rows=None):
    """摊开成最终行序，检查每一页的公里数是否严格递增。

    这是"数字倒挂"的最后一道闸。屏幕上出现 "48.6 后面跟 43.4"
    （爬坡末行的结束公里数比坡内提醒大）就是这里报出来的。
    返回按页分的告警列表，空 = 通过。
    """
    max_rows = max_rows or rb.MAX_ROWS
    bad = []
    for pi, rows in enumerate(rb.paginate(events, max_rows)):
        prev = None
        for r in rows:
            if prev is not None and r["km"] < prev - 1e-9:
                bad.append("第 %d 页：%.1f 后面跟 %.1f —— 公里数倒挂"
                           % (pi + 1, prev, r["km"]))
            prev = r["km"]
    return bad


# ======================================================================
# 主流程
# ======================================================================
def build(gpx_path, args):
    pts, meta = parse_gpx(gpx_path)
    if len(pts) < 10:
        sys.exit("轨迹点太少（%d），不像一条路线" % len(pts))

    dists = cumulative(pts)
    total_km = dists[-1] / 1000.0
    eles_raw = [p[2] for p in pts]
    eles = smooth(eles_raw, args.smooth)

    raw_gain = sum(max(0.0, eles_raw[i] - eles_raw[i - 1]) for i in range(1, len(eles_raw)))
    sm_gain = sum(max(0.0, eles[i] - eles[i - 1]) for i in range(1, len(eles)))

    climbs = detect_climbs(dists, eles,
                           min_grade=args.min_grade, min_len_m=args.min_len,
                           win_m=args.climb_window,
                           merge_gap_m=args.climb_merge, min_gain_m=args.min_gain)
    all_turns = detect_turns(dists, pts, min_angle=args.turn_angle,
                             cluster_m=args.turn_cluster)
    # 终点前 2km 的转弯没意义（马上就到了，不用再提示转向）
    all_turns = [t for t in all_turns if t["km"] <= total_km - 2.0]

    # 落在爬坡区间里的事件要拿掉。爬坡占两行，第二行写的是"结束公里数"，
    # 里面再插转弯/补给会出现"17.6 后面跟 14.6"这种倒挂，读者会以为写错。
    climb_ranges = [(c["km"], c["km"] + c["length_km"]) for c in climbs]

    def _in_climb(k):
        return any(a <= k <= b for a, b in climb_ranges)

    all_turns = [t for t in all_turns if not _in_climb(t["km"])]

    # ---- 转弯：只保留 N 条大弯（用户 2026-09-18：150km 山路 8 条太吵）----
    # select_turns 按角度从大到小挑，且彼此至少隔 turn_spacing km。
    turns = select_turns(all_turns, args.max_turns, min_spacing_km=args.turn_spacing)

    # ---- 固定补给点 CP：只来自 GPX 自带航点 ----
    # 用户明确要求（2026-09-18）：这些是骑手人工标的"固定补给点"，
    # **不能用 GLU 代替**，屏幕上要显示成 CP1 / CP2 / ...。
    # GLU 是另一回事 —— 见下面 place_fuel()，那是"该吃胶了"的提醒。
    wpt_proj = project_waypoints(pts, dists, meta["waypoints"]) if meta["waypoints"] else []
    cp_list = []
    if not args.no_wpt:
        for w in sorted((x for x in wpt_proj if x["km"] is not None),
                        key=lambda x: x["km"]):
            cp_list.append({"km": round(w["km"], 1), "type": "cp",
                            "label": "", "name": w["name"], "sym": w["sym"]})
    # CP 不能丢（那是骑手亲自标的店/补给位置），落在爬坡区间里就顺延到爬坡结束后
    wpt_moved = []
    for c in cp_list:
        for a, b in sorted(climb_ranges):
            if a <= c["km"] <= b:
                orig = c["km"]
                c["km"] = round(b + 0.4, 1)
                wpt_moved.append((orig, c["km"], c["name"]))
                break
    # 按最终里程重新编号（屏幕上必须单调递增）
    cp_list.sort(key=lambda x: x["km"])
    for i, c in enumerate(cp_list):
        c["n"] = i + 1
        c["label"] = "CP%d" % (i + 1)
    cp_km = [c["km"] for c in cp_list]

    # ---- 中点提示（HALFWAY）----
    # 两个硬约束：
    #   ① 绝不能落在爬坡区间内 —— 爬坡第二行写的是"结束公里数"，
    #      中间再插一个更小的公里数会被读成倒挂
    #      （真踩过：第 2 页出现 "79.4" 后面跟 "77.7"）
    #   ② 不能和邻近事件挤在一起（两行贴太近看着乱）
    #
    # 做法：真中点 ±8km 每 0.4km 撒候选，过滤掉爬坡区间和拥挤位置，
    # 取离真中点最近的那个。
    # ⚠️ 别再用"从真中点一路 +0.4 往后找"的写法：它只检查了起点是否在爬坡里，
    #    中途会跨过爬坡起点钻进爬坡区间内部（这就是上面那个倒挂 bug 的成因）。
    half_true = total_km / 2.0
    busy = ([c["km"] for c in climbs] + [c["km"] + c["length_km"] for c in climbs]
            + cp_km + [t["km"] for t in turns] + [total_km])

    cands = []
    for i in range(-20, 21):
        k = round(half_true + i * 0.4, 1)
        if not (1.0 <= k <= total_km - 1.0):
            continue
        if _in_climb(k):
            continue
        if any(abs(k - b) < 1.2 for b in busy):
            continue
        cands.append(k)
    if cands:
        half = min(cands, key=lambda x: abs(x - half_true))
        if abs(half - half_true) > 6.0:
            half = None        # 让得太远，这条提示就失去"过半"的意义了
    else:
        half = None

    # ---- GLU 提醒：按里程铺，避开爬坡 / CP / 转弯 / 中点 ----
    # 页数预算：爬坡、CP、转弯、中点、终点先占掉，剩下的行数才给 GLU。
    # 放不下就把间隔拉大（宁可少几个提醒，也不要把页数撑爆）。
    fixed_rows = (2 * len(climbs) + len(cp_list) + len(turns)
                  + (1 if half is not None else 0) + 1)      # +1 = 终点
    busy2 = [t["km"] for t in turns] + ([half] if half is not None else []) + [total_km]

    # 时间轴只在 time 模式下用，算一次就够（与间隔无关）
    taxis, t_mov = None, None
    if args.fuel_mode == "time":
        taxis = time_axis(dists, eles, scale=args.speed_scale)

    glu, interval = [], args.fuel_interval
    for _ in range(10):
        cands, t_mov = fuel_cands_km(total_km, args, interval, taxis)
        glu = place_fuel(total_km, climbs, busy2, cp_km, cands,
                         spread_km=args.fuel_spread,
                         min_gap_km=args.fuel_min_gap,
                         edge_gap_km=args.edge_gap, cp_gap_km=args.cp_gap,
                         in_climb=args.glu_in_climb)
        # 坡内提醒会各自多占一行，页数预算要算上，否则"目标 6 页"会悄悄变 7 页
        n_inside = len([k for k in glu
                        if any(a < k < b for a, b in climb_ranges)])
        if fixed_rows + len(glu) + n_inside <= args.pages * rb.MAX_ROWS:
            break
        interval *= 1.2

    events = []
    for c in climbs:
        # ⚠️ 爬坡第二行显示的"结束公里数"是 km + length 反算出来的
        #    （预览器和固件都是这么算的，见 roadbook.event_rows）。
        #    如果这里把 km 和 length 各自 round 到 1 位，两者相加就会和真实终点差 0.1：
        #    真实 30.2133 + 18.3444 = 48.5578 -> 应显示 48.6，
        #    但 round 后 30.2 + 18.3 = 48.5，屏幕上就印成 48.5（错 0.1 km）。
        #    Far02 上真踩到两处（48.5 / 136.2）。
        #    正解：先把**终点**round 到 1 位，再用 end - km 反推 length，
        #    这样"起点 + 长度"必然等于显示出来的终点，读者能自己验算。
        km_r = round(c["km"], 1)
        end_r = round(c["km"] + c["length_km"], 1)
        events.append({"km": km_r, "type": "climb",
                       "length": round(end_r - km_r, 1),
                       "elev": c["elev_m"], "grade": c["grade"],
                       "stars": rb.climb_stars(c["grade"], c["length_km"])})
    for c in cp_list:
        events.append(dict(c))
    for f in glu:
        events.append({"km": f, "type": "glu"})
    for t in turns:
        events.append({"km": round(t["km"], 1), "type": "turn", "dir": t["dir"]})
    if half is not None:
        events.append({"km": half, "type": "halfway"})
    events.append({"km": round(total_km, 1), "type": "finish"})
    events.sort(key=lambda e: e["km"])

    # ---- 同一公里数合并成一行（用户 2026-09-18 要求）----
    notes = []
    events = merge_same_km(events, climbs, notes)

    # ---- 落在爬坡块内部的 GLU：标成 sub ----
    # 缩进 = "我属于上面那个爬坡块"。屏幕上这一块的行序是
    #     首行(起点 km + CLM 长度)  ->  坡内提醒(按 km 升序)  ->  末行(结束 km + 坡度 + 星级)
    # （见 tools/roadbook.py 的 event_blocks()），所以整块公里数严格递增。
    # 用户 2026-09-18：缩进可以，但必须夹在两行**中间**，保证按公里数排序。
    #
    # ⚠️ 这里用**屏幕上印出来的**爬坡区间（events 里 round 过的那份），
    #    不是 detect_climbs 的原始浮点区间 —— 否则边界上会差 0.1km 判错。
    disp_ranges = [(float(e["km"]), float(e["km"]) + float(e.get("length", 0)))
                   for e in events if e["type"] == "climb"]
    if args.glu_in_climb:
        for e in events:
            if e["type"] == "glu" and any(a < e["km"] < b for a, b in disp_ranges):
                e["sub"] = 1

    # ---- 把坡内提醒归位（爬坡后面紧跟）并做排序自检 ----
    events = order_sub_after_climb(events)
    order_warn = check_row_order(events)
    n_sub = len([e for e in events if e.get("sub") and e["type"] != "climb"])

    # 合并后重新数一遍行数（合并可能少了几个 GLU；爬坡 2 行 + 坡内提醒 1 行）
    n_rows = rb.total_rows(events)

    data = {
        "name": args.name,
        "note": "由 tools/gpx_to_roadbook.py 生成自 %s" % os.path.basename(gpx_path),
        "events": events,
    }
    stats = {
        "total_km": total_km, "raw_gain": raw_gain, "sm_gain": sm_gain,
        "n_climb": len(climbs), "n_turn_all": len(all_turns), "n_turn_kept": len(turns),
        "n_cp": len(cp_list), "n_glu": len([e for e in events if e["type"] == "glu"]),
        "n_events": len(events), "n_rows": n_rows, "half_km": half,
        "fp_rows": fixed_rows, "glu_interval": interval,
        "fuel_mode": args.fuel_mode, "t_mov_min": t_mov,
        "speed_scale": args.speed_scale,
        "meta": meta, "n_pts": len(pts),
        "n_sub": n_sub, "order_warn": order_warn,
        "n_pages": len(rb.paginate(events, rb.MAX_ROWS)),
        "wpt_proj": wpt_proj, "wpt_moved": wpt_moved, "cp_list": cp_list,
        "glu_km": [e["km"] for e in events if e["type"] == "glu"], "notes": notes,
        "glu_time_txt": (_frame_minutes([e["km"] for e in events if e["type"] == "glu"],
                                        dists, eles, args.speed_scale)
                         if args.fuel_mode == "time" else ""),
    }
    return data, events, climbs, stats


def main():
    ap = argparse.ArgumentParser(description="GPX -> 路书 JSON（阶段 A，离线）")
    ap.add_argument("gpx")
    ap.add_argument("--out", default=None)
    ap.add_argument("--name", default=None, help="路名（屏幕只有 ASCII，中文要换成拼音）")

    # 高程
    ap.add_argument("--smooth", type=int, default=9,
                    help="高程平滑窗口（点数），0/1=不平滑。默认 9")
    # 爬坡
    ap.add_argument("--min-grade", type=float, default=4.0, help="爬坡最小坡度%%")
    ap.add_argument("--min-len", type=float, default=300.0, help="爬坡最小长度(米)")
    ap.add_argument("--climb-window", type=float, default=250.0, help="坡度计算窗口(米)")
    ap.add_argument("--climb-merge", type=float, default=800.0,
                    help="相邻爬坡段间隔小于此值就合并(米)。默认 800（越小坡切得越细）")
    ap.add_argument("--min-gain", type=float, default=30.0,
                    help="爬坡最小爬升(米)。默认 30（越小保留的小坡越多）")
    # 转弯
    ap.add_argument("--turn-angle", type=float, default=60.0, help="转弯角度阈值")
    ap.add_argument("--turn-cluster", type=float, default=200.0, help="转弯聚类半径(米)")
    ap.add_argument("--max-turns", type=int, default=5,
                    help="最多保留几个转弯提示（按角度从大到小挑）。默认 5")
    ap.add_argument("--turn-spacing", type=float, default=8.0,
                    help="保留的转弯之间最小间隔(km)。默认 8")
    # 补给（GLU = "该吃胶了"的提醒，和 CP 固定补给点是两件事）
    ap.add_argument("--fuel-mode", choices=("km", "time"), default="time",
                    help="GLU 铺点依据：km=按里程（简单但爬坡段会补得太晚），"
                         "time=按时间（爬坡慢->提醒变密，贴近 dincalculator）。默认 time")
    ap.add_argument("--fuel-interval", type=float, default=None,
                    help="GLU 间隔。km 模式单位是 km（默认 13），time 模式单位是"
                         "分钟（默认 40）。不指定就按模式取默认值")
    ap.add_argument("--speed-scale", type=float, default=1.0,
                    help="time 模式下速度模型的整体缩放：0.8 = 比经验表慢 20%%，"
                         "1.2 = 快 20%%。默认 1.0")
    ap.add_argument("--fuel-tail", type=float, default=4.0,
                    help="终点前多少 km 之内不再铺 GLU（默认 4）")
    ap.add_argument("--glu-in-climb", action="store_true",
                    help="允许 GLU 落在爬坡块内部（缩进显示，夹在爬坡两行中间，"
                         "块内公里数仍递增）。默认禁止 —— 长爬坡中途就没有提醒了")
    ap.add_argument("--fuel-spread", type=float, default=5.0,
                    help="目标点放不下时前后找空位的范围(km)")
    ap.add_argument("--fuel-min-gap", type=float, default=7.0,
                    help="两个 GLU 之间至少隔多远(km)")
    ap.add_argument("--edge-gap", type=float, default=1.2,
                    help="事件与爬坡区间/其它事件的最小间距(km)")
    ap.add_argument("--cp-gap", type=float, default=3.0,
                    help="GLU 离 CP 至少多远(km)。到了真实补给点就不用再提醒吃胶")
    ap.add_argument("--no-wpt", action="store_true",
                    help="忽略 GPX 自带航点（于是没有 CP，只有 GLU）")
    # 页数
    ap.add_argument("--pages", type=int, default=6,
                    help="目标页数上限（超了就把 GLU 间隔拉大）。默认 6")
    args = ap.parse_args()

    # --fuel-interval 在两个模式下单位不同，不指定就按模式取默认
    if args.fuel_interval is None:
        args.fuel_interval = 40.0 if args.fuel_mode == "time" else 13.0

    if not os.path.exists(args.gpx):
        sys.exit("找不到 %s" % args.gpx)

    # 路名：中文/emoji 屏幕显示不了 -> 取 ASCII，取不到就 ROUTE
    _, meta0 = parse_gpx(args.gpx)
    raw = args.name or meta0["name"] or os.path.splitext(os.path.basename(args.gpx))[0]
    ascii_name = "".join(ch for ch in raw if 32 <= ord(ch) < 127).strip()
    if args.name is None and not ascii_name:
        print("!! 路名 '%s' 全是非 ASCII（屏幕字体只有 0x20-0x7E），请用 --name 指定拼音/英文"
              % raw)
    args.name = ascii_name or "ROUTE"

    data, events, climbs, st = build(args.gpx, args)

    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(args.gpx if args.gpx.lower().endswith(".json") else __file__)),
        "..", "02_Roadbook", "gpx_roadbook.json")
    out = os.path.normpath(out)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("输入   : %s" % args.gpx)
    print("轨迹点 : %d   时间戳 %d   航点 wpt=%d rtept=%d"
          % (st["n_pts"], st["meta"]["n_time"], st["meta"]["n_wpt"], st["meta"]["n_rtept"]))
    print("距离   : %.2f km   爬升(原始/平滑) %+.0f / %+.0f m"
          % (st["total_km"], st["raw_gain"], st["sm_gain"]))
    print("爬坡   : %d 段" % st["n_climb"])
    for c in climbs:
        # 打印的是"屏幕上会出现的三个数"：起点 / 终点 / 长度
        _km, _end = round(c["km"], 1), round(c["km"] + c["length_km"], 1)
        print("         %6.1f -> %6.1f km  %4.1f km  +%3dm  %.1f%%   %s"
              % (_km, _end, round(_end - _km, 1), c["elev_m"], c["grade"],
                 "*" * rb.climb_stars(c["grade"], c["length_km"])))
    print("转弯   : 候选 %d -> 保留 %d 条大弯（最多 %d 条、间隔 >=%.0fkm）"
          % (st["n_turn_all"], st["n_turn_kept"], args.max_turns, args.turn_spacing))

    # CP = GPX 自带航点（固定补给点，人工标注）
    if st["cp_list"]:
        print("CP     : %d 个固定补给点（来自 GPX 自带航点，非算法估算）" % st["n_cp"])
        by_name = dict((w["name"], w) for w in st["wpt_proj"] if w["km"] is not None)
        for c in st["cp_list"]:
            w = by_name.get(c["name"], {})
            print("         %-4s %6.1f km   %-12s (%s)"
                  % (c["label"], c["km"], c["name"], w.get("sym", "")))
        for w in st["wpt_proj"]:
            if w["km"] is None:
                print("         !! '%s' 离轨迹 %.0f m，判定不在路线上，已忽略"
                      % (w["name"], w["off_m"]))
        for a, b, nm in st["wpt_moved"]:
            print("         ~  %.1f -> %.1f km（%s 原本落在爬坡内，顺延到爬坡后）" % (a, b, nm))
    else:
        print("CP     : 无（GPX 里%s航点%s）"
              % ("有 %d 个但被 --no-wpt 忽略" % st["meta"]["n_wpt"]
                 if st["meta"]["n_wpt"] else "没有", ""))

    if st["fuel_mode"] == "time":
        tm = st["t_mov_min"] or 0.0
        print("GLU    : %d 个吃胶提醒（按时间铺：每 %.0f 分钟一个；"
              "模型全程 %dh%02d，速度系数 %.2f）"
              % (st["n_glu"], st["glu_interval"], tm // 60, tm % 60, st["speed_scale"]))
        print("         出发后 %s" % st["glu_time_txt"])
    else:
        print("GLU    : %d 个吃胶提醒（按里程铺：每 %.1f km 一个，避让爬坡/CP/转弯）"
              % (st["n_glu"], st["glu_interval"]))
    if st["glu_km"]:
        print("         " + "  ".join("%.1f" % k for k in st["glu_km"]))
    print("中点   : %s" % (("%.1f km" % st["half_km"]) if st["half_km"] else "无"))

    if st["notes"]:
        print("合并   : 同一公里数合并成一行")
        for n in st["notes"]:
            print("         - %s" % n)

    print("事件   : 共 %d 个 / %d 行 -> %d 页（每页最多 %d 行）"
          % (st["n_events"], st["n_rows"], st["n_pages"], rb.MAX_ROWS))
    if st["n_sub"]:
        print("坡内提醒: %d 个（左列缩进 8px，夹在爬坡两行中间，块内公里数递增）"
              % st["n_sub"])
    if st["order_warn"]:
        print("排序自检: !! 发现公里数倒挂，别烧录：")
        for w in st["order_warn"]:
            print("         !! %s" % w)
    else:
        print("排序自检: 每一页的公里数都严格递增 ✅")
    print("路名   : %s" % args.name)
    print("已写出 : %s" % out)
    print()
    print("下一步看图：")
    print("  python tools/preview_roadbook.py \"%s\"" % out.replace("\\", "/"))


if __name__ == "__main__":
    main()
