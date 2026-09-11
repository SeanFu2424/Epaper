"""
校验 out/roadbook.bin 的格式、长度、CRC。
ESP32 启动会做相同的检查（除了 CRC），这里用 Python 提前跑一遍。
"""
import struct, sys, zlib

PAGE_W = 200
PAGE_H = 200
PAGE_BYTES = PAGE_W * PAGE_H // 8
HEADER_SIZE = 16

with open("out/roadbook.bin", "rb") as f:
    data = f.read()

assert len(data) >= HEADER_SIZE, f"文件太小: {len(data)} 字节"
magic, ver, flags, w, h, cnt, crc, _ = struct.unpack("<2sBBHHHIH", data[:HEADER_SIZE])
print(f"magic     : {magic!r}  ({'OK' if magic==b'RB' else 'FAIL'})")
print(f"version   : {ver}")
print(f"flags     : 0x{flags:02x}  (bit0 = {flags & 0x01} -> bit1 是{'黑' if flags & 0x01 else '白'})")
print(f"size      : {w} x {h}  ({'OK' if (w,h)==(PAGE_W,PAGE_H) else 'FAIL'})")
print(f"page count: {cnt}")

expected = HEADER_SIZE + cnt * PAGE_BYTES
ok_len = len(data) == expected
print(f"file len  : {len(data)}  expected {expected}  ({'OK' if ok_len else 'FAIL'})")
if not ok_len:
    sys.exit(1)

payload = data[HEADER_SIZE:]
actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
print(f"CRC32     : stored=0x{crc:08x}  actual=0x{actual_crc:08x}  "
      f"({'OK' if crc == actual_crc else 'DIFF'})")
print(f"total     : {len(data)/1024:.1f} KB  ({cnt} 页)")
