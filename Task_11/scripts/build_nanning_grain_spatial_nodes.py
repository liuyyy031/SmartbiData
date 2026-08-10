from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from pyproj import CRS, Transformer
from shapely.geometry import Point

from coordinate_transform import gcj02_to_wgs84, wgs84_to_gcj02
from pipeline_common import PROCESSED_DIR, TASK_ROOT, read_csv, truthy, write_csv


EXPECTED_SPATIAL_READY = 7
INPUT_PATH = PROCESSED_DIR / "nanning_grain_physical_sites.csv"
SPATIAL_CRS_PATH = TASK_ROOT.parent / "Task_06" / "config" / "spatial_crs.json"
GRID_PATH = TASK_ROOT.parent / "Task_05" / "data" / "grid" / "gx_grid_1km.gpkg"
GRID_RELATION_PATH = TASK_ROOT.parent / "Task_05" / "data" / "grid" / "gx_grid_county_relation.csv"
GRID_VALIDATION_PATH = TASK_ROOT.parent / "Task_05" / "reports" / "grid_validation_report.json"
GRID_CONFIG_PATH = TASK_ROOT.parent / "Task_05" / "config" / "spatial_grid.json"

SPATIAL_CSV_PATH = PROCESSED_DIR / "nanning_grain_spatial_nodes.csv"
PHYSICAL_GEOJSON_PATH = PROCESSED_DIR / "nanning_grain_physical_sites.geojson"
PHYSICAL_GPKG_PATH = PROCESSED_DIR / "nanning_grain_physical_sites.gpkg"
SPATIAL_GEOJSON_PATH = PROCESSED_DIR / "nanning_grain_spatial_nodes.geojson"
SPATIAL_GPKG_PATH = PROCESSED_DIR / "nanning_grain_spatial_nodes.gpkg"
ADMIN_MISMATCH_PATH = PROCESSED_DIR / "administrative_mismatch.csv"
VALIDATION_PATH = PROCESSED_DIR / "nanning_grain_spatial_validation.json"
REPORT_PATH = PROCESSED_DIR / "nanning_grain_spatial_report.md"

SPATIAL_FIELDS = [
    "candidate_id", "name", "parent_candidate_id", "parent_organization",
    "city", "county", "address", "entity_type", "node_type", "evidence_level",
    "address_confidence", "longitude_raw", "latitude_raw", "coordinate_system_raw",
    "longitude_project", "latitude_project", "coordinate_system_project",
    "coordinate_shift_m", "coordinate_roundtrip_error_m", "coordinate_shift_quality",
    "grid_id", "grid_assignment_method", "grid_primary_county_adcode",
    "grid_primary_county_name", "grid_county_names", "administrative_match",
    "geocoding_confidence", "spatial_ready", "source_url", "source_note",
]

ADMIN_MISMATCH_FIELDS = [
    "candidate_id", "name", "city", "county", "grid_id", "grid_assignment_method",
    "grid_primary_county_adcode", "grid_primary_county_name", "grid_county_names",
    "mismatch_reason",
]


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def load_project_crs() -> tuple[CRS, CRS, dict[str, Any]]:
    config = load_json(SPATIAL_CRS_PATH)
    source_epsg = int(config["source_crs"]["epsg"])
    source_crs = CRS.from_epsg(source_epsg)
    analysis_wkt = config["analysis_crs"]["wkt"]
    analysis_crs = CRS.from_wkt(analysis_wkt)
    if source_epsg != 4490:
        raise RuntimeError(f"项目 source_crs 与本阶段预期不一致：EPSG:{source_epsg}")
    if not analysis_crs.is_projected or analysis_crs.axis_info[0].unit_name.lower() not in {"metre", "meter"}:
        raise RuntimeError("项目 analysis_crs 不是米制投影坐标系。")
    return source_crs, analysis_crs, config


def transform_records(
    rows: list[dict[str, str]], source_crs: CRS, analysis_crs: CRS
) -> tuple[list[dict[str, Any]], list[str]]:
    to_analysis = Transformer.from_crs(source_crs, analysis_crs, always_xy=True)
    transformed: list[dict[str, Any]] = []
    errors: list[str] = []
    for row in rows:
        try:
            if row.get("coordinate_system_raw") != "GCJ02":
                raise ValueError(f"coordinate_system_raw={row.get('coordinate_system_raw')}")
            raw_lon, raw_lat = float(row["longitude_raw"]), float(row["latitude_raw"])
            if not (70 <= raw_lon <= 140 and 0 <= raw_lat <= 60):
                raise ValueError("原始经纬度超出合理范围")

            corrected_lon, corrected_lat = gcj02_to_wgs84(raw_lon, raw_lat)
            reconstructed_lon, reconstructed_lat = wgs84_to_gcj02(corrected_lon, corrected_lat)

            # GCJ-02 has no EPSG CRS.  We deliberately transform its numeric pair
            # with the project's metre projection only to measure the offset vector;
            # the raw coordinates are never assigned to a GeoDataFrame CRS.
            raw_x, raw_y = to_analysis.transform(raw_lon, raw_lat)
            corrected_x, corrected_y = to_analysis.transform(corrected_lon, corrected_lat)
            reconstructed_x, reconstructed_y = to_analysis.transform(reconstructed_lon, reconstructed_lat)
            shift_m = math.hypot(raw_x - corrected_x, raw_y - corrected_y)
            roundtrip_error_m = math.hypot(raw_x - reconstructed_x, raw_y - reconstructed_y)

            if shift_m < 10 or shift_m > 5000:
                shift_quality = "extreme_review"
            elif shift_m < 50 or shift_m > 2000:
                shift_quality = "attention"
            else:
                shift_quality = "normal"
            transformed.append({
                **row,
                "longitude_project": round(corrected_lon, 8),
                "latitude_project": round(corrected_lat, 8),
                "coordinate_system_project": "EPSG:4490",
                "coordinate_shift_m": round(shift_m, 3),
                "coordinate_roundtrip_error_m": round(roundtrip_error_m, 4),
                "coordinate_shift_quality": shift_quality,
            })
        except (TypeError, ValueError, OverflowError) as exc:
            errors.append(f"{row.get('candidate_id', '')}: {exc}")
    return transformed, errors


def load_relevant_grid(node_analysis: gpd.GeoDataFrame, analysis_crs: CRS) -> gpd.GeoDataFrame:
    min_x, min_y, max_x, max_y = node_analysis.total_bounds
    bbox = (min_x - 2000, min_y - 2000, max_x + 2000, max_y + 2000)
    grid = gpd.read_file(
        GRID_PATH,
        layer="gx_grid_1km",
        bbox=bbox,
        columns=["grid_id", "primary_county_adcode", "primary_county_name", "geometry"],
    )
    if grid.empty:
        raise RuntimeError("在7个节点范围内未读取到任何1 km网格。")
    if not CRS.from_user_input(grid.crs).equals(analysis_crs):
        raise RuntimeError("gx_grid_1km.gpkg CRS 与 spatial_crs.json analysis_crs 不一致。")
    if grid["grid_id"].duplicated().any():
        raise RuntimeError("局部网格存在重复 grid_id。")
    return grid


def assign_grids(
    node_analysis: gpd.GeoDataFrame, grid: gpd.GeoDataFrame
) -> dict[str, dict[str, str]]:
    point_view = node_analysis[["candidate_id", "geometry"]]
    grid_view = grid[["grid_id", "primary_county_adcode", "primary_county_name", "geometry"]]
    joined = gpd.sjoin(point_view, grid_view, how="left", predicate="within")
    assignments: dict[str, dict[str, str]] = {}
    for candidate_id, group in joined.groupby("candidate_id", sort=False):
        matches = group[group["grid_id"].notna()].sort_values("grid_id")
        if not matches.empty:
            selected = matches.iloc[0]
            assignments[candidate_id] = {
                "grid_id": str(selected["grid_id"]),
                "grid_assignment_method": "within",
                "grid_primary_county_adcode": str(selected["primary_county_adcode"]),
                "grid_primary_county_name": str(selected["primary_county_name"]),
            }

    for _, point_row in node_analysis.iterrows():
        candidate_id = point_row["candidate_id"]
        if candidate_id in assignments:
            continue
        boundary_matches = grid[grid.intersects(point_row.geometry)].sort_values("grid_id")
        if not boundary_matches.empty:
            selected = boundary_matches.iloc[0]
            assignments[candidate_id] = {
                "grid_id": str(selected["grid_id"]),
                "grid_assignment_method": "boundary_intersects",
                "grid_primary_county_adcode": str(selected["primary_county_adcode"]),
                "grid_primary_county_name": str(selected["primary_county_name"]),
            }
    return assignments


def validate_administration(
    records: list[dict[str, Any]], assignments: dict[str, dict[str, str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grid_ids = {item["grid_id"] for item in assignments.values()}
    relation = pd.read_csv(
        GRID_RELATION_PATH,
        usecols=["grid_id", "county_adcode", "county_name", "city_adcode", "city_name", "grid_area_ratio"],
        dtype={"grid_id": str, "county_adcode": str, "county_name": str, "city_adcode": str, "city_name": str},
    )
    relation = relation[relation["grid_id"].isin(grid_ids)].copy()
    by_grid = {grid_id: group for grid_id, group in relation.groupby("grid_id")}
    mismatches: list[dict[str, Any]] = []
    for row in records:
        assignment = assignments.get(row["candidate_id"], {})
        row.update(assignment)
        grid_id = assignment.get("grid_id", "")
        group = by_grid.get(grid_id)
        county_names: list[str] = []
        city_names: list[str] = []
        if group is not None:
            ordered = group.sort_values(["grid_area_ratio", "county_name"], ascending=[False, True])
            county_names = list(dict.fromkeys(ordered["county_name"].astype(str)))
            city_names = list(dict.fromkeys(ordered["city_name"].astype(str)))
        row["grid_county_names"] = ";".join(county_names)
        county_match = bool(grid_id and row["county"] in county_names)
        city_match = bool(grid_id and row["city"] in city_names)
        row["administrative_match"] = "true" if county_match and city_match else "false"
        if not county_match or not city_match:
            reason = "grid_unmatched" if not grid_id else (
                "city_and_county_mismatch" if not city_match and not county_match else ("city_mismatch" if not city_match else "county_mismatch")
            )
            mismatches.append({
                "candidate_id": row["candidate_id"],
                "name": row["name"],
                "city": row["city"],
                "county": row["county"],
                "grid_id": grid_id,
                "grid_assignment_method": assignment.get("grid_assignment_method", "unmatched"),
                "grid_primary_county_adcode": assignment.get("grid_primary_county_adcode", ""),
                "grid_primary_county_name": assignment.get("grid_primary_county_name", ""),
                "grid_county_names": row["grid_county_names"],
                "mismatch_reason": reason,
            })
    return records, mismatches


def atomic_write_vector(gdf: gpd.GeoDataFrame, path: Path, driver: str, layer: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"_{path.stem}.tmp{path.suffix}")
    if temp_path.exists():
        temp_path.unlink()
    kwargs: dict[str, Any] = {"driver": driver, "index": False}
    if layer:
        kwargs["layer"] = layer
    gdf.to_file(temp_path, **kwargs)
    if path.exists():
        path.unlink()
    temp_path.replace(path)


def build_vector_outputs(records: list[dict[str, Any]], source_crs: CRS) -> dict[str, bool]:
    physical_gdf = gpd.GeoDataFrame(
        records,
        geometry=[Point(float(row["longitude_project"]), float(row["latitude_project"])) for row in records],
        crs=source_crs,
    )
    spatial_gdf = physical_gdf[SPATIAL_FIELDS + ["geometry"]].copy()
    geojson_properties = [
        "candidate_id", "name", "node_type", "city", "county", "address", "grid_id",
        "grid_assignment_method", "geocoding_confidence", "evidence_level",
        "longitude_project", "latitude_project", "coordinate_shift_m",
    ]
    atomic_write_vector(physical_gdf, PHYSICAL_GEOJSON_PATH, "GeoJSON")
    atomic_write_vector(physical_gdf, PHYSICAL_GPKG_PATH, "GPKG", "nanning_grain_physical_sites")
    atomic_write_vector(spatial_gdf[geojson_properties + ["geometry"]], SPATIAL_GEOJSON_PATH, "GeoJSON")
    atomic_write_vector(spatial_gdf, SPATIAL_GPKG_PATH, "GPKG", "grain_supply_nodes")

    checks = {
        "physical_geojson_created": PHYSICAL_GEOJSON_PATH.is_file(),
        "physical_gpkg_created": PHYSICAL_GPKG_PATH.is_file(),
        "spatial_geojson_created": SPATIAL_GEOJSON_PATH.is_file(),
        "spatial_gpkg_created": SPATIAL_GPKG_PATH.is_file(),
    }
    check_physical_geojson = gpd.read_file(PHYSICAL_GEOJSON_PATH)
    check_physical_gpkg = gpd.read_file(PHYSICAL_GPKG_PATH, layer="nanning_grain_physical_sites")
    check_geojson = gpd.read_file(SPATIAL_GEOJSON_PATH)
    check_gpkg = gpd.read_file(SPATIAL_GPKG_PATH, layer="grain_supply_nodes")
    checks["physical_geojson_feature_count_valid"] = len(check_physical_geojson) == len(records)
    checks["physical_gpkg_feature_count_valid"] = len(check_physical_gpkg) == len(records)
    checks["physical_gpkg_crs_valid"] = CRS.from_user_input(check_physical_gpkg.crs).to_epsg() == 4490
    checks["geojson_feature_count_valid"] = len(check_geojson) == len(records)
    checks["gpkg_feature_count_valid"] = len(check_gpkg) == len(records)
    checks["gpkg_crs_valid"] = CRS.from_user_input(check_gpkg.crs).to_epsg() == 4490
    return checks


def write_report(validation: dict[str, Any]) -> None:
    node_lines = [
        f"- {row['name']}：{row['grid_id']}（{row['grid_assignment_method']}），县区校验={'通过' if row['administrative_match'] else '冲突'}，纠偏 {row['coordinate_shift_m']:.3f} m"
        for row in validation["nodes"]
    ]
    lines = [
        "# 南宁粮食 physical_site 坐标统一与1 km网格关联报告",
        "",
        "## 结论",
        "",
        f"输入 {validation['input_node_count']} 个 spatial_ready 节点，GCJ-02显式纠偏成功 {validation['coordinate_conversion_success_count']} 个、失败 {validation['coordinate_conversion_failed_count']} 个。",
        f"项目最终地理 CRS 为 {validation['coordinate_system_project']}；距离和网格计算使用既有 {validation['analysis_crs_name']}（米制）。",
        f"平均纠偏距离 {validation['average_coordinate_shift_m']:.3f} m，最大 {validation['max_coordinate_shift_m']:.3f} m，最小 {validation['min_coordinate_shift_m']:.3f} m。",
        f"1 km网格匹配 {validation['grid_matched_count']}/{validation['input_node_count']}，匹配率 {validation['grid_match_rate']:.1%}；行政区冲突 {validation['administrative_mismatch_count']} 条。",
        f"SPATIAL_DATA_READY = {str(validation['SPATIAL_DATA_READY']).lower()}；验证状态 = {validation['validation_status']}。",
        "",
        "## 7个节点对应网格",
        "",
        *node_lines,
        "",
        "## 输出验证",
        "",
        f"- GeoJSON：{'成功' if validation['outputs']['spatial_geojson_created'] and validation['outputs']['geojson_feature_count_valid'] else '失败'}。",
        f"- GPKG：{'成功' if validation['outputs']['spatial_gpkg_created'] and validation['outputs']['gpkg_feature_count_valid'] and validation['outputs']['gpkg_crs_valid'] else '失败'}，图层为 grain_supply_nodes。",
        "- 原始 longitude_raw / latitude_raw / GCJ02 字段完整保留；正式几何使用纠偏后的 EPSG:4490 经纬度。",
        "- GCJ-02没有被直接 set_crs 或直接 to_crs；纠偏算法位于 scripts/coordinate_transform.py。",
        "",
        "## 后续适用性",
        "",
        "当前节点数据已可作为后续洪涝空间分析的节点输入。本轮未计算洪水距离、运输路径、服务半径、优先级或调度结果。",
    ]
    if validation["warnings"]:
        lines += ["", "## 验证提示", "", *[f"- {warning}" for warning in validation["warnings"]]]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    source_crs, analysis_crs, crs_config = load_project_crs()
    grid_config = load_json(GRID_CONFIG_PATH)
    grid_validation = load_json(GRID_VALIDATION_PATH)
    if grid_validation.get("status") != "PASS":
        raise RuntimeError("既有1 km网格验证状态不是 PASS。")
    if int(grid_config.get("grid_size_m", 0)) != 1000:
        raise RuntimeError("既有网格尺寸不是1 km。")

    all_rows = read_csv(INPUT_PATH)
    ready_rows = [row for row in all_rows if truthy(row.get("spatial_ready"))]
    transformed, conversion_errors = transform_records(ready_rows, source_crs, analysis_crs)
    if not transformed:
        raise RuntimeError("没有坐标转换成功的节点。")

    node_geo = gpd.GeoDataFrame(
        transformed,
        geometry=[Point(float(row["longitude_project"]), float(row["latitude_project"])) for row in transformed],
        crs=source_crs,
    )
    node_analysis = node_geo.to_crs(analysis_crs)
    grid = load_relevant_grid(node_analysis, analysis_crs)
    assignments = assign_grids(node_analysis, grid)
    transformed, mismatches = validate_administration(transformed, assignments)

    write_csv(SPATIAL_CSV_PATH, transformed, SPATIAL_FIELDS)
    write_csv(ADMIN_MISMATCH_PATH, mismatches, ADMIN_MISMATCH_FIELDS)
    output_checks = build_vector_outputs(transformed, source_crs)

    shifts = [float(row["coordinate_shift_m"]) for row in transformed]
    roundtrip_errors = [float(row["coordinate_roundtrip_error_m"]) for row in transformed]
    grid_matched_count = sum(bool(row.get("grid_id")) for row in transformed)
    admin_match_count = sum(row.get("administrative_match") == "true" for row in transformed)
    extreme_shift_count = sum(row["coordinate_shift_quality"] == "extreme_review" for row in transformed)
    warnings: list[str] = []
    if len(ready_rows) != EXPECTED_SPATIAL_READY:
        warnings.append(f"expected_spatial_ready={EXPECTED_SPATIAL_READY}，actual_spatial_ready={len(ready_rows)}。")
    if conversion_errors:
        warnings.append("部分坐标转换失败：" + "; ".join(conversion_errors))
    if grid_matched_count != len(transformed):
        warnings.append("存在未匹配1 km网格的节点。")
    if mismatches:
        warnings.append("存在节点县区与网格县区关系冲突。")
    if extreme_shift_count:
        warnings.append("存在接近0或超过5 km的极端纠偏距离。")
    if max(roundtrip_errors) > 0.5:
        warnings.append("GCJ-02反解回代误差超过0.5 m。")
    if not all(output_checks.values()):
        warnings.append("空间文件输出或回读验证失败。")

    spatial_ready = (
        len(ready_rows) == EXPECTED_SPATIAL_READY
        and len(transformed) == EXPECTED_SPATIAL_READY
        and not conversion_errors
        and grid_matched_count == EXPECTED_SPATIAL_READY
        and not mismatches
        and not extreme_shift_count
        and max(roundtrip_errors) <= 0.5
        and all(output_checks.values())
    )
    validation = {
        "expected_spatial_ready": EXPECTED_SPATIAL_READY,
        "actual_spatial_ready": len(ready_rows),
        "input_node_count": len(ready_rows),
        "spatial_node_count": len(transformed),
        "coordinate_conversion_success_count": len(transformed),
        "coordinate_conversion_failed_count": len(conversion_errors),
        "coordinate_system_raw": "GCJ02",
        "coordinate_system_project": "EPSG:4490",
        "analysis_crs_name": crs_config["analysis_crs"]["name"],
        "analysis_crs_unit": crs_config["analysis_crs"]["unit"],
        "average_coordinate_shift_m": round(sum(shifts) / len(shifts), 3),
        "max_coordinate_shift_m": round(max(shifts), 3),
        "min_coordinate_shift_m": round(min(shifts), 3),
        "max_coordinate_roundtrip_error_m": round(max(roundtrip_errors), 4),
        "extreme_coordinate_shift_count": extreme_shift_count,
        "grid_matched_count": grid_matched_count,
        "grid_unmatched_count": len(transformed) - grid_matched_count,
        "grid_match_rate": round(grid_matched_count / len(transformed), 6),
        "administrative_match_count": admin_match_count,
        "administrative_mismatch_count": len(mismatches),
        "outputs": output_checks,
        "nodes": [
            {
                "candidate_id": row["candidate_id"],
                "name": row["name"],
                "longitude_project": row["longitude_project"],
                "latitude_project": row["latitude_project"],
                "coordinate_shift_m": row["coordinate_shift_m"],
                "grid_id": row.get("grid_id", ""),
                "grid_assignment_method": row.get("grid_assignment_method", "unmatched"),
                "administrative_match": row.get("administrative_match") == "true",
            }
            for row in transformed
        ],
        "warnings": warnings,
        "validation_status": "PASS" if spatial_ready else ("WARN" if transformed else "FAIL"),
        "SPATIAL_DATA_READY": spatial_ready,
    }
    VALIDATION_PATH.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if validation["validation_status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
