#!/usr/bin/env python3
"""按108°E名义分幅线构建Task_17南宁市30 m地表覆盖分类COG。"""

from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.shutil import copy as raster_copy
from rasterio.vrt import WarpedVRT


SEAM_LONGITUDE = 108.0
NODATA = 0
EXCLUDED_SEA = 255
OFFICIAL_CODES = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
MAX_FILE_SIZE_BYTES = 95 * 1024 * 1024


class LandcoverBuildError(RuntimeError):
    """当分类投影、拼接、裁剪或COG验证失败时抛出。"""


def hex_to_rgba(value: str) -> tuple[int, int, int, int]:
    """把类别字典中的十六进制颜色转换为RGBA。"""
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise LandcoverBuildError(f"无效颜色值: {value}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), 255


def load_colormap(path: Path) -> dict[int, tuple[int, int, int, int]]:
    """从UTF-8类别字典读取官方调色板。"""
    lookup = pd.read_csv(path)
    if lookup["class_code"].duplicated().any():
        raise LandcoverBuildError("类别字典存在重复编码")
    return {
        int(row.class_code): hex_to_rgba(str(row.hex_color))
        for row in lookup.itertuples()
    }


def raster_statistics(path: Path) -> dict[str, Any]:
    """按块统计正式交付栅格的编码和结构。"""
    counts: dict[int, int] = {}
    with rasterio.open(path) as dataset:
        for _, window in dataset.block_windows(1):
            values, numbers = np.unique(dataset.read(1, window=window), return_counts=True)
            for value, number in zip(values, numbers):
                code = int(value)
                counts[code] = counts.get(code, 0) + int(number)
        try:
            colormap_count = len(dataset.colormap(1))
        except ValueError:
            colormap_count = 0
        return {
            "driver": dataset.driver,
            "width": int(dataset.width),
            "height": int(dataset.height),
            "count": int(dataset.count),
            "dtype": str(dataset.dtypes[0]),
            "crs": dataset.crs.to_wkt(),
            "crs_name": CRS.from_user_input(dataset.crs).name,
            "transform": list(dataset.transform)[:6],
            "resolution": [float(dataset.res[0]), float(dataset.res[1])],
            "bounds": [float(value) for value in dataset.bounds],
            "nodata": dataset.nodata,
            "color_interpretation": dataset.colorinterp[0].name,
            "color_table_entry_count": colormap_count,
            "code_counts": {str(code): count for code, count in sorted(counts.items())},
            "image_structure": dataset.tags(ns="IMAGE_STRUCTURE"),
            "overview_factors": dataset.overviews(1),
        }


def main() -> int:
    """执行最近邻投影、分幅线选择、边界裁剪、冲突统计和COG构建。"""
    repository = Path(__file__).resolve().parents[2]
    task_root = repository / "Task_17"
    raw_root = task_root / "data/raw/globeland30_2020"
    processed_root = task_root / "data/processed"
    reports_root = task_root / "reports"
    reference_path = repository / "Task_14/data/processed/nanning_dem_30m_albers.tif"
    boundary_path = repository / "Task_01/data/processed/nanning_county_boundary_projected.gpkg"
    lookup_path = processed_root / "landcover_class_lookup.csv"
    source_report_path = reports_root / "source_validation_report.json"
    output_path = processed_root / "nanning_landcover_2020_30m_albers.tif"

    if not source_report_path.is_file():
        raise LandcoverBuildError("缺少源数据质量报告，请先运行inspect_landcover_sources.py")
    source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    if source_report.get("status") != "PASS":
        raise LandcoverBuildError("源数据质量状态不是PASS")
    source48 = next((raw_root / "N48_20_2020LC030").glob("*.tif"))
    source49 = next((raw_root / "N49_20_2020LC030").glob("*.tif"))
    colormap = load_colormap(lookup_path)

    boundaries = gpd.read_file(boundary_path)
    if len(boundaries) != 12 or not boundaries.geometry.is_valid.all():
        raise LandcoverBuildError("Task_01南宁市边界数量或几何质量异常")
    geometries = [geometry.__geo_interface__ for geometry in boundaries.geometry]

    with rasterio.open(reference_path) as reference:
        target_width = int(reference.width)
        target_height = int(reference.height)
        target_transform = reference.transform
        target_crs = reference.crs
        target_bounds = [float(value) for value in reference.bounds]
        target_resolution = [float(reference.res[0]), float(reference.res[1])]
    if target_resolution != [30.0, 30.0]:
        raise LandcoverBuildError("Task_14参考网格不是30 m")

    transformer = Transformer.from_crs(target_crs, "EPSG:4326", always_xy=True)
    code_to_index = {code: index for index, code in enumerate(OFFICIAL_CODES)}
    confusion = np.zeros((len(OFFICIAL_CODES), len(OFFICIAL_CODES)), dtype=np.int64)
    selected_counts = np.zeros(256, dtype=np.int64)
    inside_pixel_count = 0
    overlap_valid_count = 0
    overlap_conflict_count = 0
    invalid_selected_counts: dict[int, int] = {}

    processed_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="task17_landcover_", dir=task_root) as temporary:
        temporary_root = Path(temporary)
        temporary_tif = temporary_root / "nanning_landcover_temp.tif"
        temporary_cog = temporary_root / "nanning_landcover_cog.tif"
        profile = {
            "driver": "GTiff",
            "width": target_width,
            "height": target_height,
            "count": 1,
            "dtype": "uint8",
            "crs": target_crs,
            "transform": target_transform,
            "nodata": NODATA,
            "tiled": True,
            "blockxsize": 512,
            "blockysize": 512,
            "compress": "DEFLATE",
            "predictor": 2,
            "BIGTIFF": "IF_SAFER",
        }
        with (
            rasterio.open(source48) as dataset48,
            rasterio.open(source49) as dataset49,
            WarpedVRT(
                dataset48,
                crs=target_crs,
                transform=target_transform,
                width=target_width,
                height=target_height,
                resampling=Resampling.nearest,
                src_nodata=NODATA,
                nodata=NODATA,
                dtype="uint8",
            ) as vrt48,
            WarpedVRT(
                dataset49,
                crs=target_crs,
                transform=target_transform,
                width=target_width,
                height=target_height,
                resampling=Resampling.nearest,
                src_nodata=NODATA,
                nodata=NODATA,
                dtype="uint8",
            ) as vrt49,
            rasterio.open(temporary_tif, "w", **profile) as destination,
        ):
            destination.write_colormap(1, colormap)
            for _, window in destination.block_windows(1):
                data48 = vrt48.read(1, window=window)
                data49 = vrt49.read(1, window=window)
                window_transform = destination.window_transform(window)
                inside = geometry_mask(
                    geometries,
                    out_shape=(int(window.height), int(window.width)),
                    transform=window_transform,
                    invert=True,
                    all_touched=False,
                )
                inside_pixel_count += int(inside.sum())

                row_indices = np.arange(
                    int(window.row_off), int(window.row_off + window.height), dtype=np.float64
                )
                column_indices = np.arange(
                    int(window.col_off), int(window.col_off + window.width), dtype=np.float64
                )
                x_coordinates = (
                    target_transform.c + (column_indices + 0.5) * target_transform.a
                )
                y_coordinates = (
                    target_transform.f + (row_indices + 0.5) * target_transform.e
                )
                x_grid, y_grid = np.meshgrid(x_coordinates, y_coordinates)
                longitude, _ = transformer.transform(x_grid, y_grid)
                selected = np.where(longitude < SEAM_LONGITUDE, data48, data49).astype(np.uint8)

                official48 = np.isin(data48, OFFICIAL_CODES)
                official49 = np.isin(data49, OFFICIAL_CODES)
                overlap = inside & official48 & official49
                conflict = overlap & (data48 != data49)
                overlap_valid_count += int(overlap.sum())
                overlap_conflict_count += int(conflict.sum())
                if overlap.any():
                    rows = np.fromiter(
                        (code_to_index[int(code)] for code in data48[overlap]),
                        dtype=np.int16,
                        count=int(overlap.sum()),
                    )
                    columns = np.fromiter(
                        (code_to_index[int(code)] for code in data49[overlap]),
                        dtype=np.int16,
                        count=int(overlap.sum()),
                    )
                    np.add.at(confusion, (rows, columns), 1)

                invalid = inside & ~np.isin(selected, OFFICIAL_CODES)
                if invalid.any():
                    values, numbers = np.unique(selected[invalid], return_counts=True)
                    for value, number in zip(values, numbers):
                        code = int(value)
                        invalid_selected_counts[code] = (
                            invalid_selected_counts.get(code, 0) + int(number)
                        )
                valid_values = selected[inside & np.isin(selected, OFFICIAL_CODES)]
                selected_counts += np.bincount(valid_values, minlength=256)
                selected[~inside] = NODATA
                destination.write(selected, 1, window=window)

        if invalid_selected_counts:
            raise LandcoverBuildError(
                f"南宁市内部存在无值、海水或未知编码: {invalid_selected_counts}"
            )
        if int(selected_counts.sum()) != inside_pixel_count:
            raise LandcoverBuildError("南宁市边界像元数与正式类别计数不守恒")

        raster_copy(
            temporary_tif,
            temporary_cog,
            driver="COG",
            compress="DEFLATE",
            predictor=2,
            blocksize=512,
            overview_resampling="NEAREST",
            BIGTIFF="IF_SAFER",
        )
        statistics = raster_statistics(temporary_cog)
        if temporary_cog.stat().st_size >= MAX_FILE_SIZE_BYTES:
            raise LandcoverBuildError("分类COG达到95 MB门槛，需要拆分后交付")
        if statistics["dtype"] != "uint8" or statistics["nodata"] != NODATA:
            raise LandcoverBuildError("分类COG数据类型或NoData不符合要求")
        if statistics["image_structure"].get("LAYOUT") != "COG":
            raise LandcoverBuildError("分类栅格未被识别为COG布局")
        if statistics["color_interpretation"] != "palette" or statistics["color_table_entry_count"] != 256:
            raise LandcoverBuildError("分类COG调色板未完整保留")
        if [statistics["width"], statistics["height"]] != [target_width, target_height]:
            raise LandcoverBuildError("分类COG尺寸与Task_14网格不一致")
        if statistics["transform"] != list(target_transform)[:6]:
            raise LandcoverBuildError("分类COG transform与Task_14网格不一致")
        if statistics["bounds"] != target_bounds or statistics["resolution"] != target_resolution:
            raise LandcoverBuildError("分类COG范围或分辨率与Task_14网格不一致")
        if not CRS.from_wkt(statistics["crs"]).equals(CRS.from_user_input(target_crs)):
            raise LandcoverBuildError("分类COG CRS与Task_14网格不一致")
        output_codes = set(int(code) for code in statistics["code_counts"])
        if not output_codes.issubset(set(OFFICIAL_CODES) | {NODATA}):
            raise LandcoverBuildError(f"输出包含未知编码: {sorted(output_codes)}")
        if output_path.exists():
            output_path.unlink()
        temporary_cog.replace(output_path)

    transition_matrix = {
        str(row_code): {
            str(column_code): int(confusion[row_index, column_index])
            for column_index, column_code in enumerate(OFFICIAL_CODES)
        }
        for row_index, row_code in enumerate(OFFICIAL_CODES)
    }
    overlap_report = {
        "task": "Task_17",
        "target_grid": {
            "reference": reference_path.relative_to(repository).as_posix(),
            "width": target_width,
            "height": target_height,
            "resolution_m": 30,
        },
        "seam_rule": "lon < 108°使用N48；lon >= 108°使用N49",
        "overlap_valid_pixel_count": overlap_valid_count,
        "overlap_same_pixel_count": overlap_valid_count - overlap_conflict_count,
        "overlap_conflict_pixel_count": overlap_conflict_count,
        "overlap_conflict_ratio": (
            overlap_conflict_count / overlap_valid_count if overlap_valid_count else None
        ),
        "transition_matrix_rows_n48_columns_n49": transition_matrix,
        "status": "PASS",
    }
    (reports_root / "overlap_analysis.json").write_text(
        json.dumps(overlap_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    output_statistics = raster_statistics(output_path)
    class_counts = {
        str(code): int(selected_counts[code]) for code in OFFICIAL_CODES
    }
    if sum(class_counts.values()) != inside_pixel_count:
        raise LandcoverBuildError("最终类别计数与南宁市像元数不守恒")
    report = {
        "task": "Task_17",
        "dataset": "南宁市GlobeLand30 2020地表覆盖",
        "source_validation_status": source_report["status"],
        "algorithm": {
            "resampling": "nearest",
            "seam_longitude": SEAM_LONGITUDE,
            "seam_rule": "lon < 108°使用N48；lon >= 108°使用N49",
            "fallback_to_other_tile": False,
            "mask_rule": "Task_01南宁市边界内保留，边界外写0",
        },
        "inside_pixel_count": inside_pixel_count,
        "class_counts": class_counts,
        "internal_nodata_count": int(invalid_selected_counts.get(NODATA, 0)),
        "internal_sea_count": int(invalid_selected_counts.get(EXCLUDED_SEA, 0)),
        "overlap_analysis_status": overlap_report["status"],
        "output": {
            "file": output_path.relative_to(repository).as_posix(),
            "file_size_bytes": output_path.stat().st_size,
            "file_size_limit_bytes": MAX_FILE_SIZE_BYTES,
            **output_statistics,
        },
        "status": "PASS",
    }
    (reports_root / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Task_17分类构建完成：{target_width}x{target_height}，"
        f"有效像元{inside_pixel_count}，冲突率"
        f"{overlap_report['overlap_conflict_ratio']:.4%}，质量状态PASS。"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, LandcoverBuildError,
            rasterio.errors.RasterioError) as error:
        print(f"Task_17分类构建失败：{error}", file=sys.stderr)
        sys.exit(1)
