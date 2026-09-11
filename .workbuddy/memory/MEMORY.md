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

## 五、官方例程索引（`waveshareteam/ESP32-S3-ePaper-1.54`，本地无副本，走 GitHub raw）
`07_BATT_PWR_Test`（PWR 键开关机，含 `src/button_bsp.c`）· `02_I2C_PCF85063` / `11_RTC_Sleep_Test`（RTC、深睡）·
`01_ADC_Test`（电池 ADC，`adc_bsp.cpp`）· `04_SD_Card` · `09_LVGL_V8_Test/user_config.h`（引脚总表）

**关键结论**：官方例程**没有"软件长按开机"**——出厂"要长按"只是硬件供电→固件锁电的时间差（LVGL 初始化 1~2s）。
我们 setup 只要 0.4s 所以短按也能开；想做成"长按才开机"**必须自己主动断电**。

## 六、项目资产
`00_HelloScreen/`（第 0 步里程碑，已验证，**不要改坏**）· `01_Paging/`（第 1 步分页）·
`02_Roadbook/`（第 2 步路书，**当前活跃**）· `tools/roadbook.py`（渲染核心，PC 与固件共用规则）·
`tools/preview_roadbook.py` / `preview_paging.py`（预览器）· `tools/roadbook_gen.py`（JSON→C 头文件，
**唯一"跟 JSON 有关"的代码**）· `02_Roadbook/sample.json`（示例路线，**是我编的占位，非用户真实路线**）·
`第0/1/2步_*.md`（三份教程）· `_archive/`（旧 V1 工具链）

## 七、Roadbook V1 规范
`sample.json → roadbook_gen.py → roadbook.h → 02_Roadbook.ino → GxEPD2`
- 5 事件：`turn/glu/climb/danger/finish`，**爬坡唯一占两行**
- 页眉 y16 基线 / y22 横线；正文基线 **38..162**；每页最多 **6 行**（爬坡算 2）
- 页脚：横线 **y=174**，状态栏基线 **y=190**，左时间 / 右电量
- 字体 **FreeSansBold9pt7b**（yAdvance 22），行距自适应 24~38 + 垂直居中；边距 6px
- 箭头 **16×16 自制位图**（字体只有 ASCII 0x20-0x7E）；爬坡第二行缩进 8px 显示结束公里数
- 定点整数（km×10/length×10/elev/grade×10），零浮点；`PROGMEM` 是空宏
- **9pt Bold 是两列布局极限**：12pt 下 `108.9 km`+`DANGER`=196px>188px（已试过并回退）
- 不显示当前公里数；右对齐必须 `getTextBounds()` 测宽（非等宽字体手打空格是假的）
- 不上 ArduinoJson（V2 才上）：省编译时间 + Flash

## 八、踩过的坑
1. `getTextBounds()` 量的是**当前字体**，在 `setFont()` 之前调用会拿到内置 5×7 宽度 → 低估近一半
   → 溢出换行压下一行。**正解：用字体表 `xAdvance` 自己算宽 + `setTextWrap(false)`**
2. 爬坡两行必须与其它行**等距**，否则块高与排版假设对不上、底部又空一块
3. 按键**不能轮询**（全刷 2s 里 loop 卡在 nextPage），必须 GPIO 中断 + **按下即排队**
4. 局部刷新**残影不可接受**（用户实测），用全刷
5. 预览器行距自检要追踪 `min_gap`（**允许负数**），只在 ov>0 时更新会算出假数字

## 九、已知不完美
- 渲染规则**两份实现**（C 在 `02_Roadbook.ino`，Python 在 `tools/roadbook.py`）靠手抄对齐
- 电量曲线 3.3V=0% ~ 4.15V=100% 是**按常见锂电拟的，非官方值**
- PCF85063 断电保持**尚未实测**；固件用编译时刻兜底 + 串口 `T2026-09-11 11:35:00` 手动对时
