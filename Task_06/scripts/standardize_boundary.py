#!/usr/bin/env python3
"""Standardize and validate Guangxi county administrative boundaries."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely import union_all

EXPECTED_EPSG = 4490
OVERLAP_TOLERANCE = 1e-10
BASIC_DIFFERENCE_TOLERANCE = 1e-8
CITY_CODE_TO_NAME = {
    "450100": "南宁市", "450200": "柳州市", "450300": "桂林市",
    "450400": "梧州市", "450500": "北海市", "450600": "防城港市",
    "450700": "钦州市", "450800": "贵港市", "450900": "玉林市",
    "451000": "百色市", "451100": "贺州市", "451200": "河池市",
    "451300": "来宾市", "451400": "崇左市",
}
STANDARD_COLUMNS = [
    "province_name", "province_adcode", "city_name", "city_adcode",
    "county_name", "county_adcode", "name", "adcode", "gb", "geometry",
]
LOGGER = logging.getLogger("boundary_standardization")


class BoundaryValidationError(RuntimeError):
    """Raised when boundary processing cannot safely continue."""


def _crs_text(gdf: gpd.GeoDataFrame) -> str | None:
    if gdf.crs is None:
        return None
    epsg = gdf.crs.to_epsg()
    return f"EPSG:{epsg}" if epsg else gdf.crs.to_string()


def load_boundary(path: Path, label: str = "boundary") -> gpd.GeoDataFrame:
    """Read a boundary and strictly require EPSG:4490."""
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    try:
        gdf = gpd.read_file(path)
    except Exception as exc:
        raise BoundaryValidationError(f"Unable to read {label}: {exc}") from exc
    if gdf.crs is None:
        raise BoundaryValidationError(f"{label} has no CRS")
    if gdf.crs.to_epsg() != EXPECTED_EPSG:
        raise BoundaryValidationError(
            f"{label} CRS is {_crs_text(gdf)}, expected EPSG:4490; no reprojection performed"
        )
    return gdf


def inspect_boundary(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Return schema, extent, attribute and geometry diagnostics."""
    types = Counter(gdf.geometry.geom_type.fillna("None"))
    return {
        "feature_count": int(len(gdf)),
        "fields": [str(c) for c in gdf.columns],
        "crs": _crs_text(gdf),
        "bounds": [float(x) for x in gdf.total_bounds],
        "geometry_types": {str(k): int(v) for k, v in types.items()},
        "empty_geometry": int(gdf.geometry.is_empty.sum()),
        "null_geometry": int(gdf.geometry.isna().sum()),
        "invalid_geometry": int((~gdf.geometry.is_valid & gdf.geometry.notna()).sum()),
        "missing_name": int(gdf["name"].isna().sum()) if "name" in gdf else len(gdf),
        "missing_gb": int(gdf["gb"].isna().sum()) if "gb" in gdf else len(gdf),
        "duplicate_name_rows": int(gdf.loc[gdf["name"].notna(), "name"].duplicated(False).sum()) if "name" in gdf else 0,
        "duplicate_gb_rows": int(gdf.loc[gdf["gb"].notna(), "gb"].astype(str).duplicated(False).sum()) if "gb" in gdf else 0,
    }


def extract_adcode(value: Any) -> str:
    """Extract the trailing six-digit administrative code from gb."""
    if value is None or pd.isna(value):
        raise ValueError("gb is missing")
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    if not re.fullmatch(r"\d+", text) or len(text) < 6:
        raise ValueError(f"unparseable gb: {value!r}")
    return text[-6:]


def add_admin_hierarchy(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add province, city and county fields from administrative codes."""
    missing = [c for c in ("name", "gb") if c not in gdf]
    if missing:
        raise BoundaryValidationError(f"Missing required fields: {missing}")
    result = gdf.copy()
    try:
        result["adcode"] = result["gb"].map(extract_adcode).astype("string")
    except ValueError as exc:
        raise BoundaryValidationError(str(exc)) from exc
    result["province_name"] = "广西壮族自治区"
    result["province_adcode"] = "450000"
    result["city_adcode"] = result["adcode"].str[:4] + "00"
    result["city_name"] = result["city_adcode"].map(CITY_CODE_TO_NAME).astype("string")
    result["county_name"] = result["name"].astype("string")
    result["county_adcode"] = result["adcode"]
    return result[STANDARD_COLUMNS]


def validate_attributes(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Validate required standardized attributes."""
    duplicate = gdf["adcode"].duplicated(False) & gdf["adcode"].notna()
    return {
        "missing_name": int(gdf["name"].isna().sum()),
        "missing_gb": int(gdf["gb"].isna().sum()),
        "missing_adcode": int(gdf["adcode"].isna().sum()),
        "duplicate_name_rows": int(gdf.loc[gdf["name"].notna(), "name"].duplicated(False).sum()),
        "duplicate_gb_rows": int(gdf.loc[gdf["gb"].notna(), "gb"].astype(str).duplicated(False).sum()),
        "duplicate_adcode_rows": int(duplicate.sum()),
        "duplicate_adcodes": sorted(gdf.loc[duplicate, "adcode"].astype(str).unique().tolist()),
        "gb_parse_error_count": 0,
        "gb_parse_errors": [],
    }


def validate_geometry(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Check geometry and positive-area overlaps without repair."""
    types = gdf.geometry.geom_type.fillna("None")
    overlaps: list[dict[str, Any]] = []
    index = gdf.sindex
    for left, geom in enumerate(gdf.geometry):
        if geom is None or geom.is_empty or not geom.is_valid:
            continue
        for right in index.query(geom, predicate="intersects"):
            right = int(right)
            if right <= left:
                continue
            overlap_area = float(geom.intersection(gdf.geometry.iloc[right]).area)
            if overlap_area > OVERLAP_TOLERANCE:
                overlaps.append({
                    "left_adcode": str(gdf.iloc[left].adcode),
                    "right_adcode": str(gdf.iloc[right].adcode),
                    "intersection_area_square_degrees_approx": overlap_area,
                })
    invalid = ~gdf.geometry.is_valid & gdf.geometry.notna()
    return {
        "empty": int(gdf.geometry.is_empty.sum()), "null": int(gdf.geometry.isna().sum()),
        "invalid_before": int(invalid.sum()), "invalid_after": int(invalid.sum()),
        "geometry_repaired": False,
        "polygon": int((types == "Polygon").sum()),
        "multipolygon": int((types == "MultiPolygon").sum()),
        "other": int((~types.isin(["Polygon", "MultiPolygon"])).sum()),
        "overlap_area_tolerance_square_degrees_approx": OVERLAP_TOLERANCE,
        "topology_overlap_count": len(overlaps), "topology_overlaps": overlaps,
    }


def _reference(path: Path, label: str) -> gpd.GeoDataFrame:
    result = load_boundary(path, label).copy()
    if "name" not in result or "gb" not in result:
        raise BoundaryValidationError(f"{label} missing name/gb")
    result["adcode"] = result["gb"].map(extract_adcode).astype("string")
    return result


def _compare(left: Any, right: Any) -> dict[str, Any]:
    equal = bool(left.equals(right))
    difference = float(left.symmetric_difference(right).area)
    relative = difference / max(float(right.area), 1e-30)
    return {
        "geometry_equal": equal,
        "symmetric_difference_square_degrees_approx": difference,
        "relative_symmetric_difference": relative,
        "geometry_basic_match": equal or relative <= BASIC_DIFFERENCE_TOLERANCE,
        "basic_match_relative_tolerance": BASIC_DIFFERENCE_TOLERANCE,
    }


def validate_city_boundaries(counties: gpd.GeoDataFrame, path: Path) -> dict[str, Any]:
    """Compare county unions with all 14 city reference boundaries."""
    if not path.is_file():
        return {"performed": False, "reason": "file not found", "results": []}
    cities = _reference(path, "city boundary")
    results = []
    for code, name in CITY_CODE_TO_NAME.items():
        county_rows = counties[counties.city_adcode == code]
        city_rows = cities[cities.adcode == code]
        item = {"city_name": name, "city_adcode": code, "county_count": int(len(county_rows)), "reference_feature_count": int(len(city_rows))}
        if county_rows.empty or len(city_rows) != 1:
            item.update({"geometry_equal": False, "geometry_basic_match": False})
        else:
            item.update(_compare(union_all(county_rows.geometry.array), city_rows.geometry.iloc[0]))
        results.append(item)
    codes = set(cities.adcode.astype(str))
    return {
        "performed": True, "reference_feature_count": int(len(cities)),
        "reference_city_codes": sorted(codes),
        "missing_expected_city_codes": sorted(set(CITY_CODE_TO_NAME) - codes),
        "unexpected_city_codes": sorted(codes - set(CITY_CODE_TO_NAME)),
        "area_metric_note": "Angular CRS indicator only; not m² or km².",
        "results": results,
    }


def validate_nanning_boundary(counties: gpd.GeoDataFrame, path: Path) -> dict[str, Any]:
    """Compare the Guangxi Nanning subset with the optional local file."""
    if not path.is_file():
        return {"performed": False, "reason": "file not found"}
    reference = _reference(path, "Nanning boundary")
    subset = counties[counties.city_adcode == "450100"]
    names_a, names_b = set(subset.name.astype(str)), set(reference.name.astype(str))
    codes_a, codes_b = set(subset.adcode.astype(str)), set(reference.adcode.astype(str))
    geometry_results = []
    for code in sorted(codes_a | codes_b):
        a, b = subset[subset.adcode == code], reference[reference.adcode == code]
        item = {"adcode": code}
        if len(a) == len(b) == 1:
            item["name"] = str(a.iloc[0]["name"])
            item.update(_compare(a.geometry.iloc[0], b.geometry.iloc[0]))
        else:
            item.update({"geometry_equal": False, "geometry_basic_match": False})
        geometry_results.append(item)
    return {
        "performed": True, "guangxi_subset_count": int(len(subset)), "reference_count": int(len(reference)),
        "count_equal": len(subset) == len(reference), "name_set_equal": names_a == names_b,
        "adcode_set_equal": codes_a == codes_b,
        "all_geometries_equal": all(x["geometry_equal"] for x in geometry_results),
        "all_geometries_basic_match": all(x["geometry_basic_match"] for x in geometry_results),
        "geometry_results": geometry_results,
    }


def save_processed_boundary(gdf: gpd.GeoDataFrame, gpkg: Path, geojson: Path) -> None:
    """Write standardized files without coordinate transformation."""
    gpkg.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(gpkg, layer="gx_county_boundary", driver="GPKG", index=False)
    gdf.to_file(geojson, driver="GeoJSON", index=False)


def generate_validation_report(source: Path, inspection: dict[str, Any], gdf: gpd.GeoDataFrame, attributes: dict[str, Any], geometry: dict[str, Any], city: dict[str, Any], nanning: dict[str, Any], unchanged: bool) -> dict[str, Any]:
    counts = gdf.groupby(["city_adcode", "city_name"]).size().reset_index(name="county_count")
    present = set(gdf.city_adcode.astype(str))
    admin = {
        "province_count": int(gdf.province_adcode.nunique()), "city_count": int(gdf.city_adcode.nunique()),
        "county_count": int(len(gdf)), "unmatched_city": int(gdf.city_name.isna().sum()),
        "all_14_city_codes_present": present == set(CITY_CODE_TO_NAME),
        "missing_city_codes": sorted(set(CITY_CODE_TO_NAME) - present),
        "unexpected_city_codes": sorted(present - set(CITY_CODE_TO_NAME)),
        "county_count_by_city": counts.to_dict(orient="records"),
    }
    failures = []
    if any(attributes[k] for k in ("missing_name", "missing_gb", "missing_adcode", "duplicate_adcode_rows")): failures.append("attribute validation failed")
    if any(geometry[k] for k in ("empty", "null", "invalid_before", "other", "topology_overlap_count")): failures.append("geometry validation failed")
    if admin["unmatched_city"] or not admin["all_14_city_codes_present"]: failures.append("administrative hierarchy failed")
    if city["performed"] and any(not x.get("geometry_basic_match", False) for x in city["results"]): failures.append("city validation failed")
    if nanning["performed"] and not all(nanning[k] for k in ("count_equal", "name_set_equal", "adcode_set_equal", "all_geometries_basic_match")): failures.append("Nanning validation failed")
    return {
        "source_file": str(source.resolve()), "source_crs": inspection["crs"], "output_crs": _crs_text(gdf),
        "coordinate_transformed": False, "geometry_modified": not unchanged, "geometry_repaired": False,
        "feature_count": int(len(gdf)), "source_inspection": inspection, "geometry": geometry,
        "attributes": attributes, "administrative_structure": admin,
        "city_validation": city, "nanning_validation": nanning,
        "notes": ["No coordinate transformation was performed.", "No geometry repair was performed."],
        "status": "PASS" if not failures else "FAIL", "failures": failures,
    }


def _paths() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[1]
    raw, processed = root / "data/boundary/raw", root / "data/boundary/processed"
    return {"county": raw / "广西壮族自治区_县.geojson", "city": raw / "广西壮族自治区_市.geojson", "nanning": raw / "南宁市_县.geojson", "gpkg": processed / "gx_county_boundary.gpkg", "geojson": processed / "gx_county_boundary.geojson", "report": root / "reports/boundary_validation_report.json"}


def main() -> int:
    """Run the boundary standardization workflow."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = _paths()
    try:
        LOGGER.info("[1/7] Loading source GeoJSON...")
        source = load_boundary(p["county"], "county boundary")
        inspection = inspect_boundary(source)
        LOGGER.info("      Features: %s; CRS: %s", len(source), inspection["crs"])
        LOGGER.info("[2/7] Checking attributes...")
        original_wkb = [g.wkb if g is not None else None for g in source.geometry]
        LOGGER.info("[3/7] Standardizing administrative codes...")
        standardized = add_admin_hierarchy(source)
        attributes = validate_attributes(standardized)
        LOGGER.info("      Matched cities: %s/%s", standardized.city_name.notna().sum(), len(standardized))
        LOGGER.info("[4/7] Checking geometries...")
        geometry = validate_geometry(standardized)
        unchanged = original_wkb == [g.wkb if g is not None else None for g in standardized.geometry]
        LOGGER.info("      Invalid: %s; overlaps: %s", geometry["invalid_before"], geometry["topology_overlap_count"])
        LOGGER.info("[5/7] Validating city and Nanning boundaries...")
        city = validate_city_boundaries(standardized, p["city"])
        nanning = validate_nanning_boundary(standardized, p["nanning"])
        report = generate_validation_report(p["county"], inspection, standardized, attributes, geometry, city, nanning, unchanged)
        if report["status"] != "PASS":
            p["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            raise BoundaryValidationError(str(report["failures"]))
        LOGGER.info("[6/7] Writing processed data...")
        save_processed_boundary(standardized, p["gpkg"], p["geojson"])
        LOGGER.info("[7/7] Writing validation report...")
        p["report"].parent.mkdir(parents=True, exist_ok=True)
        p["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        LOGGER.info("Boundary preprocessing completed. Status: PASS")
        return 0
    except (FileNotFoundError, BoundaryValidationError) as exc:
        LOGGER.error("ERROR: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
