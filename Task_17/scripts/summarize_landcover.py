#!/usr/bin/env python3
"""生成Task_17统一网格宽表、类别长表、县区汇总和最终交付校验。"""

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
from pyproj import CRS
from rasterstats import zonal_stats


EXPECTED_GRID_COUNT = 22_770
EXPECTED_RELATION_COUNT = 24_033
EXPECTED_COUNTY_COUNT = 12
OFFICIAL_CODES = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
NODATA = 0
PIXEL_AREA_M2 = 900.0
GRID_SIZE_M = 1000.0
GRID_ORIGIN_X = -400_000.0
GRID_ORIGIN_Y = -300_000.0
RATIO_COLUMNS = {
    10: "cultivated_land_ratio",
    20: "forest_ratio",
    30: "grass_land_ratio",
    40: "shrubland_ratio",
    50: "wetland_ratio",
    60: "water_body_ratio",
    70: "tundra_ratio",
    80: "artificial_surfaces_ratio",
    90: "bareland_ratio",
    100: "permanent_snow_ice_ratio",
}


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
    """把统计值转换为CSV可表达的有限数值。"""
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def grid_quality_flag(valid_count: int, area_m2: float, ratio: float | None) -> str:
    """依据有效像元与南宁市相交面积标记网格质量。"""
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


def accumulate_grid_counts(
    raster_path: Path,
    selected_grids: gpd.GeoDataFrame,
) -> np.ndarray:
    """按Task_05固定原点把有效分类像元快速归入22,770个网格。"""
    key_to_position = {
        (int(row.row), int(row.col)): position
        for position, row in enumerate(selected_grids.itertuples())
    }
    class_to_position = {code: position for position, code in enumerate(OFFICIAL_CODES)}
    counts = np.zeros((len(selected_grids), len(OFFICIAL_CODES)), dtype=np.int64)
    with rasterio.open(raster_path) as dataset:
        for _, window in dataset.block_windows(1):
            data = dataset.read(1, window=window)
            valid = np.isin(data, OFFICIAL_CODES)
            if not valid.any():
                continue
            local_rows, local_columns = np.nonzero(valid)
            global_rows = local_rows + int(window.row_off)
            global_columns = local_columns + int(window.col_off)
            x_coordinates = (
                dataset.transform.c + (global_columns + 0.5) * dataset.transform.a
            )
            y_coordinates = (
                dataset.transform.f + (global_rows + 0.5) * dataset.transform.e
            )
            grid_columns = np.floor((x_coordinates - GRID_ORIGIN_X) / GRID_SIZE_M).astype(int)
            grid_rows = np.floor((y_coordinates - GRID_ORIGIN_Y) / GRID_SIZE_M).astype(int)
            grid_positions = np.fromiter(
                (key_to_position.get((int(row), int(column)), -1)
                 for row, column in zip(grid_rows, grid_columns)),
                dtype=np.int64,
                count=len(grid_rows),
            )
            if np.any(grid_positions < 0):
                raise SummaryValidationError("存在无法关联Task_05南宁市网格的有效分类像元")
            class_positions = np.fromiter(
                (class_to_position[int(code)] for code in data[valid]),
                dtype=np.int16,
                count=int(valid.sum()),
            )
            np.add.at(counts, (grid_positions, class_positions), 1)
    return counts


def county_categorical_counts(
    counties: gpd.GeoDataFrame,
    raster_path: Path,
) -> np.ndarray:
    """按12县区几何计算官方10类像元数。"""
    statistics = zonal_stats(
        counties.geometry,
        raster_path,
        categorical=True,
        nodata=NODATA,
        all_touched=False,
    )
    return np.asarray(
        [[int(record.get(code, 0)) for code in OFFICIAL_CODES] for record in statistics],
        dtype=np.int64,
    )


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


def write_manifest_and_checksums(task_root: Path, entries: list[dict[str, Any]]) -> None:
    """写入文件清单和Task_17全部正式交付文件校验值。"""
    manifest = task_root / "file_manifest.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(entries[0]))
        writer.writeheader()
        writer.writerows(entries)

    checksum_files = [task_root / "README.md", manifest]
    checksum_files.extend(sorted((task_root / "data/raw").rglob("*")))
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
    """生成网格宽表、类别长表、县区汇总、质量报告和交付清单。"""
    repository = Path(__file__).resolve().parents[2]
    task_root = repository / "Task_17"
    processed_root = task_root / "data/processed"
    reports_root = task_root / "reports"
    raster_path = processed_root / "nanning_landcover_2020_30m_albers.tif"
    lookup_path = processed_root / "landcover_class_lookup.csv"
    build_report_path = reports_root / "build_report.json"
    source_report_path = reports_root / "source_validation_report.json"
    overlap_report_path = reports_root / "overlap_analysis.json"
    if not all(path.is_file() for path in [raster_path, lookup_path, build_report_path,
                                            source_report_path, overlap_report_path]):
        raise SummaryValidationError("缺少分类栅格、类别字典或前置报告")
    build_report = json.loads(build_report_path.read_text(encoding="utf-8"))
    source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    overlap_report = json.loads(overlap_report_path.read_text(encoding="utf-8"))
    if any(report.get("status") != "PASS" for report in [build_report, source_report, overlap_report]):
        raise SummaryValidationError("源数据、构建或重叠报告不是PASS")

    lookup = pd.read_csv(lookup_path)
    official_lookup = (
        lookup.loc[lookup["class_code"].isin(OFFICIAL_CODES)]
        .set_index("class_code")
        .loc[OFFICIAL_CODES]
    )
    if len(official_lookup) != len(OFFICIAL_CODES):
        raise SummaryValidationError("官方类别字典不完整")

    relations = pd.read_csv(
        repository / "Task_05/data/grid/gx_grid_county_relation.csv",
        dtype={"grid_id": "string", "city_adcode": "string", "county_adcode": "string"},
    )
    nanning_relations = relations.loc[relations["city_adcode"] == "450100"].copy()
    if len(nanning_relations) != EXPECTED_RELATION_COUNT:
        raise SummaryValidationError(f"南宁市网格关系数量异常: {len(nanning_relations)}")
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
    selected = selected.sort_values("grid_id").reset_index(drop=True)
    if len(selected) != EXPECTED_GRID_COUNT or selected["grid_id"].duplicated().any():
        raise SummaryValidationError(f"Task_05网格筛选结果异常: {len(selected)}")
    with rasterio.open(raster_path) as dataset:
        if not CRS.from_user_input(selected.crs).equals(CRS.from_user_input(dataset.crs)):
            raise SummaryValidationError("Task_05网格与Task_17分类栅格坐标系不一致")

    grid_counts = accumulate_grid_counts(raster_path, selected)
    valid_counts = grid_counts.sum(axis=1)
    if int(valid_counts.sum()) != int(build_report["inside_pixel_count"]):
        raise SummaryValidationError("网格类别像元总数与构建报告不守恒")
    result = selected[["grid_id", "center_lon", "center_lat"]].copy()
    result = result.merge(grid_area, on="grid_id", how="left", validate="one_to_one")
    result["valid_pixel_count"] = valid_counts
    result["valid_area_m2"] = valid_counts * PIXEL_AREA_M2
    result["valid_coverage_ratio"] = result["valid_area_m2"] / result["nanning_area_m2"]

    dominant_codes: list[int | None] = []
    dominant_names: list[str | None] = []
    for row_counts, valid_count in zip(grid_counts, valid_counts):
        if valid_count == 0:
            dominant_codes.append(None)
            dominant_names.append(None)
        else:
            code = OFFICIAL_CODES[int(np.argmax(row_counts))]
            dominant_codes.append(code)
            dominant_names.append(str(official_lookup.loc[code, "class_name_zh"]))
    result["dominant_class_code"] = pd.Series(dominant_codes, dtype="Int64")
    result["dominant_class_name_zh"] = dominant_names
    for position, code in enumerate(OFFICIAL_CODES):
        ratios = np.divide(
            grid_counts[:, position],
            valid_counts,
            out=np.full(len(valid_counts), np.nan, dtype=float),
            where=valid_counts > 0,
        )
        result[RATIO_COLUMNS[code]] = ratios
    result["quality_flag"] = result.apply(
        lambda row: grid_quality_flag(
            int(row["valid_pixel_count"]),
            float(row["nanning_area_m2"]),
            normalize_stat(row["valid_coverage_ratio"]),
        ),
        axis=1,
    )
    result["data_source"] = "GlobeLand30 2020"
    result["raster_resolution_m"] = 30
    wide_output = processed_root / "nanning_landcover_grid_1km.csv"
    write_csv(result, wide_output)

    long_records: list[dict[str, Any]] = []
    for grid_position, row in enumerate(result.itertuples()):
        valid_count = int(row.valid_pixel_count)
        nanning_area = float(row.nanning_area_m2)
        for class_position, code in enumerate(OFFICIAL_CODES):
            pixel_count = int(grid_counts[grid_position, class_position])
            pixel_area = pixel_count * PIXEL_AREA_M2
            long_records.append({
                "grid_id": row.grid_id,
                "class_code": code,
                "class_name_en": official_lookup.loc[code, "class_name_en"],
                "class_name_zh": official_lookup.loc[code, "class_name_zh"],
                "pixel_count": pixel_count,
                "area_m2": pixel_area,
                "valid_pixel_ratio": pixel_count / valid_count if valid_count > 0 else None,
                "nanning_area_ratio": pixel_area / nanning_area if valid_count > 0 else None,
                "quality_flag": row.quality_flag,
                "data_source": "GlobeLand30 2020",
                "raster_resolution_m": 30,
            })
    long_result = pd.DataFrame(long_records)
    long_output = processed_root / "nanning_landcover_grid_1km_long.csv"
    write_csv(long_result, long_output)

    counties = gpd.read_file(repository / "Task_01/data/processed/nanning_county_boundary_projected.gpkg")
    counties = counties.sort_values("county_adcode").reset_index(drop=True)
    if len(counties) != EXPECTED_COUNTY_COUNT:
        raise SummaryValidationError(f"南宁市县区数量异常: {len(counties)}")
    county_counts = county_categorical_counts(counties, raster_path)
    county_valid_counts = county_counts.sum(axis=1)
    county_records: list[dict[str, Any]] = []
    for county_position, county in enumerate(counties.itertuples()):
        valid_count = int(county_valid_counts[county_position])
        county_area = float(county.geometry.area)
        for class_position, code in enumerate(OFFICIAL_CODES):
            pixel_count = int(county_counts[county_position, class_position])
            pixel_area = pixel_count * PIXEL_AREA_M2
            county_records.append({
                "county_adcode": str(county.county_adcode),
                "county_name": county.county_name,
                "class_code": code,
                "class_name_en": official_lookup.loc[code, "class_name_en"],
                "class_name_zh": official_lookup.loc[code, "class_name_zh"],
                "pixel_count": pixel_count,
                "area_m2": pixel_area,
                "valid_pixel_ratio": pixel_count / valid_count if valid_count > 0 else None,
                "county_area_ratio": pixel_area / county_area if valid_count > 0 else None,
                "county_valid_pixel_count": valid_count,
                "county_area_m2": county_area,
                "data_source": "GlobeLand30 2020",
                "raster_resolution_m": 30,
            })
    county_result = pd.DataFrame(county_records)
    county_output = processed_root / "nanning_landcover_county_summary.csv"
    write_csv(county_result, county_output)

    ratio_columns = list(RATIO_COLUMNS.values())
    flag_counts = {
        str(key): int(value) for key, value in result["quality_flag"].value_counts().items()
    }
    failures: list[str] = []
    if len(result) != EXPECTED_GRID_COUNT or result["grid_id"].duplicated().any():
        failures.append("网格宽表主键检查失败")
    if len(long_result) != EXPECTED_GRID_COUNT * len(OFFICIAL_CODES):
        failures.append("网格类别长表行数异常")
    if long_result.duplicated(["grid_id", "class_code"]).any():
        failures.append("网格类别长表复合主键重复")
    if len(county_result) != EXPECTED_COUNTY_COUNT * len(OFFICIAL_CODES):
        failures.append("县区类别汇总行数异常")
    if county_result.duplicated(["county_adcode", "class_code"]).any():
        failures.append("县区类别汇总复合主键重复")
    valid_wide = result.loc[result["valid_pixel_count"] > 0, ratio_columns]
    if not np.allclose(valid_wide.sum(axis=1).to_numpy(), 1.0, atol=1e-12):
        failures.append("网格宽表10类比例之和不为1")
    if ((long_result["valid_pixel_ratio"].dropna() < 0) |
            (long_result["valid_pixel_ratio"].dropna() > 1)).any():
        failures.append("网格类别长表比例超出0至1")
    if not np.array_equal(
        long_result.groupby("grid_id", sort=False)["pixel_count"].sum().to_numpy(),
        valid_counts,
    ):
        failures.append("网格宽表与长表像元数不守恒")
    if int(county_valid_counts.min()) <= 0:
        failures.append("存在无有效地表覆盖像元的县区")

    class_totals = grid_counts.sum(axis=0)
    build_class_totals = np.asarray(
        [int(build_report["class_counts"][str(code)]) for code in OFFICIAL_CODES],
        dtype=np.int64,
    )
    if not np.array_equal(class_totals, build_class_totals):
        failures.append("网格类别汇总与构建报告类别计数不守恒")

    quality_report = {
        "task": "Task_17",
        "dataset": "南宁市GlobeLand30 2020地表覆盖",
        "source_validation_status": source_report["status"],
        "build_status": build_report["status"],
        "overlap_analysis_status": overlap_report["status"],
        "raster": build_report["output"],
        "class_counts": {
            str(code): int(class_totals[position])
            for position, code in enumerate(OFFICIAL_CODES)
        },
        "grid_wide": {
            "row_count": int(len(result)),
            "unique_grid_count": int(result["grid_id"].nunique()),
            "quality_flag_counts": flag_counts,
            "ratio_columns": ratio_columns,
        },
        "grid_long": {
            "row_count": int(len(long_result)),
            "unique_composite_key_count": int(
                long_result[["grid_id", "class_code"]].drop_duplicates().shape[0]
            ),
        },
        "county_summary": {
            "row_count": int(len(county_result)),
            "county_count": int(county_result["county_adcode"].nunique()),
            "unique_composite_key_count": int(
                county_result[["county_adcode", "class_code"]].drop_duplicates().shape[0]
            ),
            "zero_valid_county_count": int((county_valid_counts == 0).sum()),
        },
        "ratio_denominators": {
            "valid_pixel_ratio": "统计区域内有效地表覆盖像元数",
            "nanning_area_ratio": "网格与南宁市相交面积",
            "county_area_ratio": "县区矢量面积",
        },
        "terminology_policy": "比赛板块称土地利用；数据产品准确表述为地表覆盖",
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }
    quality_path = reports_root / "quality_report.json"
    quality_path.write_text(
        json.dumps(quality_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if failures:
        raise SummaryValidationError("；".join(failures))

    crs_name = build_report["output"]["crs_name"]
    entries: list[dict[str, Any]] = []
    for path in sorted((task_root / "data/raw").rglob("*")):
        if path.is_file():
            entries.append(manifest_entry(
                repository,
                path.relative_to(repository).as_posix(),
                "raw",
                "GlobeLand30 2020原始数据包文件",
            ))
    entries.extend([
        manifest_entry(repository, raster_path.relative_to(repository).as_posix(), "data", "南宁市30 m地表覆盖分类COG", crs_name, int(build_report["inside_pixel_count"])),
        manifest_entry(repository, lookup_path.relative_to(repository).as_posix(), "data", "GlobeLand30官方类别字典", "class_code", len(lookup)),
        manifest_entry(repository, wide_output.relative_to(repository).as_posix(), "data", "Task_05统一1 km网格地表覆盖宽表", "grid_id", len(result)),
        manifest_entry(repository, long_output.relative_to(repository).as_posix(), "data", "Task_05网格—类别长表", "grid_id+class_code", len(long_result)),
        manifest_entry(repository, county_output.relative_to(repository).as_posix(), "data", "南宁市12县区类别汇总", "county_adcode+class_code", len(county_result)),
        manifest_entry(repository, "Task_17/reports/source_inventory.csv", "report", "两个原始包逐文件清单", "", source_report["source_file_count"]),
        manifest_entry(repository, "Task_17/reports/source_validation_report.json", "report", "原始包、类别、影像索引和覆盖验证"),
        manifest_entry(repository, "Task_17/reports/overlap_analysis.json", "report", "N48/N49重叠冲突与转移矩阵"),
        manifest_entry(repository, "Task_17/reports/build_report.json", "report", "30 m分类COG构建报告"),
        manifest_entry(repository, "Task_17/reports/quality_report.json", "report", "Task_17最终质量报告"),
        manifest_entry(repository, "Task_17/reports/data_lineage.md", "documentation", "Task_17数据血缘说明"),
    ])
    write_manifest_and_checksums(task_root, entries)
    print(
        f"Task_17统计完成：{len(result)}格宽表、{len(long_result)}行长表、"
        f"{len(county_result)}行县区汇总，质量状态PASS。"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, SummaryValidationError,
            rasterio.errors.RasterioError) as error:
        print(f"Task_17统计失败：{error}", file=sys.stderr)
        sys.exit(1)
