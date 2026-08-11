#!/usr/bin/env python3
"""生成Task_14统一网格与县区高程统计、总质量报告和交付校验清单。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import rasterio
from pyproj import CRS
from rasterstats import zonal_stats


EXPECTED_GRID_COUNT = 22_770
EXPECTED_RELATION_COUNT = 24_033
EXPECTED_COUNTY_COUNT = 12
NODATA = -9999


class SummaryValidationError(RuntimeError):
    """当网格、县区统计或交付检查失败时抛出。"""


def sha256_file(path: Path) -> str:
    """计算文件SHA256。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_stat(value: Any) -> float | int | None:
    """把栅格统计值转换为可写入CSV的标准数值。"""
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def calculate_statistics(geometries: gpd.GeoSeries, raster_path: Path) -> list[dict[str, Any]]:
    """对指定几何批量计算高程统计。"""
    return zonal_stats(
        geometries,
        raster_path,
        stats=["min", "max", "mean", "std", "count"],
        nodata=NODATA,
        all_touched=False,
    )


def grid_quality_flag(valid_count: int, area_m2: float, ratio: float | None) -> str:
    """依据有效像元与边界面积关系标记网格统计质量。"""
    if valid_count == 0:
        return "no_valid_pixel_center"
    if area_m2 < 900:
        return "small_boundary_sliver"
    if ratio is None or ratio < 0.8 or ratio > 1.2:
        return "review_coverage_ratio"
    return "pass"


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    """以UTF-8 BOM格式输出SmartBI友好CSV。"""
    frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")


def manifest_entry(repository: Path, relative_path: str, category: str,
                   description: str, crs: str = "", record_count: int | str = "") -> dict[str, Any]:
    """创建交付文件清单记录。"""
    path = repository / relative_path
    return {
        "relative_path": relative_path.replace("\\", "/"),
        "category": category,
        "format": path.suffix.lower().lstrip("."),
        "crs": crs,
        "record_count": record_count,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "description": description,
    }


def write_manifest_and_checksums(repository: Path, task_root: Path,
                                 entries: list[dict[str, Any]]) -> None:
    """写入文件清单，并校验Task_14全部正式交付文件。"""
    manifest = task_root / "file_manifest.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(entries[0]))
        writer.writeheader()
        writer.writerows(entries)

    checksum_files = [task_root / "README.md", manifest]
    checksum_files.extend(sorted((task_root / "data/raw/aster_gdem_v3").glob("*.zip")))
    checksum_files.extend(sorted((task_root / "data/processed").glob("*")))
    checksum_files.extend(sorted((task_root / "reports").glob("*")))
    checksum_files.extend(sorted((task_root / "scripts").glob("*.py")))
    unique_files = sorted({path.resolve() for path in checksum_files if path.is_file()})
    lines = [
        f"{sha256_file(path)}  {path.relative_to(task_root.resolve()).as_posix()}"
        for path in unique_files
    ]
    (task_root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    """执行网格统计、县区汇总和最终交付验收。"""
    repository = Path(__file__).resolve().parents[2]
    task_root = repository / "Task_14"
    processed_root = task_root / "data/processed"
    reports_root = task_root / "reports"
    dem_path = processed_root / "nanning_dem_30m_albers.tif"
    if not dem_path.is_file():
        raise SummaryValidationError("缺少30 m分析DEM，请先运行build_nanning_dem.py")

    source_report = json.loads((reports_root / "source_validation_report.json").read_text(encoding="utf-8"))
    build_report = json.loads((reports_root / "build_report.json").read_text(encoding="utf-8"))
    if source_report.get("status") != "PASS" or build_report.get("status") != "PASS":
        raise SummaryValidationError("源数据或DEM构建报告不是PASS")

    relations = pd.read_csv(
        repository / "Task_05/data/grid/gx_grid_county_relation.csv",
        dtype={"grid_id": "string", "city_adcode": "string", "county_adcode": "string"},
    )
    nanning_relations = relations.loc[relations["city_adcode"] == "450100"].copy()
    if len(nanning_relations) != EXPECTED_RELATION_COUNT:
        raise SummaryValidationError(
            f"南宁市网格关系数量异常: {len(nanning_relations)} != {EXPECTED_RELATION_COUNT}"
        )
    grid_area = (
        nanning_relations.groupby("grid_id", as_index=False)
        .agg(
            nanning_area_m2=("intersection_area_m2", "sum"),
            related_county_count=("county_adcode", "nunique"),
        )
    )
    if len(grid_area) != EXPECTED_GRID_COUNT or grid_area["grid_id"].duplicated().any():
        raise SummaryValidationError(f"南宁市唯一网格数量异常: {len(grid_area)}")

    grids = gpd.read_file(repository / "Task_05/data/grid/gx_grid_1km.gpkg")
    selected = grids.loc[grids["grid_id"].astype("string").isin(set(grid_area["grid_id"]))].copy()
    selected["grid_id"] = selected["grid_id"].astype("string")
    if len(selected) != EXPECTED_GRID_COUNT or selected["grid_id"].duplicated().any():
        raise SummaryValidationError(f"Task_05网格筛选结果异常: {len(selected)}")
    with rasterio.open(dem_path) as dataset:
        if not CRS.from_user_input(selected.crs).equals(CRS.from_user_input(dataset.crs)):
            raise SummaryValidationError("Task_05网格与Task_14 DEM坐标系不一致")

    selected = selected.sort_values("grid_id").reset_index(drop=True)
    grid_stats = calculate_statistics(selected.geometry, dem_path)
    statistics = pd.DataFrame(grid_stats).rename(columns={
        "min": "elevation_min_m",
        "max": "elevation_max_m",
        "mean": "elevation_mean_m",
        "std": "elevation_std_m",
        "count": "valid_pixel_count",
    })
    result = pd.concat([
        selected[["grid_id", "center_lon", "center_lat"]].reset_index(drop=True),
        statistics,
    ], axis=1)
    result = result.merge(grid_area, on="grid_id", how="left", validate="one_to_one")
    result["valid_pixel_count"] = result["valid_pixel_count"].fillna(0).astype("int64")
    result["valid_area_m2"] = result["valid_pixel_count"] * 900.0
    result["valid_coverage_ratio"] = result.apply(
        lambda row: row["valid_area_m2"] / row["nanning_area_m2"]
        if row["nanning_area_m2"] > 0 else None,
        axis=1,
    )
    for column in ["elevation_min_m", "elevation_max_m", "elevation_mean_m", "elevation_std_m"]:
        result[column] = result[column].map(normalize_stat)
    result["quality_flag"] = result.apply(
        lambda row: grid_quality_flag(
            int(row["valid_pixel_count"]),
            float(row["nanning_area_m2"]),
            normalize_stat(row["valid_coverage_ratio"]),
        ),
        axis=1,
    )
    result["data_source"] = "ASTER GDEM V3"
    result["dem_resolution_m"] = 30
    grid_output = processed_root / "nanning_dem_grid_1km.csv"
    write_csv(result, grid_output)

    counties = gpd.read_file(repository / "Task_01/data/processed/nanning_county_boundary_projected.gpkg")
    counties = counties.sort_values("county_adcode").reset_index(drop=True)
    if len(counties) != EXPECTED_COUNTY_COUNT:
        raise SummaryValidationError(f"南宁市县区数量异常: {len(counties)}")
    county_stats = pd.DataFrame(calculate_statistics(counties.geometry, dem_path)).rename(columns={
        "min": "elevation_min_m",
        "max": "elevation_max_m",
        "mean": "elevation_mean_m",
        "std": "elevation_std_m",
        "count": "valid_pixel_count",
    })
    county_result = pd.concat([
        counties[["county_adcode", "county_name"]].reset_index(drop=True),
        county_stats,
    ], axis=1)
    county_result["county_area_m2"] = counties.geometry.area
    county_result["valid_area_m2"] = county_result["valid_pixel_count"] * 900.0
    county_result["valid_coverage_ratio"] = county_result["valid_area_m2"] / county_result["county_area_m2"]
    county_result["data_source"] = "ASTER GDEM V3"
    county_result["dem_resolution_m"] = 30
    county_output = processed_root / "nanning_dem_county_summary.csv"
    write_csv(county_result, county_output)

    flag_counts = {str(key): int(value) for key, value in result["quality_flag"].value_counts().items()}
    failures = []
    if len(result) != EXPECTED_GRID_COUNT or result["grid_id"].duplicated().any():
        failures.append("1 km网格统计主键检查失败")
    if len(county_result) != EXPECTED_COUNTY_COUNT or county_result["county_adcode"].duplicated().any():
        failures.append("县区统计主键检查失败")
    if int((county_result["valid_pixel_count"] == 0).sum()) != 0:
        failures.append("存在无有效DEM像元的县区")
    if flag_counts.get("no_valid_pixel_center", 0) > 100:
        failures.append("无有效DEM像元中心的边界网格超过100个")

    quality_report = {
        "task": "Task_14",
        "dataset": "南宁市DEM高程数据",
        "source_validation_status": source_report["status"],
        "dem_build_status": build_report["status"],
        "dem": build_report["output"],
        "grid_statistics": {
            "relation_row_count": int(len(nanning_relations)),
            "unique_grid_count": int(len(result)),
            "duplicate_grid_id_count": int(result["grid_id"].duplicated().sum()),
            "nanning_area_sum_m2": float(result["nanning_area_m2"].sum()),
            "quality_flag_counts": flag_counts,
            "minimum_elevation_m": normalize_stat(result["elevation_min_m"].min()),
            "maximum_elevation_m": normalize_stat(result["elevation_max_m"].max()),
        },
        "county_statistics": {
            "county_count": int(len(county_result)),
            "duplicate_county_adcode_count": int(county_result["county_adcode"].duplicated().sum()),
            "county_adcodes": sorted(county_result["county_adcode"].astype(str).tolist()),
            "zero_valid_pixel_count": int((county_result["valid_pixel_count"] == 0).sum()),
        },
        "vertical_reference_policy": "沿用ASTER源高程含义；源文件未编码垂直CRS且未执行垂直转换",
        "num_layer_policy": "仅保留并统计源质量辅助层，不作为高程或风险指标",
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }
    quality_path = reports_root / "quality_report.json"
    quality_path.write_text(
        json.dumps(quality_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if failures:
        raise SummaryValidationError("；".join(failures))

    analysis_crs_name = build_report["output"]["crs_name"]
    entries = []
    for archive in sorted((task_root / "data/raw/aster_gdem_v3").glob("*.zip")):
        entries.append(manifest_entry(
            repository,
            archive.relative_to(repository).as_posix(),
            "raw",
            "ASTER GDEM V3原始ZIP，含DEM与NUM层",
        ))
    entries.extend([
        manifest_entry(repository, dem_path.relative_to(repository).as_posix(), "data", "南宁市30 m分析DEM", analysis_crs_name, int(build_report["output"]["valid_pixel_count"])),
        manifest_entry(repository, grid_output.relative_to(repository).as_posix(), "data", "Task_05统一1 km网格高程统计", "grid_id", len(result)),
        manifest_entry(repository, county_output.relative_to(repository).as_posix(), "data", "南宁市12县区高程汇总", "county_adcode", len(county_result)),
        manifest_entry(repository, "Task_14/reports/source_tile_inventory.csv", "report", "ASTER原始瓦片清单", "EPSG:4326", 7),
        manifest_entry(repository, "Task_14/reports/source_validation_report.json", "report", "原始数据、接缝和覆盖验证"),
        manifest_entry(repository, "Task_14/reports/build_report.json", "report", "30 m DEM构建与COG验证"),
        manifest_entry(repository, "Task_14/reports/quality_report.json", "report", "Task_14最终质量报告"),
        manifest_entry(repository, "Task_14/reports/data_lineage.md", "documentation", "Task_14数据血缘说明"),
    ])
    write_manifest_and_checksums(repository, task_root, entries)
    print(
        f"Task_14统计完成：{len(result)}个网格、{len(county_result)}个县区，"
        f"质量状态PASS。"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, SummaryValidationError) as error:
        print(f"Task_14统计失败：{error}", file=sys.stderr)
        sys.exit(1)
