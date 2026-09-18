# -*- coding: utf-8 -*-
"""生成「GLU 补给节奏对比」HTML：网站 dincalculator vs 我们的两种铺法。

数据不手抄 —— 我们的点位直接从生成好的 JSON 里读，
网站的点位从它导出的 PDF 里读出来（见 _设计/GPX转路书_调研与方案.md）。
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import gpx_to_roadbook as G   # noqa: E402

GPX = r"C:\Users\surface\Downloads\Far+02+GroupA.gpx"
TOTAL = 150.58

# ---- 网站 dincalculator 导出的点位（从 PDF 文本读出来的）----
WEB_GEL = [18.4, 32.3, 45.2, 68.2, 94.7, 114.4, 126.6, 140.0]
WEB_H2O = [40.0, 60.0, 80.0, 100.0, 120.0]


def load_km(path):
    d = json.load(open(path, encoding="utf-8"))
    glu = [e["km"] for e in d["events"] if e["type"] == "glu"]
    cp = [e["km"] for e in d["events"] if e["type"] == "cp"]
    return glu, cp


GLU_KM, CP_KM = load_km(os.path.join(ROOT, "02_Roadbook", "far02.json"))
GLU_T, CP_T = load_km(os.path.join(ROOT, "_设计", "roadbook_variants", "far02_t35_ic.json"))

# ---- 时间轴（和工具里同一个速度模型）----
pts, meta = G.parse_gpx(GPX)
dists = G.cumulative(pts)
eles = G.smooth([p[2] for p in pts], 9)
GRID, CUM = G.time_axis(dists, eles)
T_MOV = CUM[-1]


def _t(km):
    """km -> 累计分钟（在 (GRID, CUM) 上二分）"""
    import bisect
    i = bisect.bisect_left(GRID, km)
    if i <= 0:
        return CUM[0]
    if i >= len(GRID):
        return CUM[-1]
    k0, k1 = GRID[i - 1], GRID[i]
    t0, t1 = CUM[i - 1], CUM[i]
    if k1 == k0:
        return t1
    return t0 + (km - k0) / (k1 - k0) * (t1 - t0)


def hm(t):
    return "%dh%02d" % (int(t) // 60, int(t) % 60)


def rows(km_list):
    out = []
    pk, pt = 0.0, 0.0
    for k in km_list:
        t = _t(k)
        out.append({"km": k, "min": t, "dk": k - pk, "dt": t - pt})
        pk, pt = k, t
    return out


# 网站：GEL 是"按时间铺"的。只拿 GEL 和我们按规则铺的 GLU 对照
# （CP 是 GPX 航点、网站没有这一项，单独说明）
R_WEB = rows(WEB_GEL)
R_KM = rows(GLU_KM)
R_T = rows(GLU_T)


def svg_axis(items, total_km, total_min, color, label, y):
    """一条横向刻度轴：items = [(km, 分钟, 文字)]"""
    x0, x1 = 90, 900
    parts = []
    parts.append('<text x="8" y="%d" font-size="13" fill="#5c6672">%s</text>'
                 % (y + 4, label))
    parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#dfe3e8" stroke-width="1"/>'
                 % (x0, y, x1, y))
    for km, t, txt in items:
        px = x0 + (x1 - x0) * (km / total_km)
        pt = x0 + (x1 - x0) * (t / total_min)
        parts.append('<circle cx="%.1f" cy="%d" r="4.5" fill="%s"/>' % (pt, y, color))
        parts.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" '
                     'stroke-width="1" stroke-dasharray="2,2" opacity=".45"/>'
                     % (px, y - 8, px, y + 8, color))
        parts.append('<text x="%.1f" y="%d" font-size="11" fill="#5c6672" '
                     'text-anchor="middle">%s</text>' % (pt, y - 12, txt))
    return "".join(parts)


def b64(p):
    with open(p, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def pages_html(folder, n=6):
    return "".join(
        '<img src="%s" alt="第%d页">' % (b64(os.path.join(folder, "page_%02d.png" % i)), i)
        for i in range(1, n + 1)
    )


IMG_KM = pages_html(os.path.join(ROOT, "02_Roadbook", "preview"))
IMG_T = pages_html(os.path.join(ROOT, "_设计", "roadbook_variants", "preview"))

SVG_W = svg_axis([(r["km"], r["min"], "%.1f" % r["km"]) for r in R_WEB],
                 TOTAL, T_MOV, "#c2410c", "网站 GEL", 46)
SVG_KM = svg_axis([(r["km"], r["min"], "%.0f" % r["km"]) for r in R_KM],
                  TOTAL, T_MOV, "#7c3aed", "我们 · 按里程", 108)
SVG_T = svg_axis([(r["km"], r["min"], "%.0f" % r["km"]) for r in R_T],
                 TOTAL, T_MOV, "#15803d", "我们 · 按时间", 170)


def table(rows_, name):
    h = ['<table><tr><th>#</th><th>公里</th><th>出发后</th><th>本段里程</th>'
         '<th>本段用时</th></tr>']
    for i, r in enumerate(rows_, 1):
        h.append("<tr><td>%d</td><td class='mono'>%.1f</td><td class='mono'>%s</td>"
                 "<td class='mono'>%s</td><td class='mono'>%s</td></tr>"
                 % (i, r["km"], hm(r["min"]),
                    "%.1f" % r["dk"] if i > 1 else "—",
                    "%d min" % r["dt"] if i > 1 else "—"))
    h.append("</table>")
    return "".join(h)


def gaps(rows_, key="dt"):
    return [r[key] for r in rows_[1:]]


G_WEB, G_KM, G_T = gaps(R_WEB), gaps(R_KM), gaps(R_T)
K_WEB, K_KM, K_T = gaps(R_WEB, "dk"), gaps(R_KM, "dk"), gaps(R_T, "dk")


def rng(v, unit=""):
    return "%.0f~%.0f%s" % (min(v), max(v), unit)


def rms(xs, ys):
    """两组点位的匹配误差：每个参考点找最近的点"""
    e = [min(abs(x - y) for y in ys) for x in xs]
    return (sum(v * v for v in e) / len(e)) ** 0.5


HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Far02 —— GLU 补给节奏：网站 vs 我们</title>
<style>
:root{--bg:#f5f6f8;--card:#fff;--ink:#1b1f24;--dim:#5c6672;--line:#dfe3e8}
*{box-sizing:border-box}
body{margin:0;padding:28px 22px 60px;background:var(--bg);color:var(--ink);
 font:15px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1060px;margin:0 auto}
h1{font-size:23px;margin:0 0 6px}
.sub{color:var(--dim);font-size:13.5px;margin-bottom:22px}
h2{font-size:17px;margin:34px 0 12px;padding-left:10px;border-left:4px solid #1b1f24}
h3{font-size:15px;margin:22px 0 8px;color:#242a31}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
 padding:18px 20px;margin:14px 0;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.verdict{background:#fff9ec;border:1px solid #f0d9a8;border-left:4px solid #e3b04b}
.verdict b{color:#8a5a00}
.grid3{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}
.grid3>div{flex:1 1 300px;min-width:280px}
table{border-collapse:collapse;width:100%%;font-size:13px;margin:6px 0}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left}
th{background:#eef1f4;font-weight:600}
.mono{font-family:ui-monospace,Consolas,"Cascadia Mono",monospace}
.pages{display:flex;gap:6px;flex-wrap:wrap}
.pages img{width:160px;image-rendering:pixelated;border:1px solid var(--line);
 border-radius:4px;background:#fff}
.cap{font-size:12.5px;color:var(--dim);margin-top:8px}
.ok{color:#15803d;font-weight:600}.warn{color:#c2410c;font-weight:600}
ul{margin:8px 0 0 18px;padding:0}li{margin:5px 0}
code{background:#eef1f4;border-radius:3px;padding:1px 5px;font-size:12.5px}
.legend span{display:inline-block;margin-right:16px;font-size:13px;color:#5c6672}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%%;margin-right:5px}
svg{width:100%%;height:auto;overflow:visible}
</style></head><body><div class="wrap">

<h1>Far02 —— GLU 补给节奏：网站 vs 我们</h1>
<div class="sub">同一条 GPX（150.58 km / +2728 m）｜左：dincalculator 的 route card｜右：我们的 200×200 墨水屏</div>

<div class="card verdict">
<b>结论：你看到的偏差不是点位算错，是"铺点依据"不同。</b><br>
网站按<b>时间</b>铺（每约 40 分钟一支胶），所以里程间隔忽长忽短（12.2~26.5 km）；
我们原来按<b>里程</b>铺（每 13 km 一个），结果平路补得太勤、爬坡补得太晚。<br>
现在工具加了按时间铺的模式，<b>9 个点的实际间隔变成 34~39 分钟</b>，
其中 <b>6 个点与网站误差不到 2.3 km</b>。
</div>

<h2>一、补给点位的"节奏"长什么样</h2>
<p style="color:#5c6672;font-size:13.5px">横轴 = 出发后的时间（0 ~ %s）。如果铺点依据是时间，点会<b>等距</b>排开；
如果依据是里程，爬坡段（走得慢）就会挤成一片。虚线是对应的里程位置。</p>

<div class="card">
<svg viewBox="0 0 920 200">
%s
</svg>
<div class="legend" style="margin-top:6px">
<span><i class="dot" style="background:#c2410c"></i>网站 GEL（8 个）</span>
<span><i class="dot" style="background:#7c3aed"></i>我们 · 按里程铺（现状）</span>
<span><i class="dot" style="background:#15803d"></i>我们 · 按时间铺（新）</span>
</div>
</div>

<h2>二、三种铺法的数字对照</h2>
<p style="color:#5c6672;font-size:13.5px">下面只比 <b>GLU / GEL</b> 这一组（都是"该补糖了"的提醒）。
4 个 CP 固定补给点是 GPX 里的航点、网站没有这一项，所以另外算。</p>
<div class="grid3">
<div>
<h3>网站 GEL（按时间）</h3>
%s
<p class="cap">相邻间隔 %s 分钟，可是里程差 <b>%s km</b> ——
忽长忽短，正是"按时间铺"的特征。</p>
</div>
<div>
<h3>我们 · 按里程 <code>--fuel-mode km</code>（现状）</h3>
%s
<p class="cap">里程稳稳的 13 km，用时却差 <b>%s 分钟</b>：
爬坡段要骑 79 分钟才等到下一个提醒，平路 19 分钟就来了一个。</p>
</div>
<div>
<h3>我们 · 按时间 <code>--fuel-mode time</code>（新）</h3>
%s
<p class="cap">用时差收窄到 <b>%s 分钟</b>，里程自然变成 %s km
（爬坡段短、平路段长）。</p>
</div>
</div>
<p class="cap">另外还有 <b>4 个 CP 固定补给点</b>（GPX 航点里人工标的：28.4 / 48.7 / 82.1 / 137.0 km），
它们和 GLU 并存 —— 看到 CP 是"这里有店该停"，看到 GLU 是"该补一支胶了"。</p>

<h2>三、6 页预览</h2>
<h3>现状（按里程 13 km）</h3>
<div class="pages">%s</div>
<h3>新方案（按时间 35 分钟，允许 GLU 落在爬坡块内）</h3>
<div class="pages">%s</div>
<p class="cap">注意新方案里缩进的 GLU（如第 2 页 <span class="mono">32.8 GLU</span>、<span class="mono">43.4 GLU</span>）——
它表示"在这块坡里面吃"。这是<b>唯一</b>能让长爬坡中途也有提醒的办法，代价是屏幕上会出现"48.6 后面跟 43.4"。</p>

<h2>四、为什么会有这个差别</h2>
<div class="card">
<ul>
<li><b>网站</b>：单列长卡，一条 14.5 km 的长坡写一行就完事，想在哪插补给就插在哪。</li>
<li><b>我们</b>：爬坡占两行（第二行印的是<b>结束公里数</b>），所以爬坡块<b>内部</b>默认不放任何事件——
否则读者会看到"48.6 后面跟 43.4"，像是数字倒挂（这个 bug 你之前抓到过）。</li>
</ul>
<p>而 Far02 的 30.2~48.6 km 是一整段 <b>18.4 km 的连续爬坡</b>，按速度模型要骑 <b>1 小时</b>。
在"爬坡块内不放事件"的规则下，这一小时里<b>一个提醒都放不下</b> ——
这就是旧方案里出现 79 分钟空档、以及整体与网站对不上的根本原因。</p>
<p>新方案给了两个开关：</p>
<ul>
<li><code>--fuel-mode time</code>：按骑行时间铺，而不是按里程。默认 40 分钟一个。</li>
<li><code>--glu-in-climb</code>：放行爬坡块内部，坡内的 GLU 缩进 8px 显示。</li>
</ul>
</div>

<h2>五、需要你知道的两件事</h2>
<div class="card">
<p><b>① 速度模型是经验值，不是你的实测</b><br>
工具里用的是一张"坡度 → 速度"经验表（平路 32 km/h、5%% 坡 18、9%% 坡 11.5……），
按它算这条路线全程 <b>%s</b>。如果你实际更慢或更快，
用 <code>--speed-scale 0.9</code>（慢 10%%）整体缩放，
或者干脆把 <code>--fuel-interval</code> 直接写成你想要的时间间隔（分钟）。</p>
<p style="margin-top:14px"><b>② 网站那 8 个 GEL 点，有 3 个落在我们的爬坡块里</b>
（32.3 / 45.2 / 126.6）—— 这正好是"要不要放行爬坡块"这件事的由来。</p>
</div>

</div></body></html>
""" % (
    hm(T_MOV),
    SVG_W + SVG_KM + SVG_T,
    table(R_WEB, "网站"),
    rng(G_WEB), rng(K_WEB),
    table(R_KM, "里程"),
    rng(G_KM),
    table(R_T, "时间"),
    rng(G_T), rng(K_T),
    IMG_KM,
    IMG_T,
    hm(T_MOV),
)

out = os.path.join(ROOT, "_设计", "Far02_GLU补给节奏_对比.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(HTML)
print("written: %s  (%d bytes)" % (out, os.path.getsize(out)))
print("网站 时间间隔:", " ".join("%d" % g for g in G_WEB), " 里程间隔:", " ".join("%.1f" % g for g in K_WEB))
print("里程 时间间隔:", " ".join("%d" % g for g in G_KM), " 里程间隔:", " ".join("%.1f" % g for g in K_KM))
print("时间 时间间隔:", " ".join("%d" % g for g in G_T), " 里程间隔:", " ".join("%.1f" % g for g in K_T))
print("与网站的 RMS：按里程 %.1f km   按时间 %.1f km"
      % (rms(WEB_GEL, [r["km"] for r in R_KM]), rms(WEB_GEL, [r["km"] for r in R_T])))
