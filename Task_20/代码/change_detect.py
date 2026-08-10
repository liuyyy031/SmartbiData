# -*- coding: utf-8 -*-
"""Phase 5: 变化检测 —— 灾前水体 / 灾中新增淹没 / 灾后消退。

输入: data/processed/water_<date>.tif + valid_<date>.tif (0/1/255, 10m 网格)
输出: data/results/final/
    pre_water.tif       灾前正常水体 (0/1/255)
    during_water.tif    灾中水体
    new_flood.tif       灾中新增淹没 (0/1/255, 255=无法判定)
    recession.tif       消退分析: 0=非水 1=灾前水体 2=新增淹没且仍淹 3=新增淹没已消退 255=无数据
    stats.txt           面积统计
用法: python change_detect.py
"""
import os
import numpy as np
import rasterio

PROC = "D:/SmartAI/data/processed"
OUT = "D:/SmartAI/data/results/final"
NODATA = 255


def load(name):
    with rasterio.open(os.path.join(PROC, name)) as ds:
        return ds.read(1), ds.profile


def union_water(dates):
    w = np.zeros((H, W), dtype=bool)
    v = np.zeros((H, W), dtype=bool)
    for d in dates:
        arr, _ = load(f"water_{d}.tif")
        v |= arr != NODATA
        w |= arr == 1
    return w, v


def save(name, arr, profile):
    p = profile.copy()
    p.update(dtype="uint8", count=1, compress="lzw", nodata=NODATA,
             tiled=True, blockxsize=256, blockysize=256)
    with rasterio.open(os.path.join(OUT, name), "w", **p) as ds:
        ds.write(arr.astype(np.uint8), 1)
    print("wrote", name)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    arr, profile = load("water_0511.tif")
    H, W = arr.shape
    px_km2 = 10 * 10 / 1e6

    pre_w, pre_v = union_water(["0511", "0603"])
    dur_w, dur_v = union_water(["0706", "0707"])
    post_w, post_v = union_water(["0709"])

    # 灾前/灾中水体图（255=无数据）
    pre_map = np.where(pre_v, pre_w, NODATA).astype(np.uint8)
    dur_map = np.where(dur_v, dur_w, NODATA).astype(np.uint8)
    save("pre_water.tif", pre_map, profile)
    save("during_water.tif", dur_map, profile)

    # 新增淹没 = 灾中有水 & 灾前无水 & 两期都可判定
    judge = pre_v & dur_v
    new_flood = dur_w & ~pre_w & judge
    # 最小图斑过滤（MMU = 1 ha = 100 像元@10m），去除零散斑点噪声
    from scipy import ndimage
    lbl, n = ndimage.label(new_flood)
    if n > 0:
        sizes = np.bincount(lbl.ravel())
        drop = sizes < 100
        drop[0] = False
        new_flood = new_flood & ~drop[lbl]
    nf_map = np.where(judge, new_flood, NODATA).astype(np.uint8)
    save("new_flood.tif", nf_map, profile)

    # 消退分析（相对 0709）
    rec = np.zeros((H, W), dtype=np.uint8)
    rec[pre_w & ~dur_w] = 1                     # 灾前水体（灾中未新增）
    rec[dur_w] = 1
    rec[new_flood & post_v & post_w] = 2         # 新增淹没，0709 仍淹
    rec[new_flood & post_v & ~post_w] = 3        # 新增淹没，0709 已消退
    rec[~(pre_v | dur_v | post_v)] = NODATA
    save("recession.tif", rec, profile)

    a_pre = (pre_w & pre_v).sum() * px_km2
    a_dur = (dur_w & dur_v).sum() * px_km2
    a_new = new_flood.sum() * px_km2
    a_rec = (rec == 3).sum() * px_km2
    a_per = (rec == 2).sum() * px_km2
    stats = (
        f"灾前正常水体面积: {a_pre:.2f} km²\n"
        f"灾中水体面积: {a_dur:.2f} km²\n"
        f"灾中新增淹没面积: {a_new:.2f} km²\n"
        f"  其中 0709 仍淹没: {a_per:.2f} km²\n"
        f"  其中 0709 已消退: {a_rec:.2f} km²\n"
        f"可判定区(灾前∩灾中覆盖): {judge.sum()*px_km2:.2f} km²\n"
    )
    open(os.path.join(OUT, "stats.txt"), "w", encoding="utf-8").write(stats)
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(stats)
