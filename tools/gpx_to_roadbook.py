#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPX -> 路书 JSON（阶段 A：离线纯几何，不联网）

把一条 GPX 压缩成模板要的事件：turn / glu / climb / danger / halfway / finish。

链路：
    GPX -->【本脚本】--> 路书 JSON --> roadbook_gen.py --> roadbook.h --> 墨水屏
                                    --> preview_roadbook.py --> 电脑上看效果

用法：
    python tools/gpx_to_roadbook.py "在覆卮山燃烧.gpx" --name FUZHISHAN
    python tools/gpx_to_roadbook.py x.gpx --max-events 10 --out 02_Roadbook/x.json

参数起始值来源（不是拍脑袋）：
    爬坡 >=4% 且 >=300m      <- dincalculator 官网（真实产品在跑）
    爬坡星级 1~5★            <- dincalculator 官网难度分级
    转弯角度/聚类/最小间距    <- nbareil/gpx-to-markdown（开源项目默认值）
    补给间隔 + 爬坡前移       <- dincalculator 官网"golden rule"

明确不做（V1）：
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
# 补给点（抄 dincalculator 的规则）
# ======================================================================
def place_fuel(total_km, climbs, interval_km=25.0, before_km=3.0,
               near_km=8.0, tail_km=5.0, heavy_grade=5.0, heavy_len_km=2.0):
    """按间隔铺点，再把落在"重要爬坡"前 near_km 内的点前移到爬坡前 before_km。

    对应 dincalculator 官网："if a rated climb (3 star or higher) starts within
    8 km of a planned gel stop, the stop is automatically shifted 3 km before it."
    """
    pts = []
    k = interval_km
    while k <= total_km - tail_km:
        pts.append(round(k, 1))
        k += interval_km

    heavy = [c for c in climbs
             if c["grade"] >= heavy_grade and c["length_km"] >= heavy_len_km]
    for c in heavy:
        s = c["km"]
        target = round(s - before_km, 1)
        if target < 1.0:
            continue
        for i, p in enumerate(pts):
            if s - near_km <= p <= s and abs(p - target) > 0.3:
                pts[i] = target

    merged = []
    for p in sorted(pts):
        if merged and p - merged[-1] < 5.0:
            continue
        merged.append(p)
    return merged


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

    # ---- 补给点 ----
    # 优先级：GPX 自带航点（人工标的真实补给点） > 按规则估算。
    # 覆卮山那条 GPX 没有航点，只能用规则估；这条 Far 02 有 4 个真实补给点。
    wpt_proj = project_waypoints(pts, dists, meta["waypoints"]) if meta["waypoints"] else []
    wpt_fuel = [w["km"] for w in wpt_proj if w["km"] is not None]
    if wpt_fuel and not args.no_wpt:
        fuel, fuel_src = sorted(set(wpt_fuel)), "wpt"
    else:
        fuel = place_fuel(total_km, climbs, interval_km=args.fuel_interval,
                          before_km=args.fuel_before, near_km=args.fuel_near)
        fuel_src = "rule"

    # 落在爬坡区间里的事件要拿掉。爬坡占两行，第二行写的是"结束公里数"，
    # 里面再插转弯/补给会出现"17.6 后面跟 14.6"这种倒挂，读者会以为写错。
    # 而且爬坡中本来就不该吃胶。
    climb_ranges = [(c["km"], c["km"] + c["length_km"]) for c in climbs]

    def _in_climb(k):
        return any(a <= k <= b for a, b in climb_ranges)

    all_turns = [t for t in all_turns if not _in_climb(t["km"])]
    wpt_moved = []
    if fuel_src == "rule":
        # 规则估的补给点落在爬坡里就直接丢弃
        fuel = [f for f in fuel if not _in_climb(f)]
    else:
        # 真实航点不能丢（那是骑手亲自标的店/补给位置），顺延到爬坡结束后一点
        fixed = []
        for f in fuel:
            orig = f
            for a, b in sorted(climb_ranges):
                if a <= f <= b:
                    f = round(b + 0.4, 1)
                    wpt_moved.append((orig, f))
                    break
            fixed.append(f)
        fuel = sorted(set(fixed))

    # 事件预算：爬坡 / 补给 / 中点优先，剩下给转弯
    budget = args.max_events - len(climbs) - len(fuel) - 2   # 2 = 中点 + 终点
    turns = select_turns(all_turns, budget, min_spacing_km=args.turn_spacing)

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
    busy = [c["km"] for c in climbs] + list(fuel) + [t["km"] for t in turns]
    busy += [c["km"] + c["length_km"] for c in climbs]
    busy.append(total_km)

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
    for f in fuel:
        events.append({"km": f, "type": "glu"})
    for t in turns:
        events.append({"km": round(t["km"], 1), "type": "turn", "dir": t["dir"]})
    if half is not None:
        events.append({"km": half, "type": "halfway"})
    events.append({"km": round(total_km, 1), "type": "finish"})
    events.sort(key=lambda e: e["km"])

    data = {
        "name": args.name,
        "note": "由 tools/gpx_to_roadbook.py 生成自 %s" % os.path.basename(gpx_path),
        "events": events,
    }
    stats = {
        "total_km": total_km, "raw_gain": raw_gain, "sm_gain": sm_gain,
        "n_climb": len(climbs), "n_turn_all": len(all_turns), "n_turn_kept": len(turns),
        "n_fuel": len(fuel), "n_events": len(events), "half_km": half,
        "meta": meta, "n_pts": len(pts),
        "fuel_src": fuel_src, "wpt_proj": wpt_proj, "wpt_moved": wpt_moved,
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
    ap.add_argument("--climb-merge", type=float, default=1000.0,
                    help="相邻爬坡段间隔小于此值就合并(米)。默认 1000")
    ap.add_argument("--min-gain", type=float, default=60.0, help="爬坡最小爬升(米)")
    # 转弯
    ap.add_argument("--turn-angle", type=float, default=60.0, help="转弯角度阈值")
    ap.add_argument("--turn-cluster", type=float, default=200.0, help="转弯聚类半径(米)")
    ap.add_argument("--turn-spacing", type=float, default=3.0, help="保留的转弯最小间隔(km)")
    # 补给
    ap.add_argument("--fuel-interval", type=float, default=25.0, help="补给间隔(km)")
    ap.add_argument("--fuel-before", type=float, default=3.0, help="爬坡前多少 km 放补给")
    ap.add_argument("--fuel-near", type=float, default=8.0, help="爬坡前多少 km 内的补给会被前移")
    ap.add_argument("--no-wpt", action="store_true",
                    help="忽略 GPX 自带航点，强制用规则估算补给点")
    # 总量
    ap.add_argument("--max-events", type=int, default=14, help="事件总数上限（含中点/终点）")
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
    print("转弯   : 候选 %d -> 保留 %d  补给 %d  中点 %s"
          % (st["n_turn_all"], st["n_turn_kept"], st["n_fuel"],
             ("%.1f km" % st["half_km"]) if st["half_km"] else "无"))

    # 补给点来源：GPX 自带航点 还是 规则估算
    if st["fuel_src"] == "wpt":
        print("补给   : 来自 GPX 自带航点（真实标记，非算法估算）")
        for w in st["wpt_proj"]:
            if w["km"] is None:
                print("         !! '%s' 离轨迹 %.0f m，判定不在路线上，已忽略"
                      % (w["name"], w["off_m"]))
            else:
                print("         %6.1f km   %-12s (%s)" % (w["km"], w["name"], w["sym"]))
        for a, b in st["wpt_moved"]:
            print("         ~  %.1f -> %.1f km（原本落在爬坡内，顺延到爬坡后）" % (a, b))
    else:
        if st["meta"]["n_wpt"]:
            print("补给   : 按规则估算（--no-wpt 已关闭航点；GPX 里有 %d 个航点被忽略）"
                  % st["meta"]["n_wpt"])
        else:
            print("补给   : 按规则估算（GPX 里没有航点）")

    print("事件   : 共 %d 个" % st["n_events"])
    print("路名   : %s" % args.name)
    print("已写出 : %s" % out)
    print()
    print("下一步看图：")
    print("  python tools/preview_roadbook.py \"%s\"" % out.replace("\\", "/"))


if __name__ == "__main__":
    main()
