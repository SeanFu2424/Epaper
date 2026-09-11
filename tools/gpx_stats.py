# -*- coding: utf-8 -*-
"""GPX 体检：点数 / 距离 / 爬升（原始 vs 平滑对比）/ 海拔范围 / 是否含时间戳

用法:
    python tools/gpx_stats.py "路径/xxx.gpx"

目的：拿一条新 GPX 时先看清它的"规模"，也用来验证
「高程必须平滑，否则爬升虚高」这条结论。
"""
import sys
import math
import xml.etree.ElementTree as ET

GPX = '{http://www.topografix.com/GPX/1/1}'


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def smooth(xs, w):
    """滑动平均，窗口 w（奇数）。w<=1 时原样返回。"""
    if w <= 1:
        return xs[:]
    half = w // 2
    out = []
    for i in range(len(xs)):
        lo = max(0, i - half)
        hi = min(len(xs), i + half + 1)
        out.append(sum(xs[lo:hi]) / (hi - lo))
    return out


def gain(xs):
    return sum(max(0.0, xs[i] - xs[i - 1]) for i in range(1, len(xs)))


def main(path):
    tree = ET.parse(path)
    root = tree.getroot()

    pts = []
    n_time = 0
    for tp in root.iter(GPX + 'trkpt'):
        lat = float(tp.get('lat'))
        lon = float(tp.get('lon'))
        e = tp.find(GPX + 'ele')
        ele = float(e.text) if e is not None else 0.0
        if tp.find(GPX + 'time') is not None:
            n_time += 1
        pts.append((lat, lon, ele))

    n_wpt = len(list(root.iter(GPX + 'wpt')))
    n_rte = len(list(root.iter(GPX + 'rtept')))

    print(f"文件      : {path}")
    print(f"轨迹点数  : {len(pts)}")
    print(f"含时间戳  : {n_time} 个点" + ("  （无 → 只能用均速/FTP 估时间）" if n_time == 0 else ""))
    print(f"内置航点  : wpt={n_wpt}  rtept={n_rte}" + ("  （都是 0 → GPX 里没有现成提示点）" if n_wpt == 0 and n_rte == 0 else ""))
    if len(pts) < 2:
        return

    dists = [0.0]
    for i in range(1, len(pts)):
        dists.append(dists[-1] + haversine(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1]))
    total_km = dists[-1] / 1000.0

    eles = [p[2] for p in pts]
    print(f"总距离    : {total_km:.2f} km")
    print(f"海拔范围  : {min(eles):.0f} ~ {max(eles):.0f} m")
    print(f"原始累积  : 爬升 +{gain(eles):.0f} m   （逐点累加，会被 GPS 噪声虚高）")
    for w in (5, 15, 31, 51, 101):
        print(f"平滑 w={w:3d} : 爬升 +{gain(smooth(eles, w)):.0f} m")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
