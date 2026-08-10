# -*- coding: utf-8 -*-
"""Phase 7: 渲染三张交付图件（灾前水体 / 新增淹没 / 洪水消退）。

背景为 DEM 山体阴影，叠加结果图层，含经纬度网格、比例尺、图例、指北针。
用法: python make_maps.py
"""
import json
import os
import numpy as np
import rasterio
from rasterio.warp import transform_bounds
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import matplotlib.font_manager as fm

PROC = "D:/SmartAI/data/processed"
FINAL = "D:/SmartAI/data/results/final"
OUT = "D:/SmartAI/deliverables"
DEMDIR = "D:/SmartAI/data/dem"

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

GRID = json.load(open(os.path.join(PROC, "grid.json")))


def lonlat_extent():
    b = transform_bounds("EPSG:32649", "EPSG:4326",
                         GRID["xmin"], GRID["ymin"], GRID["xmax"], GRID["ymax"])
    return b  # lon_min, lat_min, lon_max, lat_max


def load_final(name, dec=4):
    with rasterio.open(os.path.join(FINAL, name)) as ds:
        return ds.read(1, out_shape=(ds.height // dec, ds.width // dec),
                       resampling=rasterio.enums.Resampling.nearest)


def hillshade_bg(dec=4):
    """从 DEM 生成山体阴影背景（50m 分辨率）。"""
    import glob, subprocess, tempfile
    tmp = os.path.join(PROC, "dem_bg.tif")
    if not os.path.exists(tmp):
        subprocess.run(["gdalwarp", "-t_srs", "EPSG:32649",
                        "-te", str(GRID["xmin"]), str(GRID["ymin"]), str(GRID["xmax"]), str(GRID["ymax"]),
                        "-tr", "40", "40", "-r", "bilinear", "-co", "COMPRESS=LZW",
                        *glob.glob(os.path.join(DEMDIR, "*.tif")), tmp], check=True)
    with rasterio.open(tmp) as ds:
        dem = ds.read(1).astype(np.float32)
        h, w = dem.shape
    dem[dem < -100] = np.nan
    az, alt = np.radians(315), np.radians(45)
    gy, gx = np.gradient(np.where(np.isfinite(dem), dem, np.nanmean(dem)), 40.0)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    hs = np.clip(hs, 0, 1)
    return hs


def base_ax(ax, title):
    lon0, lat0, lon1, lat1 = lonlat_extent()
    H, W = GRID["height"], GRID["width"]
    ax.set_title(title, fontsize=18, fontweight="bold")
    # 经纬度刻度
    xt = np.linspace(0, W - 1, 7)
    xl = np.linspace(lon0, lon1, 7)
    yt = np.linspace(0, H - 1, 6)
    yl = np.linspace(lat1, lat0, 6)
    ax.set_xticks(xt); ax.set_xticklabels([f"{v:.2f}°E" for v in xl])
    ax.set_yticks(yt); ax.set_yticklabels([f"{v:.2f}°N" for v in yl])
    ax.grid(True, color="white", alpha=0.4, linewidth=0.5)


def add_scalebar(ax, km=20):
    W = GRID["width"]
    px = km * 1000 / 10
    x0, y0 = W * 0.05, GRID["height"] * 0.95
    ax.plot([x0, x0 + px], [y0, y0], color="black", linewidth=4)
    ax.text(x0 + px / 2, y0 - GRID["height"] * 0.015, f"{km} km",
            ha="center", fontsize=11, fontweight="bold")
    ax.annotate("N", xy=(W * 0.95, GRID["height"] * 0.12), fontsize=16,
                fontweight="bold", ha="center")
    ax.arrow(W * 0.95, GRID["height"] * 0.15, 0, -GRID["height"] * 0.06,
             head_width=W * 0.008, head_length=GRID["height"] * 0.015, fc="black")


def render(overlay, cmap, legend_items, title, out_name, dec=4):
    bg = hillshade_bg(dec=10)  # 40m
    fig, ax = plt.subplots(figsize=(14, 15))
    # 背景拉伸到全图
    ax.imshow(bg, cmap="gray", vmin=0, vmax=1,
              extent=[0, GRID["width"], GRID["height"], 0])
    ov = np.ma.masked_where(overlay == 0, overlay).astype(float)
    ax.imshow(ov, cmap=cmap, vmin=0.5, vmax=len(legend_items) + 0.5,
              extent=[0, GRID["width"], GRID["height"], 0], interpolation="nearest")
    ax.set_xlim(0, GRID["width"]); ax.set_ylim(GRID["height"], 0)
    base_ax(ax, title)
    add_scalebar(ax)
    ax.legend(handles=legend_items, loc="upper right", fontsize=12, framealpha=0.9)
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, out_name), dpi=110)
    plt.close()
    print("saved", out_name)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    dec = 4

    # 1. 灾前正常水体图
    pre = load_final("pre_water.tif", dec)
    ov = np.zeros_like(pre); ov[pre == 1] = 1
    render(ov, ListedColormap(["#1f78b4"]),
           [Patch(color="#1f78b4", label="正常水体（河流/湖泊/水库）")],
           "广西南宁灾区灾前正常水体分布（2026-05-11 LT1B + 2026-06-03 GF3B）",
           "图1_灾前正常水体图.png", dec)

    # 2. 灾中新增淹没范围图
    nf = load_final("new_flood.tif", dec)
    pre2 = load_final("pre_water.tif", dec)
    ov = np.zeros_like(nf)
    ov[(pre2 == 1)] = 1
    ov[nf == 1] = 2
    render(ov, ListedColormap(["#1f78b4", "#e31a1c"]),
           [Patch(color="#1f78b4", label="灾前正常水体"),
            Patch(color="#e31a1c", label="新增淹没区")],
           "广西南宁灾区灾中新增淹没范围（2026-07-06/07 vs 灾前）",
           "图2_灾中新增淹没范围图.png", dec)

    # 3. 灾后洪水消退图
    rec = load_final("recession.tif", dec)
    ov = np.zeros_like(rec)
    ov[rec == 1] = 1
    ov[rec == 2] = 2
    ov[rec == 3] = 3
    render(ov, ListedColormap(["#1f78b4", "#e31a1c", "#33a02c"]),
           [Patch(color="#1f78b4", label="水体（含灾前）"),
            Patch(color="#e31a1c", label="0709 仍淹没"),
            Patch(color="#33a02c", label="0709 已消退")],
           "广西南宁灾区洪水消退分析（截至 2026-07-09）",
           "图3_灾后洪水消退图.png", dec)
