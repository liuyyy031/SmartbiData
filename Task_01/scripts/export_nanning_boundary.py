#!/usr/bin/env python3
"""从Task_06权威边界导出并验证Task_01南宁市县级行政区划成果。"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import CRS


CITY_ADCODE = "450100"
EXPECTED_COUNTY_ADCODES = {
    "450102", "450103", "450105", "450107", "450108", "450109",
    "450110", "450123", "450124", "450125", "450126", "450181",
}
EXPECTED_COLUMNS = [
    "province_name", "province_adcode", "city_name", "city_adcode",
    "county_name", "county_adcode", "name", "adcode", "gb", "geometry",
]


class Task01ValidationError(RuntimeError):
    """当上游数据或输出成果不满足Task_01硬性要求时抛出。"""


def sha256_file(path: Path) -> str:
    """以分块方式计算文件SHA256。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def crs_label(crs: Any) -> str:
    """返回稳定、便于报告阅读的坐标系标识。"""
    parsed = CRS.from_user_input(crs)
    epsg = parsed.to_epsg()
    return f"EPSG:{epsg}" if epsg else parsed.name


def load_boundary(path: Path, label: str) -> gpd.GeoDataFrame:
    """读取上游边界并检查基础字段和几何。"""
    if not path.is_file():
        raise FileNotFoundError(f"缺少{label}: {path}")
    frame = gpd.read_file(path)
    missing = [column for column in EXPECTED_COLUMNS if column not in frame.columns]
    if missing:
        raise Task01ValidationError(f"{label}缺少字段: {missing}")
    if frame.crs is None:
        raise Task01ValidationError(f"{label}缺少坐标系")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise Task01ValidationError(f"{label}存在空几何")
    if (~frame.geometry.is_valid).any():
        raise Task01ValidationError(f"{label}存在无效几何")
    return frame[EXPECTED_COLUMNS].copy()


def select_nanning(frame: gpd.GeoDataFrame, label: str) -> gpd.GeoDataFrame:
    """按南宁市行政代码筛选并验证12个县级行政单元。"""
    city_codes = frame["city_adcode"].astype("string")
    subset = frame.loc[city_codes == CITY_ADCODE].copy()
    subset["county_adcode"] = subset["county_adcode"].astype("string")
    subset["adcode"] = subset["adcode"].astype("string")
    subset = subset.sort_values("county_adcode").reset_index(drop=True)
    codes = set(subset["county_adcode"].tolist())
    if len(subset) != 12 or codes != EXPECTED_COUNTY_ADCODES:
        raise Task01ValidationError(
            f"{label}南宁市县级单元不符合预期: count={len(subset)}, codes={sorted(codes)}"
        )
    if subset["county_adcode"].duplicated().any():
        raise Task01ValidationError(f"{label}存在重复县级行政代码")
    if set(subset["adcode"].tolist()) != EXPECTED_COUNTY_ADCODES:
        raise Task01ValidationError(f"{label}的adcode与county_adcode不一致")
    return subset


def summarize(frame: gpd.GeoDataFrame) -> dict[str, Any]:
    """生成质量报告所需的统一摘要。"""
    return {
        "feature_count": int(len(frame)),
        "crs": crs_label(frame.crs),
        "bounds": [float(value) for value in frame.total_bounds],
        "columns": [str(column) for column in frame.columns],
        "geometry_types": {
            str(name): int(count)
            for name, count in frame.geometry.geom_type.value_counts().sort_index().items()
        },
        "empty_geometry_count": int(frame.geometry.is_empty.sum()),
        "null_geometry_count": int(frame.geometry.isna().sum()),
        "invalid_geometry_count": int((~frame.geometry.is_valid).sum()),
        "duplicate_county_adcode_count": int(frame["county_adcode"].duplicated().sum()),
        "county_adcodes": sorted(frame["county_adcode"].astype(str).tolist()),
    }


def write_vector(frame: gpd.GeoDataFrame, path: Path, layer: str | None = None) -> None:
    """覆盖写入指定的GeoPackage或GeoJSON成果。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    if path.suffix.lower() == ".gpkg":
        frame.to_file(path, layer=layer, driver="GPKG", index=False)
    else:
        frame.to_file(path, driver="GeoJSON", index=False)


def manifest_row(root: Path, relative_path: str, category: str, description: str,
                 crs: str = "", feature_count: int | str = "") -> dict[str, Any]:
    """构造一条可校验的文件清单记录。"""
    path = root / relative_path
    return {
        "relative_path": relative_path.replace("\\", "/"),
        "category": category,
        "format": path.suffix.lower().lstrip("."),
        "crs": crs,
        "feature_count": feature_count,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "description": description,
    }


def write_manifest_and_checksums(task_root: Path, rows: list[dict[str, Any]]) -> None:
    """写入UTF-8 BOM清单，并为交付文件生成SHA256列表。"""
    manifest = task_root / "file_manifest.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    checksum_paths = [task_root / str(row["relative_path"]) for row in rows]
    checksum_paths.extend([
        task_root / "README.md",
        task_root / "scripts/export_nanning_boundary.py",
        manifest,
    ])
    lines = [
        f"{sha256_file(path)}  {path.relative_to(task_root).as_posix()}"
        for path in checksum_paths
    ]
    (task_root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    """执行导出、交叉验证、质量报告和完整性清单生成。"""
    repository = Path(__file__).resolve().parents[2]
    task_root = repository / "Task_01"
    source_geographic = repository / "Task_06/data/boundary/processed/gx_county_boundary.gpkg"
    source_projected = repository / "Task_06/data/boundary/processed/gx_county_boundary_projected.gpkg"
    spatial_config = repository / "Task_06/config/spatial_crs.json"

    geographic_all = load_boundary(source_geographic, "Task_06经纬度县界")
    projected_all = load_boundary(source_projected, "Task_06投影县界")
    if CRS.from_user_input(geographic_all.crs).to_epsg() != 4490:
        raise Task01ValidationError("Task_06经纬度县界不是EPSG:4490")

    config = json.loads(spatial_config.read_text(encoding="utf-8"))
    expected_projected_crs = CRS.from_wkt(config["preferred_crs_input"]["analysis"])
    if not CRS.from_user_input(projected_all.crs).equals(expected_projected_crs):
        raise Task01ValidationError("Task_06投影县界与空间配置WKT不一致")

    geographic = select_nanning(geographic_all, "经纬度成果")
    projected = select_nanning(projected_all, "投影成果")
    if list(geographic.columns) != list(projected.columns):
        raise Task01ValidationError("两种坐标体系的字段顺序不一致")

    expected_projection = geographic.to_crs(expected_projected_crs)
    maximum_geometry_distance = float(
        expected_projection.geometry.distance(projected.geometry).max()
    )
    if maximum_geometry_distance > 0.001:
        raise Task01ValidationError(
            f"投影成果与经纬度重投影结果不一致: max_distance={maximum_geometry_distance} m"
        )

    geographic_gpkg = task_root / "data/processed/nanning_county_boundary.gpkg"
    geographic_geojson = task_root / "data/processed/nanning_county_boundary.geojson"
    projected_gpkg = task_root / "data/processed/nanning_county_boundary_projected.gpkg"
    write_vector(geographic, geographic_gpkg, "nanning_county_boundary")
    write_vector(geographic, geographic_geojson)
    write_vector(projected, projected_gpkg, "nanning_county_boundary_projected")

    output_geographic = load_boundary(geographic_gpkg, "Task_01经纬度GPKG")
    output_geojson = load_boundary(geographic_geojson, "Task_01经纬度GeoJSON")
    output_projected = load_boundary(projected_gpkg, "Task_01投影GPKG")
    for label, frame in (
        ("Task_01经纬度GPKG", output_geographic),
        ("Task_01经纬度GeoJSON", output_geojson),
        ("Task_01投影GPKG", output_projected),
    ):
        select_nanning(frame, label)

    report = {
        "task": "Task_01",
        "dataset": "南宁市县级行政区划",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "geographic_file": source_geographic.relative_to(repository).as_posix(),
            "geographic_sha256": sha256_file(source_geographic),
            "projected_file": source_projected.relative_to(repository).as_posix(),
            "projected_sha256": sha256_file(source_projected),
            "spatial_config": spatial_config.relative_to(repository).as_posix(),
            "spatial_config_sha256": sha256_file(spatial_config),
            "selection_rule": "city_adcode == 450100",
        },
        "expected": {
            "feature_count": 12,
            "county_adcodes": sorted(EXPECTED_COUNTY_ADCODES),
            "geographic_crs": "EPSG:4490",
            "projected_crs": expected_projected_crs.name,
        },
        "outputs": {
            "geographic_gpkg": summarize(output_geographic),
            "geographic_geojson": summarize(output_geojson),
            "projected_gpkg": summarize(output_projected),
        },
        "cross_output_validation": {
            "column_order_equal": list(output_geographic.columns)
            == list(output_geojson.columns)
            == list(output_projected.columns),
            "county_adcode_sets_equal": set(output_geographic.county_adcode.astype(str))
            == set(output_geojson.county_adcode.astype(str))
            == set(output_projected.county_adcode.astype(str)),
            "maximum_projected_geometry_distance_m": maximum_geometry_distance,
            "geometry_distance_tolerance_m": 0.001,
        },
        "status": "PASS",
    }
    quality_report = task_root / "reports/quality_report.json"
    quality_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    rows = [
        manifest_row(task_root, "data/processed/nanning_county_boundary.gpkg", "data", "南宁市县级边界，GIS交换与关联", "EPSG:4490", 12),
        manifest_row(task_root, "data/processed/nanning_county_boundary.geojson", "data", "南宁市县级边界，SmartBI与通用交换", "EPSG:4490", 12),
        manifest_row(task_root, "data/processed/nanning_county_boundary_projected.gpkg", "data", "南宁市县级边界，米制空间分析", expected_projected_crs.name, 12),
        manifest_row(task_root, "reports/quality_report.json", "report", "自动化质量验收报告"),
        manifest_row(task_root, "reports/data_lineage.md", "documentation", "Task_06到Task_01的数据血缘说明"),
    ]
    write_manifest_and_checksums(task_root, rows)
    print("Task_01导出完成：12个县级行政单元，质量状态PASS。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, Task01ValidationError, OSError, ValueError) as error:
        print(f"Task_01导出失败：{error}", file=sys.stderr)
        sys.exit(1)
