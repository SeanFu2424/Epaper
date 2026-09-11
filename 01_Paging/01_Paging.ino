/*
 * 第 1 步：长文本 -> 自动分页 -> 按键翻页
 *
 * 硬件：微雪 ESP32-S3-ePaper-1.54（V2 版，200x200）
 *   面板 GDEY0154D67 / 驱动 IC SSD1681 / GxEPD2 类 GxEPD2_154_GDEY0154D67
 *
 * ------------------------------------------------------------------
 * 这一步要验证什么（只验证这三件事，别的都不碰）
 *   1. 一段放不下的长文本，能不能自动切成多页
 *   2. 按 PWR 键能不能翻到下一页（考验墨水屏刷新）
 *   3. 翻到最后一页 / 第一页时边界对不对
 *
 * 故意不做的事：
 *   - 不显示中文（中文字库是独立的坑，等这一步通了再单独做）
 *   - 不用 SD 卡（文本先写死在固件里，少一个变量）
 *   - 不接 deep sleep（先证明"能翻"，再优化"省电"）
 * ------------------------------------------------------------------
 * 按键（全用板载按键，不用接线）：
 *   PWR 键  短按        -> 下一页
 *   PWR 键  按住 1.5 秒 -> 关机（显示 OFF -> GPIO17 拉低断电）
 *   BOOT 键 短按        -> 上一页
 *
 * 【电源铁律】这块板是固件自锁电源（不是 IP5306）：
 *   GPIO17 BAT_Control  高 = 维持电池供电，低 = 断电
 *   必须是 setup() 的第一件事，漏了就是"插 USB 正常、电池一松手就白屏"
 *
 * 【按键铁律】墨水屏全刷要 2 秒，这 2 秒里 loop() 是卡住的，轮询根本读不到按键。
 *   所以 PWR / BOOT 都挂了 GPIO 中断，按下和松开各记一个时间戳。
 *   刷新结束后 loop() 才去消费这些事件 —— 这 2 秒里按的键一个都不会丢。
 * ------------------------------------------------------------------
 * 上传前想看效果：在电脑上跑
 *     python tools/preview_paging.py
 *   会把每一页原样渲染成 PNG，不用烧录就能看排版。
 */

#include <GxEPD2_BW.h>
#include <Adafruit_GFX.h>
#include <Fonts/FreeSans9pt7b.h>
#include <Fonts/FreeMonoBold18pt7b.h>
#include <esp_system.h>   // esp_reset_reason()

// ---- 字体（想换字形/字号，只改下面这两行，别的地方都不用动）----
// 候选都在 Documents\Arduino\libraries\Adafruit_GFX_Library\Fonts\ 里：
//   FreeSans9pt7b / FreeSans12pt7b / FreeSansBold9pt7b / FreeSansBold12pt7b
//   FreeMono9pt7b / FreeMono12pt7b / FreeMonoBold9pt7b ...
// 换更大/更粗的字体后，记得跟着改下面的 LINE_H（行高）和 LINES_PER_PAGE（每页几行），
// 否则会行重叠或超出页脚。改完先跑预览器看，确认 over=0 再烧录。
// 电脑端预览器会读这两行，所以预览和屏幕永远一致。
#define BODY_FONT  FreeSans9pt7b        // 页眉 + 正文
#define BIG_FONT   FreeMonoBold18pt7b   // 关机时那个 OFF 大字

// ---- 屏幕引脚（官方 user_config.h 确认，别改）----
#define EPD_PWR   6
#define EPD_BUSY  8
#define EPD_RST   9
#define EPD_DC   10
#define EPD_CS   11
#define EPD_SCK  12
#define EPD_MOSI 13

// ---- 电源 / 按键 ----
#define VBAT_PWR 17   // BAT_Control：HIGH = 维持供电
#define PWR_BTN  18   // BAT_KEY：按下 = LOW
#define BOOT_BTN  0   // BOOT 键：按下 = LOW

#define EPD_W 200
#define EPD_H 200

// ---- 排版参数 ----
// 这份数值同时在电脑端预览器里被读取（tools/preview_paging.py），
// 改这里 = 预览和屏幕一起变，不会对不上。
#define RB_TITLE      "QIANDDAO LAKE"
#define RB_FOOTER     "PWR:next  BOOT:prev  HOLD:off"

#define MAX_LINES       220   // 最多存多少行
#define LINE_LEN         72   // 单行最多多少字符（含结尾 0）
#define BODY_X            6   // 正文左边距
#define BODY_MAX_W      188   // 正文可用宽度 = 200 - 6 - 6
#define BODY_TOP_Y       40   // 第一行基线
#define LINE_H           16   // 行高
#define LINES_PER_PAGE    9   // 每页几行

// ---- 按键时间 ----
#define SHORT_MIN_MS     60   // 短于这个算抖动，丢掉
#define LONG_MS        1500   // 按住这么久 = 关机
#define BOOT_GUARD_MS  3000   // 开机缓冲：这 3 秒内不响应按键

// ---- 翻页用不用局部刷新 ----
//   0 = 全刷，约 2.0 秒，画面干净，无残影（先用这个验证正确性）
//   1 = 局部刷，约 0.5 秒，快 4 倍，但会累积残影
// 改这一个数字只重新编译本文件，不会重编整个核心（前提：构建缓存还在）
#define FAST_PARTIAL     0

GxEPD2_BW<GxEPD2_154_GDEY0154D67, GxEPD2_154_GDEY0154D67::HEIGHT>
  display(GxEPD2_154_GDEY0154D67(EPD_CS, EPD_DC, EPD_RST, EPD_BUSY));

// ==================================================================
// 待分页的长文本。\n 分段，\n\n 空行会保留成空行。
// 现在是 ASCII 英文（先用现成字体跑通链路），
// 中文要等第 2 步上点阵中文字库。
// 注意：这里不要手动折行！一行写到底，交给下面的代码按屏幕宽度自动折，
//       手动折 + 自动折会折两次，冒出 "points" 这种孤字。
// ==================================================================
static const char *SAMPLE_TEXT =
"QIANDDAO LAKE LOOP\n"
"128.4 km / +1420 m gain / 15 key points on this loop\n"
"\n"
"KM 0.0  START\n"
"North gate parking lot. Rolling start, keep it easy for the first 10 km until the legs wake up.\n"
"\n"
"KM 8.6  FEED 1\n"
"Water and a banana. Refill both bottles here, the next shop is 30 km away. Toilet behind the shop.\n"
"\n"
"KM 17.2  CLIMB 1\n"
"4.1 km at 5.2 percent. Hold a steady tempo and watch for loose gravel on the inside of the corners.\n"
"\n"
"KM 24.0  SUMMIT 1\n"
"Good photo spot. Then a 6.3 km descent at minus 7.8 percent. Brake early, two corners are blind.\n"
"\n"
"KM 34.5  TURN\n"
"Sharp left immediately after the stone bridge. Easy to miss, look for the blue sign on the fence.\n"
"\n"
"KM 41.8  FEED 2\n"
"Noodles and a cola. Sit down for ten minutes before the next climb, this is the last real stop.\n"
"\n"
"KM 52.3  CLIMB 2\n"
"6.8 km at 4.6 percent. A long grind rather than a steep one, keep the cadence above 70 rpm.\n"
"\n"
"KM 63.1  SUMMIT 2\n"
"Highest point of the whole loop. Put the wind jacket on before you start descending, it is cold.\n"
"\n"
"KM 70.0  DESCENT\n"
"9.2 km at minus 6.5 percent on fresh tarmac. Good grip, but the surface changes at the bottom.\n"
"\n"
"KM 82.4  FEED 3\n"
"Water only, keep this stop short. The hard part of the day is still ahead of you.\n"
"\n"
"KM 95.6  CLIMB 3\n"
"3.2 km at 6.9 percent. This is the steep one. Drop into the smallest gear and spin it out.\n"
"\n"
"KM 101.0  SUMMIT 3\n"
"Last climb done. 27 km to go and it is mostly flat from here, so settle into a rhythm.\n"
"\n"
"KM 112.5  FLAT\n"
"Open headwind section along the water. Find a group and share the work, do not fight it alone.\n"
"\n"
"KM 122.0  FINAL TURN\n"
"Right turn into the lake road. Traffic here, stay in single file and keep your line.\n"
"\n"
"KM 128.4  FINISH\n"
"Back at the north gate. Loop closed. Good job, go eat something.\n"
"\n"
"--- END OF ROADBOOK ---\n";

// ==================================================================
static char lines[MAX_LINES][LINE_LEN];
static int  lineCount = 0;
static int  pageCount = 0;
static int  curPage   = 0;

// ------------------------------------------------------------------
// 【修 bug 2 的核心】用字体的真实 xAdvance 算宽度
//
// 之前用的是 display.getTextBounds()，但它量的是"当前字体"。
// buildLines() 跑在 setFont() 之前，所以量出来的是内置 5x7 字体的宽度
// （每个字符约 6px），而真正画出来的是 FreeSans9pt7b（小写字母约 10px）。
// 宽度被低估了近一半 -> 以为塞得下 -> 实际溢出 -> Adafruit_GFX 自动换行
// -> 换行后行距用的是字体的 yAdvance(22px) 而不是我们的 LINE_H(16px)
// -> 和下一行重叠。
//
// 现在直接读字体表里的 xAdvance，和屏幕上画出来的宽度完全一致，与当前字体无关。
// ------------------------------------------------------------------
static uint16_t textWidth(const char *s) {
  uint16_t w = 0;
  for (; *s; s++) {
    uint8_t c = (uint8_t)*s;
    if (c < BODY_FONT.first || c > BODY_FONT.last) continue;
    w += pgm_read_byte(&BODY_FONT.glyph[c - BODY_FONT.first].xAdvance);
  }
  return w;
}

// 一个词长到一行放不下时，最多能截几个字符（至少 1 个，避免死循环）
static int fitChars(const char *p, int len) {
  int k = 0;
  uint16_t w = 0;
  while (k < len) {
    uint8_t c = (uint8_t)p[k];
    uint16_t adv = 0;
    if (c >= BODY_FONT.first && c <= BODY_FONT.last)
      adv = pgm_read_byte(&BODY_FONT.glyph[c - BODY_FONT.first].xAdvance);
    if ((uint32_t)w + adv > BODY_MAX_W) break;
    w += adv;
    k++;
  }
  return k > 0 ? k : 1;
}

static void pushLine(const char *p, int len) {
  if (lineCount >= MAX_LINES) return;
  if (len < 0) len = 0;
  if (len > LINE_LEN - 1) len = LINE_LEN - 1;
  memcpy(lines[lineCount], p, len);
  lines[lineCount][len] = '\0';
  while (len > 0 && lines[lineCount][len - 1] == ' ') {   // 去掉行尾空格
    lines[lineCount][--len] = '\0';
  }
  lineCount++;
}

// 把一段文字按屏幕宽度折行，存进 lines[]
static void wrapParagraph(const char *p, int len) {
  if (len == 0) { pushLine("", 0); return; }   // 空行保留

  int i = 0;
  while (i < len) {
    while (i < len && p[i] == ' ') i++;
    if (i >= len) break;

    int start = i;
    int lastFit = -1;
    int j = i;

    while (j < len) {
      while (j < len && p[j] != ' ') j++;      // 走到词尾
      int n = j - start;
      if (n > LINE_LEN - 1) n = LINE_LEN - 1;
      char buf[LINE_LEN];
      memcpy(buf, p + start, n);
      buf[n] = '\0';

      if (textWidth(buf) <= BODY_MAX_W) lastFit = j;   // 这词塞得下
      else break;                                      // 塞不下，停

      j++;                                     // 跳过空格，看下一个词
    }

    if (lastFit < 0) lastFit = start + fitChars(p + start, len - start);

    pushLine(p + start, lastFit - start);
    i = lastFit;
  }
}

// 全部行的字符校验和，用来跟电脑端预览器对账
static uint16_t layoutChecksum() {
  uint16_t chk = 0;
  for (int i = 0; i < lineCount; i++) {
    for (const char *s = lines[i]; *s; s++)
      chk = (uint16_t)(chk * 31u + (uint8_t)*s);
    chk = (uint16_t)(chk * 31u + 0xFFu);        // 行分隔
  }
  return chk;
}

static void buildLines() {
  lineCount = 0;
  const char *p = SAMPLE_TEXT;
  while (*p) {
    const char *nl = strchr(p, '\n');
    int len = nl ? (int)(nl - p) : (int)strlen(p);
    wrapParagraph(p, len);
    if (!nl) break;
    p = nl + 1;
  }
  pageCount = (lineCount + LINES_PER_PAGE - 1) / LINES_PER_PAGE;
  if (pageCount < 1) pageCount = 1;

  // 自检：有没有还超宽的行（超了就会溢出/换行）
  uint16_t maxw = 0;
  int over = 0;
  for (int i = 0; i < lineCount; i++) {
    uint16_t w = textWidth(lines[i]);
    if (w > maxw) maxw = w;
    if (w > BODY_MAX_W) over++;
  }
  Serial.printf("layout: %d lines -> %d pages  maxw=%u/%d over=%d  chk=0x%04X\n",
                lineCount, pageCount, maxw, BODY_MAX_W, over, layoutChecksum());
}

// ------------------------------------------------------------------
// 画一页
// ------------------------------------------------------------------
static bool drawnOnce = false;

static void renderPage(int idx) {
  if (idx < 0) idx = 0;
  if (idx >= pageCount) idx = pageCount - 1;
  curPage = idx;

  char pbuf[16];
  snprintf(pbuf, sizeof(pbuf), "%d/%d", idx + 1, pageCount);

#if FAST_PARTIAL
  if (drawnOnce) display.setPartialWindow(0, 0, EPD_W, EPD_H);
  else           display.setFullWindow();
#else
  display.setFullWindow();
#endif

  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    display.setTextColor(GxEPD_BLACK);
    display.setFont(&BODY_FONT);

    // 页眉：左边标题，右边页码
    display.setCursor(BODY_X, 16);
    display.print(RB_TITLE);
    int16_t bx, by; uint16_t bw, bh;
    display.getTextBounds(pbuf, 0, 0, &bx, &by, &bw, &bh);
    display.setCursor(EPD_W - BODY_X - bw - bx, 16);
    display.print(pbuf);
    display.drawFastHLine(4, 22, EPD_W - 8, GxEPD_BLACK);

    // 正文
    int y = BODY_TOP_Y;
    for (int i = 0; i < LINES_PER_PAGE; i++) {
      int li = idx * LINES_PER_PAGE + i;
      if (li >= lineCount) break;
      display.setCursor(BODY_X, y);
      display.print(lines[li]);
      y += LINE_H;
    }

    // 页脚（用 5x7 内置字体，小一号才塞得下）
    display.drawFastHLine(4, 178, EPD_W - 8, GxEPD_BLACK);
    display.setFont();
    display.setTextColor(GxEPD_BLACK);
    display.setCursor(BODY_X, 186);
    display.print(RB_FOOTER);
    display.setFont(&BODY_FONT);
  } while (display.nextPage());

  drawnOnce = true;
  Serial.printf("page %d/%d%s\n", idx + 1, pageCount,
                FAST_PARTIAL ? " (partial)" : " (full)");
}

// 画一句大字（用于 OFF 提示）
static void renderBig(const char *msg) {
  display.setFullWindow();
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    display.setTextColor(GxEPD_BLACK);
    display.setFont(&BIG_FONT);
    int16_t bx, by; uint16_t bw, bh;
    display.getTextBounds(msg, 0, 0, &bx, &by, &bw, &bh);
    display.setCursor((EPD_W - bw) / 2 - bx, (EPD_H - bh) / 2 - by);
    display.print(msg);
  } while (display.nextPage());
  drawnOnce = true;
}

static void powerOff() {
  Serial.println("power off");
  renderBig("OFF");
  delay(400);
  digitalWrite(VBAT_PWR, LOW);   // <- 电池模式下这里就断电了
}

static void nextPage() {
  if (curPage + 1 >= pageCount) { Serial.println("last page"); return; }
  renderPage(curPage + 1);
}

static void prevPage() {
  if (curPage == 0) { Serial.println("first page"); return; }
  renderPage(curPage - 1);
}

// ------------------------------------------------------------------
// 【修 bug 3 的核心】按键走中断，边沿永远不丢
//
// 全刷那 2 秒里 loop() 卡在 display.nextPage() 里，轮询看不到任何按键。
// 挂中断后，按下/松开各记一个时间戳，刷新一结束 loop() 立刻处理。
// ------------------------------------------------------------------
volatile uint8_t  pwrEvtDown = 0, pwrEvtUp = 0;
volatile uint32_t pwrDownMs  = 0, pwrUpMs  = 0;
volatile uint8_t  bootEvtDown = 0, bootEvtUp = 0;
volatile uint32_t bootDownMs  = 0, bootUpMs  = 0;
static volatile uint32_t lastPwrIsrMs = 0, lastBootIsrMs = 0;

void IRAM_ATTR pwrISR() {
  uint32_t now = millis();
  if (now - lastPwrIsrMs < 30) return;          // 去抖
  lastPwrIsrMs = now;
  if (digitalRead(PWR_BTN) == LOW) { pwrDownMs = now; pwrEvtDown = 1; }
  else                             { pwrUpMs   = now; pwrEvtUp   = 1; }
}

void IRAM_ATTR bootISR() {
  uint32_t now = millis();
  if (now - lastBootIsrMs < 30) return;
  lastBootIsrMs = now;
  if (digitalRead(BOOT_BTN) == LOW) { bootDownMs = now; bootEvtDown = 1; }
  else                              { bootUpMs   = now; bootEvtUp   = 1; }
}

// 把中断攒下的边沿取出来（取完即清）
static inline void takeEvents(bool &d, uint32_t &dms, bool &u, uint32_t &ums,
                              volatile uint8_t &fD, volatile uint32_t &tD,
                              volatile uint8_t &fU, volatile uint32_t &tU) {
  d = u = false; dms = ums = 0;
  noInterrupts();
  if (fD) { d = true; dms = tD; fD = 0; }
  if (fU) { u = true; ums = tU; fU = 0; }
  interrupts();
}

// ------------------------------------------------------------------
void setup() {
  // ===== 第 1 件事：锁住电池供电。不能挪到后面。 =====
  pinMode(VBAT_PWR, OUTPUT);
  digitalWrite(VBAT_PWR, HIGH);

  pinMode(PWR_BTN,  INPUT_PULLUP);
  pinMode(BOOT_BTN, INPUT_PULLUP);
  delay(30);

  attachInterrupt(digitalPinToInterrupt(PWR_BTN),  pwrISR,  CHANGE);
  attachInterrupt(digitalPinToInterrupt(BOOT_BTN), bootISR, CHANGE);

  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.printf("boot - paging test (reset reason %d)\n", (int)esp_reset_reason());

  // 屏幕供电
  pinMode(EPD_PWR, OUTPUT);
  digitalWrite(EPD_PWR, LOW);
  delay(100);

  SPI.begin(EPD_SCK, -1, EPD_MOSI, -1);
  display.epd2.selectSPI(SPI, SPISettings(4000000, MSBFIRST, SPI_MODE0));
  display.init(115200);
  display.setRotation(0);
  display.setTextWrap(false);   // 保险：万一还有超宽行，宁可裁掉也不要折到下一行去

  display.setFont(&BODY_FONT);   // 量宽度前先定字体
  buildLines();                      // 折行 + 算页数
  renderPage(0);

  Serial.println("ready - PWR=next  BOOT=prev  hold PWR=off");
}

// ------------------------------------------------------------------
void loop() {
  static uint32_t tBoot = 0;
  static bool     guardDone = false;
  static bool     pwrHeld = false, pwrWasLong = false;
  static uint32_t pwrHeldT0 = 0;

  if (tBoot == 0) tBoot = millis();

  // 开机缓冲：这 3 秒里的按键事件全部丢掉
  //（用 PWR 开机时手还按着，松手那一下不能当成"短按翻页"）
  if (!guardDone) {
    if (millis() - tBoot < BOOT_GUARD_MS) { delay(5); return; }
    noInterrupts();
    pwrEvtDown = pwrEvtUp = bootEvtDown = bootEvtUp = 0;
    interrupts();
    guardDone = true;
  }

  // ---------- PWR 键 ----------
  bool d, u; uint32_t dms, ums;
  takeEvents(d, dms, u, ums, pwrEvtDown, pwrDownMs, pwrEvtUp, pwrUpMs);

  if (d) { pwrHeld = true; pwrWasLong = false; pwrHeldT0 = dms; }

  if (u && pwrHeld) {
    pwrHeld = false;
    uint32_t held = (ums >= pwrHeldT0) ? (ums - pwrHeldT0) : SHORT_MIN_MS;
    if (!pwrWasLong) {
      if (held >= LONG_MS) { powerOff(); delay(1500); return; }
      if (held >= SHORT_MIN_MS) nextPage();
    }
  }

  // 按着不放时轮询长按（空闲状态下才能走到这里）
  if (pwrHeld && !pwrWasLong && digitalRead(PWR_BTN) == LOW
      && millis() - pwrHeldT0 >= LONG_MS) {
    pwrWasLong = true;
    powerOff();
    pwrHeld = false;
    delay(1500);          // USB 供电时不会真断电，等它松手
    return;
  }
  if (pwrWasLong && digitalRead(PWR_BTN) == HIGH) { pwrWasLong = false; pwrHeld = false; }

  // ---------- BOOT 键 ----------
  takeEvents(d, dms, u, ums, bootEvtDown, bootDownMs, bootEvtUp, bootUpMs);
  if (u && (ums >= dms ? (ums - dms) : SHORT_MIN_MS) >= SHORT_MIN_MS
      && (ums >= dms ? (ums - dms) : SHORT_MIN_MS) < LONG_MS) {
    prevPage();
  }

  delay(10);
}
