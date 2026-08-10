# -*- coding: utf-8 -*-
"""Phase 6: 人工抽查 —— 热点区灾前/灾中 SAR 对比 + 新增淹没叠加。

用法: python qa_zoom.py <lon> <lat> <半径km> <out.png>
例: python qa_zoom.py 109.05 23.25 15 D:/SmartAI/outputs/qa1.png
"""
import sys
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling, transform as warp_transform
from rasterio.windows import Window
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

SAR_0511 = "D:/SmartAI/data/extracted/0511_LT1B/LT1B_MONO_KSC_STRIP1_022825_E109.0_N23.1_20260511_GEC_HH_L2_0001191892.tiff"
SAR_0706 = "D:/SmartAI/data/extracted/0706_LT1B/LT1B_MONO_KSC_STRIP1_023658_E109.0_N23.1_20260706_GEC_HH_L2_0001192210.tiff"
NEWFLOOD = "D:/SmartAI/data/results/final/new_flood.tif"
PREWATER = "D:/SmartAI/data/results/final/pre_water.tif"


def scene_window(path, lon, lat, km):
    with rasterio.open(path) as ds:
        x, y = warp_transform("EPSG:4326", ds.crs, [lon], [lat])
        col, row = ~ds.transform * (x[0], y[0])
        half = int(km * 1000 / abs(ds.transform.a) / 2)
        r0, c0 = int(row) - half, int(col) - half
        win = Window(max(c0, 0), max(r0, 0), min(2 * half, ds.width - max(c0, 0)),
                     min(2 * half, ds.height - max(r0, 0)))
        arr = ds.read(1, window=win).astype(np.float32)
        wtr = rasterio.windows.transform(win, ds.transform)
        return arr, win, wtr, ds.crs


def db(arr):
    out = np.where(arr > 0, 10 * np.log10(np.maximum(arr, 1)), np.nan)
    return out


def main():
    lon, lat, km, out = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
    a, win, wtr, crs = scene_window(SAR_0511, lon, lat, km)
    b, _, _, _ = scene_window(SAR_0706, lon, lat, km)
    da, db_ = db(a), db(b)
    lo = np.nanpercentile(np.concatenate([da[np.isfinite(da)], db_[np.isfinite(db_)]]), 2)
    hi = np.nanpercentile(np.concatenate([da[np.isfinite(da)], db_[np.isfinite(db_)]]), 98)

    # 把网格上的结果图层重投影到该窗口
    def grid_layer(path):
        dst = np.zeros(da.shape, dtype=np.uint8)
        with rasterio.open(path) as src:
            reproject(rasterio.band(src, 1), dst,
                      src_transform=src.transform, src_crs=src.crs, src_nodata=255,
                      dst_transform=wtr, dst_crs=crs, dst_nodata=255,
                      resampling=Resampling.nearest)
        return dst

    nf = grid_layer(NEWFLOOD)
    pw = grid_layer(PREWATER)

    fig, axes = plt.subplots(1, 3, figsize=(24, 8))
    axes[0].imshow(da, cmap="gray", vmin=lo, vmax=hi); axes[0].set_title("灾前 05-11 LT1B")
    axes[1].imshow(db_, cmap="gray", vmin=lo, vmax=hi); axes[1].set_title("灾中 07-06 LT1B")
    axes[2].imshow(db_, cmap="gray", vmin=lo, vmax=hi)
    from matplotlib.colors import ListedColormap
    axes[2].imshow(np.ma.masked_where(pw != 1, np.ones_like(pw)),
                   cmap=ListedColormap(["#2166ac"]), alpha=0.7, vmin=0, vmax=1)
    axes[2].imshow(np.ma.masked_where(nf != 1, np.ones_like(nf)),
                   cmap=ListedColormap(["#e31a1c"]), alpha=0.7, vmin=0, vmax=1)
    axes[2].set_title("灾中 + 灾前水体(蓝) + 新增淹没(红)")
    for ax in axes:
        ax.set_xticks([]); ax.set_yticks([])
    plt.suptitle(f"热点抽查 ({lon}°E, {lat}°N) 半径{km}km", fontsize=14)
    plt.tight_layout()
    plt.savefig(out, dpi=85)
    print("saved", out)


if __name__ == "__main__":
    main()
