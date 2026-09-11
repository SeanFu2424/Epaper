# 墨水屏骑行路书 V1 · PC 渲染器

把"路书 JSON"渲染成 ESP32-S3 屏幕能直接刷的 1-bit 位图 bin，拷到 SD 卡即用。

## 一次性安装

```bash
python -m pip install Pillow
```

(项目其余没有任何依赖。)

## 使用

```bash
# 1. 准备路书 JSON（参考 samples/roadbook_sample.json）
# 2. 渲染
python tools/render_roadbook.py samples/roadbook_sample.json --out out

# 3. 把 out/roadbook.bin 拷到 SD 卡根目录
```

输出文件：

| 文件 | 用途 |
|---|---|
| `out/roadbook.bin` | 直接拷到 SD 卡根目录 |
| `out/manifest.json` | 页码索引（调试用） |
| `out/pages/pXXX_*.png` | 每页预览（默认 3 倍放大） |
| `out/contact_sheet.png` | 全部页面拼版预览 |

## 参数

```
python tools/render_roadbook.py <json> [options]

  --out        输出目录，默认 out
  --width      屏幕宽，默认 200
  --height     屏幕高，默认 200
  --scale      预览图放大倍数，默认 3
  --mode       cycle (默认) = 每事件 L1/L2/L3 三层轮转
               simple = 总览 + 每事件 L1/L3
  --polarity   black1 (默认) / white1
               决定位图 1 是黑还是白，需与固件保持一致
```

## bin 文件格式

```
偏移  大小  含义
0     2     magic = "RB" (0x52 0x42)
2     1     version = 1
3     1     flags: bit0 = 黑极性 (1=black)
4     2     width (LE) = 200
6     2     height (LE) = 200
8     2     page count (LE)
10    4     CRC32 of payload (可选校验)
14    2     保留
16    ...   N 张 5000 字节的 1-bit 位图，MSB 在前，每行 width/8 字节
```

每页大小固定 5000 字节（200×200/8），SD 卡里顺序存放。

## JSON 字段

```json
{
  "route": "路线名",
  "total_km": 128.4,
  "date": "2026-09-20",
  "cards": [
    {
      "id": 1,
      "at_km": 0.0,             // 发生时的累计公里
      "type": "start|finish|climb|feed|sprint|danger|turn",
      "title": "主标题（≤14 字）",
      "sub": "副标题（≤18 字）",
      "detail": [                // L3 详情页用，奇数=key，偶数=value
        "集合时间", "06:30 发车",
        "前 5 km", "市区缓行热身"
      ]
    }
  ]
}
```

`type` 决定图标（爬坡 ▲、补给 💧、冲刺 ⚡、终点 🏁、危险 ⚠、转弯 ➡、起点 ▶）。
图标全部单色自绘，不依赖 emoji 字体。

## 已知限制 / 后续可加

- [ ] RLE 压缩（flag 字节已留位）
- [ ] 多语言字体（现在用 msyh / simhei，Linux 自动回退 Noto / 文泉驿）
- [ ] 翻页记录到 RTC：现在已经做了，但 V2 改成 GPX 实时算距离时需要重构
