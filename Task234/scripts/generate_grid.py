"""Generate the fixed, full-square Guangxi 1 km analysis grid and county relations."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry

from spatial_config import get_analysis_crs, load_spatial_crs_config


ROOT = Path(__file__).resolve().parents[1]
BOUNDARY_PATH = ROOT / "data" / "boundary" / "processed" / "gx_county_boundary_projected.gpkg"
CRS_CONFIG_PATH = ROOT / "config" / "spatial_crs.json"
GRID_CONFIG_PATH = ROOT / "config" / "spatial_grid.json"
GRID_PATH = ROOT / "data" / "grid" / "gx_grid_1km.gpkg"
RELATION_PATH = ROOT / "data" / "grid" / "gx_grid_county_relation.csv"
REPORT_PATH = ROOT / "reports" / "grid_validation_report.json"
GRID_SIZE = 1000.0
GRID_AREA = GRID_SIZE * GRID_SIZE
ORIGIN_SNAP = 100000.0
AREA_EPSILON = 1e-6
FULL_AREA_TOLERANCE = 0.01
CHUNK_SIZE = 25000


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def _grid_token(value: int) -> str:
    return f"N{abs(value):06d}" if value < 0 else f"{value:06d}"


def _grid_id(row: int, col: int) -> str:
    return f"GX1K_R{_grid_token(row)}_C{_grid_token(col)}"


def load_inputs(boundary_path: Path, crs_config_path: Path) -> tuple[gpd.GeoDataFrame, dict[str, Any], CRS]:
    """Load and strictly validate the projected county boundary and CRS contract."""
    if not boundary_path.exists():
        raise FileNotFoundError(boundary_path)
    if not crs_config_path.exists():
        raise FileNotFoundError(crs_config_path)
    counties = gpd.read_file(boundary_path)
    config = load_spatial_crs_config(crs_config_path)
    analysis_crs = get_analysis_crs(config)
    actual_crs = CRS.from_user_input(counties.crs)
    if not actual_crs.equals(analysis_crs, ignore_axis_order=True):
        raise ValueError("boundary CRS does not match config/spatial_crs.json")
    if len(counties) != 111:
        raise ValueError(f"expected 111 counties, found {len(counties)}")
    required = {"county_adcode", "county_name", "city_adcode", "city_name", "geometry"}
    missing = required.difference(counties.columns)
    if missing:
        raise ValueError(f"boundary is missing fields: {sorted(missing)}")
    if counties.geometry.isna().any() or counties.geometry.is_empty.any():
        raise ValueError("boundary contains null or empty geometry")
    if (~counties.geometry.is_valid).any():
        raise ValueError("boundary contains invalid geometry; grid generation stopped")
    return counties, config, analysis_crs


def load_or_create_grid_definition(
    path: Path,
    bounds: np.ndarray,
    boundary_path: Path,
) -> dict[str, Any]:
    """Load the immutable grid definition or create it from a 100 km snapped origin."""
    if path.exists():
        with path.open("r", encoding="utf-8") as stream:
            definition = json.load(stream)
        if float(definition["grid_size_m"]) != GRID_SIZE:
            raise ValueError("existing spatial_grid.json uses a different cell size")
        return definition
    min_x, min_y, _, _ = (float(value) for value in bounds)
    origin_x = math.floor(min_x / ORIGIN_SNAP) * ORIGIN_SNAP
    origin_y = math.floor(min_y / ORIGIN_SNAP) * ORIGIN_SNAP
    definition = {
        "grid_name": "Guangxi 1km Spatial Grid",
        "grid_version": "1.0",
        "grid_size_m": 1000,
        "origin_snap_m": 100000,
        "origin_x": int(origin_x),
        "origin_y": int(origin_y),
        "grid_shape": "square",
        "analysis_crs_source": "config/spatial_crs.json",
        "boundary_source": boundary_path.resolve().relative_to(ROOT.resolve()).as_posix(),
        "grid_id_rule": "GX1K_R{row_token}_C{col_token}; non-negative indices use six zero-padded digits, negative indices use N followed by six zero-padded absolute digits",
        "grid_id_example": "GX1K_R000003_C000014",
        "geometry_policy": "full_square",
        "boundary_policy": "retain cells with positive-area intersection with Guangxi and record coverage ratio",
    }
    _write_json(path, definition)
    return definition


def generate_candidate_grid(
    bounds: np.ndarray,
    definition: dict[str, Any],
    crs: CRS,
) -> gpd.GeoDataFrame:
    """Create every square needed to cover the boundary bounding box."""
    origin_x = float(definition["origin_x"])
    origin_y = float(definition["origin_y"])
    min_bound_x, min_bound_y, max_x, max_y = (float(value) for value in bounds)
    start_col = int(math.floor((min_bound_x - origin_x) / GRID_SIZE))
    end_col = int(math.ceil((max_x - origin_x) / GRID_SIZE))
    start_row = int(math.floor((min_bound_y - origin_y) / GRID_SIZE))
    end_row = int(math.ceil((max_y - origin_y) / GRID_SIZE))
    col_values = np.arange(start_col, end_col, dtype=np.int32)
    row_values = np.arange(start_row, end_row, dtype=np.int32)
    rows = np.repeat(row_values, len(col_values))
    cols = np.tile(col_values, len(row_values))
    min_x = origin_x + cols.astype(float) * GRID_SIZE
    min_y = origin_y + rows.astype(float) * GRID_SIZE
    geometry = shapely.box(min_x, min_y, min_x + GRID_SIZE, min_y + GRID_SIZE)
    return gpd.GeoDataFrame({"row": rows, "col": cols}, geometry=geometry, crs=crs)


def _intersection_areas(left: np.ndarray, right: Any) -> np.ndarray:
    left = np.asarray(left, dtype=object)
    right_is_array = not isinstance(right, BaseGeometry)
    if right_is_array:
        right = np.asarray(right, dtype=object)
    areas: list[np.ndarray] = []
    for start in range(0, len(left), CHUNK_SIZE):
        part = left[start : start + CHUNK_SIZE]
        if right_is_array:
            other = right[start : start + CHUNK_SIZE]
        else:
            other = right
        areas.append(shapely.area(shapely.intersection(part, other)))
    return np.concatenate(areas) if areas else np.array([], dtype=float)


def retain_guangxi_cells(
    candidates: gpd.GeoDataFrame,
    guangxi_geometry: Any,
) -> gpd.GeoDataFrame:
    """Retain full squares with positive-area intersection and calculate coverage."""
    possible = candidates.loc[candidates.geometry.intersects(guangxi_geometry)].copy()
    areas = _intersection_areas(possible.geometry.array, guangxi_geometry)
    keep = areas > AREA_EPSILON
    retained = possible.loc[keep].copy().reset_index(drop=True)
    areas = areas[keep]
    near_full = np.abs(areas - GRID_AREA) <= FULL_AREA_TOLERANCE
    areas[near_full] = GRID_AREA
    retained["guangxi_area_m2"] = areas
    retained["grid_area_m2"] = GRID_AREA
    retained["coverage_ratio"] = areas / GRID_AREA
    retained["is_boundary_cell"] = ~near_full
    retained["grid_id"] = [_grid_id(int(row), int(col)) for row, col in zip(retained.row, retained.col)]
    centers = shapely.centroid(retained.geometry.array)
    retained["center_x"] = shapely.get_x(centers)
    retained["center_y"] = shapely.get_y(centers)
    transformer = Transformer.from_crs(retained.crs, "EPSG:4490", always_xy=True)
    lon, lat = transformer.transform(retained["center_x"].to_numpy(), retained["center_y"].to_numpy())
    retained["center_lon"] = lon
    retained["center_lat"] = lat
    return retained


def build_county_relations(
    grid: gpd.GeoDataFrame,
    counties: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Calculate positive-area grid/county relations without clipping grid geometry."""
    pairs = counties.sindex.query(grid.geometry, predicate="intersects")
    grid_positions = pairs[0].astype(np.int64)
    county_positions = pairs[1].astype(np.int64)
    left = grid.geometry.array.take(grid_positions)
    right = counties.geometry.array.take(county_positions)
    areas = _intersection_areas(left, right)
    keep = areas > AREA_EPSILON
    grid_positions = grid_positions[keep]
    county_positions = county_positions[keep]
    areas = areas[keep]
    grid_rows = grid.iloc[grid_positions]
    county_rows = counties.iloc[county_positions]
    relation = pd.DataFrame(
        {
            "grid_id": grid_rows["grid_id"].to_numpy(),
            "county_adcode": county_rows["county_adcode"].astype(str).to_numpy(),
            "county_name": county_rows["county_name"].astype(str).to_numpy(),
            "city_adcode": county_rows["city_adcode"].astype(str).to_numpy(),
            "city_name": county_rows["city_name"].astype(str).to_numpy(),
            "intersection_area_m2": areas,
            "grid_area_ratio": areas / GRID_AREA,
            "guangxi_area_ratio": areas / grid_rows["guangxi_area_m2"].to_numpy(),
        }
    )
    relation.sort_values(["grid_id", "intersection_area_m2", "county_adcode"], ascending=[True, False, True], inplace=True)
    relation.reset_index(drop=True, inplace=True)
    return relation


def attach_primary_county(grid: gpd.GeoDataFrame, relation: pd.DataFrame) -> gpd.GeoDataFrame:
    """Attach the largest-area county to each grid as a convenient primary label."""
    primary = relation.drop_duplicates("grid_id", keep="first").set_index("grid_id")
    result = grid.copy()
    result["primary_county_adcode"] = result["grid_id"].map(primary["county_adcode"])
    result["primary_county_name"] = result["grid_id"].map(primary["county_name"])
    result["primary_county_ratio"] = result["grid_id"].map(primary["grid_area_ratio"])
    return result


def validate_grid(
    candidates: gpd.GeoDataFrame,
    grid: gpd.GeoDataFrame,
    relation: pd.DataFrame,
    counties: gpd.GeoDataFrame,
    guangxi_geometry: Any,
    definition: dict[str, Any],
) -> dict[str, Any]:
    """Validate IDs, geometry, area conservation, relations and administrative coverage."""
    duplicate_ids = int(grid["grid_id"].duplicated().sum())
    duplicate_indices = int(grid.duplicated(["row", "col"]).sum())
    invalid = int((~grid.geometry.is_valid).sum())
    empty = int(grid.geometry.is_empty.sum())
    wrong_type = int((grid.geometry.geom_type != "Polygon").sum())
    wrong_area = int((np.abs(grid.geometry.area.to_numpy() - GRID_AREA) > FULL_AREA_TOLERANCE).sum())
    coverage_bad = int(((grid.coverage_ratio <= 0) | (grid.coverage_ratio > 1 + 1e-10)).sum())
    missing_relation = int((~grid.grid_id.isin(relation.grid_id)).sum())
    missing_primary = int(grid.primary_county_adcode.isna().sum())
    unknown_counties = sorted(set(relation.county_adcode) - set(counties.county_adcode.astype(str)))

    relation_by_grid = relation.groupby("grid_id", sort=False).intersection_area_m2.sum()
    expected_by_grid = grid.set_index("grid_id").guangxi_area_m2
    aligned = relation_by_grid.reindex(expected_by_grid.index, fill_value=0)
    max_grid_area_delta = float(np.abs(aligned - expected_by_grid).max())

    geospatial_area = float(shapely.area(guangxi_geometry))
    grid_area_sum = float(grid.guangxi_area_m2.sum())
    area_delta = grid_area_sum - geospatial_area
    area_relative = abs(area_delta) / geospatial_area
    county_relation_area = relation.groupby("county_adcode").intersection_area_m2.sum()
    county_true_area = counties.assign(_area=counties.geometry.area).groupby(counties.county_adcode.astype(str))._area.sum()
    county_delta = (county_relation_area.reindex(county_true_area.index, fill_value=0) - county_true_area).abs()
    county_max_delta = float(county_delta.max())
    county_pass_count = int((county_delta <= 0.01).sum())

    relation_counts = relation.groupby("grid_id").size()
    city_counts = relation.groupby("grid_id").city_adcode.nunique()
    full_count = int((~grid.is_boundary_cell).sum())
    boundary_count = int(grid.is_boundary_cell.sum())
    checks = {
        "unique_grid_id": duplicate_ids == 0,
        "unique_row_col": duplicate_indices == 0,
        "geometry_valid": invalid == 0 and empty == 0 and wrong_type == 0,
        "full_square_geometry": wrong_area == 0,
        "coverage_ratio_valid": coverage_bad == 0,
        "all_grids_have_relation": missing_relation == 0,
        "all_grids_have_primary_county": missing_primary == 0,
        "county_codes_valid": not unknown_counties,
        "grid_relation_area_consistent": max_grid_area_delta <= 0.01,
        "guangxi_area_conserved": abs(area_delta) <= 0.01,
        "all_county_areas_conserved": county_pass_count == len(county_true_area),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "grid_definition": definition,
        "crs": {
            "name": CRS.from_user_input(grid.crs).name,
            "epsg": CRS.from_user_input(grid.crs).to_epsg(),
            "unit": CRS.from_user_input(grid.crs).axis_info[0].unit_name,
        },
        "counts": {
            "candidate_cells": len(candidates),
            "retained_cells": len(grid),
            "full_cells": full_count,
            "boundary_cells": boundary_count,
            "relation_rows": len(relation),
            "cross_county_cells": int((relation_counts > 1).sum()),
            "cross_city_cells": int((city_counts > 1).sum()),
            "counties": int(relation.county_adcode.nunique()),
            "cities": int(relation.city_adcode.nunique()),
        },
        "geometry": {
            "invalid": invalid,
            "empty": empty,
            "non_polygon": wrong_type,
            "non_1000m_square": wrong_area,
        },
        "area_validation": {
            "guangxi_union_area_m2": geospatial_area,
            "grid_intersection_area_sum_m2": grid_area_sum,
            "absolute_error_m2": abs(area_delta),
            "relative_error": area_relative,
            "grid_relation_max_absolute_error_m2": max_grid_area_delta,
            "county_pass_count": county_pass_count,
            "county_count": len(county_true_area),
            "county_max_absolute_error_m2": county_max_delta,
        },
        "problems": {
            "duplicate_grid_id": duplicate_ids,
            "duplicate_row_col": duplicate_indices,
            "invalid_coverage_ratio": coverage_bad,
            "missing_relation": missing_relation,
            "missing_primary_county": missing_primary,
            "unknown_county_codes": unknown_counties,
        },
        "checks": checks,
        "geometry_modified": False,
        "grid_geometry_clipped": False,
    }


def save_outputs(grid: gpd.GeoDataFrame, relation: pd.DataFrame, report: dict[str, Any]) -> None:
    """Write the grid GeoPackage, relation CSV and validation JSON."""
    GRID_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "grid_id", "row", "col", "center_x", "center_y", "center_lon", "center_lat",
        "grid_area_m2", "guangxi_area_m2", "coverage_ratio", "is_boundary_cell",
        "primary_county_adcode", "primary_county_name", "primary_county_ratio", "geometry",
    ]
    grid[columns].to_file(GRID_PATH, layer="gx_grid_1km", driver="GPKG", index=False)
    relation.to_csv(RELATION_PATH, index=False, encoding="utf-8-sig")
    _write_json(REPORT_PATH, report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary", type=Path, default=BOUNDARY_PATH)
    parser.add_argument("--crs-config", type=Path, default=CRS_CONFIG_PATH)
    parser.add_argument("--grid-config", type=Path, default=GRID_CONFIG_PATH)
    args = parser.parse_args()

    print("[1/8] Loading projected county boundary and CRS config...")
    counties, _, analysis_crs = load_inputs(args.boundary, args.crs_config)
    print(f"      Counties: {len(counties)} | CRS: {analysis_crs.name}")
    guangxi = counties.geometry.union_all()
    definition = load_or_create_grid_definition(args.grid_config, counties.total_bounds, args.boundary)
    print(f"[2/8] Grid origin: ({definition['origin_x']}, {definition['origin_y']})")
    candidates = generate_candidate_grid(counties.total_bounds, definition, analysis_crs)
    print(f"[3/8] Candidate full squares: {len(candidates)}")
    grid = retain_guangxi_cells(candidates, guangxi)
    print(f"[4/8] Retained positive-area cells: {len(grid)}")
    relation = build_county_relations(grid, counties)
    print(f"[5/8] County relation rows: {len(relation)}")
    grid = attach_primary_county(grid, relation)
    print("[6/8] Validating IDs, geometries, relations and area conservation...")
    report = validate_grid(candidates, grid, relation, counties, guangxi, definition)
    if report["status"] != "PASS":
        raise RuntimeError(f"grid validation failed: {report['checks']}")
    print("[7/8] Writing grid GeoPackage and county relation CSV...")
    save_outputs(grid, relation, report)
    print(f"[8/8] Validation report: {REPORT_PATH}")
    print("Spatial grid generation completed. No clipped grid geometry was created.")


if __name__ == "__main__":
    main()
