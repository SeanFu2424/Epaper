/*
 * Roadbook —— 6 种事件，左右两列，爬坡占两行
 *
 * 本版新增（2026-09-11 第二轮）：
 *   1. 爬坡第二行的右列："+237m 6.1%" 改成【难度星级】位图（爬升/坡度不上屏）
 *   2. 新增 HALFWAY 事件（路线中点提示）
 *   3. 不再有补水（H2O）事件 —— 补给统一显示 GLU
 *   星级和箭头一样是自制 1-bit 位图（字体只覆盖 ASCII，画不出 ★）
 *
 * 上一版（2026-09-11）：
 *   页脚状态栏 —— 底部一条长横线，线下左侧显示时间，右侧显示电池电量。
 *   数据来源（全部来自官方源码/wiki，不是猜的）：
 *     · 时间：板载 RTC 芯片 PCF85063，I2C 地址 0x51，SDA=GPIO47 / SCL=GPIO48
 *       寄存器 0x04 起连续 7 字节 = 秒/分/时/日/星期/月/年（BCD 编码）
 *       秒寄存器 bit7 = OS 标志，为 1 表示"掉过电，时间不可信"
 *     · 电量：VBAT 经 200K/200K 分压到 GPIO4（= ADC1 通道 3），VBAT = VADC × 2
 *   对时方式：开机时若 RTC 时间无效，自动写入「编译时刻」；
 *             之后可在串口发一行  T2026-09-11 11:35:00  精确对时。
 *
 *  数据：roadbook.h（tools/roadbook_gen.py 从 JSON 生成，不要手改）
 *  按键：PWR 按下=前进 N 页 / 长按 1.5s 关机；BOOT 按下=后退 N 页
 *  屏幕：微雪 ESP32-S3-ePaper-1.54 V2，200x200 GDEY0154D67
 */
#include <GxEPD2_BW.h>
#include <Adafruit_GFX.h>
#include <Fonts/FreeSansBold9pt7b.h>
#include <esp_system.h>
#include <Wire.h>         // 读 PCF85063 时间
#include <string.h>
#include <stdlib.h>
#include "roadbook.h"     // 自动生成，不要手改

// ---- 屏幕引脚（官方 user_config.h 确认，别改）----
#define EPD_PWR   6
#define EPD_BUSY  8
#define EPD_RST   9
#define EPD_DC   10
#define EPD_CS   11
#define EPD_SCK  12
#define EPD_MOSI 13

// ---- 电源 / 按键（铁律：setup 第一行必须锁电）----
#define VBAT_PWR 17    // HIGH=维持电池供电，LOW=断电
#define PWR_BTN  18    // 按下=LOW
#define BOOT_BTN  0    // 按下=LOW

// ---- 板载 RTC：PCF85063（官方 user_config.h：地址 0x51，SDA=47，SCL=48）----
#define RTC_SDA  47
#define RTC_SCL  48
#define RTC_ADDR 0x51
#define RTC_SEC  0x04     // 0x04..0x0A = 秒/分/时/日/星期/月/年
#define RTC_REGS 7

// ---- 电池采样（官方 wiki：200K/200K 分压 -> GPIO4，即 ADC1 通道 3）----
#define BAT_ADC   4
#define BAT_SCALE 2       // VBAT = VADC × 2

// ---- 屏幕与模板 ----
#define EPD_W       200
#define EPD_H       200
#define MARGIN        6
#define HEADER_Y     16
#define HEADER_LINE  22

// 正文区：行距自适应（与 tools/roadbook.py 的 layout() 是同一个公式）
// 加页脚状态栏后正文区从 38..190 上收为 38..162（少 28px，6 行时行距 30 -> 24）
#define BODY_TOP      38   // 第一行基线最高到这
#define BODY_BOTTOM  162   // 最后一行基线最低到这（实测正文墨迹底 = 基线+1）
#define GAP_MIN       24   // 最小行距（字体 yAdvance=22）
#define GAP_MAX       38   // 最大行距

#define MAX_ROWS      6    // 一页最多几"行"（爬坡占 2 行）

// ---- 页脚状态栏（与 tools/roadbook.py 的同名常量对应）----
#define FOOT_LINE_Y  174   // 页脚横线
#define FOOT_Y       190   // 状态栏基线（左=时间，右=电量）

// ---- 刷新 ----
#define FAST_PARTIAL   0   // 1=翻页用局部刷新（快，约0.5s，有残影）；0=全刷（2s，无残影）
                           // 实测局部刷新残影太重 -> 改回全刷
#define FULL_EVERY     4   // 局部刷新时每 4 页强制全刷一次清残影（FAST_PARTIAL=0 时无效）

#define SUB_INDENT     8   // 爬坡第二行的缩进（视觉上从属于上面那行）

// ---- 按键 ----
#define DEBOUNCE_MS   30    // 电平稳定判定
#define REPEAT_MS    120    // 两次"按下"最小间隔（防机械抖动尾巴被当成连按）
#define LONG_MS     1500
#define BOOT_GUARD   600    // 开机后这段时间内的按键丢弃（防上电抖动；原来 3000 太长）

#define HOLD_TO_BOOT   1    // 1=必须按住 PWR 达到 BOOT_HOLD_MS 才开机（防误触）
                            // 0=按一下就开机
#define BOOT_HOLD_MS 1000   // 长按开机的判定时长（从 setup 起算，加上启动耗时约 1.8s）
#define QUEUE_MAX      3    // 最多连按排队次数

GxEPD2_BW<GxEPD2_154_GDEY0154D67, GxEPD2_154_GDEY0154D67::HEIGHT>
  display(GxEPD2_154_GDEY0154D67(EPD_CS, EPD_DC, EPD_RST, EPD_BUSY));

// ---- 分页 ----
#define MAX_PAGES 24
uint16_t pageStart[MAX_PAGES];   // 每页起始事件 index
uint8_t  pageRows[MAX_PAGES];    // 每页占几"行"
int      pageCount = 0;
int      curPage   = 0;
uint8_t  sinceFull = 0;          // 距上次全刷过了几页（局部刷新用）

static int rowOf(int i) {
  return pgm_read_byte(&RB_EVENTS[i].type) == 2 ? 2 : 1;   // 2 = climb
}

static void buildPages() {
  pageCount = 0;
  int i = 0, rows = 0;
  while (i < RB_EVENT_COUNT) {
    if (i == 0 || rows + rowOf(i) > MAX_ROWS) {
      pageStart[pageCount] = i;
      pageRows[pageCount]  = 0;
      pageCount++;
      rows = 0;
      if (pageCount >= MAX_PAGES) break;
    }
    rows += rowOf(i);
    pageRows[pageCount - 1] = rows;
    i++;
  }
  if (pageCount == 0) { pageStart[0] = 0; pageRows[0] = 0; pageCount = 1; }
}

// 和 tools/roadbook.py 的 layout() 同一个公式，两边改要一起改
static void computeLayout(int rows, int &top, int &gap) {
  int avail = BODY_BOTTOM - BODY_TOP;
  if (rows <= 1) { top = BODY_TOP + avail / 2; gap = GAP_MAX; return; }
  gap = avail / (rows - 1);
  if (gap > GAP_MAX) gap = GAP_MAX;
  if (gap < GAP_MIN) gap = GAP_MIN;
  top = BODY_TOP + (avail - gap * (rows - 1)) / 2;
}

// ---- 渲染辅助 ----
static inline void ralignPrint(int16_t y, const char *s) {
  int16_t bx, by; uint16_t bw, bh;
  display.getTextBounds(s, 0, 0, &bx, &by, &bw, &bh);
  display.setCursor(EPD_W - MARGIN - bw - bx, y);
  display.print(s);
}

// 星级：右对齐画 n 颗星（y = 该行基线；位图和箭头同一套机制）
static void drawStars(int16_t y, uint8_t n) {
  if (n == 0) return;
  if (n > 5) n = 5;
  int w = n * RB_STAR_SIZE + (n - 1) * RB_STAR_GAP;
  int x0 = EPD_W - MARGIN - w;
  for (uint8_t k = 0; k < n; k++) {
    display.drawBitmap(x0 + k * (RB_STAR_SIZE + RB_STAR_GAP),
                       y - RB_STAR_SIZE + 1,
                       RB_STAR, RB_STAR_SIZE, RB_STAR_SIZE, GxEPD_BLACK);
  }
}

// ---- 状态栏数据：时间（RTC PCF85063） + 电量（ADC） ----
// 读不到就显示占位符，绝不阻塞渲染 —— 屏该出什么还出什么
char gTimeStr[8] = "--:--";
char gBattStr[8] = "--%";

static inline uint8_t bcd2dec(uint8_t v) { return (uint8_t)((v >> 4) * 10 + (v & 0x0F)); }
static inline uint8_t dec2bcd(uint8_t v) { return (uint8_t)(((v / 10) << 4) | (v % 10)); }

static void rtcBegin() {
  Wire.begin(RTC_SDA, RTC_SCL, 100000);
}

// 读 RTC。返回 false = I2C 无应答（芯片不在线）
// lost = true 表示秒寄存器 bit7（OS 标志）为 1 —— 芯片掉过电，时间不可信
static bool rtcRead(uint16_t &year, uint8_t &mon, uint8_t &day,
                    uint8_t &hour, uint8_t &min, uint8_t &sec, bool &lost) {
  Wire.beginTransmission(RTC_ADDR);
  Wire.write(RTC_SEC);
  if (Wire.endTransmission(false) != 0) return false;
  if ((int)Wire.requestFrom((uint16_t)RTC_ADDR, (uint8_t)RTC_REGS) != RTC_REGS) return false;
  uint8_t b[RTC_REGS];
  for (int i = 0; i < RTC_REGS; i++) b[i] = (uint8_t)Wire.read();
  sec  = bcd2dec(b[0] & 0x7F);
  min  = bcd2dec(b[1] & 0x7F);
  hour = bcd2dec(b[2] & 0x3F);    // 24 小时制
  day  = bcd2dec(b[3] & 0x3F);
  mon  = bcd2dec(b[5] & 0x1F);
  year = (uint16_t)(bcd2dec(b[6]) + 2000);
  lost = (b[0] & 0x80) != 0;
  return true;
}

static bool rtcWrite(uint16_t year, uint8_t mon, uint8_t day,
                     uint8_t hour, uint8_t min, uint8_t sec) {
  Wire.beginTransmission(RTC_ADDR);
  Wire.write(RTC_SEC);
  Wire.write(dec2bcd(sec) & 0x7F);    // 写秒会顺带把 OS 标志清 0
  Wire.write(dec2bcd(min) & 0x7F);
  Wire.write(dec2bcd(hour) & 0x3F);
  Wire.write(dec2bcd(day) & 0x3F);
  Wire.write(dec2bcd(1));             // 星期（页脚不显示，固定填 1）
  Wire.write(dec2bcd(mon) & 0x1F);
  Wire.write(dec2bcd(year % 100));
  return Wire.endTransmission() == 0;
}

// 编译时刻。__DATE__ = "Sep 11 2026"，__TIME__ = "11:35:00"
static void parseCompileTime(int &y, int &mo, int &d, int &h, int &mi, int &s) {
  static const char *MONTHS = "JanFebMarAprMayJunJulAugSepOctNovDec";
  const char *dt = __DATE__;
  char mon[4] = { dt[0], dt[1], dt[2], 0 };
  const char *p = strstr(MONTHS, mon);
  mo = p ? (int)(p - MONTHS) / 3 + 1 : 1;
  d  = atoi(dt + 4);
  y  = atoi(dt + 7);
  const char *tm = __TIME__;
  h  = atoi(tm);
  mi = atoi(tm + 3);
  s  = atoi(tm + 6);
}

// 电池电压（毫伏，已乘分压系数）。多次采样取平均，抗抖
static int batteryMilliVolts() {
  uint32_t acc = 0;
  for (int i = 0; i < 4; i++) { acc += analogReadMilliVolts(BAT_ADC); delay(2); }
  return (int)(acc / 4) * BAT_SCALE;
}

// 单节锂电 电压 -> 电量百分比（分段线性插值）
// ⚠️ 这张曲线是按常见单节锂电放电特性拟的，不是官方给的；实测后可微调
static int battPercent(int mv) {
  static const int16_t vt[8] = {3300, 3500, 3600, 3700, 3800, 3900, 4000, 4150};
  static const int8_t  pc[8] = {   0,   10,   25,   45,   60,   75,   85,  100};
  if (mv <= vt[0]) return 0;
  if (mv >= vt[7]) return 100;
  for (int i = 0; i < 7; i++)
    if (mv < vt[i + 1])
      return pc[i] + (pc[i + 1] - pc[i]) * (mv - vt[i]) / (vt[i + 1] - vt[i]);
  return 100;
}

static void refreshStatus() {
  uint16_t y; uint8_t mo, d, h, mi, s; bool lost = true;
  if (rtcRead(y, mo, d, h, mi, s, lost) && !lost && y >= 2024 && mo >= 1 && mo <= 12) {
    snprintf(gTimeStr, sizeof(gTimeStr), "%02u:%02u", (unsigned)h, (unsigned)mi);
  } else {
    strcpy(gTimeStr, "--:--");
  }
  int mv = batteryMilliVolts();
  if (mv > 2000) snprintf(gBattStr, sizeof(gBattStr), "%d%%", battPercent(mv));
  else           strcpy(gBattStr, "--%");
}

// ---- 渲染一页 ----
static void renderPage(int idx) {
  if (idx < 0) idx = 0;
  if (idx >= pageCount) idx = pageCount - 1;
  curPage = idx;

  refreshStatus();                 // 页脚的时间/电量（I2C + ADC，约 10ms）

  char pbuf[8];
  snprintf(pbuf, sizeof(pbuf), "%d/%d", idx + 1, pageCount);

  // 局部刷新：快但留残影；每 FULL_EVERY 页全刷一次清掉
#if FAST_PARTIAL
  if (sinceFull >= 1 && sinceFull < FULL_EVERY) {
    display.setPartialWindow(0, 0, EPD_W, EPD_H);
    sinceFull++;
  } else {
    display.setFullWindow();
    sinceFull = 1;
  }
#else
  display.setFullWindow();
#endif

  int top, gap;
  computeLayout(pageRows[idx], top, gap);

  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    display.setTextColor(GxEPD_BLACK);
    display.setFont(&FreeSansBold9pt7b);

    // ---- 页眉 ----
    display.setCursor(MARGIN, HEADER_Y);
    display.print(RB_NAME);
    ralignPrint(HEADER_Y, pbuf);
    display.drawFastHLine(MARGIN, HEADER_LINE, EPD_W - 2 * MARGIN, GxEPD_BLACK);

    // ---- 事件 ----
    int y = top;
    int end = (idx + 1 < pageCount) ? pageStart[idx + 1] : (int)RB_EVENT_COUNT;
    for (int i = pageStart[idx]; i < end; i++) {
      uint8_t type = pgm_read_byte(&RB_EVENTS[i].type);
      uint16_t km10 = pgm_read_word(&RB_EVENTS[i].km);

      char kmbuf[10];
      snprintf(kmbuf, sizeof(kmbuf), "%.1f km", km10 / 10.0);
      display.setCursor(MARGIN, y);
      display.print(kmbuf);

      if (type == 0) {                              // TURN —— 画箭头
        uint8_t dir = pgm_read_byte(&RB_EVENTS[i].dir);
        display.drawBitmap(EPD_W - MARGIN - RB_ARROW_SIZE,
                           y - RB_ARROW_SIZE + 2,
                           RB_ARROWS[dir], RB_ARROW_SIZE, RB_ARROW_SIZE, GxEPD_BLACK);
      } else if (type == 1) {                       // GLU（补给统一显示 GLU，不再分胶/水）
        ralignPrint(y, "GLU");
      } else if (type == 3) {                       // DANGER
        ralignPrint(y, "DANGER");
      } else if (type == 4) {                       // FINISH
        ralignPrint(y, "FINISH");
      } else if (type == 5) {                       // HALFWAY（路线中点）
        ralignPrint(y, "HALFWAY");
      } else if (type == 2) {                       // CLIMB —— 两行
        uint16_t length10 = pgm_read_word(&RB_EVENTS[i].length);

        char rbuf[16];
        snprintf(rbuf, sizeof(rbuf), "CLM %d.%d", length10 / 10, length10 % 10);
        ralignPrint(y, rbuf);

        // 第二行：左列 = 爬坡结束公里数（22.6 + 3.1 = 25.7），右列 = 难度星级
        // （爬升/坡度不再上屏：200px 宽塞不下，且骑的时候看星级就够了）
        y += gap;
        uint16_t endKm10 = km10 + length10;          // 定点整数相加，零浮点
        snprintf(kmbuf, sizeof(kmbuf), "%.1f km", endKm10 / 10.0);
        display.setCursor(MARGIN + SUB_INDENT, y);   // 缩进 = 从属于上面那行
        display.print(kmbuf);

        drawStars(y, pgm_read_byte(&RB_EVENTS[i].stars));
      }
      y += gap;
    }

    // ---- 页脚状态栏：横线 + 左时间 / 右电量 ----
    display.drawFastHLine(MARGIN, FOOT_LINE_Y, EPD_W - 2 * MARGIN, GxEPD_BLACK);
    display.setCursor(MARGIN, FOOT_Y);
    display.print(gTimeStr);
    ralignPrint(FOOT_Y, gBattStr);
  } while (display.nextPage());

  Serial.printf("page %d/%d  top=%d gap=%d\n", idx + 1, pageCount, top, gap);
}

// ---- 关机画面 ----
static void renderOff() {
  display.setFullWindow();
  sinceFull = 0;
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    display.setTextColor(GxEPD_BLACK);
    display.setFont(&FreeSansBold9pt7b);
    int16_t bx, by; uint16_t bw, bh;
    display.getTextBounds("OFF", 0, 0, &bx, &by, &bw, &bh);
    display.setCursor((EPD_W - bw) / 2 - bx, (EPD_H - bh) / 2 - by);
    display.print("OFF");
  } while (display.nextPage());
}

static void powerOff() {
  Serial.println("power off");
  renderOff();
  delay(400);
  digitalWrite(VBAT_PWR, LOW);   // 断电，程序到这就停了
}

// ---- 按键：中断里"按下即排队"（V1.1 核心修复）----
// 原版等松手才认定，且 up 沿可能被去抖窗口吞掉 -> 快按完全没反应；
// 刷屏 2 秒期间的单槽标志被反复覆盖 -> 连按只算一次。
// 现在：按下沿直接 +1（最多 3），刷屏结束后合并成"翻 N 页"。
volatile uint8_t  pwrQueue = 0, bootQueue = 0;
volatile uint32_t pwrDownMs = 0;
volatile bool     pwrIsDown = false, bootIsDown = false;
volatile bool     pwrSawRelease = true;   // 开机后是否见过一次"松手"（见 loop 里的长按关机条件）
static volatile uint32_t lastPwrEdge = 0, lastBootEdge = 0;
static volatile uint32_t lastPwrPress = 0, lastBootPress = 0;

void IRAM_ATTR pwrISR() {
  uint32_t now = millis();
  if (now - lastPwrEdge < DEBOUNCE_MS) return;
  bool down = (digitalRead(PWR_BTN) == LOW);
  if (down == pwrIsDown) return;          // 抖动（电平没真变）
  lastPwrEdge = now;
  pwrIsDown = down;
  if (down) {
    pwrDownMs = now;
    if (now - lastPwrPress < REPEAT_MS) return;   // 一次按下的抖动尾巴
    lastPwrPress = now;
    if (pwrQueue < QUEUE_MAX) pwrQueue++;         // 按下即排队，不等松手
  } else {
    pwrSawRelease = true;                 // 见过松手，之后才允许长按关机
  }
}

void IRAM_ATTR bootISR() {
  uint32_t now = millis();
  if (now - lastBootEdge < DEBOUNCE_MS) return;
  bool down = (digitalRead(BOOT_BTN) == LOW);
  if (down == bootIsDown) return;
  lastBootEdge = now;
  bootIsDown = down;
  if (down) {
    if (now - lastBootPress < REPEAT_MS) return;
    lastBootPress = now;
    if (bootQueue < QUEUE_MAX) bootQueue++;
  }
}

void setup() {
  pinMode(VBAT_PWR, OUTPUT);
  digitalWrite(VBAT_PWR, HIGH);                  // 第 1 件事：锁电

  pinMode(PWR_BTN,  INPUT_PULLUP);
  pinMode(BOOT_BTN, INPUT_PULLUP);
  delay(30);

  Serial.begin(115200);            // 提前：下面的长按开机检测要打日志
  delay(200);
  Serial.println();

  // ===== 长按开机：上电后必须"持续按住 PWR"才算开机 =====
  //
  // ⚠️ 旧写法 `if (digitalRead(PWR_BTN) == LOW) { ...等一会儿... }` 有致命 bug：
  //    短按时，setup 跑到这一行用户早已松手 -> 读到 HIGH -> 整段被跳过 -> 直接开机。
  //    **这就是"短按反而能开机"的原因。** 现在改成从 setup 起【采样】一段时间，
  //    不再依赖"某一瞬间"的电平。
  //
  // 三个阶段：
  //   起手 300ms 内就没按过   -> 当作 USB 插线上电，直接放行（不影响插线调试）
  //   按下后又松手（短按）     -> 主动断电，屏幕保持原样，看起来"没开机"
  //   一直按到窗口结束（长按） -> 正常开机
  //
  // ⚠️ 必须在第 261 行锁电【之后】做：否则松手瞬间硬件就断电，程序活不到这一行。
#if HOLD_TO_BOOT
  {
    bool everDown = false, held = true;
    uint32_t tb = millis();
    while (millis() - tb < 300) {                    // ① 先看有没有人按
      if (digitalRead(PWR_BTN) == LOW) { everDown = true; break; }
      delay(10);
    }
    if (everDown) {
      tb = millis();
      while (millis() - tb < BOOT_HOLD_MS) {         // ② 要求一直按着
        if (digitalRead(PWR_BTN) == HIGH) { held = false; break; }
        delay(15);
      }
      if (!held) {
        Serial.printf("boot aborted - short press (hold %dms to turn on)\n", BOOT_HOLD_MS);
        digitalWrite(VBAT_PWR, LOW);                 // 电池供电 -> 到这一行就断电了
        delay(2000);                                 // USB 供电断不掉：等 2 秒继续正常启动
      } else {
        Serial.println("boot ok - long press");
      }
    } else {
      Serial.println("boot - no key held, assume USB power");
    }
  }
#endif

  attachInterrupt(digitalPinToInterrupt(PWR_BTN),  pwrISR,  CHANGE);
  attachInterrupt(digitalPinToInterrupt(BOOT_BTN), bootISR, CHANGE);

  // ===== 把中断内部状态和"实际电平"对齐 =====
  // 长按开机时用户的手还按在 PWR 上（引脚是 LOW）。若不初始化，ISR 内部会停在
  // "未按下"，接下来那次松手不会被记成 pwrSawRelease -> 长按关机可能被误触发，
  // 表现出来就是"开机之后马上又关机"（用户实测到的现象）。
  noInterrupts();
  pwrIsDown     = (digitalRead(PWR_BTN) == LOW);
  bootIsDown    = (digitalRead(BOOT_BTN) == LOW);
  pwrSawRelease = !pwrIsDown;      // 开机时没按着 -> 视为已松手过（正常可长按关机）
  pwrDownMs     = millis();        // 长按计时从这一刻重新起算
  lastPwrPress  = millis();
  lastBootPress = millis();
  pwrQueue = bootQueue = 0;
  interrupts();

  Serial.printf("boot - roadbook v1.5: \"%s\"  events=%u%s\n",
                RB_NAME, (unsigned)RB_EVENT_COUNT,
                FAST_PARTIAL ? "  (partial on)" : "");
  // 按键诊断：1 = 没按。按住 PWR 或 BOOT 再上电，这里应该能看到 0
  Serial.printf("pins: PWR=%d BOOT=%d  (0=正被按下)\n",
                digitalRead(PWR_BTN), digitalRead(BOOT_BTN));

  // ===== RTC（PCF85063）：初始化 + 时间无效时用「编译时刻」兜底 =====
  // 判断无效的依据有两个（都来自官方 SensorLib 源码）：
  //   · 秒寄存器 bit7（OS 标志）= 1 -> 芯片掉过电
  //   · 年份 < 2024 -> 寄存器内容明显是垃圾
  rtcBegin();
  {
    uint16_t y; uint8_t mo, d, h, mi, s; bool lost = true;
    if (!rtcRead(y, mo, d, h, mi, s, lost)) {
      Serial.println("rtc: no response on I2C (addr 0x51) -> footer shows --:--");
    } else if (lost || y < 2024 || mo < 1 || mo > 12) {
      int cy, cmo, cd, ch, cmi, cs;
      parseCompileTime(cy, cmo, cd, ch, cmi, cs);
      bool ok = rtcWrite((uint16_t)cy, (uint8_t)cmo, (uint8_t)cd,
                         (uint8_t)ch, (uint8_t)cmi, (uint8_t)cs);
      Serial.printf("rtc: invalid (lost=%d %04u-%02u-%02u) -> set compile time %04d-%02d-%02d %02d:%02d:%02d  %s\n",
                    (int)lost, (unsigned)y, (unsigned)mo, (unsigned)d,
                    cy, cmo, cd, ch, cmi, cs, ok ? "OK" : "FAILED");
    } else {
      Serial.printf("rtc: %04u-%02u-%02u %02u:%02u:%02u  (kept)\n",
                    (unsigned)y, (unsigned)mo, (unsigned)d,
                    (unsigned)h, (unsigned)mi, (unsigned)s);
    }
    int mv = batteryMilliVolts();
    Serial.printf("bat: %d mV -> %d%%\n", mv, mv > 2000 ? battPercent(mv) : 0);
  }

  pinMode(EPD_PWR, OUTPUT);
  digitalWrite(EPD_PWR, LOW);
  delay(100);

  SPI.begin(EPD_SCK, -1, EPD_MOSI, -1);
  display.epd2.selectSPI(SPI, SPISettings(4000000, MSBFIRST, SPI_MODE0));
  display.init(115200);
  display.setRotation(0);
  display.setTextWrap(false);

  buildPages();
  Serial.printf("%d events -> %d pages\n", (int)RB_EVENT_COUNT, pageCount);
  for (int i = 0; i < pageCount; i++) {          // 和预览器对账用
    int t, g; computeLayout(pageRows[i], t, g);
    Serial.printf("  page %d: rows=%d top=%d gap=%d\n", i + 1, pageRows[i], t, g);
  }
  renderPage(0);

  Serial.println("ready - PWR=next  BOOT=prev  hold PWR=off");
}

// ---- 串口对时：发一行 "T2026-09-11 11:35:00" + 回车，即把时间写进 RTC ----
// （RTC 若不能断电保持，开机时只能退回"编译时刻"，会有几十分钟误差；
//   接电脑时敲这一行就能校准到秒。）
static void pollSerialTime() {
  static char buf[32];
  static uint8_t n = 0;
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (n) {
        buf[n] = 0;
        n = 0;
        int y, mo, d, h, mi, s;
        if (buf[0] == 'T' &&
            sscanf(buf + 1, "%d-%d-%d %d:%d:%d", &y, &mo, &d, &h, &mi, &s) == 6) {
          if (rtcWrite((uint16_t)y, (uint8_t)mo, (uint8_t)d,
                       (uint8_t)h, (uint8_t)mi, (uint8_t)s)) {
            Serial.printf("rtc set: %04d-%02d-%02d %02d:%02d:%02d\n", y, mo, d, h, mi, s);
            renderPage(curPage);        // 立刻重画，页脚马上显示新时间
          } else {
            Serial.println("rtc set FAILED (I2C no ack)");
          }
        } else {
          Serial.println("unknown cmd. 格式示例: T2026-09-11 11:35:00");
        }
      }
    } else if (n < sizeof(buf) - 1) {
      buf[n++] = ch;
    }
  }
}

void loop() {
  pollSerialTime();

  static bool guardDone = false;
  static uint32_t t0 = 0;
  if (!guardDone) {
    if (t0 == 0) t0 = millis();
    if (millis() - t0 < BOOT_GUARD) { delay(5); return; }
    noInterrupts();
    pwrQueue = 0; bootQueue = 0;
    pwrDownMs = millis();      // 长按计时从头开始：不然"长按开机"会被当成"长按关机"，
    interrupts();              // 开完机立刻又关机（开机是靠长按 PWR 的，必然踩到）
    guardDone = true;
    Serial.println("guard ok - keys live");
  }

  // 长按 PWR = 关机。注意：按下瞬间已经翻过页了（按下即翻是特性不是 bug，
  // 骑行时响应优先；关机画面会盖上去，无感）。
  // pwrSawRelease 这一条很关键：必须"先见过一次松手"才允许长按关机。
  // 否则长按开机时手还按着，会被当成"已经按够 1.5 秒" -> 开机后立刻又关机。
  if (pwrSawRelease && pwrIsDown && millis() - pwrDownMs >= LONG_MS) {
    powerOff();
    delay(2000);
    return;
  }

  uint8_t q;
  noInterrupts(); q = pwrQueue;  pwrQueue  = 0; interrupts();
  if (q) {
    int to = min(curPage + (int)q, pageCount - 1);
    Serial.printf("key: pwr x%d  %d -> %d\n", q, curPage + 1, to + 1);
    renderPage(to);
    return;
  }

  noInterrupts(); q = bootQueue; bootQueue = 0; interrupts();
  if (q) {
    int to = max(curPage - (int)q, 0);
    Serial.printf("key: boot x%d  %d -> %d\n", q, curPage + 1, to + 1);
    renderPage(to);
    return;
  }

  delay(10);
}
