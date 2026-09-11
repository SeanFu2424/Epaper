# GPX → 路书：现成项目调研与技术方案

> 目标：把一条 GPX 变成墨水屏上 **5~10 条提示点**的路书（cue sheet）。
> 调研日期：2026-09-11。标注约定：**事实** = 我查到并核对的；**推断** = 未验证，给了证伪方法。

---

## 一、结论先行

| 问题 | 结论 |
|---|---|
| 有现成工具能直接用吗？ | **没有**。最接近的 `gpx-to-markdown` 输出法语、依赖汽车 profile，且必须改成我们的输出格式 |
| 该抄哪个？ | **算法抄 `nbareil/gpx-to-markdown`；转向判断升级用 BRouter** |
| 爬坡能自动吗？ | ✅ 能，且可靠。参考 `PyAscent` 的分级思路 |
| 转向能自动吗？ | 🟡 **纯几何只能算角度**；**要区分"真路口"和"马路自己拐弯"必须靠路网数据** → BRouter |
| 要写多少代码？ | **约 300 行 Python**，新增 1 个脚本，复用现有 `roadbook_gen.py` 之后的所有环节 |
| 从 200 个点砍到 8 个的关键 | **丢掉所有 `C`（continue）类型** —— BRouter 的 voice hint 天生就区分了"直行经过路口"和"道路弯曲" |

---

## 二、调研到的现成项目（事实，均已核对 README）

### ① nbareil/gpx-to-markdown ⭐ 最接近，抄它

`https://github.com/nbareil/gpx-to-markdown` · Python 单文件 · 输出 Markdown

**它已经实现的（正是我们要的）：**
- 转弯检测（角度 > 80°）
- **转弯聚类**（200m 内的转弯合并成一个）
- **转弯最小间距**（120m）
- **轨迹简化**（Douglas-Peucker，容差 20）
- 爬坡检测（坡度 ≥ 4%、按 8km/h 估算耗时 > 3 分钟）
- OSRM 地图匹配补路名 + Overpass 补 POI

**它踩过的坑（我们直接继承参数）：**
```
--turn-angle          80    角度阈值
--turn-min-spacing    120   两点最小间距(米)
--turn-cluster-radius 200   聚类半径(米)
--simplify-tolerance  20    简化容差
--min-grade            4    爬坡最小坡度%
--climb-min-minutes    3    爬坡最小时长
```

**不能直接用的原因：**
- ❌ 输出**硬编码法语**（`Tourner à droite sur...`）
- ❌ OSRM 默认 profile 是 **`driving`**（公开 demo 服务只有汽车 profile）→ 对自行车路名/小径不准
- ❌ README 自述 "100% vibe coded"，是个人项目，不适合当依赖

**→ 结论：抄算法，不改它。**

### ② JCBucio/PyAscent — 爬坡分级参考

`https://github.com/JCBucio/PyAscent` · Streamlit 网页应用 · MIT

- 爬坡判定：平均坡度 ≥ 3%、爬升 ≥ 20m
- **按环法标准分级**：HC / Cat1 / Cat2 / Cat3 / Cat4
- 只做爬坡，**不做转向** → 只能参考爬坡部分

### ③ peyronth/stage-profile-maker — 前端路线参考

`https://github.com/peyronth/stage-profile-maker` · TypeScript NPM 包 + Vue 网页 · GPL-3.0

- 自动爬坡检测 + 高程剖面渲染 + 可编辑 waypoint
- 有环法/环意/环西的样式预设
- 如果以后走网页路线，这个的前端渲染可以参考

### ④ BRouter ⭐⭐ 关键拼图：解决"哪些转弯是真的"

`http://brouter.de/brouter` · Java · 开源 · **离线路由引擎，基于 OSM**

**为什么它重要**（这是整份调研最关键的一点）：

> 纯几何算角度，你得到的是一堆"马路自己拐的弯"。BRouter 的转向判断是
> **拿本路口的其他道路（"bad ways"）做比较**——它知道这是个真路口还是条弯道。
> 官方文档原话：*"an almost 90 degree hint can become 'sharp right turn'
> if another way is at 110 degrees"*，以及 *"show 'continue' only if the way
> crosses a higher priority way"*。

**它有完整的自行车 profile**（`trekking` / `fastbike` / `gravel` / MTB 等），
不像 OSRM 公开服务只有汽车。

**它的提示类型可以直接映射到我们的箭头位图**：

| BRouter hint | 含义 | 我们的处理 |
|---|---|---|
| `C` | continue（直行） | **丢弃** ← 砍掉 80% 噪音就靠这个 |
| `TL` / `TR` | 左转 / 右转 | 左/右箭头 |
| `TSLL` / `TSHL` | 稍左 / 急左 | 稍左/急左箭头 |
| `TSLR` / `TSHR` | 稍右 / 急右 | 稍右/急右箭头 |
| `KL` / `KR` | 靠左 / 靠右（岔路） | 左/右箭头 + "岔路" |
| `RNDB` / `RNLB` | 环岛 / 环岛左 | 需新画一个环岛图标 |
| `TU` / `TLU` | 掉头 | 掉头箭头 |

**接入方式（事实）**：它是**免费的 HTTP API，不需要 key**：
```
https://brouter.de/brouter?lonlats=...&profile=trekking&format=gpx
```
（`bikerouter.de` 只是前端，API 在 `brouter.de`）

**⚠️ 待验证（推断）**：把整条 GPX 轨迹喂给 BRouter 做"track-to-route"的具体做法。
我的理解是**先简化轨迹到 ~200 个点，再当 via 点传进去**（URL 长度限制），
但**我没有实测过**。如果这条成立，你会看到返回的 GPX 里带 `<rtept>` 提示点；
如果不成立（比如报错/返回空），回退到方案 A（纯几何）。

---

## 三、技术方案：分两步走，先离线后联网

```
GPX 文件
   │
   ├─【阶段 A · 离线纯几何】tools/gpx_to_roadbook.py   ← 先做这个
   │     gpxpy 解析 → 累积距离 → 高程平滑 → 爬坡检测
   │                            → 转弯检测(角度+聚类) → 排序筛选
   │     输出：sample.json（复用现有格式，后面零改动）
   │
   └─【阶段 B · 联网增强】同一个脚本加 --brouter 开关
         简化轨迹 → 调 BRouter API → 拿 voice hints + 路名
         替换阶段 A 的转向判断（角度 → 真路口）
```

**为什么分两步**：阶段 A **零联网、零 API、马上能看到效果**，
可以先验证"5~10 个点"这个密度目标能不能达到。阶段 B 只是让转向更准、补上路名。

**整条链只新增一个脚本**：
```
GPX → 【gpx_to_roadbook.py 新增】→ sample.json → roadbook_gen.py【已有】
    → roadbook.h → 02_Roadbook.ino【已有】→ 墨水屏
```

### 🔴 关键算法点：高程必须平滑（最容易翻车的地方）

> 查到的原话（cyclingarchives 教程）：*"A naive point-to-point sum treats every
> tiny GPS jitter as real elevation change... **This is the single most common
> reason a homemade elevation-gain script disagrees with Strava or Garmin Connect**."*

GPX 的 `<ele>` 有 GPS/气压计噪声，逐点累加会算出**几百米根本不存在的爬升**。
**必须先滑动平均或简化后再算坡度**，否则爬坡检测全是假的。

### 参数起步值（先抄，再用真实路线校准）

| 参数 | 起步值 | 来源 |
|---|---|---|
| 转弯角度阈值 | 80° | gpx-to-markdown 默认 |
| 转弯聚类半径 | 200 m | 同上 |
| 转弯最小间距 | 120 m | 同上 |
| 轨迹简化容差 | 20 m | 同上 |
| 爬坡最小坡度 | 4% | 同上（PyAscent 用 3%） |
| 爬坡最小时长 | 3 min | 同上 |
| 爬坡分段长度 | 0.5 km（公路）/ 1 km（碎石） | cyclingarchives 教程 |

### 🔴 砍到 5~10 个点的真正规则（推断，需实测校准）

角度阈值**不足以**把 100km 砍到 8 个点。还需要一条**距离闸门**：

> 两个提示点间隔 < 3 km **且** 后一个不是大转弯（< 90°）→ 合并或丢弃

纸质路书的实际惯例（经验值，**未验证，需要你拿真实路线校准**）：
- 每 10~15 km 至少 1 个点
- 所有 > 90° 的转弯必留
- 所有爬坡必留
- 其余按"离上一个点多远"筛

**建议做成「密度档位」而不是写死**：`--density low / mid / high`
→ 分别约 8 / 15 / 30 个点，你先看效果再定。**别让脚本替你决定。**

---

## 四、补给逻辑（按你说的：时间 + 公里数 + 主要爬坡估算）

**不做 POI 查询**（GPX 和 OSM 都不知道你路过哪家便利店），只做**公式估算 + 间隔校验**。

### 骑行时间估算（经验公式，**待用你的真实数据校准**）

```
等效平路距离(km) = 实际距离 + 爬升(m) / 10
预估时长(h)     = 等效平路距离 / 均速(km/h)
```
例：100 km + 1000 m 爬升 → 等效 200 km → 按均速 25 km/h 约 8 小时。
（爬升/10 这个系数是骑行圈常用近似，**不是物理公式**）

### 补给节奏（经验值）

- 每 **45~60 分钟** 或每 **20~25 km** 一次（两者通常一致）
- 碳水约 **60 g/小时**

### 落点规则

1. **优先放在爬坡起点之前**（爬坡中不方便吃胶）
2. 其次放在长下坡之后的平路
3. 避开终点前 10 km

### V1 只做「校验」，不硬塞

脚本算出建议的补给公里数，**检查现有路书有没有覆盖**：
- 有 → 什么都不做
- 缺 → 在候选位置插一个 `glu` 事件，**并在预览器/串口里标成"建议"**
- 你人工确认后它才变成正式事件（因为只有你知道那里到底有没有店）

---

## 五、下一步（需要你拍板）

1. **先做阶段 A 吗？**（离线纯几何，一天能看到效果，不联网）
2. **给我一条真实 GPX** —— 没有它我上面所有参数都是纸上谈兵，也没法验证"5~10 个点"能不能达到
3. 密度档位默认给几档？（建议 low=8 / mid=15 / high=30）

---

## 附：事实 / 推断 分档

**事实（已核对 README / 官方文档）**
- 上述 4 个项目的功能、参数默认值、许可证
- BRouter 用"bad ways 比较"生成转向提示；提示类型表；API 免费无 key
- gpxpy 是 Python 解析 GPX 的标准库，自带 `get_points_data()` / `get_uphill_downhill()`
- 高程噪声是自建脚本与 Strava/Garmin 数据不一致的最常见原因

**推断（未验证，已给证伪方法）**
- BRouter 能否用简化轨迹做 track-to-route → 跑一次看返回 GPX 里有没有 `<rtept>`
- 5~10 个点是否够一条 100km 路线 → 拿真实路线跑一次看密度是否可接受
- 距离闸门 3km / 角度 90° 这两个阈值 → 预览器上看效果调
- 补给公式里的「爬升/10」系数 → 用你自己的历史骑行数据回归校准
