#!/usr/bin/env python3
"""检查Task_17两个GlobeLand30原始包、类别编码、影像索引和南宁市覆盖。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import box


EXPECTED_TILES = {
    "N48_20_2020LC030": {"epsg": 32648, "width": 21431, "height": 18969},
    "N49_20_2020LC030": {"epsg": 32649, "width": 21430, "height": 18969},
}
EXPECTED_FILES_PER_TILE = 9
EXPECTED_TOTAL_FILES = 18
EXPECTED_SOURCE_SIZE_BYTES = 47_561_716
OFFICIAL_CODES = {10, 20, 30, 40, 50, 60, 70, 80, 90, 100}
SPECIAL_CODES = {0, 255}


class SourceValidationError(RuntimeError):
    """当原始包、类别或覆盖检查失败时抛出。"""


def sha256_file(path: Path) -> str:
    """分块计算文件SHA256。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def raster_code_counts(path: Path) -> dict[int, int]:
    """按块统计分类栅格编码，避免整幅载入内存。"""
    counts: dict[int, int] = {}
    with rasterio.open(path) as dataset:
        for _, window in dataset.block_windows(1):
            values, numbers = np.unique(dataset.read(1, window=window), return_counts=True)
            for value, number in zip(values, numbers):
                code = int(value)
                counts[code] = counts.get(code, 0) + int(number)
    return dict(sorted(counts.items()))


def raster_metadata(path: Path) -> dict[str, Any]:
    """读取分类栅格结构、范围、调色板和编码统计。"""
    counts = raster_code_counts(path)
    with rasterio.open(path) as dataset:
        colormap = dataset.colormap(1)
        return {
            "file": path.name,
            "driver": dataset.driver,
            "width": int(dataset.width),
            "height": int(dataset.height),
            "dtype": str(dataset.dtypes[0]),
            "crs": str(dataset.crs),
            "epsg": dataset.crs.to_epsg() if dataset.crs else None,
            "resolution": [float(dataset.res[0]), float(dataset.res[1])],
            "bounds": [float(value) for value in dataset.bounds],
            "nodata_metadata": dataset.nodata,
            "color_interpretation": dataset.colorinterp[0].name,
            "color_table_entry_count": len(colormap),
            "code_counts": {str(code): count for code, count in counts.items()},
            "codes": list(counts),
        }


def main() -> int:
    """生成原始文件清单和源数据质量报告。"""
    repository = Path(__file__).resolve().parents[2]
    task_root = repository / "Task_17"
    raw_root = task_root / "data/raw/globeland30_2020"
    reports_root = task_root / "reports"
    lookup_path = task_root / "data/processed/landcover_class_lookup.csv"
    boundary_path = repository / "Task_01/data/processed/nanning_county_boundary_projected.gpkg"
    reports_root.mkdir(parents=True, exist_ok=True)

    lookup = pd.read_csv(lookup_path)
    lookup_codes = set(lookup["class_code"].astype(int))
    if lookup_codes != OFFICIAL_CODES | SPECIAL_CODES or lookup["class_code"].duplicated().any():
        raise SourceValidationError("类别字典编码不完整或重复")

    inventory: list[dict[str, Any]] = []
    tile_reports: list[dict[str, Any]] = []
    footprints = []
    total_size = 0
    boundaries = gpd.read_file(boundary_path)
    city = boundaries.geometry.union_all()
    analysis_crs = boundaries.crs

    for tile_name, expected in EXPECTED_TILES.items():
        tile_root = raw_root / tile_name
        files = sorted(path for path in tile_root.iterdir() if path.is_file())
        if len(files) != EXPECTED_FILES_PER_TILE:
            raise SourceValidationError(f"{tile_name}文件数量不是{EXPECTED_FILES_PER_TILE}")
        for path in files:
            relative = path.relative_to(task_root).as_posix()
            inventory.append({
                "tile": tile_name,
                "relative_path": relative,
                "extension": path.suffix.lower(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
            total_size += path.stat().st_size

        tifs = list(tile_root.glob("*.tif"))
        xls_files = list(tile_root.glob("*_MAT.xls"))
        shp_files = list(tile_root.glob("*_IMG.shp"))
        if len(tifs) != 1 or len(xls_files) != 1 or len(shp_files) != 1:
            raise SourceValidationError(f"{tile_name}主TIF、MAT或IMG索引数量异常")
        metadata = raster_metadata(tifs[0])
        if metadata["epsg"] != expected["epsg"]:
            raise SourceValidationError(f"{tile_name} EPSG异常: {metadata['epsg']}")
        if [metadata["width"], metadata["height"]] != [expected["width"], expected["height"]]:
            raise SourceValidationError(f"{tile_name}栅格尺寸异常")
        if metadata["dtype"] != "uint8" or metadata["resolution"] != [30.0, 30.0]:
            raise SourceValidationError(f"{tile_name}数据类型或分辨率异常")
        unknown_codes = set(metadata["codes"]) - lookup_codes
        if unknown_codes:
            raise SourceValidationError(f"{tile_name}存在未知编码: {sorted(unknown_codes)}")

        image_index = gpd.read_file(shp_files[0])
        dates = pd.to_datetime(image_index["Date"].astype(str), format="%Y%m%d", errors="coerce")
        if dates.isna().any() or not image_index.geometry.is_valid.all():
            raise SourceValidationError(f"{tile_name}影像索引日期或几何异常")
        with rasterio.open(tifs[0]) as dataset:
            footprint = gpd.GeoSeries([box(*dataset.bounds)], crs=dataset.crs).to_crs(analysis_crs).iloc[0]
        footprints.append(footprint)
        tile_reports.append({
            "tile": tile_name,
            "raster": metadata,
            "mat_metadata_file": xls_files[0].name,
            "metadata_transcription_policy": "原始XLS保留并校验；类别由已核验MAT转录为UTF-8 CSV",
            "image_index": {
                "feature_count": int(len(image_index)),
                "sensor_values": sorted(image_index["Sensor"].dropna().astype(str).unique().tolist()),
                "resolution_values": sorted(int(value) for value in image_index["Resolution"].dropna().unique()),
                "minimum_date": dates.min().strftime("%Y-%m-%d"),
                "maximum_date": dates.max().strftime("%Y-%m-%d"),
                "pathrow_count": int(image_index["PathRow"].nunique()),
            },
            "nanning_coverage_area_km2": float(city.intersection(footprint).area / 1e6),
            "nanning_coverage_ratio": float(city.intersection(footprint).area / city.area),
        })

    if len(inventory) != EXPECTED_TOTAL_FILES or total_size != EXPECTED_SOURCE_SIZE_BYTES:
        raise SourceValidationError(
            f"原始文件总量异常: {len(inventory)}文件/{total_size}字节"
        )
    union = footprints[0].union(footprints[1])
    overlap = footprints[0].intersection(footprints[1])
    covered = city.intersection(union)
    uncovered = city.difference(union)
    county_coverages = {
        str(row.county_adcode): {
            "county_name": row.county_name,
            "coverage_ratio": float(row.geometry.intersection(union).area / row.geometry.area),
        }
        for row in boundaries.itertuples()
    }
    failures = []
    if not math.isclose(covered.area, city.area, rel_tol=0.0, abs_tol=1.0):
        failures.append("两图幅未完整覆盖南宁市")
    if any(value["coverage_ratio"] < 0.999999 for value in county_coverages.values()):
        failures.append("存在未被完整覆盖的县区")

    inventory_path = reports_root / "source_inventory.csv"
    with inventory_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(inventory[0]))
        writer.writeheader()
        writer.writerows(inventory)
    report = {
        "task": "Task_17",
        "source_product": "GlobeLand30 2020",
        "publisher": "Ministry of Natural Resources of the People's Republic of China / 自然资源部",
        "distribution_institution": "National Geomatics Center of China / 国家基础地理信息中心",
        "source_reported_overall_accuracy": "85.72%",
        "source_file_count": len(inventory),
        "source_size_bytes": total_size,
        "official_class_codes": sorted(OFFICIAL_CODES),
        "special_codes": {"0": "No Value/无值", "255": "Sea/海水"},
        "tiles": tile_reports,
        "coverage": {
            "nanning_area_km2": float(city.area / 1e6),
            "covered_area_km2": float(covered.area / 1e6),
            "coverage_ratio": float(covered.area / city.area),
            "uncovered_area_m2": float(uncovered.area),
            "overlap_area_in_nanning_km2": float(city.intersection(overlap).area / 1e6),
            "county_coverages": county_coverages,
        },
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }
    (reports_root / "source_validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if failures:
        raise SourceValidationError("；".join(failures))
    print(
        f"Task_17源检查完成：{len(inventory)}个文件，联合覆盖率100%，"
        f"重叠{report['coverage']['overlap_area_in_nanning_km2']:.2f} km²，状态PASS。"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, SourceValidationError,
            rasterio.errors.RasterioError) as error:
        print(f"Task_17源检查失败：{error}", file=sys.stderr)
        sys.exit(1)
