# -*- coding: utf-8 -*-
"""Phase 3+4 SAR 部分：单景 SAR -> 原生网格水体掩膜（uint8: 0=非水 1=水 255=无效）。

分块处理控制内存；Otsu 阈值由抽样统一计算；Lee 滤波去斑点；形态学去小斑/填洞。

用法:
    python extract_water_sar.py <input.tiff> <output_mask.tif> [--strip 2048] [--min-pixels 50]
"""
import argparse
import numpy as np
import rasterio

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flood_core import to_db, lee_filter


def sample_db(ds, step=10):
    """抽样读取 -> dB -> Lee 滤波，用于阈值估计（与正式处理链一致）。"""
    h, w = ds.height, ds.width
    arr = ds.read(1, out_shape=(h // step, w // step)).astype(np.float32)
    nd = ds.nodata
    if nd is not None:
        arr[arr == nd] = np.nan
    arr[arr <= 0] = np.nan
    db = to_db(arr)
    return lee_filter(db, size=5)


def estimate_threshold(db_sample):
    """多类 Otsu（5 类）取最暗类边界：水体是滤波后直方图左尾的最暗群体。"""
    from skimage.filters import threshold_multiotsu
    vals = db_sample[np.isfinite(db_sample)]
    return float(threshold_multiotsu(vals, classes=5)[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--strip", type=int, default=2048)
    ap.add_argument("--min-pixels", type=int, default=50)
    ap.add_argument("--manual-thresh", type=float, default=None)
    args = ap.parse_args()

    ds = rasterio.open(args.input)
    h, w = ds.height, ds.width
    pad = 4  # Lee 滤波半径+1

    # 1) 阈值估计（多类 Otsu，DN 尺度任意也适用）
    samp = sample_db(ds)
    thr = args.manual_thresh if args.manual_thresh is not None else estimate_threshold(samp)
    print(f"[{os.path.basename(args.input)}] 阈值 = {thr:.2f} dB")

    # 2) 分块处理
    mask = np.zeros((h, w), dtype=np.uint8)
    for i0 in range(0, h, args.strip):
        i1 = min(i0 + args.strip, h)
        r0, r1 = max(i0 - pad, 0), min(i1 + pad, h)
        win = rasterio.windows.Window(0, r0, w, r1 - r0)
        block = ds.read(1, window=win).astype(np.float32)
        nd = ds.nodata
        if nd is not None:
            block[block == nd] = np.nan
        block[block <= 0] = np.nan
        db = to_db(block)
        db = lee_filter(db, size=5)
        sub = db[i0 - r0: db.shape[0] - (r1 - i1)]
        m = np.isfinite(sub) & (sub < thr)
        mask[i0:i1][m] = 1
        mask[i0:i1][~np.isfinite(sub)] = 255
        print(f"  rows {i0}-{i1} done", flush=True)
    ds.close()

    # 3) 形态学清理（用 scipy 实现，避免 skimage 版本 API 变动）
    from scipy import ndimage
    water = mask == 1
    lbl, n = ndimage.label(water)
    if n > 0:
        sizes = np.bincount(lbl.ravel())
        small = sizes < args.min_pixels
        small[0] = False
        water[small[lbl]] = False
        # 填洞：对非水区做同样处理
        inv = ~water & (mask != 255)
        lbl2, n2 = ndimage.label(inv)
        if n2 > 0:
            sizes2 = np.bincount(lbl2.ravel())
            small2 = sizes2 < args.min_pixels
            small2[0] = False
            water[small2[lbl2]] = True
    mask[water] = 1
    mask[(mask != 255) & ~water] = 0
    valid = mask != 255
    print(f"  水体占比 = {water.sum()/max(valid.sum(),1)*100:.2f}%")

    # 4) 写出
    profile = {
        "driver": "GTiff", "height": h, "width": w, "count": 1,
        "dtype": "uint8", "crs": rasterio.open(args.input).crs,
        "transform": rasterio.open(args.input).transform,
        "compress": "lzw", "tiled": True, "nodata": 255,
    }
    with rasterio.open(args.output, "w", **profile) as out:
        out.write(mask, 1)
    print(f"  wrote {args.output}")


if __name__ == "__main__":
    main()
