/*
 * 第 0 步：让屏幕显示 "42.6 km"，电池模式可长按开关机
 *
 * 硬件：微雪 ESP32-S3-ePaper-1.54（V2 版，200×200）
 *  - 主控：ESP32-S3-PICO-1-N8R8（8MB Flash + 8MB OPI PSRAM）
 *  - 屏幕面板：GDEY0154D67，驱动 IC：SSD1681
 * 引脚全部按官方源码 user_config.h 填好，板载直连，不需要接任何线。
 * V1/V2 的引脚定义完全一样，这个程序两个版本都能跑。
 *
 * Arduino IDE 里 PSRAM 必须选 OPI PSRAM（V2）。Flash Size 选 4MB(32Mb)，
 * 分区方案选 Huge APP (3MB No OTA/1MB SPIFFS)。
 *
 * ============ 这块板的电源设计（最关键的一段，务必看懂）============
 *
 * 它没有"硬件电源开关"。电源键是一套【固件自锁】电路：
 *
 *   GPIO18  BAT_KEY      输入，读 PWR 按键。按下 = 低电平
 *   GPIO17  BAT_Control  输出，电池供电自锁。高 = 维持供电，低 = 断电
 *
 * 电池模式下按下 PWR 键，硬件先给板子通电；但**这只在手指按着的时候成立**。
 * 固件必须在启动后立刻把 GPIO17 拉高，把电源"接管"过来，否则一松手就断电。
 *
 * 所以 setup() 的第一行必须是：
 *       pinMode(17, OUTPUT); digitalWrite(17, HIGH);
 *
 * 漏掉它 = 串口一切正常、插 USB 一切正常、电池模式一松手就白屏。
 * 这是这块板最高频的翻车点（官方例程 07_BATT_PWR_Test 专门讲这个）。
 *
 * 关机同理：把 GPIO17 拉低，电源就切断了 —— 这就是"长按电源键关机"的实现。
 * ==================================================================
 */

#include <GxEPD2_BW.h>
#include <Adafruit_GFX.h>
#include <Fonts/FreeMonoBold18pt7b.h>

// ---- 屏幕引脚（官方资料确认，别改）----
#define EPD_PWR   6    // 屏幕电源使能：LOW=开，HIGH=关
#define EPD_BUSY  8
#define EPD_RST   9
#define EPD_DC   10
#define EPD_CS   11
#define EPD_SCK  12
#define EPD_MOSI 13

// ---- 电源相关引脚（官方 user_config.h 确认）----
#define VBAT_PWR 17    // BAT_Control：HIGH=维持电池供电，LOW=断电关机
#define PWR_BTN  18    // BAT_KEY：PWR 按键，按下=LOW（芯片内部上拉）

#define EPD_W 200
#define EPD_H 200

// 面板 = GDEY0154D67（200×200 黑白，驱动 IC: SSD1681）
// 如果编译报"未定义"，把它换成 GxEPD2_154_D67 再试（见文档排查表）
GxEPD2_BW<GxEPD2_154_GDEY0154D67, GxEPD2_154_GDEY0154D67::HEIGHT>
  display(GxEPD2_154_GDEY0154D67(EPD_CS, EPD_DC, EPD_RST, EPD_BUSY));

// 记录开机瞬间 PWR 键是不是还按着（用户按着它开机的）
static bool    pwrHeldAtBoot = false;

// ------------------------------------------------------------------
// 画一屏大字，居中，画完关屏电（画面保留）
// ------------------------------------------------------------------
void showText(const char *msg) {
  // 屏幕供电：LOW = 开
  pinMode(EPD_PWR, OUTPUT);
  digitalWrite(EPD_PWR, LOW);
  delay(100);

  // 板子把屏幕接在了非默认 SPI 脚上（默认 MOSI 是 GPIO11，这里是 GPIO13），
  // 所以必须手动指定。CS 传 -1，片选交给 GxEPD2 自己管。
  SPI.begin(EPD_SCK, -1, EPD_MOSI, -1);
  display.epd2.selectSPI(SPI, SPISettings(4000000, MSBFIRST, SPI_MODE0));

  display.init(115200);          // 打印 GxEPD2 诊断到串口，方便排错
  display.setRotation(0);
  display.setTextColor(GxEPD_BLACK);
  display.setFullWindow();

  // GxEPD2 规定必须写成 firstPage / do / nextPage 的形式
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    display.setFont(&FreeMonoBold18pt7b);
    int16_t bx, by; uint16_t bw, bh;
    display.getTextBounds(msg, 0, 0, &bx, &by, &bw, &bh);
    display.setCursor((EPD_W - bw) / 2 - bx, (EPD_H - bh) / 2 - by);
    display.print(msg);
  } while (display.nextPage());

  delay(50);
  display.hibernate();           // 屏幕控制器进深睡
  digitalWrite(EPD_PWR, HIGH);   // 关屏电：省电，画面依然保留
  Serial.print("shown: ");
  Serial.println(msg);
}

// ------------------------------------------------------------------
void setup() {
  // ============================================================
  // 第 1 件事：把电池供电锁住。必须最先做，不能挪到后面。
  // 电池模式下这一行没跑完，松手就断电 → 白屏。
  // ============================================================
  pinMode(VBAT_PWR, OUTPUT);
  digitalWrite(VBAT_PWR, HIGH);

  // 记录"开机时按键是否还按着"：按着说明用户是用它开机的，
  // 那就必须在 loop 里等松手之后才允许再次长按关机，否则会立刻自关。
  pinMode(PWR_BTN, INPUT_PULLUP);
  delay(30);
  pwrHeldAtBoot = (digitalRead(PWR_BTN) == LOW);

  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.println("boot");
  Serial.print("reset reason: ");
  Serial.println((int)esp_reset_reason());
  Serial.print("pwr held at boot: ");
  Serial.println(pwrHeldAtBoot ? "yes" : "no");

  // 画内容
  showText("42.6 km");

  Serial.println("done - long press PWR to power off");
}

// ------------------------------------------------------------------
void loop() {
  static bool     armed  = false;   // 是否允许"长按关机"
  static uint32_t tPress = 0;       // 本次按下的起始时刻
  static uint32_t tBoot  = 0;       // 上电时刻（开机后前 3 秒不响应）

  if (tBoot == 0) tBoot = millis();

  // 开机后给 3 秒缓冲：用户可能还按着 PWR 键，不能一上来就当成"长按"
  if (millis() - tBoot < 3000) return;

  // 开机时若按键还按着，先等用户松手，之后才武装长按关机
  if (!armed) {
    if (digitalRead(PWR_BTN) == HIGH) armed = true;
    return;
  }

  if (digitalRead(PWR_BTN) == LOW) {
    if (tPress == 0) {
      tPress = millis();
    } else if (millis() - tPress >= 1500) {   // 按住 1.5 秒 = 关机
      Serial.println("power off");
      showText("OFF");
      delay(300);
      digitalWrite(VBAT_PWR, LOW);            // ← 断电，电池模式下这里就黑了
      delay(2000);
      // 如果还活着（说明是 USB 供电，切不断），复位状态等下次操作
      armed  = false;
      tPress = 0;
    }
  } else {
    tPress = 0;                                // 松手，取消计时
  }

  delay(20);
}
