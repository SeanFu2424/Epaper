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
def place_fuel(total_km, climbs, busy, cp_km, interval_km=13.0, spread_km=5.0,
               step_km=0.4, min_gap_km=7.0, edge_gap_km=1.2,
               cp_gap_km=3.0, tail_km=4.0):
    """按里程间隔铺 GLU 提醒，落点要避开：

    · **爬坡区间**（含前后 edge_gap_km 余量）—— 硬禁区。爬坡块占两行、
      第二行写的是"结束公里数"，中间插一个更小的公里数会被读成倒挂。
    · busy（转弯 / 中点 / 终点等已占用位置）前后 edge_gap_km
    · cp_km 前后 cp_gap_km —— 已经到真实补给点了，不用再提醒吃胶

    某个目标点放不下时，在 ±spread_km 内按 step_km 找最近的空位；
    再找不到就放弃这个点（宁缺毋滥，别硬挤）。
    """
    climb_ranges = [(c["km"], c["km"] + c["length_km"]) for c in climbs]

    def free(x):
        for a, b in climb_ranges:
            if a - edge_gap_km <= x <= b + edge_gap_km:
                return False
        for x0 in busy:
            if abs(x - x0) < edge_gap_km:
                return False
        for x0 in cp_km:
            if abs(x - x0) < cp_gap_km:
                return False
        return True

    cands = []
    k = interval_km
    while k <= total_km - tail_km:
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
        k += interval_km

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

    glu, interval = [], args.fuel_interval
    for _ in range(10):
        glu = place_fuel(total_km, climbs, busy2, cp_km,
                         interval_km=interval, spread_km=args.fuel_spread,
                         min_gap_km=args.fuel_min_gap,
                         edge_gap_km=args.edge_gap, cp_gap_km=args.cp_gap)
        if fixed_rows + len(glu) <= args.pages * rb.MAX_ROWS:
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

    # 合并后重新数一遍行数（合并可能少了几个 GLU）
    n_rows = sum(2 if e["type"] == "climb" else 1 for e in events)

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
        "meta": meta, "n_pts": len(pts),
        "wpt_proj": wpt_proj, "wpt_moved": wpt_moved, "cp_list": cp_list,
        "glu_km": [e["km"] for e in events if e["type"] == "glu"], "notes": notes,
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
    # 补给
    ap.add_argument("--fuel-interval", type=float, default=13.0,
                    help="GLU 提醒的里程间隔(km)。默认 13（对标 dincalculator 的 12~15）")
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

    print("GLU    : %d 个吃胶提醒（间隔 %0.1f km 起铺，避让爬坡/CP/转弯）"
          % (st["n_glu"], args.fuel_interval))
    if st["glu_km"]:
        print("         " + "  ".join("%.1f" % k for k in st["glu_km"]))
    print("中点   : %s" % (("%.1f km" % st["half_km"]) if st["half_km"] else "无"))

    if st["notes"]:
        print("合并   : 同一公里数合并成一行")
        for n in st["notes"]:
            print("         - %s" % n)

    print("事件   : 共 %d 个 / %d 行 -> 约 %d 页（每页最多 %d 行）"
          % (st["n_events"], st["n_rows"],
             (st["n_rows"] + rb.MAX_ROWS - 1) // rb.MAX_ROWS, rb.MAX_ROWS))
    print("路名   : %s" % args.name)
    print("已写出 : %s" % out)
    print()
    print("下一步看图：")
    print("  python tools/preview_roadbook.py \"%s\"" % out.replace("\\", "/"))


if __name__ == "__main__":
    main()
