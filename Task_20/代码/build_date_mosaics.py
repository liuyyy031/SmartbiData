# -*- coding: utf-8 -*-
"""Phase 3 后半：把各景原生网格水体掩膜重投影到统一 10m 网格并按日期拼接。

输出（写到 data/processed/）：
    water_<date>.tif  uint8  0=非水 1=水 255=该日期无影像覆盖
    valid_<date>.tif  uint8  1=有覆盖

用法: python build_date_mosaics.py
"""
import json
import os
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling

RESULTS = "D:/SmartAI/data/results"
PROCESSED = "D:/SmartAI/data/processed"

# 日期 -> 该日期的掩膜文件列表（原生网格，0/1/255）
DATE_MASKS = {
    "0511": ["mask_0511_LT1B_north.tif", "mask_0511_LT1B_south.tif"],
    "0603": ["mask_0603_GF3B.tif"],
    "0706": ["mask_0706_LT1B_north.tif", "mask_0706_LT1B_south.tif"],
    "0707": ["mask_0707_GF3B.tif"],
    "0709": ["mask_0709_GF3B_south.tif", "mask_0709_GF3B_ne.tif"],
}


def grid_profile(grid):
    from rasterio.transform import from_origin
    return {
        "driver": "GTiff", "width": grid["width"], "height": grid["height"],
        "count": 1, "dtype": "uint8", "crs": rasterio.crs.CRS.from_string(grid["crs"]),
        "transform": from_origin(grid["xmin"], grid["ymax"], grid["res"], grid["res"]),
        "compress": "lzw", "tiled": True, "nodata": 255,
    }


def main():
    grid = json.load(open(os.path.join(PROCESSED, "grid.json")))
    H, W = grid["height"], grid["width"]
    prof = grid_profile(grid)

    # 坡度栅格（10m 网格），水体系固限定在平缓区，排除山体雷达阴影
    slope_path = os.path.join(PROCESSED, "slope_grid.tif")
    slope = None
    if os.path.exists(slope_path):
        with rasterio.open(slope_path) as ds:
            slope = ds.read(1)
    MAX_SLOPE = 8.0

    for date, files in DATE_MASKS.items():
        paths = [os.path.join(RESULTS, f) for f in files]
        paths = [p for p in paths if os.path.exists(p)]
        if not paths:
            print(f"[{date}] 无掩膜文件，跳过")
            continue
        water = np.zeros((H, W), dtype=np.uint8)
        valid = np.zeros((H, W), dtype=np.uint8)
        for p in paths:
            with rasterio.open(p) as src:
                dst = np.full((H, W), 255, dtype=np.uint8)
                reproject(
                    rasterio.band(src, 1), dst,
                    src_transform=src.transform, src_crs=src.crs, src_nodata=255,
                    dst_transform=prof["transform"], dst_crs=prof["crs"], dst_nodata=255,
                    resampling=Resampling.nearest,
                )
            water[(dst == 1)] = 1
            valid[dst != 255] = 1
            print(f"[{date}] merged {os.path.basename(p)}")
        if slope is not None:
            removed = int((water[slope > MAX_SLOPE] == 1).sum())
            water[slope > MAX_SLOPE] = 0
            print(f"[{date}] 坡度>{MAX_SLOPE}° 剔除 {removed} 像元")
        out_w = np.where(valid == 1, water, 255).astype(np.uint8)
        with rasterio.open(os.path.join(PROCESSED, f"water_{date}.tif"), "w", **prof) as ds:
            ds.write(out_w, 1)
        with rasterio.open(os.path.join(PROCESSED, f"valid_{date}.tif"), "w", **prof) as ds:
            ds.write(valid, 1)
        cov = valid.sum()
        wr = water[valid == 1].mean() * 100 if cov else 0
        print(f"[{date}] 覆盖率 {cov/(H*W)*100:.1f}%, 水体占覆盖区 {wr:.2f}%")


if __name__ == "__main__":
    main()
