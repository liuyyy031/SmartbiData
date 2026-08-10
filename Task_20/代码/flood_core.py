# -*- coding: utf-8 -*-
"""洪涝水体提取核心函数库。

SAR 原理：平静水体对雷达波呈镜面反射，后向散射（sigma0, dB）极低，
          通过自适应阈值（Otsu/双峰法）将低后向散射像元判为水体。
光学原理：NDWI = (Green - NIR) / (Green + NIR)，水体 NDWI 显著为正。
"""
import numpy as np
import rasterio
from rasterio.features import shapes
from scipy import ndimage
from skimage.filters import threshold_otsu
from skimage.morphology import remove_small_objects, remove_small_holes, binary_opening, disk


# ---------- 通用 IO ----------

def read_band(path, band=1):
    with rasterio.open(path) as ds:
        arr = ds.read(band).astype(np.float32)
        profile = ds.profile.copy()
        nodata = ds.nodata
    if nodata is not None:
        arr[arr == nodata] = np.nan
    return arr, profile


def write_raster(path, arr, profile, dtype="uint8", nodata=None):
    p = profile.copy()
    p.update(dtype=dtype, count=1, compress="lzw", nodata=nodata)
    with rasterio.open(path, "w", **p) as ds:
        ds.write(arr.astype(dtype), 1)
    print(f"  wrote {path}")


# ---------- SAR ----------

def to_db(arr):
    """自动判断数据类型并转为 dB。已是 dB（存在负值且量级合理）则原样返回。"""
    valid = arr[np.isfinite(arr) & (arr != 0)]
    if valid.size == 0:
        return arr
    if np.percentile(valid, 5) < -5:  # 已有明显负值 -> 已是 dB
        return arr
    out = np.full_like(arr, np.nan)
    pos = arr > 0
    # 若数值很小（<1）通常是线性 sigma0 功率，否则是幅度/DN；10*log10 对功率，20*log10 对幅度。
    # 阈值法只依赖相对分布，统一用 10*log10 即可（幅度转功率差一个因子 2，不影响 Otsu 分割位置）。
    out[pos] = 10.0 * np.log10(arr[pos])
    return out


def lee_filter(arr, size=5):
    """Lee 斑点滤波（边缘保持），输入 dB 或线性均可。"""
    valid = np.isfinite(arr)
    x = np.where(valid, arr, 0.0)
    w = valid.astype(np.float32)
    mean = ndimage.uniform_filter(x, size) / np.maximum(ndimage.uniform_filter(w, size), 1e-6)
    mean_sq = ndimage.uniform_filter(x * x, size) / np.maximum(ndimage.uniform_filter(w, size), 1e-6)
    var = mean_sq - mean ** 2
    var = np.maximum(var, 0)
    overall_var = np.nanvar(arr)
    k = var / (var + overall_var + 1e-12)
    out = mean + k * (x - mean)
    out[~valid] = np.nan
    return out.astype(np.float32)


def sar_water_mask(sar_path, out_path=None, filter_size=5, min_pixels=50,
                   hist_range=(-40, 5), manual_thresh=None):
    """SAR 水体提取：Lee 滤波 -> dB -> Otsu 阈值 -> 形态学清理。"""
    arr, profile = read_band(sar_path)
    db = to_db(arr)
    db = lee_filter(db, size=filter_size)
    valid = np.isfinite(db)
    vals = db[valid]
    vals = vals[(vals > hist_range[0]) & (vals < hist_range[1])]
    if manual_thresh is not None:
        thr = manual_thresh
    else:
        thr = threshold_otsu(vals)
    water = valid & (db < thr)
    water = remove_small_objects(water, min_size=min_pixels)
    water = remove_small_holes(water, area_threshold=min_pixels)
    ratio = float(water.sum()) / float(valid.sum())
    print(f"  {sar_path}: Otsu 阈值={thr:.2f} dB, 水体占比={ratio*100:.2f}%")
    if out_path:
        write_raster(out_path, water.astype(np.uint8), profile, nodata=None)
    return water, profile, thr


def apply_slope_mask(water, slope_deg_arr, max_slope=5.0):
    """坡度大于 max_slope 的区域不可能是平坦洪水淹没区（排除山体阴影误报）。"""
    return water & (slope_deg_arr <= max_slope)


# ---------- 光学 ----------

def ndwi_water_mask(green_path, nir_path, out_path=None, thresh=0.05,
                    green_band=1, nir_band=1, min_pixels=50):
    g, profile = read_band(green_path, green_band)
    n, _ = read_band(nir_path, nir_band)
    denom = g + n
    ndwi = np.where(denom > 0, (g - n) / np.maximum(denom, 1e-6), np.nan)
    water = np.isfinite(ndwi) & (ndwi > thresh)
    water = remove_small_objects(water, min_size=min_pixels)
    water = remove_small_holes(water, area_threshold=min_pixels)
    print(f"  NDWI>{thresh}: 水体占比={water.sum()/max(np.isfinite(ndwi).sum(),1)*100:.2f}%")
    if out_path:
        write_raster(out_path, water.astype(np.uint8), profile)
    return water, profile


def cloud_mask_bright(bands, thresh=3000):
    """简单亮白云检测：所有波段反射率/DN 均高的像元判为云。"""
    bright = np.ones_like(bands[0], dtype=bool)
    for b in bands:
        bright &= b > thresh
    return binary_opening(bright, disk(3))


# ---------- 变化检测 ----------

def combine_union(masks):
    out = np.zeros_like(masks[0], dtype=bool)
    for m in masks:
        out |= m
    return out


def combine_intersection(masks):
    out = np.ones_like(masks[0], dtype=bool)
    for m in masks:
        out &= m
    return out


def mask_difference(a, b):
    """在 a 中但不在 b 中。"""
    return a & ~b


# ---------- 矢量导出 ----------

def raster_to_shapefile(mask, profile, out_shp, value_field="water"):
    import geopandas as gpd
    from shapely.geometry import shape
    results = []
    for geom, val in shapes(mask.astype(np.uint8), mask=mask, transform=profile["transform"]):
        if val == 1:
            results.append({value_field: 1, "geometry": shape(geom)})
    gdf = gpd.GeoDataFrame(results, crs=profile["crs"])
    gdf.to_file(out_shp)
    print(f"  wrote {out_shp} ({len(gdf)} 个图斑)")
    return gdf
