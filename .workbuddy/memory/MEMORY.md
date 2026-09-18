# 项目：墨水屏骑行路书（Epaper / EinkRoadbook）

ESP32-S3 墨水屏骑行路书。目标：AI 骑行教练 + 路书（数据源 intervals.icu）。
**GitHub**：https://github.com/SeanFu2424/Epaper （私有，2026-09-11 建）

## 一、硬件（微雪 ESP32-S3-ePaper-1.54 **V2**，ESP32-S3-PICO-1-N8R8）
引脚全部来自官方仓库源码，**不要再猜**：

| GPIO | 信号 | 说明 |
|---|---|---|
| 6 | EPD_PWR | LOW=开 |
| 8/9/10/11/12/13 | BUSY/RST/DC/CS/SCK/MOSI | 非默认脚，须 `SPI.begin(12,-1,13,-1)` |
| **17** | **BAT_Control** | **HIGH=维持供电，LOW=断电关机** |
| **18** | **BAT_KEY / PWR** | 按下 = LOW |
| 0 | BOOT | 按下 = LOW |
| 4 | BAT_ADC | ADC1_CH3，200K/200K 分压 → **VBAT = 读数 × 2** |
| 39/40/41 | SD | CLK/MISO/MOSI（FAT32） |
| **47 / 48** | **I2C SDA / SCL** | RTC **PCF85063(0x51)** + SHTC3(0x70) |

- 面板 **GDEY0154D67** 200×200，驱动 **SSD1681**，GxEPD2 类 `GxEPD2_154_GDEY0154D67`
- V1/V2 引脚相同，仅 PSRAM 不同（V2=OPI）；**无 RST 按键**；**无电源管理芯片**（不是 IP5306）——电源键是固件自锁
- FQBN：`PSRAM=opi, FlashSize=4M, PartitionScheme=default`
- **PCF85063**：0x04 起 7 字节 = 秒/分/时/日/周/月/年（BCD），秒 bit7 = OS 掉电标志；
  掩码 秒&0x7F 分&0x7F 时&0x3F 日&0x3F 月&0x1F

## 二、铁律（违反必出故障）
1. `setup()` 第一行必须 `pinMode(17,OUTPUT); digitalWrite(17,HIGH);`
   漏掉 → **插 USB 正常，电池模式一按松手就白屏**。深睡前 `gpio_hold_en(17)` + `gpio_deep_sleep_hold_en()`
2. `attachInterrupt` 后**立刻同步** `isDown/sawRelease/downMs/队列`（否则手还按着时长按判定瞬间成立 → "开机后马上关机"）
3. 判断"有没有按键"不能读瞬间电平，要开**采样窗口**（否则短按反而能开机）
4. 别动 Arduino IDE Tools 设置；别让清理工具碰 `Arduino15` / `Documents\Arduino`

## 三、环境（这台机器是最大瓶颈）
- Arduino IDE 2.x + esp32 core 3.3.11；**装板卡包必须走 GitHub**（国内直连被掐）
- **实测完整编译 = 41.6 分钟**，这是基线不是故障；arduino-cli 每次全量重编（无增量缓存）
- 省时间三件：① `tools/trim_gxepd2.py` 给 GxEPD2 瘦身（104→1 个 .cpp）② 杀软排除目录 ③ **排版先用预览器定稿再烧**
- arduino-cli 路径：`%LOCALAPPDATA%\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe`
- 上传**不需按 BOOT**；离线装包 `_环境/download_esp32.ps1`
- **本机 GitHub 网络**：Steam++ 把 github 域名劫持到 127.0.0.1 反代 → git 报
  `CRYPT_E_NO_REVOCATION_CHECK`。**解法：`git config --global http.sslBackend schannel`**；curl 加 `--ssl-no-revoke`
  ⚠️ bash 工具默认沙箱**会断网**，联网命令要 `dangerouslyDisableSandbox`
- 本机已装 git 2.55 + GitHub Desktop 3.6.5，GitHub 凭据已存在凭据管理器

## 四、工作方式约定（用户明确立的规矩）
1. 遇到问题**先找官方例程**，不凭经验推演；优先找 GitHub 现成方案
2. 用户**软硬件零基础**：step-by-step checklist，坑点提前标，**先结论再展开**
3. 硬件行为异常**先读官方源码/原理图**，不要凭经验推断芯片型号
   （最大教训：连续 6 轮基于虚构的"IP5306"给方案）
4. **输出必须分「事实 / 实测 / 推断」三档**：推断要显式标"未验证"并给可证伪现象；
   **绝不从上下文模糊复述**用户的训练数据、路线、功率、身体指标
5. **改固件前先归档旧版本**（2026-09-11 起）：把当前 `02_Roadbook.ino` + `roadbook.h` + `fuzhishan.json`
   复制成 `_archive/firmware/*_vX.Y.*` 再动手。原因：Arduino 要求 `.ino` 在**同名文件夹**里、
   一个 sketch 只能有一个主 `.ino`，不能原地"重命名保留"。当前可烧录的永远是 `02_Roadbook/02_Roadbook.ino`。

## 五、官方例程索引（`waveshareteam/ESP32-S3-ePaper-1.54`，本地无副本，走 GitHub raw）
`07_BATT_PWR_Test`（PWR 键开关机，含 `src/button_bsp.c`）· `02_I2C_PCF85063` / `11_RTC_Sleep_Test`（RTC、深睡）·
`01_ADC_Test`（电池 ADC，`adc_bsp.cpp`）· `04_SD_Card` · `09_LVGL_V8_Test/user_config.h`（引脚总表）

**关键结论**：官方例程**没有"软件长按开机"**——出厂"要长按"只是硬件供电→固件锁电的时间差（LVGL 初始化 1~2s）。
我们 setup 只要 0.4s 所以短按也能开；想做成"长按才开机"**必须自己主动断电**。

## 六、项目资产
`00_HelloScreen/`（第 0 步里程碑，已验证，**不要改坏**）· `01_Paging/`（第 1 步分页）·
`02_Roadbook/`（第 2 步路书，**当前活跃**）· `tools/roadbook.py`（渲染核心，PC 与固件共用规则）·
`tools/preview_roadbook.py` / `preview_paging.py`（预览器）· `tools/roadbook_gen.py`（JSON→C 头文件，
**唯一"跟 JSON 有关"的代码**）· `tools/gpx_to_roadbook.py`（GPX→路书 JSON，阶段 A 核心）·
`02_Roadbook/sample.json`（示例路线，**是我编的占位，非用户真实路线**）·
`02_Roadbook/far02.json`（用户真实路线 Far02，150km）· `第0/1/2步_*.md`（三份教程）·
`_设计/`（调研文档 + 对比 HTML + `roadbook_variants/` 备选版式）· `_archive/`（旧 V1 工具链 + 固件归档）·
读 PDF 用 `.workbuddy/pylibs/`（pypdf + pymupdf，`PYTHONPATH=.workbuddy/pylibs`）

## 七、Roadbook V1 规范（v1.7）
`GPX →gpx_to_roadbook.py→ JSON →roadbook_gen.py→ roadbook.h →02_Roadbook.ino→ GxEPD2`
- **7 事件**：`turn/glu/climb/danger/finish/halfway/**cp**`，**爬坡唯一占两行**
- 🔴 **CP 与 GLU 是两件事，不是二选一**（2026-09-18 用户纠正）：
  - **CP1..CPn** = **固定补给点**，只来自 GPX 航点（骑手人工标的，有人有店必须停）
  - **GLU** = **"该吃胶了"的提醒**，按**骑行时间**估算（不一定有店）
  - 两者**同时出现在路书上**；GLU 与 CP 同点则 GLU 丢弃
- 🔴 **GLU 按"时间"铺，不按里程**（2026-09-18 用户反馈"与网站偏差大"后改）：
  实质是**生理节律**（每 30~45 分钟补一次），不是每 13km 一次。
  `time_axis()` 用坡度→速度经验表把 GPX 换算成时间轴 →
  `--fuel-mode time`（默认）`--fuel-interval 40`（分钟）。
  回到旧行为：`--fuel-mode km --fuel-interval 13`（两侧 diff 完全一致）
  ⚠️ 速度表是**经验值不是实测**（平路 32 / 5% 坡 18 / 9% 坡 11.5 km/h）；
  Far02 全程算 5h34，网站页眉 9h39（后者大概含休息）。可用 `--speed-scale` 整体缩放
- 🔴 **`--glu-in-climb` 放行爬坡块内部**（同上）：坡内的 GLU 标 `sub=1`，
  屏幕左列缩进 8px 表示"在这块坡里面吃"。
  不开的话，长爬坡段（Far02 的 30.2~48.6 = 18.4km 连续坡 ≈ 1 小时）
  **一个提醒都放不下** —— 这就是旧版出现 79 分钟空档的根因
- 🔴 **同一公里数合并成一行**（用户要求）：同点的转弯折成主事件的 `arrow` 字段，
  屏幕显示 `48.7 km  CP2 ↙`；撞上"爬坡结束公里数"的非爬坡事件顺延 0.4km。
  → 任何事件都可带 `arrow`；固件里 `dir` 语义 = **0..7 画箭头 / 255(`RB_DIR_NONE`) 不画**
- 爬坡第二行 = **结束公里数**（缩进 8px，**不带 " km" 单位**）+ **坡度%** + **难度星级**
- 星级规则抄 dincalculator：1★3-4% / 3★≥5%&≥2km / 4★≥7%&≥3km / 5★≥9% 或 ≥7km
- **GLU 不再区分胶/水**（H₂O 已按用户要求删除）
- 页眉 y16 基线 / y22 横线；正文基线 **38..162**；每页最多 **6 行**（爬坡算 2）
- 页脚：横线 **y=174**，状态栏基线 **y=190**，左时间 / 右电量
- 字体 **FreeSansBold9pt7b**（yAdvance 22），行距自适应 24~38 + 垂直居中；边距 6px
- 位图两套（字体只有 ASCII 0x20-0x7E）：箭头 **16×16** / 星 **13×13**（内径比 0.45，间距 0）。
  13px 是**星的可辨认下限**（12px 尖角糊），所以挤的时候不能靠缩星解决
- 🔴 **位图打包必须每行补齐到整字节**（`stride=(size+7)//8`）：`drawBitmap` 按
  `ceil(w/8)` 字节取行。16px 箭头是 8 的倍数所以没事，13px 星星不补就整体错位
- **右列排版规则（预览器与固件同一套）**：星贴最右、坡度%写星左边（间距 4）；
  箭头贴最右、文字写箭头左边（间距 6）；再往左才是左列的公里数
- 定点整数（km×10/length×10/elev/grade×10 + stars + sub），零浮点；`PROGMEM` 是空宏
- **事件结构体字段**：`type / dir / km / length / elev / grade / stars / n / sub`
  （`sub=1` → 左列缩进 8px，目前只有"坡内的 GLU"用；爬坡第二行的缩进是固件硬编码的）
- **9pt Bold 是两列布局极限**：12pt 下 `108.9 km`+`DANGER`=196px>188px（已试过并回退）
- 不显示当前公里数；右对齐必须 `getTextBounds()` 测宽（非等宽字体手打空格是假的）
- 不上 ArduinoJson（V2 才上）：省编译时间 + Flash
- `roadbook.h` 最新由 **far02.json** 生成（FAR02，25 事件，含 CP/合并行）

### 参数速查（`gpx_to_roadbook.py`）
| 参数 | 默认 | 说明 |
|---|---|---|
| `--climb-merge` | 800 m | 相邻爬坡间隔小于此值就合并。1000→4段 / 800→7段 / 500→10段（Far02） |
| `--min-gain` | 30 m | 爬坡最小爬升，不够就丢 |
| `--climb-window` | 250 m | 坡度计算的前向窗口 |
| `--max-turns` | 5 | 最多保留几个转弯（按转角从大到小挑） |
| `--turn-spacing` | 8 km | 保留的转弯之间最小间隔 |
| `--fuel-mode` | **time** | `time`=按骑行时间铺（推荐）/ `km`=按里程均铺（旧行为） |
| `--fuel-interval` | 40 (time) / 13 (km) | GLU 间隔。**单位随模式变**：time=分钟，km=公里 |
| `--speed-scale` | 1.0 | time 模式下速度模型的整体缩放（0.9 = 比经验表慢 10%） |
| `--glu-in-climb` | 关 | 允许 GLU 落在爬坡块内部（屏幕缩进显示）。不开则长爬坡段没有提醒 |
| `--fuel-tail` | 4 km | 终点前多少 km 内不铺 GLU |
| `--fuel-spread` | 5 km | 目标点放不下时前后找空位的范围 |
| `--fuel-min-gap` | 7 km | 两个 GLU 之间至少隔多远 |
| `--edge-gap` | 1.2 km | 事件与爬坡区间/其它事件的最小间距 |
| `--cp-gap` | 3 km | GLU 离 CP 至少多远 |
| `--pages` | 6 | 目标页数，超了自动把 GLU 间隔 ×1.2 重来 |

生成命令（Far02 6 页版）：
```bash
python tools/gpx_to_roadbook.py "Far+02+GroupA.gpx" --name FAR02 --pages 6 --out 02_Roadbook/far02.json
python tools/preview_roadbook.py 02_Roadbook/far02.json
python tools/roadbook_gen.py 02_Roadbook/far02.json      # -> 02_Roadbook/roadbook.h
```

## 八、踩过的坑
1. `getTextBounds()` 量的是**当前字体**，在 `setFont()` 之前调用会拿到内置 5×7 宽度 → 低估近一半
   → 溢出换行压下一行。**正解：用字体表 `xAdvance` 自己算宽 + `setTextWrap(false)`**
2. 爬坡两行必须与其它行**等距**，否则块高与排版假设对不上、底部又空一块
3. 按键**不能轮询**（全刷 2s 里 loop 卡在 nextPage），必须 GPIO 中断 + **按下即排队**
4. 局部刷新**残影不可接受**（用户实测），用全刷
5. 预览器行距自检要追踪 `min_gap`（**允许负数**），只在 ov>0 时更新会算出假数字
6. **位图打包要按行补齐到整字节**（`drawBitmap` 的要求）。原来按 8bit 连续打包，
   16×16 箭头因为是 8 的倍数看不出问题；13×13 星星直接整体错位 ——
   **PC 预览用的是未打包像素，所以这个错只有烧进板子才会暴露**（最贵的一种 bug）
7. **爬坡区间是"事件禁区"**：爬坡占两行、第二行写的是**结束公里数**，所以任何
   落在 `(km, km+length)` 内的事件都会被排到爬坡块后面显示 → **数字倒挂**
   （真实案例：`76.2 CLM 3.2 / 79.4 ★★` 后面跟 `77.7 HALFWAY`）。
   中转点、转弯、补给点都要过 `_in_climb()` 这一关。
   **顺带**：HALFWAY 原来"从真中点一路 +0.4 往后找"的写法有 bug，它会跨过爬坡起点
   钻进区间内部；改成"±8km 撒候选→过滤禁区→取离真中点最近"才对
8. **爬坡的 `km` 和 `length` 不能各自 round**：屏幕上的"结束公里数"是 `km + length`
   反算的（`roadbook.event_rows` / 固件同款），两边各自四舍五入会差 0.1 km
   （`30.2+18.3=48.5`，真值 `48.5578→48.6`；Far02 上两处踩中）。
   **正解：先 `end = round(km + length_km, 1)`，再 `length = round(end - km, 1)` 反推**，
   保证屏幕上的 `起点+长度` 恒等于终点。
9. **和 dincalculator 对账的结论（Far02 实测）**：同一份 GPX 两边总距离/总爬升完全一致，
   差异只在口径 —— 网站 route card = **15 条坡 + 13 处补给，零转弯**（按时间/卡路里铺补给）；
   我们（v1.7）= 7 条坡 + 4 个 CP + 8 个 GLU + 5 条大弯。
   星级规则两边是同一套，差的是"喂进去的段"
10. **别把"有 wpt 就用 wpt"当成"CP 和 GLU 二选一"**（2026-09-18 用户纠正）：
    CP 是 GPX 里人工标的固定补给点，GLU 是算法推的"该吃胶了"，**两者要在同一张路书上并存**。
    早先的实现把航点当"补给点来源"，有航点就完全不铺 GLU → 150km/9.5h 只 4 个补给点，明显偏少
11. **GLU"与网站偏差大"的真因是铺点依据不同，不是坐标算错**（2026-09-18 用户反馈）：
    网站按**时间**铺（里程间隔 13.9/12.9/23.0/26.5/19.7/12.2/13.4 忽长忽短，
    换算成时间却是 30/44/41/59/37/29/40 分钟）；我们按**里程**均铺 13km，
    结果是时间间隔 25/**78**/18/58/24/23/**68** 分钟 —— 平路补太勤、爬坡补太晚。
    **对表要看"时间轴"而不是"里程轴"**：里程均匀 ≠ 节奏均匀
12. **"爬坡区间禁放事件"这条规则会吃掉补给提醒**（同上，同日发现）：
    爬坡块占两行且第二行印"结束公里数"，块内插事件会倒挂 —— 这规则本身没错，
    但 Far02 有 30.2~48.6 一整段 **18.4km 连续爬坡（≈1 小时）**，
    于是这一小时里**一个提醒都放不下**（79 分钟空档就是这么来的）。
    解法 = `--glu-in-climb` + `sub` 缩进字段，让坡内 GLU 以"从属"姿态显示

## 九、已知不完美
- 渲染规则**两份实现**（C 在 `02_Roadbook.ino`，Python 在 `tools/roadbook.py`）靠手抄对齐
- 电量曲线 3.3V=0% ~ 4.15V=100% 是**按常见锂电拟的，非官方值**
- PCF85063 断电保持**尚未实测**；固件用编译时刻兜底 + 串口 `T2026-09-11 11:35:00` 手动对时
- **转弯方向未经验证**：5 条大弯全被几何判成"急转"（转角 150°+，实际是发夹弯），
  方向靠 GPX 方位角反推，山路上可能把连续弯误判，**需要用户实地骑一次核对**
- **GLU 的速度模型是经验值不是实测**（平路 32 / 5% 坡 18 / 9% 坡 11.5 km/h）：
  它算 Far02 全程 5h34，网站页眉写 9h39。绝对时间可能偏快，
  但"爬坡段提醒变密"这个**相对分布**是对的；用户可用 `--speed-scale` 校准
- **坡内 GLU 会让屏幕出现"48.6 后面跟 43.4"**（靠缩进表达从属）。
  是否接受这个读法**待用户确认**；不接受就只能接受长坡中途没有提醒
- 读 PDF 的库装在 `.workbuddy/pylibs/`（pypdf / pymupdf），用 `PYTHONPATH=.workbuddy/pylibs` 调用
