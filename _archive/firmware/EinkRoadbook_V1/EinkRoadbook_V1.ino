/*
 * 墨水屏骑行路书 · V1 固件
 * ----------------------------------------------------------------
 * 数据流：PC 渲染好的 roadbook.bin（16 字节头 + N × 5000 字节 1-bit 位图）
 *        存进 SD 卡根目录  ->  ESP32-S3 读取并翻页
 *
 * 交互（默认）：
 *   NEXT 键 短按 → 下一页（按键唤醒用局部刷，快）
 *   NEXT 键 长按 1.5s → 上一页
 *   30 分钟定时唤醒 → 维护刷新（整页全刷清残影）
 *
 * 重要：第一次烧录前，把下面的"硬件配置"按你的板子实际引脚填好；
 *       板子型号和屏幕驱动类没确定前，先用注释里的占位值，
 *       点屏不亮时优先对照 第1课_点亮屏幕并显示42.6km.md 排查。
 */

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <GxEPD2_BW.h>
#include <esp_sleep.h>

// ======================== 硬件配置（按你的板子改） ========================

// 屏幕：填你资料包里厂商 Demo 用的驱动类。常见 200×200：
//   GxEPD2_154_D67   (SSD1680, 200x200)
//   GxEPD2_154_GDEY0154D67
//   GxEPD2_154_M09   (JD79653, 200x200)
// 跑过厂商 Demo 后把 GxEPD2_154_D67 全部替换成你那个。
#define EPD_DRIVER_CLASS  GxEPD2_154_D67

// 屏幕 SPI 引脚（按厂商 Demo 抄过来；不确定时先跑 GxEPD2 自带 Example）
#define EPD_CS    10
#define EPD_DC     8
#define EPD_RST    9
#define EPD_BUSY   7
// VSPI 默认 SCK=18 MOSI=23；多数一体板用这俩，先这样
#define EPD_SCK   18
#define EPD_MOSI  23

// 按键：内部上拉到 VCC，按下拉低
// S3 上 RTC GPIO 是 0-21，下面脚必须落在 0-21 才能用 ext1 唤醒 deep sleep
#define BTN_NEXT   0    // 下一页。**注意 GPIO0=BOOT 键，上电瞬间不能按住**
#define BTN_PREV   2
// 备选：直接用板上 PWR 键（丝印 PWR 附近一般有 GPIO 编号）

// 维护刷新周期（微秒）。30 分钟
#define MAINT_US    (30ULL * 60 * 1000000)

// ======================== 位图格式（与 render_roadbook.py 一致） ========================

#define BIN_MAGIC       0x4252          // "RB" little-endian
#define BIN_VERSION     1
#define FLAG_BLACK_IS_1 0x01
#define PAGE_W          200
#define PAGE_H          200
#define PAGE_BYTES      ((PAGE_W * PAGE_H) / 8)   // 5000
#define HEADER_SIZE     16

// ======================== 全局状态 ========================

RTC_DATA_ATTR static uint16_t g_page   = 0;   // 当前页（RTC 内存：deep sleep 不掉）
static uint16_t g_totalPages = 0;            // bin 里总页数
static bool     g_blackIs1   = true;         // 1=黑（默认，与 renderer --polarity 对齐）

static SPIClass epdSpi(SPI);
GxEPD2_BW<EPD_DRIVER_CLASS, EPD_DRIVER_CLASS::HEIGHT>
  display(EPD_DRIVER_CLASS(EPD_CS, EPD_DC, EPD_RST, EPD_BUSY));

static uint8_t pageBuf[PAGE_BYTES];          // 5KB，刚好放进 SRAM 不用 PSRAM

// ======================== SD 卡 & bin ========================

static bool openBin() {
    File f = SD.open("/roadbook.bin", FILE_READ);
    if (!f) { Serial.println("bin not found"); return false; }

    uint8_t hdr[HEADER_SIZE];
    if (f.read(hdr, HEADER_SIZE) != HEADER_SIZE) { f.close(); return false; }

    uint16_t magic = hdr[0] | (hdr[1] << 8);
    if (magic != BIN_MAGIC) { Serial.println("bad magic"); f.close(); return false; }
    uint8_t  ver   = hdr[2];
    uint8_t  flags = hdr[3];
    uint16_t w     = hdr[4]  | (hdr[5]  << 8);
    uint16_t h     = hdr[6]  | (hdr[7]  << 8);
    uint16_t cnt   = hdr[8]  | (hdr[9]  << 8);
    f.close();

    if (ver != BIN_VERSION || w != PAGE_W || h != PAGE_H) {
        Serial.printf("bin mismatch: ver=%d %dx%d vs %dx%d\n", ver, w, h, PAGE_W, PAGE_H);
        return false;
    }
    g_totalPages = cnt;
    g_blackIs1   = (flags & FLAG_BLACK_IS_1) != 0;
    Serial.printf("bin OK: %u pages, bit1=%s\n", g_totalPages, g_blackIs1 ? "black" : "white");
    return true;
}

static void loadPageBuf(uint16_t idx) {
    File f = SD.open("/roadbook.bin", FILE_READ);
    if (!f) return;
    size_t off = HEADER_SIZE + (size_t)idx * PAGE_BYTES;
    f.seek(off);
    f.read(pageBuf, PAGE_BYTES);
    f.close();

    if (!g_blackIs1) {
        for (size_t i = 0; i < PAGE_BYTES; i++) pageBuf[i] = (uint8_t)~pageBuf[i];
    }
}

// ======================== 刷屏 ========================

static void showCurrent(bool fullRefresh) {
    if (g_totalPages == 0) return;
    if (g_page >= g_totalPages) g_page = g_totalPages - 1;

    loadPageBuf(g_page);
    display.hibernate();

    if (fullRefresh) {
        display.setFullWindow();
        display.firstPage();
        do { display.writeImage(pageBuf, 0, 0, PAGE_W, PAGE_H); }
        while (display.nextPage());
    } else {
        // 局部刷：先快速 init 跳过 LUT 加载
        display.init(115200, /* initial */ false);
        display.setPartialWindow(0, 0, PAGE_W, PAGE_H);
        display.firstPage();
        do { display.writeImage(pageBuf, 0, 0, PAGE_W, PAGE_H); }
        while (display.nextPage());
    }
    display.hibernate();
    Serial.printf("page %u/%u  full=%d\n", g_page + 1, g_totalPages, fullRefresh);
}

// ======================== 按键 ========================

static void gotoPage(uint16_t p) {
    if (p >= g_totalPages) p = 0;
    g_page = p;
    showCurrent(false);
}

static void onKeyNext() {
    // 醒来后这个函数被跳过（ext1 唤醒直接重启），这里仅做"刚启动时"的轮询
    static uint32_t lastMs = 0;
    uint32_t now = millis();
    if (now - lastMs < 250) return;
    lastMs = now;

    // 长按检测
    if (digitalRead(BTN_NEXT) == LOW) {
        delay(30);
        uint32_t t = millis();
        while (digitalRead(BTN_NEXT) == LOW) {
            if (millis() - t > 1500) {
                gotoPage(g_page == 0 ? g_totalPages - 1 : g_page - 1);
                return;
            }
        }
    }
    gotoPage(g_page + 1);
}

// ======================== 唤醒源 ========================

static void enableWakeup() {
    esp_sleep_enable_timer_wakeup(MAINT_US);
    uint64_t mask = (1ULL << BTN_NEXT) | (1ULL << BTN_PREV);
    esp_sleep_enable_ext1_wakeup(mask, ESP_EXT1_WAKEUP_ALL_LOW);
}

// ======================== 错误屏 ========================

static void errorScreen(const char* line1, const char* line2) {
    display.init(115200);
    display.setFullWindow();
    display.firstPage();
    do {
        display.fillScreen(GxEPD_WHITE);
        display.setTextColor(GxEPD_BLACK);
        display.setFont();
        display.setCursor(10, 60);
        display.print(line1);
        display.setCursor(10, 90);
        display.print(line2);
    } while (display.nextPage());
    display.hibernate();
}

// ======================== 启动 ========================

void setup() {
    Serial.begin(115200);
    delay(200);

    // SPI 初始化
    epdSpi.begin(EPD_SCK, -1, EPD_MOSI, EPD_CS);
    display.epd2.selectSPI(epdSpi, SPISettings(4000000, MSBFIRST, SPI_MODE0));
    display.init(115200);

    // 按键
    pinMode(BTN_NEXT, INPUT_PULLUP);
    pinMode(BTN_PREV, INPUT_PULLUP);

    // SD 卡
    if (!SD.begin()) {
        Serial.println("SD init failed");
        errorScreen("SD card", "init failed");
        enableWakeup();
        Serial.flush();
        esp_deep_sleep_start();
    }
    Serial.println("SD OK");

    if (!openBin()) {
        Serial.println("roadbook.bin bad");
        errorScreen("roadbook.bin", "not found or bad");
        enableWakeup();
        Serial.flush();
        esp_deep_sleep_start();
    }

    // 区分唤醒原因：定时 → 全刷（防残影）；按键 → 局部刷（快）
    esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    bool fullRefresh = (cause == ESP_SLEEP_WAKEUP_TIMER);
    Serial.printf("wakeup cause=%d  full=%d\n", cause, fullRefresh);

    showCurrent(fullRefresh);

    // 如果是被按键唤醒，等几毫秒看一下是不是长按（基础轮询，不进 loop）
    if (cause != ESP_SLEEP_WAKEUP_TIMER) {
        delay(50);
        onKeyNext();           // 短按/长按都处理
    }

    enableWakeup();
    Serial.flush();
    esp_deep_sleep_start();
}

void loop() {
    // 不会到这里（setup 末尾直接进 deep sleep）
}
