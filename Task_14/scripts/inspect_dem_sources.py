#!/usr/bin/env python3
"""检查Task_14原始ASTER ZIP、瓦片元数据、接缝和南宁市覆盖范围。"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import CRS
from shapely.geometry import box
from shapely.ops import unary_union


EXPECTED_TILES = {
    "ASTGTMV003_N22E107", "ASTGTMV003_N22E108", "ASTGTMV003_N22E109",
    "ASTGTMV003_N23E107", "ASTGTMV003_N23E108", "ASTGTMV003_N23E109",
    "ASTGTMV003_N24E108",
}


class SourceValidationError(RuntimeError):
    """当DEM原始来源不满足硬性条件时抛出。"""


def sha256_file(path: Path) -> str:
    """计算文件SHA256。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archive_members(path: Path) -> tuple[str, str]:
    """校验ZIP并返回唯一DEM和NUM条目。"""
    with zipfile.ZipFile(path) as archive:
        damaged = archive.testzip()
        if damaged is not None:
            raise SourceValidationError(f"ZIP存在损坏条目: {path.name}/{damaged}")
        names = archive.namelist()
    dem = [name for name in names if name.lower().endswith("_dem.tif")]
    num = [name for name in names if name.lower().endswith("_num.tif")]
    if len(names) != 2 or len(dem) != 1 or len(num) != 1:
        raise SourceValidationError(f"ZIP条目不符合预期: {path.name} -> {names}")
    return dem[0], num[0]


def vsi_path(archive: Path, member: str) -> str:
    """构造GDAL可读取的ZIP内部路径。"""
    return f"/vsizip/{archive.resolve().as_posix()}/{member}"


def raster_summary(path: str, read_values: bool = True) -> tuple[dict[str, Any], np.ndarray | None]:
    """读取栅格元数据，并可选计算完整像元统计。"""
    with rasterio.open(path) as dataset:
        array = dataset.read(1) if read_values else None
        summary: dict[str, Any] = {
            "width": int(dataset.width),
            "height": int(dataset.height),
            "count": int(dataset.count),
            "dtype": str(dataset.dtypes[0]),
            "crs": str(dataset.crs),
            "resolution_x": float(dataset.res[0]),
            "resolution_y": float(dataset.res[1]),
            "bounds": [float(value) for value in dataset.bounds],
            "nodata": dataset.nodata,
        }
        if array is not None:
            summary.update({
                "minimum": int(array.min()),
                "maximum": int(array.max()),
                "count_below_minus_500": int((array < -500).sum()),
                "count_equal_minus_9999": int((array == -9999).sum()),
            })
        return summary, array


def tile_key(name: str) -> tuple[int, int]:
    """从ASTER瓦片名提取纬度和经度整数索引。"""
    latitude = int(name.split("_N", 1)[1].split("E", 1)[0])
    longitude = int(name.rsplit("E", 1)[1])
    return latitude, longitude


def seam_statistics(arrays: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    """比较共享一像元边界的相邻DEM瓦片。"""
    by_key = {tile_key(name): (name, array) for name, array in arrays.items()}
    results: list[dict[str, Any]] = []
    for (latitude, longitude), (name, array) in sorted(by_key.items()):
        east = by_key.get((latitude, longitude + 1))
        if east is not None:
            other_name, other = east
            difference = np.abs(array[:, -1].astype(np.int32) - other[:, 0].astype(np.int32))
            results.append({
                "left_tile": name, "right_tile": other_name, "direction": "east_west",
                "sample_count": int(difference.size),
                "maximum_absolute_difference_m": int(difference.max()),
                "mean_absolute_difference_m": float(difference.mean()),
                "equal_pixel_ratio": float((difference == 0).mean()),
            })
        north = by_key.get((latitude + 1, longitude))
        if north is not None:
            other_name, other = north
            difference = np.abs(array[0, :].astype(np.int32) - other[-1, :].astype(np.int32))
            results.append({
                "lower_tile": name, "upper_tile": other_name, "direction": "south_north",
                "sample_count": int(difference.size),
                "maximum_absolute_difference_m": int(difference.max()),
                "mean_absolute_difference_m": float(difference.mean()),
                "equal_pixel_ratio": float((difference == 0).mean()),
            })
    return results


def main() -> int:
    """生成原始瓦片清单和来源验证报告。"""
    repository = Path(__file__).resolve().parents[2]
    task_root = repository / "Task_14"
    raw_root = task_root / "data/raw/aster_gdem_v3"
    report_root = task_root / "reports"
    archives = sorted(raw_root.glob("ASTGTMV003_*.zip"))
    names = {path.stem for path in archives}
    if len(archives) != 7 or names != EXPECTED_TILES:
        raise SourceValidationError(f"原始瓦片集合错误: {sorted(names)}")

    boundary = gpd.read_file(repository / "Task_01/data/processed/nanning_county_boundary.gpkg")
    config = json.loads((repository / "Task_06/config/spatial_crs.json").read_text(encoding="utf-8"))
    analysis_crs = CRS.from_wkt(config["preferred_crs_input"]["analysis"])
    arrays: dict[str, np.ndarray] = {}
    footprints = []
    rows: list[dict[str, Any]] = []

    for archive in archives:
        dem_member, num_member = archive_members(archive)
        dem, array = raster_summary(vsi_path(archive, dem_member))
        num, num_array = raster_summary(vsi_path(archive, num_member))
        if array is None or num_array is None:
            raise SourceValidationError(f"未读取到栅格数组: {archive.name}")
        if (dem["width"], dem["height"], dem["dtype"], dem["crs"]) != (3601, 3601, "int16", "EPSG:4326"):
            raise SourceValidationError(f"DEM规格异常: {archive.name} -> {dem}")
        if (num["width"], num["height"], num["dtype"], num["crs"]) != (3601, 3601, "uint8", "EPSG:4326"):
            raise SourceValidationError(f"NUM规格异常: {archive.name} -> {num}")
        if dem["count_below_minus_500"] or dem["count_equal_minus_9999"]:
            raise SourceValidationError(f"DEM发现异常低值或-9999: {archive.name}")
        arrays[archive.stem] = array
        footprint = box(*dem["bounds"])
        footprints.append(footprint)
        intersection = boundary.geometry.intersection(footprint)
        intersection_area = float(
            gpd.GeoSeries(intersection, crs=boundary.crs).to_crs(analysis_crs).area.sum()
        )
        values, counts = np.unique(num_array, return_counts=True)
        top_num = sorted(zip(values.tolist(), counts.tolist()), key=lambda item: item[1], reverse=True)[:8]
        rows.append({
            "tile_id": archive.stem,
            "archive_file": archive.name,
            "archive_size_bytes": archive.stat().st_size,
            "archive_sha256": sha256_file(archive),
            "dem_member": dem_member,
            "num_member": num_member,
            "dem_crs": dem["crs"],
            "dem_width": dem["width"],
            "dem_height": dem["height"],
            "dem_dtype": dem["dtype"],
            "dem_resolution_degree": dem["resolution_x"],
            "dem_minimum_m": dem["minimum"],
            "dem_maximum_m": dem["maximum"],
            "dem_nodata_metadata": dem["nodata"],
            "num_minimum": int(num_array.min()),
            "num_maximum": int(num_array.max()),
            "num_top_values": json.dumps(top_num, ensure_ascii=False),
            "nanning_intersection_km2": intersection_area / 1_000_000,
            "zip_integrity": "PASS",
        })

    boundary_area = float(boundary.to_crs(analysis_crs).area.sum())
    covered = boundary.geometry.intersection(unary_union(footprints))
    covered_area = float(gpd.GeoSeries(covered, crs=boundary.crs).to_crs(analysis_crs).area.sum())
    coverage_ratio = covered_area / boundary_area
    seams = seam_statistics(arrays)
    failures = []
    if abs(coverage_ratio - 1.0) > 1e-10:
        failures.append("南宁市边界未被原始DEM完全覆盖")
    if any(item["maximum_absolute_difference_m"] != 0 for item in seams):
        failures.append("相邻瓦片共享边缘存在高程差异")

    inventory = report_root / "source_tile_inventory.csv"
    with inventory.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    report = {
        "task": "Task_14",
        "source_product": "ASTER GDEM V3",
        "acquisition_channel": "地理空间数据云（GSCloud）",
        "vertical_crs_metadata": None,
        "vertical_reference_policy": "源文件未编码垂直CRS；Task_14不执行垂直基准转换",
        "archive_count": len(archives),
        "archive_total_size_bytes": sum(path.stat().st_size for path in archives),
        "tile_ids": sorted(names),
        "dem_global_minimum_m": min(row["dem_minimum_m"] for row in rows),
        "dem_global_maximum_m": max(row["dem_maximum_m"] for row in rows),
        "nanning_coverage": {
            "boundary_area_km2": boundary_area / 1_000_000,
            "covered_area_km2": covered_area / 1_000_000,
            "uncovered_area_m2": boundary_area - covered_area,
            "coverage_ratio": coverage_ratio,
        },
        "seam_validation": seams,
        "num_layer_policy": "仅记录分布，不作为高程、风险值或自动删值依据",
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }
    (report_root / "source_validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if failures:
        raise SourceValidationError("；".join(failures))
    print("Task_14原始DEM检查完成：7个ZIP，覆盖率100%，共享边缘一致。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, SourceValidationError) as error:
        print(f"Task_14原始DEM检查失败：{error}", file=sys.stderr)
        sys.exit(1)
