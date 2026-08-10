from __future__ import annotations

import math


# Parameters used by the public GCJ-02 forward transformation.
# GCJ-02 has no EPSG identifier: these functions explicitly remove its offset
# before coordinates enter the project's EPSG:4490 / analysis-CRS workflow.
_A = 6378245.0
_EE = 0.00669342162296594323


def _outside_china(longitude: float, latitude: float) -> bool:
    return not (72.004 <= longitude <= 137.8347 and 0.8293 <= latitude <= 55.8271)


def _transform_lat(longitude_delta: float, latitude_delta: float) -> float:
    result = (
        -100.0
        + 2.0 * longitude_delta
        + 3.0 * latitude_delta
        + 0.2 * latitude_delta * latitude_delta
        + 0.1 * longitude_delta * latitude_delta
        + 0.2 * math.sqrt(abs(longitude_delta))
    )
    result += (20.0 * math.sin(6.0 * longitude_delta * math.pi) + 20.0 * math.sin(2.0 * longitude_delta * math.pi)) * 2.0 / 3.0
    result += (20.0 * math.sin(latitude_delta * math.pi) + 40.0 * math.sin(latitude_delta / 3.0 * math.pi)) * 2.0 / 3.0
    result += (160.0 * math.sin(latitude_delta / 12.0 * math.pi) + 320.0 * math.sin(latitude_delta * math.pi / 30.0)) * 2.0 / 3.0
    return result


def _transform_lon(longitude_delta: float, latitude_delta: float) -> float:
    result = (
        300.0
        + longitude_delta
        + 2.0 * latitude_delta
        + 0.1 * longitude_delta * longitude_delta
        + 0.1 * longitude_delta * latitude_delta
        + 0.1 * math.sqrt(abs(longitude_delta))
    )
    result += (20.0 * math.sin(6.0 * longitude_delta * math.pi) + 20.0 * math.sin(2.0 * longitude_delta * math.pi)) * 2.0 / 3.0
    result += (20.0 * math.sin(longitude_delta * math.pi) + 40.0 * math.sin(longitude_delta / 3.0 * math.pi)) * 2.0 / 3.0
    result += (150.0 * math.sin(longitude_delta / 12.0 * math.pi) + 300.0 * math.sin(longitude_delta / 30.0 * math.pi)) * 2.0 / 3.0
    return result


def wgs84_to_gcj02(longitude: float, latitude: float) -> tuple[float, float]:
    """Forward transform used only to solve and validate the GCJ-02 inverse."""
    if _outside_china(longitude, latitude):
        return longitude, latitude
    latitude_delta = _transform_lat(longitude - 105.0, latitude - 35.0)
    longitude_delta = _transform_lon(longitude - 105.0, latitude - 35.0)
    rad_lat = latitude / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1.0 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    latitude_delta = latitude_delta * 180.0 / ((_A * (1.0 - _EE)) / (magic * sqrt_magic) * math.pi)
    longitude_delta = longitude_delta * 180.0 / (_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return longitude + longitude_delta, latitude + latitude_delta


def gcj02_to_wgs84(
    longitude: float,
    latitude: float,
    *,
    tolerance_degrees: float = 1e-9,
    max_iterations: int = 40,
) -> tuple[float, float]:
    """Iteratively remove the GCJ-02 offset.

    The common one-step inverse leaves residual error.  This bisection solver
    repeatedly applies the public forward model until its reconstructed GCJ-02
    coordinate agrees with the input.  The result is an approximately unbiased
    geodetic longitude/latitude suitable for the project's documented
    engineering convention of storing domestic exchange coordinates in
    EPSG:4490.  It is not an EPSG ``to_crs`` operation on GCJ-02.
    """
    if _outside_china(longitude, latitude):
        return longitude, latitude
    delta = 0.01
    min_lon, max_lon = longitude - delta, longitude + delta
    min_lat, max_lat = latitude - delta, latitude + delta
    best_lon, best_lat = longitude, latitude
    for _ in range(max_iterations):
        best_lon = (min_lon + max_lon) / 2.0
        best_lat = (min_lat + max_lat) / 2.0
        gcj_lon, gcj_lat = wgs84_to_gcj02(best_lon, best_lat)
        lon_error = gcj_lon - longitude
        lat_error = gcj_lat - latitude
        if abs(lon_error) <= tolerance_degrees and abs(lat_error) <= tolerance_degrees:
            break
        if lon_error > 0:
            max_lon = best_lon
        else:
            min_lon = best_lon
        if lat_error > 0:
            max_lat = best_lat
        else:
            min_lat = best_lat
    return best_lon, best_lat

