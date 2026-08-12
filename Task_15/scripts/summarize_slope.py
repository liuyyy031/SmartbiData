#!/usr/bin/env python3
"""生成Task_15统一网格与县区坡度统计、质量报告和交付校验清单。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS
from rasterstats import zonal_stats


EXPECTED_GRID_COUNT = 22_770
EXPECTED_RELATION_COUNT = 24_033
EXPECTED_COUNTY_COUNT = 12
NODATA = -9999.0
PIXEL_AREA_M2 = 900.0


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
    """把栅格统计值转换为CSV可表达的有限数值。"""
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def threshold_ratio(threshold: float) -> Callable[[np.ma.MaskedArray], float | None]:
    """构造以有效坡度像元为分母的阈值比例函数。"""
    def calculate(values: np.ma.MaskedArray) -> float | None:
        compressed = np.ma.asarray(values).compressed().astype(np.float64)
        finite = compressed[np.isfinite(compressed)]
        if finite.size == 0:
            return None
        return float((finite <= threshold).sum() / finite.size)
    return calculate


def calculate_statistics(geometries: gpd.GeoSeries, raster_path: Path) -> list[dict[str, Any]]:
    """对指定几何计算坡度描述统计和平缓地形比例。"""
    return zonal_stats(
        geometries,
        raster_path,
        stats=["min", "max", "mean", "std", "count"],
        add_stats={
            "slope_le_3deg_ratio": threshold_ratio(3.0),
            "slope_le_5deg_ratio": threshold_ratio(5.0),
            "slope_le_8deg_ratio": threshold_ratio(8.0),
        },
        nodata=NODATA,
        all_touched=False,
    )


def grid_quality_flag(valid_count: int, area_m2: float, ratio: float | None) -> str:
    """依据有效像元与南宁市相交面积标记网格统计质量。"""
    if valid_count == 0:
        return "no_valid_pixel_center"
    if area_m2 < PIXEL_AREA_M2:
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
    """写入文件清单和Task_15全部正式交付文件的校验值。"""
    manifest = task_root / "file_manifest.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(entries[0]))
        writer.writeheader()
        writer.writerows(entries)

    checksum_files = [task_root / "README.md", manifest]
    checksum_files.extend(sorted((task_root / "data/processed").glob("*")))
    checksum_files.extend(sorted((task_root / "reports").glob("*")))
    checksum_files.extend(sorted((task_root / "scripts").glob("*.py")))
    unique_files = sorted({path.resolve() for path in checksum_files if path.is_file()})
    lines = [
        f"{sha256_file(path)}  {path.relative_to(task_root.resolve()).as_posix()}"
        for path in unique_files
    ]
    (task_root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_ratios(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    """检查阈值比例值域与单调关系。"""
    failures: list[str] = []
    for column in columns:
        invalid = frame[column].dropna().loc[lambda values: (values < 0.0) | (values > 1.0)]
        if not invalid.empty:
            failures.append(f"{column}存在0至1范围外数值")
    valid = frame.dropna(subset=columns)
    if not ((valid[columns[0]] <= valid[columns[1]]) &
            (valid[columns[1]] <= valid[columns[2]])).all():
        failures.append("平缓坡度比例不满足3°≤5°≤8°单调关系")
    return failures


def main() -> int:
    """执行网格统计、县区汇总和最终交付验收。"""
    repository = Path(__file__).resolve().parents[2]
    task_root = repository / "Task_15"
    processed_root = task_root / "data/processed"
    reports_root = task_root / "reports"
    build_report_path = reports_root / "build_report.json"
    if not build_report_path.is_file():
        raise SummaryValidationError("缺少坡度栅格或构建报告，请先运行build_nanning_slope.py")
    build_report = json.loads(build_report_path.read_text(encoding="utf-8"))
    if build_report.get("status") != "PASS":
        raise SummaryValidationError("坡度构建报告不是PASS")
    slope_path = repository / build_report["output"]["file"]
    if not slope_path.is_file():
        raise SummaryValidationError("构建报告登记的坡度交付入口不存在")

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
    with rasterio.open(slope_path) as dataset:
        if not CRS.from_user_input(selected.crs).equals(CRS.from_user_input(dataset.crs)):
            raise SummaryValidationError("Task_05网格与Task_15坡度栅格坐标系不一致")

    selected = selected.sort_values("grid_id").reset_index(drop=True)
    statistics = pd.DataFrame(calculate_statistics(selected.geometry, slope_path)).rename(columns={
        "min": "slope_min_deg",
        "max": "slope_max_deg",
        "mean": "slope_mean_deg",
        "std": "slope_std_deg",
        "count": "valid_pixel_count",
    })
    result = pd.concat([
        selected[["grid_id", "center_lon", "center_lat"]].reset_index(drop=True),
        statistics,
    ], axis=1)
    result = result.merge(grid_area, on="grid_id", how="left", validate="one_to_one")
    result["valid_pixel_count"] = result["valid_pixel_count"].fillna(0).astype("int64")
    result["valid_area_m2"] = result["valid_pixel_count"] * PIXEL_AREA_M2
    result["valid_coverage_ratio"] = result.apply(
        lambda row: row["valid_area_m2"] / row["nanning_area_m2"]
        if row["nanning_area_m2"] > 0 else None,
        axis=1,
    )
    numeric_columns = [
        "slope_min_deg", "slope_max_deg", "slope_mean_deg", "slope_std_deg",
        "slope_le_3deg_ratio", "slope_le_5deg_ratio", "slope_le_8deg_ratio",
    ]
    for column in numeric_columns:
        result[column] = result[column].map(normalize_stat)
    result["quality_flag"] = result.apply(
        lambda row: grid_quality_flag(
            int(row["valid_pixel_count"]),
            float(row["nanning_area_m2"]),
            normalize_stat(row["valid_coverage_ratio"]),
        ),
        axis=1,
    )
    result["data_source"] = "Task_14 ASTER GDEM V3 30 m DEM"
    result["slope_algorithm"] = "GDAL Horn"
    result["slope_unit"] = "degree"
    result["raster_resolution_m"] = 30
    grid_output = processed_root / "nanning_slope_grid_1km.csv"
    write_csv(result, grid_output)

    counties = gpd.read_file(repository / "Task_01/data/processed/nanning_county_boundary_projected.gpkg")
    counties = counties.sort_values("county_adcode").reset_index(drop=True)
    if len(counties) != EXPECTED_COUNTY_COUNT:
        raise SummaryValidationError(f"南宁市县区数量异常: {len(counties)}")
    county_statistics = pd.DataFrame(calculate_statistics(counties.geometry, slope_path)).rename(columns={
        "min": "slope_min_deg",
        "max": "slope_max_deg",
        "mean": "slope_mean_deg",
        "std": "slope_std_deg",
        "count": "valid_pixel_count",
    })
    county_result = pd.concat([
        counties[["county_adcode", "county_name"]].reset_index(drop=True),
        county_statistics,
    ], axis=1)
    county_result["county_area_m2"] = counties.geometry.area
    county_result["valid_area_m2"] = county_result["valid_pixel_count"] * PIXEL_AREA_M2
    county_result["valid_coverage_ratio"] = (
        county_result["valid_area_m2"] / county_result["county_area_m2"]
    )
    county_result["data_source"] = "Task_14 ASTER GDEM V3 30 m DEM"
    county_result["slope_algorithm"] = "GDAL Horn"
    county_result["slope_unit"] = "degree"
    county_result["raster_resolution_m"] = 30
    county_output = processed_root / "nanning_slope_county_summary.csv"
    write_csv(county_result, county_output)

    ratio_columns = ["slope_le_3deg_ratio", "slope_le_5deg_ratio", "slope_le_8deg_ratio"]
    flag_counts = {
        str(key): int(value) for key, value in result["quality_flag"].value_counts().items()
    }
    failures: list[str] = []
    if len(result) != EXPECTED_GRID_COUNT or result["grid_id"].duplicated().any():
        failures.append("1 km网格统计主键检查失败")
    if len(county_result) != EXPECTED_COUNTY_COUNT or county_result["county_adcode"].duplicated().any():
        failures.append("县区统计主键检查失败")
    if int((county_result["valid_pixel_count"] == 0).sum()) != 0:
        failures.append("存在无有效坡度像元的县区")
    if flag_counts.get("no_valid_pixel_center", 0) > 200:
        failures.append("无有效坡度像元中心的边界网格超过200个")
    failures.extend(validate_ratios(result, ratio_columns))
    failures.extend(validate_ratios(county_result, ratio_columns))

    quality_report = {
        "task": "Task_15",
        "dataset": "南宁市坡度数据",
        "build_status": build_report["status"],
        "input_dem_sha256": build_report["input"]["sha256"],
        "algorithm": build_report["algorithm"],
        "slope_raster": build_report["output"],
        "independent_horn_audit": build_report["independent_horn_audit"],
        "grid_statistics": {
            "relation_row_count": int(len(nanning_relations)),
            "unique_grid_count": int(len(result)),
            "duplicate_grid_id_count": int(result["grid_id"].duplicated().sum()),
            "quality_flag_counts": flag_counts,
            "minimum_slope_degrees": normalize_stat(result["slope_min_deg"].min()),
            "maximum_slope_degrees": normalize_stat(result["slope_max_deg"].max()),
            "mean_slope_degrees": normalize_stat(
                build_report["output"]["mean_degrees"]
            ),
        },
        "county_statistics": {
            "county_count": int(len(county_result)),
            "duplicate_county_adcode_count": int(county_result["county_adcode"].duplicated().sum()),
            "county_adcodes": sorted(county_result["county_adcode"].astype(str).tolist()),
            "zero_valid_pixel_count": int((county_result["valid_pixel_count"] == 0).sum()),
        },
        "threshold_ratio_denominator": "各统计区域内有效坡度像元数",
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
    entries = [
        manifest_entry(repository, slope_path.relative_to(repository).as_posix(), "data", "南宁市30 m Horn坡度角统一入口", analysis_crs_name, int(build_report["output"]["valid_pixel_count"])),
        manifest_entry(repository, grid_output.relative_to(repository).as_posix(), "data", "Task_05统一1 km网格坡度统计", "grid_id", len(result)),
        manifest_entry(repository, county_output.relative_to(repository).as_posix(), "data", "南宁市12县区坡度汇总", "county_adcode", len(county_result)),
        manifest_entry(repository, "Task_15/reports/build_report.json", "report", "坡度构建与独立Horn复算报告"),
        manifest_entry(repository, "Task_15/reports/quality_report.json", "report", "Task_15最终质量报告"),
        manifest_entry(repository, "Task_15/reports/data_lineage.md", "documentation", "Task_15数据血缘说明"),
    ]
    for cog in build_report["output"]["cog_files"]:
        entries.append(manifest_entry(
            repository, cog["file"], "data", "南宁市30 m Horn坡度角分块COG",
            analysis_crs_name, int(cog["valid_pixel_count"]),
        ))
    write_manifest_and_checksums(repository, task_root, entries)
    print(
        f"Task_15统计完成：{len(result)}个网格、{len(county_result)}个县区，"
        f"质量状态PASS。"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, RuntimeError, SummaryValidationError,
            rasterio.errors.RasterioError) as error:
        print(f"Task_15统计失败：{error}", file=sys.stderr)
        sys.exit(1)
