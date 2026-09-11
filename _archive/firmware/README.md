# 烧录到 ESP32-S3

## 1. 装好 Arduino IDE

- 装 Arduino IDE 2.x
- 文件 → 首选项 → 附加开发板管理器网址：
  `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
- 工具 → 开发板 → 开发板管理器 → 搜 `esp32` → 装 Espressif Systems 的 3.x 包
- 库管理器搜 `GxEPD2` 装上；`Adafruit GFX` 通常自动依赖进来

## 2. 改引脚（重要！）

打开 `EinkRoadbook_V1.ino`，把顶部 **硬件配置** 段按你的板子实测填好：

| 宏 | 含义 | 怎么定 |
|---|---|---|
| `EPD_DRIVER_CLASS` | GxEPD2 驱动类（如 `GxEPD2_154_D67`） | 资料包 Demo 的 `#include` 行 |
| `EPD_CS / DC / RST / BUSY` | 屏幕四脚 | 资料包 Demo 里的 `GxEPD2_xxx(CS, DC, RST, BUSY)` 参数 |
| `EPD_SCK / EPD_MOSI` | SPI 时钟和数据 | 默认 18 / 23 多数一体板 OK；不对再改 |
| `BTN_NEXT / BTN_PREV` | 按键 GPIO | **必须 0-21**（S3 的 RTC GPIO 范围） |

`GPIO0` 是板上的 BOOT 键，**上电瞬间不能按住**，否则进下载模式。

## 3. 选板子参数

工具 → 开发板 → **ESP32S3 Dev Module**，然后：

- USB CDC On Boot: **Enabled**（S3 必开，否则串口看不到字）
- PSRAM: **OPI PSRAM**
- Flash Size: 8MB (64Mb)
- Flash Mode: QIO 80MHz
- Upload Mode: UART0 / Hardware CDC

## 4. 烧录

- 用数据 USB 线接板子
- 选对 COM 口 → 上传
- 烧录完打开串口监视器（115200）按 RESET，看到 "SD OK" / "page 1/37" 之类的日志就行

## 5. 拷路书到 SD

1. 渲染：`python tools/render_roadbook.py samples/roadbook_sample.json --out out`
2. 把 `out/roadbook.bin` 拷到 SD 卡根目录（文件名固定就是这个）
3. SD 卡插回板子

## 6. 按键交互

- NEXT 短按：下一页
- NEXT 长按 1.5s：上一页
- 30 分钟自动全刷（清残影），按键触发的是局部刷（更快、不闪）

## 7. 故障排查

| 现象 | 处理 |
|---|---|
| 串口无输出 | USB CDC On Boot 没开 / 数据线不带数据 / 按 RESET |
| 上传卡 `Connecting...` | 按住 BOOT 再点上传，出现进度后松开 |
| 屏幕全白 | 引脚错 / 驱动类错 → 跑 GxEPD2 自带 Example 对比 |
| 屏幕花屏 | 供电不足 → 换 USB 口 / `display.init(115200, true, 10, false)` 降速 |
| SD init failed | 默认 SPI 引脚与屏幕冲突 → 在 `SD.begin(SS_PIN)` 显式给 SD 的 CS |
| 翻页没反应 | 按键不在 RTC GPIO 范围（必须 0-21），查板子引脚定义 |
| Bit 黑白反了 | 重新跑 renderer 时加 `--polarity white1` 重新生成 bin |
