# -*- coding: utf-8 -*-
"""批量对全部 SAR 场景执行水体提取（调用 extract_water_sar.py 的逻辑）。

场景清单自动扫描 data/extracted 下的 HH tiff。
用法: python run_all_sar.py [--manual-thresh 文件名=阈值 ...]
"""
import glob
import os
import subprocess
import sys

EXTRACTED = "D:/SmartAI/data/extracted"
RESULTS = "D:/SmartAI/data/results"

# 输出名 -> (输入文件 glob)
SCENES = {
    "mask_0511_LT1B_north.tif": "0511_LT1B/*E109.0_N23.1*.tiff",
    "mask_0511_LT1B_south.tif": "0511_LT1B/*E109.1_N22.7*.tiff",
    "mask_0603_GF3B.tif": "0603_GF3B/*_L2_HH_*.tiff",
    "mask_0706_LT1B_north.tif": "0706_LT1B/*E109.0_N23.1*.tiff",
    "mask_0706_LT1B_south.tif": "0706_LT1B/*E109.1_N22.7*.tiff",
    "mask_0707_GF3B.tif": "0707_GF3B/*_L2_HH_*.tiff",
    "mask_0709_GF3B_south.tif": "0709_GF3B_south/*_L2_HH_*.tiff",
    "mask_0709_GF3B_ne.tif": "0709_GF3B_ne/*_L2_HH_*.tiff",
}


def main():
    os.makedirs(RESULTS, exist_ok=True)
    for out_name, pattern in SCENES.items():
        out_path = os.path.join(RESULTS, out_name)
        if os.path.exists(out_path):
            print(f"SKIP {out_name} (已存在)")
            continue
        hits = glob.glob(os.path.join(EXTRACTED, pattern))
        if not hits:
            print(f"MISS {out_name}: 无输入 {pattern}")
            continue
        cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "extract_water_sar.py"),
               hits[0], out_path]
        print(f"RUN {out_name} <- {os.path.basename(hits[0])}", flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = [l for l in r.stdout.splitlines() if "阈值" in l or "占比" in l or "wrote" in l]
        for l in tail:
            print("   ", l, flush=True)
        if r.returncode != 0:
            print("    ERROR:", r.stderr[-500:], flush=True)


if __name__ == "__main__":
    main()
