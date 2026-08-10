# -*- coding: utf-8 -*-
"""生成 SAR 底图 + 水体掩膜叠加的验证预览图。

用法: python preview_mask.py <sar.tiff> <mask.tif> <out.png> [--dec 10]
"""
import argparse
import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sar")
    ap.add_argument("mask")
    ap.add_argument("out")
    ap.add_argument("--dec", type=int, default=10)
    args = ap.parse_args()

    with rasterio.open(args.sar) as ds:
        sar = ds.read(1, out_shape=(ds.height // args.dec, ds.width // args.dec)).astype(np.float32)
    with rasterio.open(args.mask) as ds:
        mk = ds.read(1, out_shape=(ds.height // args.dec, ds.width // args.dec),
                     resampling=rasterio.enums.Resampling.nearest)

    db = np.where(sar > 0, 10 * np.log10(np.maximum(sar, 1)), np.nan)
    lo, hi = np.nanpercentile(db, [2, 98])

    fig, axes = plt.subplots(1, 2, figsize=(20, 10))
    axes[0].imshow(db, cmap="gray", vmin=lo, vmax=hi)
    axes[0].set_title("SAR (dB)")
    axes[1].imshow(db, cmap="gray", vmin=lo, vmax=hi)
    overlay = np.ma.masked_where(mk != 1, mk)
    axes[1].imshow(overlay, cmap="autumn", alpha=0.6, vmin=0, vmax=1)
    axes[1].set_title("SAR + water mask")
    plt.tight_layout()
    plt.savefig(args.out, dpi=80)
    print("saved", args.out)


if __name__ == "__main__":
    main()
