#!/usr/bin/env python3
"""拼接ASTER瓦片并构建Task_14南宁市30 m Albers分析DEM。"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import CRS
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin
from rasterio.warp import reproject
from shapely.geometry import mapping


RESOLUTION_METRES = 30.0
OUTPUT_NODATA = -9999
MAX_FILE_SIZE_BYTES = 95 * 1024 * 1024


class DemBuildError(RuntimeError):
    """当分析DEM构建或验证失败时抛出。"""


def archive_dem_member(path: Path) -> str:
    """返回ZIP中的唯一DEM条目。"""
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith("_dem.tif")]
    if len(members) != 1:
        raise DemBuildError(f"ZIP中的DEM条目数量不是1: {path.name}")
    return members[0]


def extract_dem_to_temporary(archive: Path, member: str, directory: Path) -> Path:
    """把ZIP内唯一DEM安全提取到任务临时目录，避免批量VSI合并不稳定。"""
    output = directory / f"{archive.stem}_dem.tif"
    with zipfile.ZipFile(archive) as source_archive:
        member_path = Path(member)
        if member_path.name != member or member_path.suffix.lower() != ".tif":
            raise DemBuildError(f"ZIP条目路径不安全或格式错误: {archive.name}/{member}")
        with source_archive.open(member) as source, output.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
    return output


def gdal_program(name: str) -> Path:
    """定位当前Conda环境内的GDAL命令行工具。"""
    executable = f"{name}.exe" if sys.platform == "win32" else name
    candidates = [
        Path(sys.prefix) / "Library/bin" / executable,
        Path(sys.prefix) / "bin" / executable,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    located = shutil.which(name)
    if located:
        return Path(located)
    raise DemBuildError(f"当前环境找不到GDAL工具: {name}")


def build_virtual_mosaic(sources: list[Path], output: Path) -> None:
    """使用GDAL VRT建立无复制的确定性瓦片拼接。"""
    command = [
        str(gdal_program("gdalbuildvrt")),
        "-overwrite",
        "-srcnodata", str(OUTPUT_NODATA),
        "-vrtnodata", str(OUTPUT_NODATA),
        str(output),
        *[str(path) for path in sources],
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0 or not output.is_file():
        message = completed.stderr.strip() or completed.stdout.strip() or "未知错误"
        raise DemBuildError(f"gdalbuildvrt失败: {message}")


def snapped_grid(bounds: np.ndarray) -> tuple[Any, int, int, list[float]]:
    """将输出范围向外取整到30 m整数坐标网格。"""
    minimum_x, minimum_y, maximum_x, maximum_y = [float(value) for value in bounds]
    left = math.floor(minimum_x / RESOLUTION_METRES) * RESOLUTION_METRES
    bottom = math.floor(minimum_y / RESOLUTION_METRES) * RESOLUTION_METRES
    right = math.ceil(maximum_x / RESOLUTION_METRES) * RESOLUTION_METRES
    top = math.ceil(maximum_y / RESOLUTION_METRES) * RESOLUTION_METRES
    width = int(round((right - left) / RESOLUTION_METRES))
    height = int(round((top - bottom) / RESOLUTION_METRES))
    return from_origin(left, top, RESOLUTION_METRES, RESOLUTION_METRES), width, height, [left, bottom, right, top]


def mask_outside_boundary(path: Path, geometries: list[dict[str, Any]]) -> None:
    """按块把南宁市边界外像元设置为NoData。"""
    with rasterio.open(path, "r+") as dataset:
        for _, window in dataset.block_windows(1):
            data = dataset.read(1, window=window)
            inside = geometry_mask(
                geometries,
                out_shape=(int(window.height), int(window.width)),
                transform=dataset.window_transform(window),
                invert=True,
                all_touched=False,
            )
            data[~inside] = OUTPUT_NODATA
            dataset.write(data, 1, window=window)


def raster_statistics(path: Path) -> dict[str, Any]:
    """以窗口方式统计有效高程和栅格结构。"""
    count = 0
    total = 0.0
    total_square = 0.0
    minimum: int | None = None
    maximum: int | None = None
    with rasterio.open(path) as dataset:
        for _, window in dataset.block_windows(1):
            data = dataset.read(1, window=window)
            valid = data[data != OUTPUT_NODATA].astype(np.float64)
            if valid.size == 0:
                continue
            count += int(valid.size)
            total += float(valid.sum())
            total_square += float(np.square(valid).sum())
            block_minimum = int(valid.min())
            block_maximum = int(valid.max())
            minimum = block_minimum if minimum is None else min(minimum, block_minimum)
            maximum = block_maximum if maximum is None else max(maximum, block_maximum)
        if count == 0:
            raise DemBuildError("输出DEM没有有效像元")
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
            "resolution": [float(dataset.res[0]), float(dataset.res[1])],
            "bounds": [float(value) for value in dataset.bounds],
            "nodata": dataset.nodata,
            "valid_pixel_count": count,
            "nodata_pixel_count": int(dataset.width * dataset.height - count),
            "minimum_m": minimum,
            "maximum_m": maximum,
            "mean_m": mean,
            "standard_deviation_m": math.sqrt(variance),
            "image_structure": dataset.tags(ns="IMAGE_STRUCTURE"),
            "overview_factors": dataset.overviews(1),
        }


def main() -> int:
    """执行拼接、重投影、裁剪、COG压缩和质量验证。"""
    repository = Path(__file__).resolve().parents[2]
    task_root = repository / "Task_14"
    raw_root = task_root / "data/raw/aster_gdem_v3"
    processed_root = task_root / "data/processed"
    reports_root = task_root / "reports"
    archives = sorted(raw_root.glob("ASTGTMV003_*.zip"))
    if len(archives) != 7:
        raise DemBuildError(f"预期7个原始ZIP，实际{len(archives)}个")

    source_report_path = reports_root / "source_validation_report.json"
    if not source_report_path.is_file():
        raise DemBuildError("缺少source_validation_report.json，请先运行源检查脚本")
    source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    if source_report.get("status") != "PASS":
        raise DemBuildError("原始DEM质量状态不是PASS")

    config = json.loads((repository / "Task_06/config/spatial_crs.json").read_text(encoding="utf-8"))
    analysis_crs = CRS.from_wkt(config["preferred_crs_input"]["analysis"])
    boundary = gpd.read_file(repository / "Task_01/data/processed/nanning_county_boundary_projected.gpkg")
    if not CRS.from_user_input(boundary.crs).equals(analysis_crs):
        raise DemBuildError("Task_01投影边界与Task_06分析坐标系不一致")
    transform, width, height, output_bounds = snapped_grid(boundary.total_bounds)
    geometries = [mapping(geometry) for geometry in boundary.geometry]
    output_path = processed_root / "nanning_dem_30m_albers.tif"

    with tempfile.TemporaryDirectory(prefix="task14_dem_", dir=task_root) as temporary:
        temporary_root = Path(temporary)
        extracted_root = temporary_root / "extracted"
        extracted_root.mkdir()
        mosaic_path = temporary_root / "aster_mosaic_epsg4326.vrt"
        warped_path = temporary_root / "nanning_dem_warped.tif"
        cog_path = temporary_root / "nanning_dem_30m_albers.tif"
        extracted_paths = [
            extract_dem_to_temporary(archive, archive_dem_member(archive), extracted_root)
            for archive in archives
        ]
        build_virtual_mosaic(extracted_paths, mosaic_path)

        profile = {
            "driver": "GTiff",
            "width": width,
            "height": height,
            "count": 1,
            "dtype": "int16",
            "crs": analysis_crs,
            "transform": transform,
            "nodata": OUTPUT_NODATA,
            "compress": "DEFLATE",
            "predictor": 2,
            "tiled": True,
            "blockxsize": 512,
            "blockysize": 512,
            "BIGTIFF": "IF_SAFER",
        }
        with rasterio.open(mosaic_path) as source, rasterio.open(warped_path, "w", **profile) as target:
            reproject(
                source=rasterio.band(source, 1),
                destination=rasterio.band(target, 1),
                src_transform=source.transform,
                src_crs=source.crs,
                src_nodata=OUTPUT_NODATA,
                dst_transform=transform,
                dst_crs=analysis_crs,
                dst_nodata=OUTPUT_NODATA,
                resampling=Resampling.bilinear,
                init_dest_nodata=True,
                num_threads=2,
                warp_mem_limit=512,
            )

        mask_outside_boundary(warped_path, geometries)
        raster_copy(
            warped_path,
            cog_path,
            driver="COG",
            compress="DEFLATE",
            predictor=2,
            blocksize=512,
            overview_resampling="AVERAGE",
            BIGTIFF="IF_SAFER",
        )
        statistics = raster_statistics(cog_path)
        file_size = cog_path.stat().st_size
        if file_size >= MAX_FILE_SIZE_BYTES:
            raise DemBuildError(
                f"压缩DEM为{file_size}字节，达到95 MB门槛，需要按方案拆分后再入库"
            )
        if statistics["dtype"] != "int16" or statistics["nodata"] != OUTPUT_NODATA:
            raise DemBuildError("输出DEM数据类型或NoData不符合要求")
        if statistics["resolution"] != [RESOLUTION_METRES, RESOLUTION_METRES]:
            raise DemBuildError("输出DEM分辨率不是30 m")
        if not CRS.from_wkt(statistics["crs"]).equals(analysis_crs):
            raise DemBuildError("输出DEM坐标系与Task_06 WKT不一致")
        if statistics["image_structure"].get("LAYOUT") != "COG":
            raise DemBuildError("输出栅格未被GDAL识别为COG布局")
        processed_root.mkdir(parents=True, exist_ok=True)
        cog_path.replace(output_path)

    report = {
        "task": "Task_14",
        "source_archive_count": len(archives),
        "source_product": "ASTER GDEM V3",
        "resampling": "bilinear",
        "mask_rule": "Task_01南宁市边界内保留，边界外设为-9999",
        "horizontal_reprojection": True,
        "vertical_datum_transformation": False,
        "vertical_reference_policy": "沿用ASTER源高程含义；源文件未编码垂直CRS",
        "hydrological_conditioning": False,
        "slope_generated": False,
        "output": {
            "file": output_path.relative_to(repository).as_posix(),
            "file_size_bytes": output_path.stat().st_size,
            "file_size_limit_bytes": MAX_FILE_SIZE_BYTES,
            "snapped_output_bounds": output_bounds,
            **raster_statistics(output_path),
        },
        "status": "PASS",
    }
    (reports_root / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Task_14分析DEM构建完成：{width}x{height}，"
        f"{output_path.stat().st_size / 1024 / 1024:.2f} MB，COG质量PASS。"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, DemBuildError, rasterio.errors.RasterioError) as error:
        print(f"Task_14分析DEM构建失败：{error}", file=sys.stderr)
        sys.exit(1)
