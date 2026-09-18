# -*- coding: utf-8 -*-
"""生成 Far02 改版对比页：网站路书 / 我们 6 页 / 我们 7 页（细分）"""
import base64
import os

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(BASE, "..", ".."))
OUT = os.path.join(os.path.dirname(BASE), "Far02_路书改版_6页vs7页.html")
P6 = os.path.join(ROOT, "02_Roadbook", "preview")
P7 = os.path.join(ROOT, "_设计", "roadbook_variants", "preview")


def b64(path):
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


CSS = """
:root{--bg:#f5f6f8;--card:#fff;--ink:#1b1f24;--dim:#5c6672;--line:#dfe3e8;--bd:#e3b04b;--wa:#c2410c;--ok:#15803d}
*{box-sizing:border-box}
body{margin:0;padding:26px 22px 60px;background:var(--bg);color:var(--ink);
 font:15px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:23px;margin:0 0 6px}
.sub{color:var(--dim);font-size:13.5px;margin-bottom:20px}
h2{font-size:17px;margin:32px 0 12px;padding-left:10px;border-left:4px solid #1b1f24}
h3{font-size:15px;margin:20px 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 20px;margin:13px 0;
 box-shadow:0 1px 2px rgba(16,24,40,.04)}
.verdict{background:#fff9ec;border:1px solid #f0d9a8;border-left:4px solid var(--bd)}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin:6px 0}
th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:#eef1f4;font-weight:600}
.mono{font-family:ui-monospace,Consolas,"Cascadia Mono",monospace;font-size:12.5px}
.row{display:flex;gap:22px;align-items:flex-start;flex-wrap:wrap;margin-top:6px}
.col h3{margin:0 0 2px}
.col .meta{font-size:12.5px;color:var(--dim);margin-bottom:8px}
.stack{display:flex;gap:7px;flex-wrap:wrap}
.stack img{width:174px;image-rendering:pixelated;border:1px solid var(--line);border-radius:4px;background:#fff}
.webimg{width:280px;border:1px solid var(--line);border-radius:6px}
ul{margin:8px 0 0 18px;padding:0}
code{background:#eef1f4;border-radius:3px;padding:1px 5px;font-size:12.5px}
.tag{display:inline-block;font-size:11.5px;padding:1px 7px;border-radius:20px;vertical-align:1px}
.t-ok{background:#e8f5ec;color:#15803d;border:1px solid #bfe3cb}
.t-todo{background:#fdeee6;color:#c2410c;border:1px solid #f5cdb6}
.note{font-size:13px;color:#5c6672}
"""

BODY = """
<h1>Far 02 GroupA —— 按你 4 条要求改完的版本</h1>
<div class="sub">左边是 dincalculator 的 A4 打印卡（对照），右边两套是我们的墨水屏路书：
<b>6 页</b>（爬坡合并阈值 800 m）和 <b>7 页</b>（阈值 500 m，切得更细）</div>

<div class="card verdict">
<b>四条要求的落实情况</b>
<table>
<tr><th style="width:52px">#</th><th style="width:210px">你提的</th><th>已做的</th></tr>
<tr><td>1</td><td>4 个航点是<b>固定补给点</b>，不能用 GLU 代替，用 CP1/2/3</td>
<td>新增 <b>CP</b> 事件类型。屏幕上显示 <span class="mono">CP1 28.4</span> / <span class="mono">CP2 48.7</span> /
<span class="mono">CP3 82.1</span> / <span class="mono">CP4 137.0</span>（按里程重排编号）。<br>
<b>关键修正：CP 和 GLU 现在是两件事，不再二选一 ——</b>
CP = GPX 航点里作者标的真实补给点（有人有店）；GLU = 按里程推的"该吃胶了"提醒。两者同时出现在路书上。</td></tr>
<tr><td>2</td><td>GLU 参考网站的补给密度</td>
<td>GLU 单独用规则估算：基础间隔 <b>13 km</b>（对标网站的 12~15 km），
避开爬坡区间 / CP 前后 3 km / 转弯。本路线出 <b>8 个</b>，和网站的 8 次 gel <b>数量一致</b>。</td></tr>
<tr><td>3</td><td>爬坡调细，整体 6~7 页</td>
<td>合并阈值 1000→<b>800 m</b>、最小爬升 60→<b>30 m</b>：爬坡 <b>4 → 7 段</b>（6 页）；
再降到 500 m 是 <b>10 段</b>（7 页）。两版都给你，你挑。</td></tr>
<tr><td>4</td><td>转弯只留 5 条大弯</td>
<td>按<b>转角大小</b>排序取前 5，且彼此间隔 ≥8 km：<span class="mono">7.0 ← / 48.7 ↙ / 57.4 ↘ / 84.0 ↘ / 143.9 ↘</span>。
原来 8 条 → 5 条。</td></tr>
<tr><td>5</td><td>同一公里数合并成一行</td>
<td>已实现：<span class="mono">48.7 km  CP2 ↙</span>（补给点+拐弯合成一行）；
<span class="mono">82.1</span> 那个撞上爬坡结束公里数的 CP 顺延到 <span class="mono">82.5</span>。</td></tr>
</table>
</div>

<h2>一、三套并排看</h2>
<div class="row">
  <div class="col">
    <h3>网站（对照）</h3>
    <div class="meta">30 条事件 / A4 两页 / 0 转弯</div>
    <img class="webimg" src="__WEB__" alt="网站路书">
  </div>
  <div class="col">
    <h3>我们 · 6 页 <span class="tag t-ok">默认</span></h3>
    <div class="meta">25 事件 / 32 行 / 7 段爬坡 / 5 转弯 / 4 CP / 8 GLU</div>
    <div class="stack">__P6__</div>
  </div>
  <div class="col">
    <h3>我们 · 7 页（爬坡更细）</h3>
    <div class="meta">28 事件 / 38 行 / 10 段爬坡 / 5 转弯 / 4 CP / 8 GLU</div>
    <div class="stack">__P7__</div>
  </div>
</div>
<p class="note">两版只差爬坡的"切法"：6 页版把 30.2–33.6 和 34.2–48.6 当两段、
124.7–136.3 当一整段；7 页版在 34.2/35.7 与 36.1 之间、124.7/133.9 与 134.2 之间又切开一刀。
转弯、CP、GLU、中点完全一样。</p>

<h2>二、补给点对照</h2>
<table>
<tr><th style="width:150px">类型</th><th>点位（km）</th><th style="width:150px">数量</th></tr>
<tr><td><b>CP</b> 固定补给点<br><span class="note">GPX 航点，人工标注</span></td>
    <td class="mono">28.4　48.7　82.1　137.0</td><td>4 个</td></tr>
<tr><td><b>GLU</b> 该吃胶了<br><span class="note">按里程推的提醒</span></td>
    <td class="mono">13.0　25.2　52.0　65.0　91.0　104.0　117.0　142.6</td><td>8 个</td></tr>
<tr><td>网站 GEL<br><span class="note">它按 9h39 的时间/卡路里算</span></td>
    <td class="mono">18.4　32.3　45.2　68.2　94.7　114.4　126.6　140.0</td><td>8 个</td></tr>
</table>
<p class="note">点位不会完全一样 —— 网站按"骑行时间"铺（爬坡慢、平路快，所以间隔 12~26 km 不均匀），
我们按"里程"铺（间隔均匀）。<b>数量对上了（都是 8 个）</b>，节奏感一致。
如果你想让 GLU 也用"时间"逻辑，需要给 GPX 补一个配速/坡度速度模型（现在这份 GPX 没有时间戳）。</p>

<h2>三、爬坡颗粒度对照（看你偏好）</h2>
<table>
<tr><th style="width:100px">里程带</th><th style="width:210px">网站（15 段）</th><th>我们 6 页版（7 段）</th><th>我们 7 页版（10 段）</th></tr>
<tr><td>19–22</td><td class="mono">19.2 ▲4% 0.3km ★1<br>20.2 ▲4% 1.6km ★2</td><td class="mono">20.6 → 21.4　CLM 0.8 4.8%★★</td><td class="mono">20.6 → 21.4　CLM 0.8 4.8%★★</td></tr>
<tr><td>25–34</td><td class="mono">25.3 ▲5% 0.3km ★1<br>30.4 ▲5% 3km ★3</td><td class="mono">30.2 → 33.6　CLM 3.4 4.6%★★</td><td class="mono">30.2 → 33.6　CLM 3.4 4.6%★★</td></tr>
<tr><td>34–49</td><td class="mono">34.1 ▲6% 14.5km ★5</td><td class="mono">34.2 → 48.6　CLM 14.4 5.5%★★★★★</td><td class="mono">34.2 → 35.7　CLM 1.5 5.0%★★<br>36.1 → 48.6　CLM 12.5 5.7%★★★★★</td></tr>
<tr><td>70–73</td><td class="mono">70.1 ▲3% 1.1km ★1<br>72 ▲6% 1km ★2</td><td class="mono">72.0 → 72.8　CLM 0.8 4.9%★★</td><td class="mono">72.0 → 72.8　CLM 0.8 4.9%★★</td></tr>
<tr><td>74–82</td><td class="mono">74.1 ▲4% 1km ★2<br>76.2 ▲5% 1km ★2<br>77.7 ▲6% 0.9km ★1<br>78.9 ▲8% 3km ★4</td><td class="mono">76.2 → 79.4　CLM 3.2 4.0%★★<br>80.4 → 82.1　CLM 1.7 7.9%★★</td><td class="mono">76.2 → 77.2　CLM 1.0 4.3%★★<br>77.7 → 79.4　CLM 1.7 5.1%★★<br>80.4 → 82.1　CLM 1.7 7.9%★★</td></tr>
<tr><td>97–102</td><td class="mono">97.2 ▲4% 0.3km ★1<br>101.1 ▲6% 0.3km ★1</td><td>无（爬升 &lt; 30 m 或无对比）</td><td>无</td></tr>
<tr><td>121–136</td><td class="mono">121.4 ▲4% 0.4km ★1<br>124.4 ▲7% 6.8km ★4</td><td class="mono">124.7 → 136.3　CLM 11.6 5.5%★★★★★</td><td class="mono">124.7 → 133.9　CLM 9.2 5.7%★★★★★<br>134.2 → 136.3　CLM 2.1 5.4%★★★</td></tr>
</table>

<h2>四、这一轮改了哪些代码</h2>
<ul>
<li><code>tools/gpx_to_roadbook.py</code> —— 新增 CP（只来自航点，不去重、不估算）；
GLU 改成独立规则估算（避开爬坡/CP/转弯/中点，放不下就在 ±5 km 找空位）；
转弯按角度取前 N；新增 <code>merge_same_km()</code> 做同公里数合并；
新增 <code>--pages</code> 控制页数（超了自动把 GLU 间隔拉大）。</li>
<li><code>tools/roadbook.py</code> —— 新增 <code>TYPE_CP</code>；任何事件都能带 <code>arrow</code> 字段
（合并成一行时用）。</li>
<li><code>tools/preview_roadbook.py</code> —— 右列支持"文字 + 箭头"组合，箭头永远贴最右。</li>
<li><code>tools/roadbook_gen.py</code> —— 导出类型 6=cp、<code>dir=255</code> 表示不画箭头、新增 <code>n</code> 字段（CP 编号）。</li>
<li><code>02_Roadbook/02_Roadbook.ino</code> —— 同步支持 CP 与"文字+箭头"同一行。</li>
<li><code>02_Roadbook/roadbook.h</code> —— 已用 FAR02（25 事件）重新生成，和上面固件配套。</li>
<li><code>_archive/firmware/02_Roadbook_v1.7.ino</code> + <code>roadbook_v1.7.h</code> + <code>far02_v1.7.json</code>
—— 改固件前的旧版本存档（按你定的归档规则）。</li>
</ul>

<h2>五、还没做的</h2>
<div class="card">
<p><span class="tag t-todo">待你定</span> <b>选 6 页还是 7 页</b>：上面的图直接对比。
定下来我把它做成默认参数。</p>
<p><span class="tag t-todo">待你定</span> <b>转弯方向对不对</b>：5 条全是"急转"（转角 150°+，都是发夹弯）。
方向是从 GPX 轨迹的方位角几何反推的，山路上有可能把连续弯道误判。这个只能你实地骑一次验证。</p>
<p><span class="tag t-todo">未编译</span> 固件从 v1.6 到 v1.7 加了 CP 事件和合并行渲染，
<b>还没有编译过</b>（这台机器完整编译约 41.6 分钟）。版式你点头之后我再烧。</p>
</div>
"""


def imgs(folder, n):
    return "".join('<img src="%s" alt="第%d页">' % (b64(os.path.join(folder, "page_%02d.png" % i)), i)
                   for i in range(1, n + 1))


def main():
    html = (
        '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">\n'
        "<title>Far02 路书改版 —— 6 页 vs 7 页</title>\n"
        "<style>" + CSS + "</style></head><body><div class=\"wrap\">\n"
        + BODY.replace("__WEB__", b64(os.path.join(BASE, "web_p1.png")))
              .replace("__P6__", imgs(P6, 6))
              .replace("__P7__", imgs(P7, 7))
        + "\n</div></body></html>\n"
    )
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("written: %s  (%d bytes)" % (OUT, os.path.getsize(OUT)))


if __name__ == "__main__":
    main()
