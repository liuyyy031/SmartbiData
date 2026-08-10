"""Create and validate the shared CRS configuration for Task_6."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import CRS


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "reports" / "projection_evaluation_report.json"
DEFAULT_SOURCE = ROOT / "data" / "boundary" / "processed" / "gx_county_boundary.gpkg"
DEFAULT_PROJECTED = ROOT / "data" / "boundary" / "processed" / "gx_county_boundary_projected.gpkg"
DEFAULT_OUTPUT = ROOT / "config" / "spatial_crs.json"


def load_json(path: Path) -> dict[str, Any]:
    """Read a UTF-8 JSON object."""
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def load_spatial_crs_config(path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    """Load the generated spatial CRS configuration."""
    return load_json(path)


def get_source_crs(config: dict[str, Any]) -> CRS:
    """Return the configured source CRS."""
    return CRS.from_user_input(config["preferred_crs_input"]["source"])


def get_analysis_crs(config: dict[str, Any]) -> CRS:
    """Return the configured analysis CRS from its authoritative WKT."""
    return CRS.from_wkt(config["preferred_crs_input"]["analysis"])


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _assert_boundary(gdf: gpd.GeoDataFrame, label: str) -> None:
    if len(gdf) != 111:
        raise ValueError(f"{label}: expected 111 features, found {len(gdf)}")
    if gdf.geometry.isna().any() or gdf.geometry.is_empty.any():
        raise ValueError(f"{label}: contains null or empty geometries")
    if (~gdf.geometry.is_valid).any():
        raise ValueError(f"{label}: contains invalid geometries")


def build_spatial_config(
    report_path: Path = DEFAULT_REPORT,
    source_path: Path = DEFAULT_SOURCE,
    projected_path: Path = DEFAULT_PROJECTED,
) -> dict[str, Any]:
    """Validate boundary outputs and construct the reusable CRS contract."""
    report = load_json(report_path)
    recommendation = report["recommendation"]
    source = gpd.read_file(source_path)
    projected = gpd.read_file(projected_path)
    _assert_boundary(source, "source boundary")
    _assert_boundary(projected, "projected boundary")

    source_crs = CRS.from_user_input(source.crs)
    analysis_crs = CRS.from_user_input(projected.crs)
    expected_crs = CRS.from_wkt(recommendation["wkt"])
    if source_crs.to_epsg() != 4490:
        raise ValueError(f"source CRS must be EPSG:4490, found {source_crs.to_string()}")
    if not analysis_crs.equals(expected_crs, ignore_axis_order=True):
        raise ValueError("projected GPKG CRS does not match projection recommendation")
    units = {axis.unit_name.lower() for axis in analysis_crs.axis_info}
    if not units or not all(unit in {"metre", "meter"} for unit in units):
        raise ValueError(f"analysis CRS is not metre based: {sorted(units)}")

    coordinate_operation = analysis_crs.coordinate_operation
    params = {
        parameter.name: parameter.value
        for parameter in (coordinate_operation.params if coordinate_operation else [])
    }
    datum_name = analysis_crs.datum.name if analysis_crs.datum else "unknown"
    if "china 2000" not in datum_name.lower():
        raise ValueError(f"analysis CRS does not preserve CGCS2000 datum: {datum_name}")

    return {
        "config_version": "1.0",
        "region": "广西壮族自治区",
        "files": {
            "source_boundary": _relative(source_path),
            "analysis_boundary": _relative(projected_path),
            "projection_report": _relative(report_path),
        },
        "source_crs": {
            "name": source_crs.name,
            "epsg": source_crs.to_epsg(),
            "datum": source_crs.datum.name if source_crs.datum else None,
            "unit": source_crs.axis_info[0].unit_name,
        },
        "analysis_crs": {
            "candidate_id": recommendation.get("candidate_id"),
            "name": analysis_crs.name,
            "epsg": analysis_crs.to_epsg(),
            "datum": datum_name,
            "ellipsoid": analysis_crs.ellipsoid.name,
            "projection_method": coordinate_operation.method_name if coordinate_operation else None,
            "unit": analysis_crs.axis_info[0].unit_name,
            "central_meridian": params.get("Longitude of false origin"),
            "latitude_of_origin": params.get("Latitude of false origin"),
            "standard_parallel_1": params.get("Latitude of 1st standard parallel"),
            "standard_parallel_2": params.get("Latitude of 2nd standard parallel"),
            "proj_string": analysis_crs.to_proj4(),
            "wkt": analysis_crs.to_wkt(),
        },
        "preferred_crs_input": {
            "source": "EPSG:4490",
            "analysis": analysis_crs.to_wkt(),
        },
        "usage": {
            "storage_and_domestic_exchange": "EPSG:4490",
            "distance_area_buffer_and_grid": "analysis CRS WKT in this file",
            "warning": "Do not calculate metre distances or areas in EPSG:4490.",
        },
        "validation": {
            "source_feature_count": len(source),
            "analysis_feature_count": len(projected),
            "attributes_unchanged": list(source.columns) == list(projected.columns),
            "analysis_unit_is_metre": True,
            "analysis_crs_matches_report": True,
            "invalid_geometry_count": int((~projected.geometry.is_valid).sum()),
            "empty_geometry_count": int(projected.geometry.is_empty.sum()),
        },
    }


def write_spatial_config(config: dict[str, Any], output_path: Path = DEFAULT_OUTPUT) -> None:
    """Write the shared CRS configuration as UTF-8 JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as stream:
        json.dump(config, stream, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--projected", type=Path, default=DEFAULT_PROJECTED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print("[1/3] Loading projection recommendation...")
    config = build_spatial_config(args.report, args.source, args.projected)
    print("[2/3] Validating source and projected boundaries...")
    write_spatial_config(config, args.output)
    print(f"[3/3] Spatial CRS config written: {args.output}")


if __name__ == "__main__":
    main()
