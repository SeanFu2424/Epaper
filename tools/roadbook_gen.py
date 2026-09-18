#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Roadbook V1 数据生成器：把 JSON 路书 转成 C 头文件，给 ESP32 直接 include。

为什么不在固件里直接 parse JSON：
    - ArduinoJson 要多编 30~60 秒 + 占 Flash
    - V1 的目标就是验证渲染器，数据用定点整数零成本
    - 等 V0.2 改成 SD 卡读 JSON 时，渲染器不用动，只换数据源

用法：
    python tools/roadbook_gen.py 02_Roadbook/sample.json
    产生 02_Roadbook/roadbook.h
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roadbook as rb


# 必须和 roadbook.py 里的 DIRS 顺序一致
DIR_LIST = ["up", "up_right", "right", "down_right",
            "down", "down_left", "left", "up_left"]
DIR_INDEX = {d: i for i, d in enumerate(DIR_LIST)}

TYPE_INDEX = {
    rb.TYPE_TURN: 0,
    rb.TYPE_GLU: 1,
    rb.TYPE_CLIMB: 2,
    rb.TYPE_DANGER: 3,
    rb.TYPE_FINISH: 4,
    rb.TYPE_HALFWAY: 5,
    rb.TYPE_CP: 6,
}

DIR_NONE = 255   # dir 字段的哨兵：这一行不画箭头


def gen_h(json_path, h_path):
    data = rb.load(json_path)
    name = data.get("name", "ROADBOOK")
    events = data["events"]

    arrows = rb.arrows_all()
    arrow_bytes = [rb.pack_bitmap(arrows[d]) for d in DIR_LIST]
    star_bytes = rb.pack_bitmap(rb.make_star(), rb.STAR)

    # 固定前缀 RB_*，固件只 include 一次就能用
    P = "RB"

    out = []
    out.append("// 自动生成自 %s —— 不要手改，改完再跑一次生成器" % json_path.replace("\\", "/"))
    out.append("#pragma once")
    out.append("#include <stdint.h>")
    out.append("")
    out.append("const char %s_NAME[] = \"%s\";" % (P, name))
    out.append("const uint16_t %s_EVENT_COUNT = %d;" % (P, len(events)))
    out.append("")
    out.append("// 8 个方向箭头（16x16 1-bit，row-major，MSB 在左）")
    out.append("// 顺序和 %s_DIR_* 常量一致" % P)
    out.append("#define %s_ARROW_SIZE  %d" % (P, rb.ARROW))
    out.append("#define %s_ARROW_BYTES %d" % (P, rb.ARROW_BYTES))
    for i, d in enumerate(DIR_LIST):
        out.append("#define %s_DIR_%-9s %d" % (P, d.upper(), i))
    out.append("#define %s_DIR_NONE      %d   // dir 字段的哨兵：这一行不画箭头"
               % (P, DIR_NONE))
    out.append("")
    out.append("// 事件类型编号（固件里用 RB_TYPE_* 判断，别再写裸数字）")
    for t, i in sorted(TYPE_INDEX.items(), key=lambda kv: kv[1]):
        out.append("#define %s_TYPE_%-8s %d" % (P, t.upper(), i))
    out.append("")
    out.append("static const uint8_t %s_ARROWS[8][%d] PROGMEM = {" % (P, rb.ARROW_BYTES))
    for d, b in zip(DIR_LIST, arrow_bytes):
        out.append("    { %s },  // %s" % (", ".join("0x%02X" % x for x in b), d))
    out.append("};")
    out.append("")
    out.append("// 爬坡星级位图（%dx%d 1-bit，画 n 颗就重复画 n 次，间距 RB_STAR_GAP）"
               % (rb.STAR, rb.STAR))
    out.append("#define %s_STAR_SIZE  %d" % (P, rb.STAR))
    out.append("#define %s_STAR_GAP   %d" % (P, rb.STAR_GAP))
    out.append("#define %s_STAR_BYTES %d" % (P, rb.STAR_BYTES))
    out.append("static const uint8_t %s_STAR[%d] PROGMEM = { %s };"
               % (P, rb.STAR_BYTES, ", ".join("0x%02X" % x for x in star_bytes)))
    out.append("")
    out.append("// 事件（定点整数，无浮点）：")
    out.append("//   km    /10, 0.1km 精度   length /10   elev  m   grade /10  (0.1%%)")
    out.append("struct %s_Event {" % P)
    out.append("    uint8_t  type;   // 0=turn 1=glu 2=climb 3=danger 4=finish 5=halfway 6=cp")
    out.append("    uint8_t  dir;    // 箭头方向 0..7；255 = 这一行不画箭头")
    out.append("    uint16_t km;     // 0.1 km")
    out.append("    uint16_t length; // 0.1 km, only for climb")
    out.append("    uint16_t elev;   // m, only for climb")
    out.append("    int16_t  grade;  // 0.1 %%, only for climb (signed)")
    out.append("    uint8_t  stars;  // 1..5, only for climb")
    out.append("    uint8_t  n;      // CP 编号（cp 事件显示成 \"CP<n>\"）")
    out.append("    uint8_t  sub;    // 1 = 左列缩进 8px（落在爬坡块内部的 GLU）")
    out.append("};")
    out.append("")
    out.append("static const struct %s_Event %s_EVENTS[%d] PROGMEM = {" % (P, P, len(events)))
    for i, ev in enumerate(events):
        t = TYPE_INDEX[ev["type"].strip().lower()]
        arw = rb.arrow_of(ev, ev["type"].strip().lower())
        d = DIR_INDEX[arw] if arw else DIR_NONE
        km10 = int(round(float(ev["km"]) * 10))
        if t == 2:
            length10 = int(round(float(ev.get("length", 0)) * 10))
            elev = int(ev.get("elev", 0))
            grade10 = int(round(float(ev.get("grade", 0)) * 10))
            stars = int(ev.get("stars") or 0) or rb.climb_stars(
                ev.get("grade"), ev.get("length"))
            sub = 0    # 爬坡的第二行由固件硬编码缩进，不走这个字段
        else:
            length10 = elev = grade10 = stars = 0
            sub = int(ev.get("sub") or 0)
        n = int(ev.get("n") or 0) if t == 6 else 0
        out.append("    { %d, %d, %d, %d, %d, %d, %d, %d, %d },  // %2d: %s"
                   % (t, d, km10, length10, elev, grade10, stars, n, sub,
                      i + 1, _one_line(ev)))
    out.append("};")
    out.append("")
    with open(h_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("已生成 %s   事件=%d  名称=%s" % (h_path, len(events), name))


def _one_line(ev):
    t = ev["type"].strip().lower()
    if t == rb.TYPE_CLIMB:
        st = int(ev.get("stars") or 0) or rb.climb_stars(ev.get("grade"), ev.get("length"))
        return "climb %.1fkm +%dm %.1f%% %s" % (
            ev.get("length", 0), ev.get("elev", 0), ev.get("grade", 0), "*" * st)
    if t == rb.TYPE_CP:
        return rb.cp_label(ev)
    arw = rb.arrow_of(ev, t)
    return t + (" +" + arw if arw else "")


def main():
    ap = argparse.ArgumentParser(description="Roadbook V1 JSON -> C 头文件")
    ap.add_argument("json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if not os.path.exists(args.json):
        sys.exit("找不到 %s" % args.json)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.json)), "roadbook.h")
    gen_h(args.json, out)


if __name__ == "__main__":
    main()
