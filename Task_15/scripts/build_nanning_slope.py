#!/usr/bin/env python3
"""从Task_14标准DEM生成Task_15南宁市30 m Horn坡度COG并验证。"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from osgeo import gdal
from pyproj import CRS
from rasterio.windows import Window


OUTPUT_NODATA = -9999.0
MAX_FILE_SIZE_BYTES = 95 * 1024 * 1024
HORN_TOLERANCE_DEGREES = 1e-3
MINIMUM_AUDIT_SAMPLES = 30


class SlopeBuildError(RuntimeError):
    """当坡度输入、计算或质量验证失败时抛出。"""


def sha256_file(path: Path) -> str:
    """以分块方式计算文件SHA256。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_task14_hash(task14_root: Path, relative_path: str) -> str:
    """从Task_14校验清单读取指定文件的预期哈希。"""
    checksum_path = task14_root / "SHA256SUMS.txt"
    if not checksum_path.is_file():
        raise SlopeBuildError("缺少Task_14/SHA256SUMS.txt")
    normalized_target = relative_path.replace("\\", "/")
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        relative = parts[1].lstrip("*").replace("\\", "/")
        if relative == normalized_target:
            return parts[0].lower()
    raise SlopeBuildError(f"Task_14校验清单未登记输入DEM: {normalized_target}")


def validate_input(dem_path: Path, task14_root: Path) -> dict[str, Any]:
    """验证Task_14质量状态、输入哈希和栅格基础规格。"""
    quality_path = task14_root / "reports/quality_report.json"
    if not quality_path.is_file() or not dem_path.is_file():
        raise SlopeBuildError("缺少Task_14主DEM或质量报告")
    task14_quality = json.loads(quality_path.read_text(encoding="utf-8"))
    if task14_quality.get("status") != "PASS":
        raise SlopeBuildError("Task_14质量状态不是PASS")

    relative_path = dem_path.relative_to(task14_root).as_posix()
    expected_hash = expected_task14_hash(task14_root, relative_path)
    actual_hash = sha256_file(dem_path)
    if actual_hash != expected_hash:
        raise SlopeBuildError("Task_14主DEM的SHA256与校验清单不一致")

    with rasterio.open(dem_path) as dataset:
        metadata = {
            "file": dem_path.as_posix(),
            "sha256": actual_hash,
            "driver": dataset.driver,
            "width": int(dataset.width),
            "height": int(dataset.height),
            "dtype": str(dataset.dtypes[0]),
            "crs": dataset.crs.to_wkt(),
            "crs_name": CRS.from_user_input(dataset.crs).name,
            "transform": list(dataset.transform)[:6],
            "resolution": [float(dataset.res[0]), float(dataset.res[1])],
            "bounds": [float(value) for value in dataset.bounds],
            "nodata": dataset.nodata,
        }
    if metadata["resolution"] != [30.0, 30.0]:
        raise SlopeBuildError("Task_14主DEM分辨率不是30 m")
    if metadata["nodata"] != OUTPUT_NODATA:
        raise SlopeBuildError("Task_14主DEM NoData不是-9999")
    if not CRS.from_wkt(metadata["crs"]).is_projected:
        raise SlopeBuildError("Task_14主DEM不是米制投影坐标系")
    return metadata


def raster_statistics(path: Path) -> dict[str, Any]:
    """按块统计坡度数值和COG结构，避免整幅载入内存。"""
    count = 0
    total = 0.0
    total_square = 0.0
    minimum: float | None = None
    maximum: float | None = None
    nan_count = 0
    infinite_count = 0
    out_of_range_count = 0
    with rasterio.open(path) as dataset:
        for _, window in dataset.block_windows(1):
            data = dataset.read(1, window=window)
            valid_mask = data != OUTPUT_NODATA
            values = data[valid_mask].astype(np.float64)
            if values.size == 0:
                continue
            nan_count += int(np.isnan(values).sum())
            infinite_count += int(np.isinf(values).sum())
            finite = values[np.isfinite(values)]
            out_of_range_count += int(((finite < 0.0) | (finite > 90.0)).sum())
            if finite.size == 0:
                continue
            count += int(finite.size)
            total += float(finite.sum())
            total_square += float(np.square(finite).sum())
            block_minimum = float(finite.min())
            block_maximum = float(finite.max())
            minimum = block_minimum if minimum is None else min(minimum, block_minimum)
            maximum = block_maximum if maximum is None else max(maximum, block_maximum)
        if count == 0:
            raise SlopeBuildError("输出坡度栅格没有有效像元")
        mean = total / count
        variance = max(total_square / count - mean * mean, 0.0)
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
            "valid_pixel_count": count,
            "nodata_pixel_count": int(dataset.width * dataset.height - count),
            "minimum_degrees": minimum,
            "maximum_degrees": maximum,
            "mean_degrees": mean,
            "standard_deviation_degrees": math.sqrt(variance),
            "nan_count": nan_count,
            "infinite_count": infinite_count,
            "out_of_range_count": out_of_range_count,
            "image_structure": dataset.tags(ns="IMAGE_STRUCTURE"),
            "overview_factors": dataset.overviews(1),
        }


def audit_horn_samples(dem_path: Path, slope_path: Path) -> dict[str, Any]:
    """用独立Horn公式复算确定性样本并与GDAL输出比较。"""
    differences: list[float] = []
    with rasterio.open(dem_path) as dem, rasterio.open(slope_path) as slope:
        row_step = max((dem.height - 2) // 35, 1)
        col_step = max((dem.width - 2) // 35, 1)
        for row in range(1, dem.height - 1, row_step):
            for column in range(1, dem.width - 1, col_step):
                neighborhood = dem.read(1, window=Window(column - 1, row - 1, 3, 3))
                if neighborhood.shape != (3, 3) or np.any(neighborhood == dem.nodata):
                    continue
                z = neighborhood.astype(np.float64)
                dz_dx = ((z[0, 2] + 2 * z[1, 2] + z[2, 2]) -
                         (z[0, 0] + 2 * z[1, 0] + z[2, 0])) / (8 * dem.res[0])
                dz_dy = ((z[2, 0] + 2 * z[2, 1] + z[2, 2]) -
                         (z[0, 0] + 2 * z[0, 1] + z[0, 2])) / (8 * dem.res[1])
                expected = math.degrees(math.atan(math.hypot(dz_dx, dz_dy)))
                actual = float(slope.read(1, window=Window(column, row, 1, 1))[0, 0])
                if actual == slope.nodata or not math.isfinite(actual):
                    raise SlopeBuildError("完整3×3邻域对应的坡度样本无效")
                differences.append(abs(actual - expected))
                if len(differences) >= 100:
                    break
            if len(differences) >= 100:
                break
    if len(differences) < MINIMUM_AUDIT_SAMPLES:
        raise SlopeBuildError(f"独立Horn复算有效样本不足: {len(differences)}")
    maximum_difference = max(differences)
    if maximum_difference > HORN_TOLERANCE_DEGREES:
        raise SlopeBuildError(
            f"Horn独立复算最大差异{maximum_difference}°超过容差{HORN_TOLERANCE_DEGREES}°"
        )
    return {
        "sample_count": len(differences),
        "maximum_absolute_difference_degrees": maximum_difference,
        "tolerance_degrees": HORN_TOLERANCE_DEGREES,
        "status": "PASS",
    }


def cog_translate_options() -> gdal.TranslateOptions:
    """返回Task_15统一COG转换参数。"""
    return gdal.TranslateOptions(
        format="COG",
        outputType=gdal.GDT_Float32,
        noData=OUTPUT_NODATA,
        creationOptions=[
            "COMPRESS=DEFLATE", "PREDICTOR=FLOATING_POINT", "BLOCKSIZE=512",
            "OVERVIEWS=AUTO", "RESAMPLING=AVERAGE", "BIGTIFF=IF_SAFER",
        ],
    )


def translate_cog(source: Path, target: Path, source_window: list[int] | None = None) -> None:
    """把坡度临时栅格整体或按窗口转换为COG。"""
    options = cog_translate_options() if source_window is None else gdal.TranslateOptions(
        format="COG",
        outputType=gdal.GDT_Float32,
        noData=OUTPUT_NODATA,
        srcWin=source_window,
        creationOptions=[
            "COMPRESS=DEFLATE", "PREDICTOR=FLOATING_POINT", "BLOCKSIZE=512",
            "OVERVIEWS=AUTO", "RESAMPLING=AVERAGE", "BIGTIFF=IF_SAFER",
        ],
    )
    translated = gdal.Translate(str(target), str(source), options=options)
    if translated is None:
        raise SlopeBuildError(f"坡度结果转换COG失败: {target.name}")
    translated = None


def validate_cog(path: Path) -> dict[str, Any]:
    """验证单个坡度COG的结构、数值和文件门槛。"""
    statistics = raster_statistics(path)
    if path.stat().st_size >= MAX_FILE_SIZE_BYTES:
        raise SlopeBuildError(f"{path.name}仍达到95 MB门槛")
    if statistics["dtype"] != "float32" or statistics["nodata"] != OUTPUT_NODATA:
        raise SlopeBuildError(f"{path.name}数据类型或NoData不符合要求")
    if statistics["image_structure"].get("LAYOUT") != "COG":
        raise SlopeBuildError(f"{path.name}未被GDAL识别为COG布局")
    if statistics["nan_count"] or statistics["infinite_count"] or statistics["out_of_range_count"]:
        raise SlopeBuildError(f"{path.name}存在NaN、Inf或0°至90°外数值")
    return statistics


def main() -> int:
    """完成输入校验、Horn坡度计算、COG转换和构建报告。"""
    gdal.UseExceptions()
    repository = Path(__file__).resolve().parents[2]
    task_root = repository / "Task_15"
    task14_root = repository / "Task_14"
    dem_path = task14_root / "data/processed/nanning_dem_30m_albers.tif"
    processed_root = task_root / "data/processed"
    reports_root = task_root / "reports"
    processed_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    single_output = processed_root / "nanning_slope_30m_albers.tif"
    vrt_output = processed_root / "nanning_slope_30m_albers.vrt"
    north_output = processed_root / "nanning_slope_30m_albers_north.tif"
    south_output = processed_root / "nanning_slope_30m_albers_south.tif"

    input_metadata = validate_input(dem_path, task14_root)
    with tempfile.TemporaryDirectory(prefix="task15_slope_", dir=task_root) as temporary:
        temporary_root = Path(temporary)
        temporary_slope = temporary_root / "slope_horn.tif"
        temporary_cog = temporary_root / "slope_horn_cog.tif"
        dem_options = gdal.DEMProcessingOptions(
            format="GTiff",
            alg="Horn",
            slopeFormat="degree",
            scale=1.0,
            computeEdges=False,
            creationOptions=[
                "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512",
                "COMPRESS=DEFLATE", "PREDICTOR=3", "BIGTIFF=IF_SAFER",
            ],
        )
        result = gdal.DEMProcessing(
            str(temporary_slope), str(dem_path), "slope", options=dem_options
        )
        if result is None:
            raise SlopeBuildError("GDAL Horn坡度计算未生成结果")
        result = None

        translate_cog(temporary_slope, temporary_cog)

        statistics = raster_statistics(temporary_cog)
        file_size = temporary_cog.stat().st_size
        if statistics["dtype"] != "float32" or statistics["nodata"] != OUTPUT_NODATA:
            raise SlopeBuildError("坡度栅格数据类型或NoData不符合要求")
        if statistics["image_structure"].get("LAYOUT") != "COG":
            raise SlopeBuildError("坡度栅格未被GDAL识别为COG布局")
        if statistics["nan_count"] or statistics["infinite_count"] or statistics["out_of_range_count"]:
            raise SlopeBuildError("坡度栅格存在NaN、Inf或0°至90°外数值")
        if statistics["width"] != input_metadata["width"] or statistics["height"] != input_metadata["height"]:
            raise SlopeBuildError("坡度栅格尺寸与Task_14 DEM不一致")
        if statistics["transform"] != input_metadata["transform"]:
            raise SlopeBuildError("坡度栅格transform与Task_14 DEM不一致")
        if statistics["bounds"] != input_metadata["bounds"] or statistics["resolution"] != input_metadata["resolution"]:
            raise SlopeBuildError("坡度栅格范围或分辨率与Task_14 DEM不一致")
        if not CRS.from_wkt(statistics["crs"]).equals(CRS.from_wkt(input_metadata["crs"])):
            raise SlopeBuildError("坡度栅格CRS与Task_14 DEM不一致")

        delivery_mode = "single_cog"
        cog_records: list[dict[str, Any]] = []
        for stale in [single_output, vrt_output, north_output, south_output]:
            if stale.exists():
                stale.unlink()
        if file_size < MAX_FILE_SIZE_BYTES:
            temporary_cog.replace(single_output)
            analysis_path = single_output
            cog_records.append({
                "file": single_output.relative_to(repository).as_posix(),
                "file_size_bytes": single_output.stat().st_size,
                **validate_cog(single_output),
            })
        else:
            delivery_mode = "split_cog_with_vrt"
            split_row = statistics["height"] // 2
            temporary_north = temporary_root / "slope_horn_north.tif"
            temporary_south = temporary_root / "slope_horn_south.tif"
            translate_cog(
                temporary_slope, temporary_north,
                [0, 0, statistics["width"], split_row],
            )
            translate_cog(
                temporary_slope, temporary_south,
                [0, split_row, statistics["width"], statistics["height"] - split_row],
            )
            north_statistics = validate_cog(temporary_north)
            south_statistics = validate_cog(temporary_south)
            temporary_north.replace(north_output)
            temporary_south.replace(south_output)
            vrt = gdal.BuildVRT(
                str(vrt_output), [str(north_output), str(south_output)],
                options=gdal.BuildVRTOptions(srcNodata=OUTPUT_NODATA, VRTNodata=OUTPUT_NODATA),
            )
            if vrt is None:
                raise SlopeBuildError("南北坡度COG的VRT索引创建失败")
            vrt = None
            analysis_path = vrt_output
            cog_records.extend([
                {
                    "file": north_output.relative_to(repository).as_posix(),
                    "file_size_bytes": north_output.stat().st_size,
                    **north_statistics,
                },
                {
                    "file": south_output.relative_to(repository).as_posix(),
                    "file_size_bytes": south_output.stat().st_size,
                    **south_statistics,
                },
            ])

    analysis_statistics = raster_statistics(analysis_path)
    if analysis_statistics["width"] != input_metadata["width"] or analysis_statistics["height"] != input_metadata["height"]:
        raise SlopeBuildError("交付坡度入口尺寸与Task_14 DEM不一致")
    if analysis_statistics["transform"] != input_metadata["transform"]:
        raise SlopeBuildError("交付坡度入口transform与Task_14 DEM不一致")
    horn_audit = audit_horn_samples(dem_path, analysis_path)
    report = {
        "task": "Task_15",
        "dataset": "南宁市坡度数据",
        "input": {
            **input_metadata,
            "file": dem_path.relative_to(repository).as_posix(),
            "task14_quality_status": "PASS",
        },
        "algorithm": {
            "implementation": "GDAL DEMProcessing",
            "algorithm": "Horn",
            "neighborhood": "3x3",
            "slope_unit": "degree",
            "scale": 1.0,
            "compute_edges": False,
            "dem_conditioning": False,
            "resampling": False,
        },
        "output": {
            "file": analysis_path.relative_to(repository).as_posix(),
            "delivery_mode": delivery_mode,
            "file_size_bytes": analysis_path.stat().st_size,
            "file_size_limit_bytes": MAX_FILE_SIZE_BYTES,
            "cog_files": cog_records,
            **analysis_statistics,
        },
        "independent_horn_audit": horn_audit,
        "status": "PASS",
    }
    (reports_root / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Task_15坡度构建完成：{statistics['width']}x{statistics['height']}，"
        f"交付模式{delivery_mode}，质量状态PASS。"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, RuntimeError, SlopeBuildError,
            rasterio.errors.RasterioError) as error:
        print(f"Task_15坡度构建失败：{error}", file=sys.stderr)
        sys.exit(1)
