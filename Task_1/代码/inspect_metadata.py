# -*- coding: utf-8 -*-
"""Phase 2: 数据质量检查 —— 扫描解压后的数据集，输出影像清单表。

用法:
    python inspect_metadata.py --root D:/SmartAI/data/raw --out D:/SmartAI/outputs/影像清单表.csv
"""
import argparse
import os
import re
import xml.etree.ElementTree as ET

IMG_EXT = {".tif", ".tiff", ".img"}


def find_files(root):
    for dirpath, _, files in os.walk(root):
        for f in files:
            yield os.path.join(dirpath, f)


def parse_xml_meta(path):
    """从元数据 XML 中提取常见字段（不同卫星字段名不同，尽量多抓）。"""
    info = {}
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return info
    text = open(path, encoding="utf-8", errors="ignore").read()
    keys = {
        "satellite": ["SatelliteID", "satellite", "SensorID"],
        "sensor": ["SensorID", "sensor"],
        "acquire_time": ["StartTime", "ReceiveTime", "ImagingTime", "ProduceTime"],
        "cloud_cover": ["CloudPercent", "cloudCover", "CloudCover"],
        "resolution": ["ImageGSD", "Resolution", "resolution"],
        "top_left_lat": ["TopLeftLatitude"], "top_left_lon": ["TopLeftLongitude"],
        "top_right_lat": ["TopRightLatitude"], "top_right_lon": ["TopRightLongitude"],
        "bottom_left_lat": ["BottomLeftLatitude"], "bottom_left_lon": ["BottomLeftLongitude"],
        "bottom_right_lat": ["BottomRightLatitude"], "bottom_right_lon": ["BottomRightLongitude"],
    }
    for field, tags in keys.items():
        for t in tags:
            m = re.search(rf"<{t}>\s*([^<]+?)\s*</{t}>", text)
            if m:
                info[field] = m.group(1)
                break
    return info


def tif_info(path):
    try:
        import rasterio
    except ImportError:
        return {"error": "rasterio 未安装"}
    try:
        with rasterio.open(path) as ds:
            return {
                "width": ds.width, "height": ds.height, "bands": ds.count,
                "dtype": ds.dtypes[0],
                "crs": str(ds.crs),
                "res_x": round(abs(ds.transform.a), 3),
                "res_y": round(abs(ds.transform.e), 3),
                "size_mb": round(os.path.getsize(path) / 1e6, 1),
            }
    except Exception as e:
        return {"error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import csv
    rows = []
    for p in find_files(args.root):
        ext = os.path.splitext(p)[1].lower()
        rel = os.path.relpath(p, args.root)
        dataset = rel.split(os.sep)[0]
        if ext in IMG_EXT:
            info = tif_info(p)
            info.update({"dataset": dataset, "file": os.path.basename(p), "type": "image"})
            rows.append(info)
        elif ext == ".xml":
            info = parse_xml_meta(p)
            if info:
                info.update({"dataset": dataset, "file": os.path.basename(p), "type": "xml_meta"})
                rows.append(info)

    all_keys = ["dataset", "file", "type", "satellite", "sensor", "acquire_time",
                "cloud_cover", "resolution", "width", "height", "bands", "dtype",
                "crs", "res_x", "res_y", "size_mb",
                "top_left_lat", "top_left_lon", "top_right_lat", "top_right_lon",
                "bottom_left_lat", "bottom_left_lon", "bottom_right_lat", "bottom_right_lon",
                "error"]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"wrote {len(rows)} rows -> {args.out}")
    # 同时打印目录结构概览
    for dirpath, dirnames, files in os.walk(args.root):
        depth = dirpath.replace(args.root, "").count(os.sep)
        if depth <= 2:
            print("  " * depth + os.path.basename(dirpath) + f"  [{len(files)} files]")


if __name__ == "__main__":
    main()
