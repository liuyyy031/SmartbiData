#!/usr/bin/env python3
"""Evaluate candidate metre CRSs and create the recommended projected boundary."""

from __future__ import annotations

import json
import logging
import math
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import shapely
from pyproj import CRS, Transformer, database
from pyproj.crs import ProjectedCRS
from pyproj.crs.coordinate_operation import AlbersEqualAreaConversion, TransverseMercatorConversion
from pyproj.enums import PJType
from shapely import get_coordinates, union_all
from shapely.geometry import Point, Polygon
from shapely.prepared import prep

SOURCE_EPSG = 4490
GRID_AXIS_SIZE = 23
DISTANCE_M = 1000.0
DIRECTIONS = (("N", 0.0), ("NE", 45.0), ("E", 90.0), ("SE", 135.0), ("S", 180.0), ("SW", 225.0), ("W", 270.0), ("NW", 315.0))
STANDARD_NAMES = (
    ("utm48_wgs84", "WGS 84 / UTM zone 48N"),
    ("utm49_wgs84", "WGS 84 / UTM zone 49N"),
    ("cgcs2000_gk6_cm105", "CGCS2000 / Gauss-Kruger CM 105E"),
    ("cgcs2000_gk6_cm111", "CGCS2000 / Gauss-Kruger CM 111E"),
    ("cgcs2000_gk3_cm108", "CGCS2000 / 3-degree Gauss-Kruger CM 108E"),
    ("cgcs2000_gk3_cm111", "CGCS2000 / 3-degree Gauss-Kruger CM 111E"),
)
LOGGER = logging.getLogger("projection_evaluation")


class ProjectionError(RuntimeError):
    """Raised when projection evaluation cannot continue."""


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    crs: CRS
    is_custom: bool = False
    intended_area: str | None = None


def _paths() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[1]
    return {
        "source": root / "data/boundary/processed/gx_county_boundary.gpkg",
        "output": root / "data/boundary/processed/gx_county_boundary_projected.gpkg",
        "csv": root / "reports/projection_comparison.csv",
        "report": root / "reports/projection_evaluation_report.json",
    }


def load_source(path: Path) -> gpd.GeoDataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    gdf = gpd.read_file(path, layer="gx_county_boundary")
    if gdf.crs is None or gdf.crs.to_epsg() != SOURCE_EPSG:
        raise ProjectionError(f"Source CRS must be EPSG:{SOURCE_EPSG}; got {gdf.crs}")
    return gdf


def discover_candidates(bounds: Sequence[float]) -> list[Candidate]:
    """Resolve standard CRS by name from the current EPSG DB and add regional CRS."""
    infos = database.query_crs_info(auth_name="EPSG", pj_types=[PJType.PROJECTED_CRS], allow_deprecated=False)
    index = {x.name: x.code for x in infos}
    result = []
    for candidate_id, name in STANDARD_NAMES:
        if name not in index:
            raise ProjectionError(f"EPSG database does not contain {name}")
        result.append(Candidate(candidate_id, CRS.from_authority("EPSG", index[name])))
    min_lon, min_lat, max_lon, max_lat = map(float, bounds)
    lon0, lat0 = (min_lon + max_lon) / 2, (min_lat + max_lat) / 2
    span = max_lat - min_lat
    lat1, lat2 = min_lat + span / 6, max_lat - span / 6
    base = CRS.from_epsg(SOURCE_EPSG)
    intended = f"Actual Guangxi bbox [{min_lon:.6f}, {min_lat:.6f}, {max_lon:.6f}, {max_lat:.6f}]"
    tm = ProjectedCRS(
        name="Guangxi CGCS2000 Regional Transverse Mercator",
        conversion=TransverseMercatorConversion(longitude_natural_origin=lon0, scale_factor_natural_origin=1.0, false_easting=500000),
        geodetic_crs=base,
    )
    albers = ProjectedCRS(
        name="Guangxi CGCS2000 Regional Albers Equal Area",
        conversion=AlbersEqualAreaConversion(latitude_first_parallel=lat1, latitude_second_parallel=lat2, latitude_false_origin=lat0, longitude_false_origin=lon0),
        geodetic_crs=base,
    )
    result.extend([
        Candidate("gx_custom_tm", CRS.from_user_input(tm), True, intended),
        Candidate("gx_custom_albers", CRS.from_user_input(albers), True, intended),
    ])
    return result


def _parameter(crs: CRS, names: set[str]) -> float | None:
    if crs.coordinate_operation is None:
        return None
    for p in crs.coordinate_operation.params:
        if p.name in names:
            return float(p.value)
    return None


def _metre(crs: CRS) -> bool:
    return bool(crs.axis_info) and all(a.unit_name.lower() in {"metre", "meter"} for a in crs.axis_info)


def metadata(candidate: Candidate, bounds: Sequence[float]) -> dict[str, Any]:
    crs = candidate.crs
    area = crs.area_of_use
    min_lon, min_lat, max_lon, max_lat = map(float, bounds)
    if candidate.is_custom:
        area_name, area_bounds, warning = candidate.intended_area, list(bounds), False
    elif area is None:
        area_name, area_bounds, warning = "Unknown", None, True
    else:
        area_name = area.name
        area_bounds = [area.west, area.south, area.east, area.north]
        warning = not (area.west <= min_lon and area.south <= min_lat and area.east >= max_lon and area.north >= max_lat)
    cm = _parameter(crs, {"Longitude of natural origin", "Longitude of false origin", "Longitude of projection centre"})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        proj = crs.to_proj4()
    return {
        "candidate_id": candidate.candidate_id, "crs_name": crs.name,
        "epsg": str(crs.to_epsg()) if crs.to_epsg() else None,
        "projection_method": crs.coordinate_operation.method_name if crs.coordinate_operation else None,
        "datum": crs.datum.name, "ellipsoid": crs.ellipsoid.name,
        "unit": crs.axis_info[0].unit_name, "central_meridian": cm,
        "scale_factor": _parameter(crs, {"Scale factor at natural origin"}),
        "first_standard_parallel": _parameter(crs, {"Latitude of 1st standard parallel"}),
        "second_standard_parallel": _parameter(crs, {"Latitude of 2nd standard parallel"}),
        "area_of_use": area_name, "area_of_use_bounds": area_bounds,
        "area_of_use_warning": warning, "is_standard_epsg": not candidate.is_custom and crs.to_epsg() is not None,
        "is_custom_crs": candidate.is_custom, "proj_string": proj,
        "wkt": crs.to_wkt(version="WKT2_2019"), "projjson": crs.to_json_dict(),
        "western_offset_from_central_meridian_degrees": None if cm is None else min_lon - cm,
        "eastern_offset_from_central_meridian_degrees": None if cm is None else max_lon - cm,
    }


def samples(geometry: Any, bounds: Sequence[float]) -> tuple[list[Point], dict[str, Any]]:
    prepared = prep(geometry)
    min_lon, min_lat, max_lon, max_lat = bounds
    points = [Point(float(x), float(y)) for y in np.linspace(min_lat, max_lat, GRID_AXIS_SIZE) for x in np.linspace(min_lon, max_lon, GRID_AXIS_SIZE) if prepared.contains(Point(float(x), float(y)))]
    representative = geometry.representative_point()
    if prepared.contains(representative) and not any(representative.equals(x) for x in points):
        points.append(representative)
    if not 100 <= len(points) <= 500:
        raise ProjectionError(f"Unexpected sample count: {len(points)}")
    special = {
        "west_near_extreme": [min(points, key=lambda p: p.x).x, min(points, key=lambda p: p.x).y],
        "east_near_extreme": [max(points, key=lambda p: p.x).x, max(points, key=lambda p: p.x).y],
        "south_near_extreme": [min(points, key=lambda p: p.y).x, min(points, key=lambda p: p.y).y],
        "north_near_extreme": [max(points, key=lambda p: p.y).x, max(points, key=lambda p: p.y).y],
    }
    return points, {"sample_count": len(points), "method": "deterministic bbox grid; retain points strictly inside Guangxi union", "grid_axis_size": GRID_AXIS_SIZE, "grid_candidate_count": GRID_AXIS_SIZE**2, "special_representative_points": special, "random_sampling": False}


def _stats(values: np.ndarray) -> dict[str, float]:
    return {"mean": float(values.mean()), "median": float(np.median(values)), "p95": float(np.quantile(values, .95)), "max": float(values.max())}


def evaluate_distance(candidate: Candidate, points: Sequence[Point], geod: Any) -> dict[str, Any]:
    transformer = Transformer.from_crs(SOURCE_EPSG, candidate.crs, always_xy=True)
    lons, lats, end_lons, end_lats, labels = [], [], [], [], []
    for point in points:
        for label, azimuth in DIRECTIONS:
            end_lon, end_lat, _ = geod.fwd(point.x, point.y, azimuth, DISTANCE_M)
            lons.append(point.x); lats.append(point.y); end_lons.append(end_lon); end_lats.append(end_lat); labels.append(label)
    x1, y1 = transformer.transform(lons, lats)
    x2, y2 = transformer.transform(end_lons, end_lats)
    projected = np.hypot(np.asarray(x2)-np.asarray(x1), np.asarray(y2)-np.asarray(y1))
    errors = np.abs(projected - DISTANCE_M); relative = errors / DISTANCE_M
    i = int(np.argmax(errors))
    return {
        "test_count": int(len(errors)), "directions": [x[0] for x in DIRECTIONS], "true_distance_m": DISTANCE_M,
        "absolute_error_m": _stats(errors), "relative_error": _stats(relative),
        "maximum_error_location": {"longitude": float(lons[i]), "latitude": float(lats[i]), "direction": labels[i], "projected_distance_m": float(projected[i]), "absolute_error_m": float(errors[i]), "relative_error": float(relative[i])},
    }


def _square(point: Point, geod: Any) -> tuple[list[float], list[float]]:
    distance = math.sqrt(2) * DISTANCE_M / 2
    coords = [geod.fwd(point.x, point.y, azimuth, distance)[:2] for azimuth in (225, 315, 45, 135)]
    return [x[0] for x in coords], [x[1] for x in coords]


def evaluate_local_area(candidate: Candidate, points: Sequence[Point], geod: Any) -> dict[str, Any]:
    transformer = Transformer.from_crs(SOURCE_EPSG, candidate.crs, always_xy=True)
    true, projected = [], []
    for point in points:
        lons, lats = _square(point, geod)
        true_area, _ = geod.polygon_area_perimeter(lons, lats)
        x, y = transformer.transform(lons, lats)
        true.append(abs(true_area)); projected.append(Polygon(zip(x, y)).area)
    true_a, projected_a = np.asarray(true), np.asarray(projected)
    absolute = np.abs(projected_a - true_a); relative = absolute / true_a
    i = int(np.argmax(relative))
    return {
        "test_count": len(points), "geodesic_area_mean_m2": float(true_a.mean()), "projected_area_mean_m2": float(projected_a.mean()),
        "absolute_error_m2": _stats(absolute), "relative_error": _stats(relative),
        "maximum_error_location": {"longitude": points[i].x, "latitude": points[i].y, "geodesic_area_m2": float(true_a[i]), "projected_area_m2": float(projected_a[i]), "absolute_error_m2": float(absolute[i]), "relative_error": float(relative[i])},
    }


def evaluate(candidate: Candidate, source: gpd.GeoDataFrame, union_geometry: Any, points: Sequence[Point], geod: Any, geodesic_area: float, bounds: Sequence[float]) -> dict[str, Any]:
    result = metadata(candidate, bounds)
    try:
        projected = source.to_crs(candidate.crs)
        coords = get_coordinates(projected.geometry.array)
        validation = {"transform_success": True, "feature_count": len(projected), "coordinate_values_finite": bool(np.isfinite(coords).all()), "invalid_geometry": int((~projected.geometry.is_valid).sum()), "empty_geometry": int(projected.geometry.is_empty.sum()), "null_geometry": int(projected.geometry.isna().sum())}
    except Exception as exc:
        validation = {"transform_success": False, "error": str(exc)}
    validation["passed"] = bool(validation.get("transform_success") and validation.get("feature_count") == len(source) and validation.get("coordinate_values_finite") and validation.get("invalid_geometry") == validation.get("empty_geometry") == validation.get("null_geometry") == 0 and _metre(candidate.crs))
    result["projection_validation"] = validation
    if not validation["passed"]:
        result["evaluation_status"] = "FAIL"; return result
    result["distance_1km"] = evaluate_distance(candidate, points, geod)
    result["local_area_approximately_1km2"] = evaluate_local_area(candidate, points, geod)
    projected_union = gpd.GeoSeries([union_geometry], crs=SOURCE_EPSG).to_crs(candidate.crs).iloc[0]
    projected_area = float(projected_union.area); error = abs(projected_area-geodesic_area)
    result["guangxi_union_area"] = {"geodesic_area_m2": geodesic_area, "projected_area_m2": projected_area, "absolute_error_m2": error, "relative_error": error/geodesic_area}
    result["evaluation_status"] = "PASS"
    return result


def _score(result: dict[str, Any]) -> float:
    d, a = result["distance_1km"]["absolute_error_m"], result["local_area_approximately_1km2"]["relative_error"]
    return .35*d["p95"] + .35*d["max"] + .2*a["p95"]*1000 + .1*a["max"]*1000


def choose(candidates: Sequence[Candidate], results: list[dict[str, Any]]) -> tuple[Candidate, dict[str, Any], list[dict[str, Any]]]:
    passed = [x for x in results if x["evaluation_status"] == "PASS"]
    for result in passed:
        core = _score(result); datum_penalty = 100 if "China 2000" not in result["datum"] else 0; coverage_penalty = 10 if result["area_of_use_warning"] else 0; custom_penalty = .02 if result["is_custom_crs"] else 0
        result["ranking"] = {"core_distortion_score": core, "datum_penalty": datum_penalty, "area_of_use_penalty": coverage_penalty, "custom_crs_documentation_penalty": custom_penalty, "decision_score": core+datum_penalty+coverage_penalty+custom_penalty}
    ranked = sorted(passed, key=lambda x: x["ranking"]["decision_score"])
    for i, result in enumerate(ranked, 1): result["ranking"]["rank"] = i
    eligible = [x for x in passed if "China 2000" in x["datum"] and not x["area_of_use_warning"]]
    selected = min(eligible, key=_score)
    candidate = next(x for x in candidates if x.candidate_id == selected["candidate_id"])
    rule = "No standard CGCS2000 candidate covers the full actual Guangxi bbox; selected the lowest-distortion full-coverage regional CGCS2000 candidate."
    recommendation = {
        "candidate_id": selected["candidate_id"], "crs_name": selected["crs_name"], "epsg": selected["epsg"], "proj_string": selected["proj_string"], "wkt": selected["wkt"],
        "unit": selected["unit"], "datum": selected["datum"], "ellipsoid": selected["ellipsoid"], "central_meridian": selected["central_meridian"],
        "first_standard_parallel": selected["first_standard_parallel"], "second_standard_parallel": selected["second_standard_parallel"],
        "distance_max_error_m": selected["distance_1km"]["absolute_error_m"]["max"], "distance_p95_error_m": selected["distance_1km"]["absolute_error_m"]["p95"],
        "area_max_relative_error": selected["local_area_approximately_1km2"]["relative_error"]["max"], "area_p95_relative_error": selected["local_area_approximately_1km2"]["relative_error"]["p95"],
        "guangxi_area_relative_error": selected["guangxi_union_area"]["relative_error"], "is_standard_epsg": selected["is_standard_epsg"], "is_custom_crs": selected["is_custom_crs"],
        "selection_rule": rule, "reason": rule + " It preserves China 2000, metre units, equal area and a stable single analysis surface.",
    }
    return candidate, recommendation, ranked


def _rows(results: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for r in results:
        d, a = r["distance_1km"], r["local_area_approximately_1km2"]
        rows.append({
            "candidate_id": r["candidate_id"], "crs_name": r["crs_name"], "epsg": r["epsg"], "proj_string": r["proj_string"], "projection_method": r["projection_method"], "datum": r["datum"], "ellipsoid": r["ellipsoid"], "unit": r["unit"], "central_meridian": r["central_meridian"], "area_of_use": r["area_of_use"], "area_of_use_warning": r["area_of_use_warning"],
            "distance_mean_error_m": d["absolute_error_m"]["mean"], "distance_median_error_m": d["absolute_error_m"]["median"], "distance_p95_error_m": d["absolute_error_m"]["p95"], "distance_max_error_m": d["absolute_error_m"]["max"],
            "distance_mean_relative_error": d["relative_error"]["mean"], "distance_p95_relative_error": d["relative_error"]["p95"], "distance_max_relative_error": d["relative_error"]["max"],
            "area_mean_absolute_error_m2": a["absolute_error_m2"]["mean"], "area_median_absolute_error_m2": a["absolute_error_m2"]["median"], "area_p95_absolute_error_m2": a["absolute_error_m2"]["p95"], "area_max_absolute_error_m2": a["absolute_error_m2"]["max"],
            "area_mean_relative_error": a["relative_error"]["mean"], "area_median_relative_error": a["relative_error"]["median"], "area_p95_relative_error": a["relative_error"]["p95"], "area_max_relative_error": a["relative_error"]["max"],
            "guangxi_area_relative_error": r["guangxi_union_area"]["relative_error"], "is_standard_epsg": r["is_standard_epsg"], "is_custom_crs": r["is_custom_crs"], "rank": r["ranking"]["rank"], "decision_score": r["ranking"]["decision_score"],
        })
    return rows


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = _paths()
    try:
        LOGGER.info("[1/6] Loading standardized Guangxi boundary...")
        source = load_source(p["source"]); bounds = [float(x) for x in source.total_bounds]
        LOGGER.info("      Features: %s; CRS: %s; Bounds: %s", len(source), source.crs.to_string(), bounds)
        union_geometry = union_all(source.geometry.array); geod = source.crs.get_geod(); geodesic_area = abs(float(geod.geometry_area_perimeter(union_geometry)[0]))
        LOGGER.info("[2/6] Discovering candidate CRS...")
        candidates = discover_candidates(bounds)
        LOGGER.info("      Candidates: %s; EPSG database: %s", len(candidates), database.get_database_metadata("EPSG.VERSION"))
        LOGGER.info("[3/6] Generating evaluation samples...")
        points, sampling = samples(union_geometry, bounds); LOGGER.info("      Sample points: %s", len(points))
        LOGGER.info("[4/6] Evaluating projection distortion...")
        results = []
        for candidate in candidates:
            result = evaluate(candidate, source, union_geometry, points, geod, geodesic_area, bounds); results.append(result)
            if result["evaluation_status"] != "PASS": raise ProjectionError(candidate.candidate_id)
            LOGGER.info("      %s P95/max: %.6f/%.6f m", candidate.candidate_id, result["distance_1km"]["absolute_error_m"]["p95"], result["distance_1km"]["absolute_error_m"]["max"])
        LOGGER.info("[5/6] Ranking candidate CRS...")
        selected, recommendation, ranked = choose(candidates, results); LOGGER.info("      Recommended: %s", recommendation["crs_name"])
        LOGGER.info("[6/6] Reprojecting Guangxi boundary...")
        projected = source.to_crs(selected.crs)
        if len(projected) != len(source) or (~projected.geometry.is_valid).any() or projected.geometry.is_empty.any(): raise ProjectionError("projected validation failed")
        p["output"].parent.mkdir(parents=True, exist_ok=True)
        projected.to_file(p["output"], layer="gx_county_boundary_projected", driver="GPKG", index=False)
        source_info = {"file": str(p["source"].resolve()), "crs": "EPSG:4490", "feature_count": len(source), "bounds": bounds, "longitude_span_degrees": bounds[2]-bounds[0], "latitude_span_degrees": bounds[3]-bounds[1], "bbox_center_longitude": (bounds[0]+bounds[2])/2, "bbox_center_latitude": (bounds[1]+bounds[3])/2, "union_geometry_type": union_geometry.geom_type, "union_geodesic_area_m2": geodesic_area}
        report = {
            "source": source_info,
            "software": {"epsg_database_version": database.get_database_metadata("EPSG.VERSION"), "geopandas": gpd.__version__, "pyproj": pyproj.__version__, "shapely": shapely.__version__, "pandas": pd.__version__},
            "sampling": sampling, "candidates": results, "ranking_candidate_ids": [x["candidate_id"] for x in ranked], "recommendation": recommendation,
            "output": {"file": str(p["output"].resolve()), "layer": "gx_county_boundary_projected", "source_crs": "EPSG:4490", "coordinate_transformed": True, "feature_count": len(projected), "invalid_geometry": 0, "empty_geometry": 0},
            "status": "PASS",
        }
        p["csv"].parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(_rows(results)).sort_values("rank").to_csv(p["csv"], index=False, encoding="utf-8-sig")
        p["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        LOGGER.info("Projection CRS selection completed. Status: PASS")
        return 0
    except (FileNotFoundError, ProjectionError) as exc:
        LOGGER.error("ERROR: %s", exc); return 1


if __name__ == "__main__":
    sys.exit(main())
