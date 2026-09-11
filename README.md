# 墨水屏骑行路书 · Epaper Roadbook

把一条骑行路线的关键节点（哪里转弯、哪里有坡、哪里有补给、哪里危险）渲染成一张 **200×200 黑白墨水屏**上的**事件清单**，按键翻页，电池供电、随手揣兜里。最终目标是接上 `intervals.icu` 的数据，做「AI 骑行教练 + 路书」的一体化设备。

> 面向 **软硬件零基础** 的从零实践项目，每一步都有配套中文文档（见下方「三步走」）。

---

## 硬件

| 项目 | 规格 |
|---|---|
| 开发板 | 微雪 **ESP32-S3-ePaper-1.54 V2**（ESP32-S3-PICO-1-N8R8，8M Flash + 8M PSRAM） |
| 屏幕 | **GDEY0154D67**，200×200 黑白墨水屏，驱动 IC **SSD1681**（支持局部刷新） |
| 驱动库 | [GxEPD2](https://github.com/ZinggJM/GxEPD2)，驱动类 `GxEPD2_154_GDEY0154D67` |
| 开发环境 | Arduino IDE 2.x + esp32 core **3.3.11** |
| 板卡选项 | `PSRAM=opi`、`FlashSize=4M`、`PartitionScheme=default` |

### 引脚（已从官方仓库源码核实，**不是**默认脚，SPI 必须重映射）

| GPIO | 信号 | 说明 |
|---|---|---|
| 6 | EPD_PWR | 屏幕电源，**LOW = 开** |
| 8 / 9 / 10 / 11 / 12 / 13 | BUSY / RST / DC / CS / SCK / MOSI | 屏幕 SPI |
| **17** | **BAT_Control** | **电池供电自锁：HIGH = 维持供电，LOW = 断电关机** |
| **18** | **BAT_KEY（PWR 键）** | 按下 = LOW |
| 0 | BOOT | 上电按住进下载模式 |
| 4 | BAT_ADC | 电池电压采样（ADC1_CH3，200K/200K 分压 → VBAT = 读数 ×2） |
| 39 / 40 / 41 | SD | CLK / MISO / MOSI（FAT32） |
| **47 / 48** | **I2C SDA / SCL** | **RTC（PCF85063，地址 0x51）+ SHTC3 温湿度** |

> ⚠️ **铁律**：`setup()` 第一行必须是 `pinMode(17, OUTPUT); digitalWrite(17, HIGH);`
> 漏掉的话症状是「插 USB 一切正常，电池模式一按松手就白屏」——因为没有电源管理芯片，
> 电源键是**固件自锁**的，不是硬件锁存。

---

## 目录结构

```
00_HelloScreen/     第 0 步 · 点亮屏幕 + 电池开关机（已验证的里程碑，不要改坏）
01_Paging/          第 1 步 · 长文本自动分页 + 按键翻页
02_Roadbook/        第 2 步 · 路书事件清单（当前活跃）
  ├─ 02_Roadbook.ino   固件：渲染模板 + 按键 + 电源 + RTC/电量状态栏
  ├─ roadbook.h        由 JSON 自动生成的 C 数组（不要手改）
  ├─ sample.json       路书数据源（人编辑这个）
  └─ preview/          渲染预览图
tools/              全部 PC 侧工具（渲染核心、生成器、预览器）
_archive/           旧 V1 路书工具链（SD 卡方案，翻页骨架可复用）
_环境/              Arduino 离线装板卡包的脚本（国内网络救急用）
第0/1/2步_*.md      三份配套中文教程
新电脑恢复指南.md    换机器时怎么把环境重新搭起来
```

---

## 核心设计：数据与渲染分离

```
sample.json  (人编辑路线)
    │  python tools/roadbook_gen.py sample.json
    ▼
roadbook.h   (C 结构体数组，定点整数、零浮点)
    │  #include
    ▼
02_Roadbook.ino  (纯模板：只管怎么画，不知道画了什么)
    ▼
GxEPD2 → 墨水屏
```

- **改路线** → 只改 `sample.json`，跑一次生成器，重新编译
- **改样式**（字体 / 行距 / 事件类型）→ 只改 `02_Roadbook.ino`，JSON 那侧一个字不用动
- 固件**不解析 JSON**（V1 刻意不上 ArduinoJson：省编译时间、省 Flash），
  真正"跟 JSON 有关的代码"只有 `tools/roadbook_gen.py` 一个文件

### V1 事件规范（5 种）

| 类型 | 含义 | 布局 |
|---|---|---|
| `turn` | 转弯 | 箭头位图 + 公里数（左） / 事件文字（右） |
| `glu` | 能量胶补给 | 同上 |
| `climb` | 爬坡 | **唯一占两行**：高度/坡度 + 第二行缩进显示**爬坡结束公里数** |
| `danger` | 危险 | 同 turn |
| `finish` | 终点 | 同 turn |

- 一页最多 **6 行**（爬坡算 2 行），爬坡块不跨页
- 页眉：路线名 + 横线；页脚：横线 + 左侧时间 / 右侧电量
- 字体 `FreeSansBold9pt7b`，行距在 24~38px 之间自适应并垂直居中
- 箭头是**自制 16×16 位图**（字体只覆盖 ASCII 0x20–0x7E，`↰↱←→` 这些符号系统里根本没有）

---

## 预览器：改排版零编译成本

这台开发机编译一次固件约 **40 分钟**，所以排版一律先在电脑上定稿再烧录。
预览器不是"模拟"排版，而是把固件那套规则**原样搬到 PC 上重跑**：

```bash
# 路书预览（页眉 / 正文 / 页脚全部还原）
python tools/preview_roadbook.py --time 14:32 --batt 86

# 长文本分页预览，还能试字体/行高/每页行数而不动固件
python tools/preview_paging.py --font FreeSans12pt7b --line-h 22 --lpp 7
```

输出在 `02_Roadbook/preview/`（单页 PNG + `contact_sheet.png` 拼版）和 `01_Paging/preview/`。

预览器带三个自动自检，报警就别急着烧：
`over=`（行超宽）、行距重叠（上下行压上了）、正文墨迹到页脚线的距离。

---

## 编译提示

- 装 esp32 板卡包**必须走 GitHub**，国内直连会被掐；`_环境/download_esp32.ps1` 是带断点续传 + SHA256 校验的离线方案
- 如果装了 Steam++ / Watt Toolkit 之类的 GitHub 加速工具，git 可能会报
  `CRYPT_E_NO_REVOCATION_CHECK`（证书吊销列表联不上），执行
  `git config --global http.sslBackend schannel` 即可
- 上传**不需要按 BOOT**（ESP32-S3 的 USB CDC 有自动下载电路）
- `tools/trim_gxepd2.py` 可以把 GxEPD2 的 104 个 `.cpp` 裁到只剩要用的 1 个，显著缩短编译时间（可逆）

---

## 已知限制 / 待办

- 渲染规则有 **两份实现**（C 版在 `02_Roadbook.ino`，Python 版在 `tools/roadbook.py`），靠手抄对齐；
  改一边忘了另一边，预览器就会骗人。（未来计划合并成单一数据源）
- 电量百分比曲线（3.3V=0% ~ 4.15V=100%）是**按常见锂电特性拟的，非官方标定值**
- PCF85063 能否断电保持走时**尚未实测**；固件会用「编译时刻」兜底，也支持串口 `T2026-09-11 11:35:00` 手动对时
- `02_Roadbook/sample.json` 里的路线数据是**占位示例**，非真实骑行路线
- V2 计划：从 SD 卡读 JSON，换路线不用重新编译（渲染器一行业不用改）

---

## 许可

个人项目，未附许可协议。如需引用请先联系作者。
