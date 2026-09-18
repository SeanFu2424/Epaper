# -*- coding: utf-8 -*-
"""把 网站 PDF 渲染图 + 我们的四页预览 拼成一个并排对比页（图片内嵌 base64，单文件可离线看）"""
import base64
import os

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(BASE), "Far02_网站路书_vs_我们的路书.html")
# 我们的四页预览图不在这里再存一份，直接用预览器输出的原件
OURS_DIR = os.path.normpath(os.path.join(BASE, "..", "..", "02_Roadbook", "preview"))


def b64(name, folder=None):
    with open(os.path.join(folder or BASE, name), "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


CSS = """
:root{--bg:#f5f6f8;--card:#fff;--ink:#1b1f24;--dim:#5c6672;--line:#dfe3e8;--bd:#e3b04b;--wa:#c2410c;--ok:#15803d}
*{box-sizing:border-box}
body{margin:0;padding:28px 22px 60px;background:var(--bg);color:var(--ink);
 font:15px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1060px;margin:0 auto}
h1{font-size:23px;margin:0 0 6px;letter-spacing:-.2px}
.sub{color:var(--dim);font-size:13.5px;margin-bottom:22px}
h2{font-size:17px;margin:34px 0 12px;padding-left:10px;border-left:4px solid #1b1f24}
h3{font-size:15px;margin:22px 0 8px;color:#242a31}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:14px 0;
 box-shadow:0 1px 2px rgba(16,24,40,.04)}
.verdict{background:#fff9ec;border:1px solid #f0d9a8;border-left:4px solid var(--bd)}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin:6px 0}
th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:#eef1f4;font-weight:600}
td.same{color:var(--ok);font-weight:600}
td.diff{color:var(--wa);font-weight:600}
.mono{font-family:ui-monospace,Consolas,"Cascadia Mono",monospace;font-size:12.5px}
.panes{display:flex;gap:22px;align-items:flex-start;flex-wrap:wrap}
.webimg{width:290px;border:1px solid var(--line);border-radius:6px}
.pages{display:flex;gap:8px;flex-wrap:wrap}
.pages img{width:186px;image-rendering:pixelated;border:1px solid var(--line);border-radius:4px;background:#fff}
.cap{font-size:12.5px;color:var(--dim);margin-top:8px}
ul{margin:8px 0 0 18px;padding:0}
li{margin:5px 0}
code{background:#eef1f4;border-radius:3px;padding:1px 5px;font-size:12.5px}
.tag{display:inline-block;font-size:11.5px;padding:1px 7px;border-radius:20px;vertical-align:1px}
.t-ok{background:#e8f5ec;color:#15803d;border:1px solid #bfe3cb}
.t-todo{background:#fdeee6;color:#c2410c;border:1px solid #f5cdb6}
.note{font-size:13.5px;color:#5c6672}
"""

BODY = """
<h1>Far 02 GroupA —— 网站路书 vs 我们的墨水屏路书</h1>
<div class="sub">网站 = dincalculator.com/bike/route-card 导出的 A4 打印卡 ｜ 我们 = <span class="mono">tools/gpx_to_roadbook.py</span> 生成的 200×200 四页</div>

<div class="card verdict">
<b>一句话结论</b><br>
两份路书出自 <b>同一份 GPX</b> —— 总距离 150.58 km、总爬升 +2728 m、终点 150.6 km 三项完全一致。
所以"公里数不一样"不是谁算错了，而是<b>两者的分段口径和信息定位不同</b>：<br>
网站是一张「<b>补给时刻表 + 爬坡难度表</b>」，通篇不告诉你往哪拐；<br>
我们是「<b>导航转弯 + 难度 + 真实补给点</b>」，要塞进 6 行/页的墨水屏里。
</div>

<h2>一、总览对照</h2>
<table>
<tr><th style="width:120px">项目</th><th style="width:260px">网站 dincalculator</th><th>我们的墨水屏路书</th><th style="width:78px">判定</th></tr>
<tr><td>总距离</td><td>150.6 km</td><td>150.58 km</td><td class="same">一致</td></tr>
<tr><td>总爬升</td><td>+2728 m</td><td>+2728 m（原始高程）</td><td class="same">一致</td></tr>
<tr><td>终点</td><td>150.6 FINISH</td><td>150.6 FINISH</td><td class="same">一致</td></tr>
<tr><td>预计用时</td><td>9h39（它自己的配速模型）</td><td>不算</td><td>—</td></tr>
<tr><td>爬坡条数</td><td>15 条</td><td>4 条</td><td class="diff">差 11</td></tr>
<tr><td>补给点数</td><td>13 处（8 次胶 + 5 次水）</td><td>4 处（全是胶）</td><td class="diff">差 9</td></tr>
<tr><td>转弯提示</td><td>0 条</td><td>8 条</td><td class="diff">只有我们有</td></tr>
<tr><td>过半提示</td><td>75.3 km</td><td>74.9 km</td><td class="diff">差 0.4</td></tr>
<tr><td>事件总数</td><td>30 条</td><td>18 条</td><td>—</td></tr>
<tr><td>载体</td><td>A4 打印 / 塑封</td><td>200×200 墨水屏，6 行/页，共 4 页</td><td>—</td></tr>
</table>

<h2>二、并排看</h2>
<div class="panes">
  <div>
    <img class="webimg" src="__WEB1__" alt="网站路书">
    <div class="cap">网站：单列长卡，A4 两页（第 2 页只有 FINISH 一行）</div>
  </div>
  <div>
    <div class="pages">__OURS__</div>
    <div class="cap">我们：200×200 四页，左→右 = 第 1~4 页</div>
  </div>
</div>

<h2>三、"公里数不一样"的四处根因</h2>

<h3>① 爬坡 —— 分段粒度不同（差异最大的一处）</h3>
<p>我们有两条硬规则：<b>相邻两段坡间隔小于 1000 m 就合并成一段</b>；<b>爬升不足 60 m 的小坡直接丢掉</b>。
网站基本不合并，小到 0.3 km / 4% 也要单列。于是同一条长坡，我们写 1 行，网站写 5 行。
注意两边「同一条坡」的<b>终点是对上的</b>（我们 48.6 / 网站 48.6），说明检测没跑偏，只是切得粗细不同。</p>
<table>
<tr><th style="width:100px">里程带</th><th>网站（15 条）</th><th>我们（4 条）</th></tr>
<tr><td>19 – 33 km</td><td class="mono">19.2 ▲4% 0.3km ★1<br>20.2 ▲4% 1.6km ★2<br>25.3 ▲5% 0.3km ★1<br>30.4 ▲5% 3km ★3</td><td>前两段爬升 &lt; 60 m 被丢弃；后两段被并入下一行</td></tr>
<tr><td>30 – 49 km</td><td class="mono">34.1 ▲6% 14.5km ★5</td><td class="mono">30.2 → 48.6　CLM 18.4　5.2% ★5</td></tr>
<tr><td>70 – 75 km</td><td class="mono">70.1 ▲3% 1.1km ★1<br>72 ▲6% 1km ★2<br>74.1 ▲4% 1km ★2</td><td>无（爬升均 &lt; 60 m）</td></tr>
<tr><td>76 – 82 km</td><td class="mono">76.2 ▲5% 1km ★2<br>77.7 ▲6% 0.9km ★1<br>78.9 ▲8% 3km ★4</td><td class="mono">76.2 → 79.4　CLM 3.2　4.0% ★2<br>80.4 → 82.1　CLM 1.7　7.9% ★2</td></tr>
<tr><td>97 – 102 km</td><td class="mono">97.2 ▲4% 0.3km ★1<br>101.1 ▲6% 0.3km ★1</td><td>无（爬升均 &lt; 60 m）</td></tr>
<tr><td>121 – 136 km</td><td class="mono">121.4 ▲4% 0.4km ★1<br>124.4 ▲7% 6.8km ★4</td><td class="mono">124.7 → 136.3　CLM 11.6　5.5% ★5</td></tr>
</table>
<p class="note">星级规则两边其实是同一套（都抄 dincalculator：≥5%&amp;≥2km→3★，≥7%&amp;≥3km→4★，≥9% 或 ≥7km→5★）。
差别只出在<b>喂进去的"段"不一样</b>：我们把 11.6 km 当一段（长度 ≥7 → 5★），网站切成 6.8 km（7% 但不够 7km → 4★）。</p>

<h3>② 补给点 —— 数据源根本不同（不是 bug）</h3>
<ul>
<li><b>我们</b>：这份 GPX 里作者自己标了 <b>4 个航点</b>（<span class="mono">固定补给点 / 补给点1 / 补给点2 / 补给点3</span>），
我们直接采信人工标注 → 28.4 / 48.7 / 82.1 / 137.0，间隔 20 / 33 / 55 km。</li>
<li><b>网站</b>：它拿不到航点，改成按 9h39 的骑行时间和卡路里推算，每 12~15 km 铺一个，
还区分 GEL（标 kcal、g carbs）和 H₂O（标 ml）→ 13 处。</li>
</ul>
<p>所以这 9 个点的差额，本质是「<b>哪里有店</b>」和「<b>什么时候该吃</b>」两件事，不是同一个量。
<span class="tag t-todo">待你定</span> 那 4 个航点是你亲手标的真实店铺位置，还是当时随手点的占位？若是后者，4 次补给撑 150 km / 9.5 h 偏少。</p>

<h3>③ 中点差 0.4 km</h3>
<p>网站把 150.6 ÷ 2 直接取 75.3。我们是"真中点 ±8 km 撒候选 → 剔除落在爬坡区间里的 → 取离真中点最近的"，
为了避开爬坡块落在 74.9。<b>两边都没错</b>，我们这条规则是为了防止屏幕上出现"公里数倒挂"。</p>

<h3>④ 转弯：网站压根没有</h3>
<p>dincalculator 的 route card 是一张「补给 + 难度」卡，通篇没有一个左右转符号。
我们有 8 条转弯，靠 GPX 轨迹的方位角几何反推——这是两套路书最本质的功能差别。</p>

<h2>四、顺带查出的两个真问题</h2>
<div class="card">
<p><span class="tag t-ok">已修</span> <b>爬坡结束公里数差 0.1 km</b><br>
屏幕上第二行的"结束公里数"是用 <code>起点 + 长度</code> 反算出来的。如果起点和长度各自先四舍五入，
相加就会和真实终点错开 0.1：<br>
<span class="mono">真实 30.2133 + 18.3444 = 48.5578 → 该显示 48.6，实际印成 30.2 + 18.3 = 48.5</span><br>
Far02 上踩到两处（<span class="mono">48.5 / 136.2</span>，正确值 <span class="mono">48.6 / 136.3</span>）。
已改成「先把终点取整，再用 终点−起点 反推长度」——现在 <span class="mono">km + length</span> 必然等于屏幕上的终点，读者能自己验算。</p>
<p style="margin-top:18px"><span class="tag t-todo">待你定</span> <b>同一公里数撞两行</b><br>
第 1 页出现两行 <span class="mono">48.7</span>（GLU 和 ↙ 转弯落在同一个点），第 3 页 <span class="mono">82.1</span> 也出现两次
（一次是爬坡的结束公里数，一次是 GLU）。数字没错，但屏幕上看着像重复。要不要错开 0.3~0.4 km，或者把它们合并成一行？</p>
</div>
"""


def main():
    ours = "".join(
        '<img src="%s" alt="我们的第%d页">' % (b64("page_0%d.png" % i, OURS_DIR), i)
        for i in (1, 2, 3, 4)
    )
    html = (
        '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">\n'
        "<title>Far 02 GroupA —— 网站路书 vs 墨水屏路书</title>\n"
        "<style>" + CSS + "</style></head><body><div class=\"wrap\">\n"
        + BODY.replace("__WEB1__", b64("web_p1.png")).replace("__OURS__", ours)
        + "\n</div></body></html>\n"
    )
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("written: %s  (%d bytes)" % (OUT, os.path.getsize(OUT)))


if __name__ == "__main__":
    main()
