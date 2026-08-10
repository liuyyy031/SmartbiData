# -*- coding: utf-8 -*-
"""Phase 7: 结果矢量化 —— 导出 Shapefile/GeoJSON 供后续任务（灾中救助/灾后治理）使用。

输出到 deliverables/数据/:
    pre_water.shp / .geojson      灾前正常水体
    new_flood.shp / .geojson      灾中新增淹没
    recession.shp / .geojson      消退分析（class 字段: 1水体 2仍淹 3已消退）
用法: python export_vectors.py
"""
import os
import numpy as np
import rasterio
from rasterio.features import shapes
import geopandas as gpd
from shapely.geometry import shape

FINAL = "D:/SmartAI/data/results/final"
OUT = "D:/SmartAI/deliverables/数据"
NODATA = 255

CLASS_NAMES = {1: "水体(含灾前)", 2: "新增淹没-仍淹", 3: "新增淹没-已消退"}


def export(raster, out_base, field, classes=None):
    with rasterio.open(raster) as ds:
        arr = ds.read(1)
        transform = ds.transform
        crs = ds.crs
    recs = []
    vals = classes if classes else [1]
    for geom, val in shapes(arr, mask=np.isin(arr, vals), transform=transform):
        v = int(val)
        if v not in vals:
            continue
        recs.append({field: v, "类型": CLASS_NAMES.get(v, "水体") if classes else "水体",
                     "geometry": shape(geom)})
    gdf = gpd.GeoDataFrame(recs, crs=crs)
    # 面积（公顷）
    gdf["面积ha"] = (gdf.geometry.area / 1e4).round(3)
    gdf = gdf[gdf["面积ha"] >= 0.5]  # 矢量层面再去掉过小图斑
    gdf.to_file(os.path.join(OUT, out_base + ".shp"), encoding="utf-8")
    gdf.to_file(os.path.join(OUT, out_base + ".geojson"), driver="GeoJSON")
    print(f"{out_base}: {len(gdf)} 个图斑, 总面积 {gdf['面积ha'].sum()/100:.2f} km²")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(OUT, exist_ok=True)
    export(os.path.join(FINAL, "pre_water.tif"), "灾前正常水体_pre_water", "water")
    export(os.path.join(FINAL, "new_flood.tif"), "灾中新增淹没_new_flood", "flood")
    export(os.path.join(FINAL, "recession.tif"), "洪水消退分析_recession", "class", classes=[1, 2, 3])
