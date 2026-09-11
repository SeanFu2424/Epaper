#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GxEPD2 瘦身：把用不到的面板驱动挪走，让编译快一截。

为什么需要这个
--------------
GxEPD2 支持上百款墨水屏，它的 src/ 下有 **104 个 .cpp**。
Arduino 编译库时会把 src/ 下所有 .cpp 都编一遍，**不管你用不用**。
你这块板只用 GDEY0154D67 一个面板，剩下 103 个（4.2 寸、6 寸、7.8 寸、10.3 寸…）纯属陪跑。

而每次编译要对这些文件跑两遍：
  1. libsdetect（依赖探测）—— 每个 .cpp 预处理一遍
  2. 真正的编译

在这台 2 核老笔记本上，这是编译时间的主要来源。

安全吗
------
已经静态核对过：
  - 没有任何 .h 文件 #include 了 .cpp
  - 要留下的两个文件只引用自己 + 基类，不引用别的面板类
  - 基类的实现只在 GxEPD2_EPD.cpp 里

**而且是可逆的**：文件是被"挪走"不是删除，`--restore` 一条命令原样搬回来。

用法
----
    # 1) 先空跑，看看会动哪些文件（不改任何东西）
    python tools/trim_gxepd2.py

    # 2) 确认没问题，真正执行
    python tools/trim_gxepd2.py --apply

    # 3) 万一编译报错，一条命令完全还原
    python tools/trim_gxepd2.py --restore

挪走的文件放在 <库目录>/_disabled_drivers/ 里，带一份 manifest.json 记录原始位置。
"""

import argparse
import json
import os
import shutil
import sys

# 保留：基类 + 我们真正用的那一个面板
KEEP = [
    "GxEPD2_EPD.cpp",
    os.path.join("gdey", "GxEPD2_154_GDEY0154D67.cpp"),
]

BACKUP_DIRNAME = "_disabled_drivers"
MANIFEST = "manifest.json"


def default_lib_dir():
    return os.path.join(os.path.expanduser("~"), "Documents", "Arduino",
                        "libraries", "GxEPD2")


def collect(lib):
    src = os.path.join(lib, "src")
    if not os.path.isdir(src):
        sys.exit("找不到 %s —— 用 --lib 指定 GxEPD2 目录" % src)
    keep_abs = {os.path.normcase(os.path.join(src, k)) for k in KEEP}
    out = []
    for root, _dirs, files in os.walk(src):
        for f in files:
            if not f.endswith(".cpp"):
                continue
            full = os.path.join(root, f)
            if os.path.normcase(full) in keep_abs:
                continue
            out.append(os.path.relpath(full, src))
    return src, sorted(out)


def size_of(paths, src):
    total = 0
    for p in paths:
        try:
            total += os.path.getsize(os.path.join(src, p))
        except OSError:
            pass
    return total


def main():
    ap = argparse.ArgumentParser(description="GxEPD2 瘦身（默认空跑）")
    ap.add_argument("--lib", default=default_lib_dir(), help="GxEPD2 库目录")
    ap.add_argument("--apply", action="store_true", help="真正执行（挪走文件）")
    ap.add_argument("--restore", action="store_true", help="还原（把文件搬回来）")
    args = ap.parse_args()

    lib = args.lib
    src = os.path.join(lib, "src")
    backup = os.path.join(lib, BACKUP_DIRNAME)
    manifest_path = os.path.join(backup, MANIFEST)

    # ---------------- restore ----------------
    if args.restore:
        if not os.path.isfile(manifest_path):
            sys.exit("没有找到 %s —— 说明没执行过 --apply，或已经还原过了" % manifest_path)
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        n = 0
        for rel in data.get("moved", []):
            s = os.path.join(backup, rel)
            d = os.path.join(src, rel)
            if os.path.isfile(s):
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.move(s, d)
                n += 1
        # 清掉空目录
        for root, dirs, files in os.walk(backup, topdown=False):
            if not dirs and not files:
                try:
                    os.rmdir(root)
                except OSError:
                    pass
        print("已还原 %d 个文件到 %s" % (n, src))
        print("现在 GxEPD2 和原来一模一样了。")
        return

    # ---------------- 计算 ----------------
    src, victims = collect(lib)
    if not victims:
        print("没有可挪走的文件 —— 要么已经瘦过身了，要么路径不对。")
        print("当前保留：%s" % ", ".join(KEEP))
        return

    total = size_of(victims, src)
    print("GxEPD2 目录: %s" % lib)
    print("保留      : %d 个 .cpp  ->  %s" % (len(KEEP), ", ".join(KEEP)))
    print("要挪走    : %d 个 .cpp  (%.1f MB)" % (len(victims), total / 1024 / 1024))
    print()
    for v in victims:
        print("   %s" % v)

    if not args.apply:
        print()
        print("这是空跑，什么都没动。")
        print("确认没问题后加 --apply 执行：")
        print("    python tools/trim_gxepd2.py --apply")
        return

    # ---------------- apply ----------------
    os.makedirs(backup, exist_ok=True)
    moved = []
    for rel in victims:
        s = os.path.join(src, rel)
        d = os.path.join(backup, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.move(s, d)
        moved.append(rel)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"lib": lib, "moved": moved}, f, ensure_ascii=False, indent=1)

    print()
    print("完成：挪走 %d 个文件 -> %s" % (len(moved), backup))
    print()
    print("接着做两件事：")
    print("  1. 在 Arduino IDE 里重新编译一次（这次会明显快一些）")
    print("  2. 能编过 + 屏幕显示正常 => 以后就一直这么快")
    print("     万一报错（比如 undefined reference）=> 一条命令完全还原：")
    print("        python tools/trim_gxepd2.py --restore")
    print()
    print("注意：以后升级 GxEPD2 库会把文件装回来，需要重新跑一次 --apply。")


if __name__ == "__main__":
    main()
