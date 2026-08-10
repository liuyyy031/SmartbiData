from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pipeline_common import PROCESSED_DIR, TASK_ROOT, normalize_address, normalize_name, read_csv, write_csv


ENV_PATH = TASK_ROOT.parent / ".env"
CACHE_DIR = TASK_ROOT / "data" / "interim" / "geocoding_cache"
AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_POI_URL = "https://restapi.amap.com/v3/place/text"
COORDINATE_SYSTEM = "GCJ02"

TARGET_FIELDS = [
    "candidate_id", "name", "normalized_name", "entity_type", "node_type",
    "province", "city", "county", "address", "analysis_priority",
    "parent_organization", "source_files", "source_record_ids", "evidence_level",
    "address_status", "geocoding_status", "address_query", "geocoding_query",
]

REQUEST_FIELDS = [
    "candidate_id", "name", "entity_type", "node_type", "city", "county",
    "priority_order", "request_type", "query", "region", "query_variant",
    "request_status", "notes",
]

GEOCODED_FIELDS = [
    "candidate_id", "name", "entity_type", "node_type", "province", "city", "county",
    "address_original", "address_normalized", "longitude_raw", "latitude_raw",
    "coordinate_system_raw", "address_source", "address_confidence",
    "geocoding_provider", "geocoding_query", "geocoding_match_name",
    "geocoding_confidence", "geocoding_timestamp", "analysis_priority",
    "source_files", "source_record_ids", "evidence_level",
]

REVIEW_FIELDS = [
    "candidate_id", "name", "city", "county", "address", "failure_reason",
    "candidate_matches", "recommended_action",
]

CRITICAL_NAMES = [
    "南宁市储备粮管理有限责任公司五象粮库",
    "南宁市储备粮管理有限责任公司沙井粮库",
    "南宁市邕宁区粮食储备库",
    "南宁市江丰粮食收储管理中心",
    "横州市六景粮食储备中心库",
    "马山县储备粮管理公司",
    "隆安县储备粮管理公司",
    "上林县安恒储备粮管理有限公司",
    "广西壮族自治区五象粮食储备库有限公司",
    "广西壮族自治区南宁粮食储备库有限公司",
    "柳州市五里卡粮库有限公司",
    "广西柳州黄村粮食储备库有限公司",
    "广西壮族自治区柳州粮食储备库有限公司",
    "柳城县金稻香粮食收储有限责任公司",
    "柳州市柳江区柳粮粮油有限公司",
    "融水苗族自治县储备粮管理公司",
    "三江侗族自治县粮食购销和储备粮管理中心",
    "鹿寨县储备粮管理公司",
    "融安县储备粮管理公司",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_env_value(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name].strip()
    if not ENV_PATH.is_file():
        return ""
    for raw_line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def scalar(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def normalize_match_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    return re.sub(r"[\s·•,，.。()（）\[\]【】\-_—/\\]", "", text)


def name_similarity(left: str, right: str) -> float:
    left_norm, right_norm = normalize_match_name(left), normalize_match_name(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        shorter, longer = sorted((len(left_norm), len(right_norm)))
        return max(SequenceMatcher(None, left_norm, right_norm).ratio(), shorter / longer)
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def semantic_name(value: str) -> str:
    """Remove only generic geography/legal wrappers so corporate-family mismatches remain visible."""
    text = normalize_match_name(value)
    text = re.sub(r"^(?:广西壮族自治区|广西|南宁市|柳州市)", "", text)
    text = re.sub(
        r"^(?:兴宁区|青秀区|江南区|西乡塘区|良庆区|邕宁区|武鸣区|横州市|宾阳县|上林县|马山县|隆安县|城中区|鱼峰区|柳南区|柳北区|柳江区|柳城县|鹿寨县|融安县|融水苗族自治县|三江侗族自治县)",
        "",
        text,
    )
    return re.sub(r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司)", "", text)


def safe_poi_name_match(candidate_name: str, poi_name: str) -> bool:
    left, right = semantic_name(candidate_name), semantic_name(poi_name)
    if not left or not right:
        return False
    return left == right or SequenceMatcher(None, left, right).ratio() >= 0.90


def is_detailed_address(address: str, city: str, county: str) -> bool:
    text = normalize_address(address)
    for token in ("广西壮族自治区", "广西", city, county):
        if token:
            text = text.replace(token, "")
    return len(text) >= 6 and bool(re.search(r"路|街|道|巷|号|村|镇|乡|园|区|大厦|楼|屯|坡", text))


def entity_priority(entity_type: str) -> int:
    return {
        "physical_site": 0,
        "market": 1,
        "outlet": 2,
        "base": 3,
        "unknown": 4,
        "organization": 5,
    }.get(entity_type, 4)


def build_search_names(row: dict[str, str]) -> list[str]:
    names = [row["name"]]
    parent = row.get("parent_organization", "")
    if parent and row["name"].startswith(parent):
        suffix = row["name"][len(parent):].strip()
        if len(suffix) >= 3:
            names.append(suffix)
    if row.get("entity_type") in {"physical_site", "market", "outlet", "base"}:
        short = re.sub(
            r"^(?:广西壮族自治区|广西省|广西)?(?:南宁市|柳州市)?(?:兴宁区|青秀区|江南区|西乡塘区|良庆区|邕宁区|武鸣区|横州市|宾阳县|上林县|马山县|隆安县|城中区|鱼峰区|柳南区|柳北区|柳江区|柳城县|鹿寨县|融安县|融水苗族自治县|三江侗族自治县)?",
            "",
            row["name"],
        ).strip()
        if len(short) >= 4:
            names.append(short)
    return list(dict.fromkeys(name for name in names if name))[:3]


def build_targets() -> list[dict[str, str]]:
    candidates = read_csv(PROCESSED_DIR / "supply_node_candidates.csv")
    targets: list[dict[str, str]] = []
    for candidate in candidates:
        if candidate.get("analysis_priority") not in {"primary", "secondary"}:
            continue
        address = candidate.get("address", "").strip()
        city = candidate.get("city", "").strip()
        county = candidate.get("county", "").strip()
        query_region = " ".join(part for part in (city, county) if part)
        target = {
            "candidate_id": candidate.get("candidate_id", ""),
            "name": candidate.get("name", ""),
            "normalized_name": candidate.get("normalized_name", ""),
            "entity_type": candidate.get("entity_type", ""),
            "node_type": candidate.get("node_type", ""),
            "province": candidate.get("province", ""),
            "city": city,
            "county": county,
            "address": address,
            "analysis_priority": candidate.get("analysis_priority", ""),
            "parent_organization": candidate.get("parent_entity_name", ""),
            "source_files": candidate.get("source_files", ""),
            "source_record_ids": candidate.get("source_record_ids", ""),
            "evidence_level": candidate.get("evidence_level", ""),
            "address_status": "source_confirmed" if address else "region_only",
            "geocoding_status": "pending",
            "address_query": address,
            "geocoding_query": address or f"{candidate.get('name', '')} {query_region}".strip(),
        }
        targets.append(target)
    targets.sort(key=lambda row: (entity_priority(row["entity_type"]), row["analysis_priority"], row["city"], row["name"]))
    return targets


def request_json(url: str, params: dict[str, str], key: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({**params, "key": key})
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "Task11-auditable-geocoder/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {"status": "0", "info": "NETWORK_OR_RESPONSE_ERROR", "infocode": "LOCAL_ERROR"}


def amap_call(request_type: str, query: str, city: str, key: str) -> dict[str, Any]:
    if request_type == "geocode":
        return request_json(AMAP_GEOCODE_URL, {"address": query, "city": city, "output": "JSON"}, key)
    return request_json(
        AMAP_POI_URL,
        {"keywords": query, "city": city, "citylimit": "true", "offset": "20", "page": "1", "extensions": "all", "output": "JSON"},
        key,
    )


def split_location(value: str) -> tuple[str, str]:
    try:
        lon_text, lat_text = value.split(",", 1)
        lon, lat = float(lon_text), float(lat_text)
    except (ValueError, AttributeError):
        return "", ""
    if not (70 <= lon <= 140 and 0 <= lat <= 60):
        return "", ""
    return f"{lon:.6f}", f"{lat:.6f}"


def region_match(target: dict[str, str], city: str, county: str, address: str) -> tuple[bool, bool]:
    combined = f"{city}{county}{address}"
    city_ok = target["city"] in combined
    county_ok = not target["county"] or target["county"] in combined
    return city_ok, county_ok


def score_pois(target: dict[str, str], search_names: list[str], responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for response in responses:
        for poi in response.get("pois", []) if isinstance(response.get("pois"), list) else []:
            poi_id = scalar(poi.get("id")) or hashlib.sha1(json.dumps(poi, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if poi_id in seen_ids:
                continue
            seen_ids.add(poi_id)
            poi_name = scalar(poi.get("name"))
            city = scalar(poi.get("cityname"))
            county = scalar(poi.get("adname"))
            address = scalar(poi.get("address"))
            city_ok, county_ok = region_match(target, city, county, address)
            similarity = max((name_similarity(name, poi_name) for name in search_names), default=0.0)
            lon, lat = split_location(scalar(poi.get("location")))
            parent_only = bool(
                target.get("parent_organization")
                and normalize_match_name(poi_name) == normalize_match_name(target["parent_organization"])
            )
            score = similarity + (0.10 if city_ok else -0.40) + (0.05 if county_ok else -0.10)
            matches.append({
                "name": poi_name,
                "address": "".join(part for part in (scalar(poi.get("pname")), city, county, address) if part),
                "city": city,
                "county": county,
                "location": f"{lon},{lat}" if lon and lat else "",
                "similarity": round(similarity, 4),
                "score": round(score, 4),
                "city_match": city_ok,
                "county_match": county_ok,
                "parent_only": parent_only,
            })
    return sorted(matches, key=lambda item: (-item["score"], -item["similarity"], item["name"]))


def choose_poi(target: dict[str, str], matches: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str, str]:
    eligible = [item for item in matches if item["location"] and item["city_match"] and item["county_match"] and not item["parent_only"]]
    if not eligible:
        if any(item.get("parent_only") for item in matches):
            return None, "organization_site_ambiguity", ""
        if any(not item.get("city_match") for item in matches):
            return None, "region_mismatch", ""
        return None, "no_result" if not matches else "name_mismatch", ""
    top = eligible[0]
    close = [item for item in eligible[1:] if top["score"] - item["score"] < 0.08]
    if top["similarity"] == 1.0 and not any(item["similarity"] == 1.0 for item in close):
        return top, "", "high"
    if close:
        return None, "multiple_matches", ""
    if top["similarity"] >= 0.78:
        return top, "", "medium"
    return None, "name_mismatch", ""


def score_geocodes(target: dict[str, str], response: dict[str, Any]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for item in response.get("geocodes", []) if isinstance(response.get("geocodes"), list) else []:
        city = scalar(item.get("city"))
        county = scalar(item.get("district"))
        formatted = scalar(item.get("formatted_address"))
        city_ok, county_ok = region_match(target, city, county, formatted)
        lon, lat = split_location(scalar(item.get("location")))
        similarity = name_similarity(target["address"], formatted)
        level = scalar(item.get("level"))
        score = similarity + (0.20 if city_ok else -0.50) + (0.10 if county_ok else -0.15)
        matches.append({
            "name": formatted,
            "address": formatted,
            "city": city,
            "county": county,
            "location": f"{lon},{lat}" if lon and lat else "",
            "similarity": round(similarity, 4),
            "score": round(score, 4),
            "city_match": city_ok,
            "county_match": county_ok,
            "level": level,
        })
    return sorted(matches, key=lambda item: (-item["score"], -item["similarity"], item["name"]))


def choose_geocode(target: dict[str, str], matches: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str, str]:
    eligible = [item for item in matches if item["location"] and item["city_match"] and item["county_match"]]
    if not eligible:
        if matches and any(not item["city_match"] for item in matches):
            return None, "region_mismatch", ""
        return None, "no_result", ""
    top = eligible[0]
    if len(eligible) > 1 and top["score"] - eligible[1]["score"] < 0.08:
        return None, "multiple_matches", ""
    coarse_levels = {"省", "市", "区县", "乡镇", "村庄"}
    if top.get("level") in coarse_levels and not is_detailed_address(target["address"], target["city"], target["county"]):
        return None, "name_mismatch", ""
    return top, "", "high" if top["similarity"] >= 0.75 else "medium"


def compact_matches(matches: list[dict[str, Any]], limit: int = 5) -> str:
    safe = [
        {key: item.get(key, "") for key in ("name", "address", "city", "county", "location", "similarity", "city_match", "county_match")}
        for item in matches[:limit]
    ]
    return json.dumps(safe, ensure_ascii=False, separators=(",", ":"))


def enforce_result_safety(
    targets: list[dict[str, str]],
    results: list[dict[str, str]],
    reviews: list[dict[str, str]],
) -> None:
    """Demote POI family-name matches that are not the same named entity."""
    target_by_id = {row["candidate_id"]: row for row in targets}
    review_ids = {row["candidate_id"] for row in reviews}
    for index, result in enumerate(results):
        if not result.get("longitude_raw") or result.get("address_source") != "map_poi":
            continue
        target = target_by_id[result["candidate_id"]]
        match_name = result.get("geocoding_match_name", "")
        parent_match = bool(
            target.get("parent_organization")
            and normalize_match_name(match_name) == normalize_match_name(target["parent_organization"])
        )
        branch_sensitive = bool(target.get("parent_organization") or "分公司" in f"{target['name']}{match_name}")
        branch_exact = semantic_name(target["name"]) == semantic_name(match_name)
        if safe_poi_name_match(target["name"], match_name) and not parent_match and (not branch_sensitive or branch_exact):
            continue

        reason = "organization_site_ambiguity" if parent_match or "分公司" in f"{target['name']}{match_name}" else "name_mismatch"
        blank = blank_result(target)
        blank.update({
            "geocoding_provider": "amap",
            "geocoding_query": result.get("geocoding_query", target["geocoding_query"]),
            "geocoding_match_name": match_name,
            "geocoding_confidence": "manual_review",
            "geocoding_timestamp": result.get("geocoding_timestamp", ""),
        })
        results[index] = blank
        target["geocoding_status"] = "manual_review"
        target["address_status"] = "region_only" if not target["address"] else "source_confirmed"
        if target["candidate_id"] not in review_ids:
            reviews.append({
                "candidate_id": target["candidate_id"], "name": target["name"], "city": target["city"], "county": target["county"],
                "address": target["address"], "failure_reason": reason,
                "candidate_matches": json.dumps([{
                    "name": match_name,
                    "address": result.get("address_normalized", ""),
                    "location": f"{result.get('longitude_raw', '')},{result.get('latitude_raw', '')}",
                }], ensure_ascii=False, separators=(",", ":")),
                "recommended_action": "核查同一企业体系中的主体、分公司或设施，不自动复用相近实体坐标。",
            })
            review_ids.add(target["candidate_id"])

        path = cache_path(target["candidate_id"])
        if path.is_file():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                cached["final"] = {**blank, "success": False, "failure_reason": reason, "request_type": "poi"}
                path.write_text(json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8")
            except (json.JSONDecodeError, OSError):
                pass


def cache_path(candidate_id: str) -> Path:
    return CACHE_DIR / f"{candidate_id}.json"


def input_fingerprint(target: dict[str, str]) -> str:
    text = "|".join(target.get(field, "") for field in ("candidate_id", "name", "entity_type", "city", "county", "address"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_success_cache(target: dict[str, str]) -> dict[str, Any] | None:
    path = cache_path(target["candidate_id"])
    if not path.is_file():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    final = cached.get("final", {})
    unsafe_parent_match = bool(
        target.get("parent_organization")
        and normalize_match_name(scalar(final.get("geocoding_match_name")))
        == normalize_match_name(target["parent_organization"])
    )
    if cached.get("input_fingerprint") == input_fingerprint(target) and final.get("success") and not unsafe_parent_match:
        return cached
    return None


def save_cache(target: dict[str, str], attempts: list[dict[str, Any]], final: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "candidate_id": target["candidate_id"],
        "provider": "amap",
        "coordinate_system_raw": COORDINATE_SYSTEM,
        "input_fingerprint": input_fingerprint(target),
        "cached_at": utc_now(),
        "attempts": attempts,
        "final": final,
    }
    cache_path(target["candidate_id"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def blank_result(target: dict[str, str]) -> dict[str, str]:
    return {
        "candidate_id": target["candidate_id"],
        "name": target["name"],
        "entity_type": target["entity_type"],
        "node_type": target["node_type"],
        "province": target["province"],
        "city": target["city"],
        "county": target["county"],
        "address_original": target["address"],
        "address_normalized": normalize_address(target["address"]),
        "longitude_raw": "",
        "latitude_raw": "",
        "coordinate_system_raw": "",
        "address_source": "original_source" if target["address"] else "unknown",
        "address_confidence": "high" if target["address"] else "unknown",
        "geocoding_provider": "",
        "geocoding_query": target["geocoding_query"],
        "geocoding_match_name": "",
        "geocoding_confidence": "failed",
        "geocoding_timestamp": "",
        "analysis_priority": target["analysis_priority"],
        "source_files": target["source_files"],
        "source_record_ids": target["source_record_ids"],
        "evidence_level": target["evidence_level"],
    }


def apply_success(target: dict[str, str], selected: dict[str, Any], confidence: str, query: str, request_type: str, timestamp: str) -> dict[str, str]:
    result = blank_result(target)
    lon, lat = selected["location"].split(",", 1)
    enriched = not target["address"] and bool(selected.get("address"))
    result.update({
        "address_normalized": selected.get("address") or normalize_address(target["address"]),
        "longitude_raw": lon,
        "latitude_raw": lat,
        "coordinate_system_raw": COORDINATE_SYSTEM,
        "address_source": "original_source" if target["address"] else ("map_poi" if request_type == "poi" else "map_geocoder"),
        "address_confidence": "high" if target["address"] else confidence,
        "geocoding_provider": "amap",
        "geocoding_query": query,
        "geocoding_match_name": selected.get("name", ""),
        "geocoding_confidence": confidence,
        "geocoding_timestamp": timestamp,
    })
    if enriched:
        target["address_status"] = "map_enriched"
    target["geocoding_status"] = "success"
    return result


def run_geocoding(targets: list[dict[str, str]], key: str) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], dict[str, int]]:
    results: list[dict[str, str]] = []
    reviews: list[dict[str, str]] = []
    requests: list[dict[str, str]] = []
    counters = {"api_request_count": 0, "cache_hit_count": 0}
    api_usable = bool(key)

    for index, target in enumerate(targets, start=1):
        cached = load_success_cache(target)
        if cached:
            final = cached["final"]
            target["geocoding_status"] = "success"
            if not target["address"] and final.get("address_normalized"):
                target["address_status"] = "map_enriched"
            result = blank_result(target)
            result.update({field: scalar(final.get(field)) for field in GEOCODED_FIELDS if field in final})
            results.append(result)
            counters["cache_hit_count"] += 1
            requests.append({
                "candidate_id": target["candidate_id"], "name": target["name"], "entity_type": target["entity_type"],
                "node_type": target["node_type"], "city": target["city"], "county": target["county"],
                "priority_order": index, "request_type": final.get("request_type", "cache"),
                "query": final.get("geocoding_query", target["geocoding_query"]), "region": target["city"],
                "query_variant": "cached_success", "request_status": "cache_hit", "notes": "使用成功缓存，未重复请求 API。",
            })
            continue

        if not api_usable:
            target["geocoding_status"] = "not_run"
            result = blank_result(target)
            results.append(result)
            requests.append({
                "candidate_id": target["candidate_id"], "name": target["name"], "entity_type": target["entity_type"],
                "node_type": target["node_type"], "city": target["city"], "county": target["county"],
                "priority_order": index, "request_type": "geocode" if target["address"] else "poi",
                "query": target["geocoding_query"], "region": target["city"], "query_variant": "primary",
                "request_status": "queued_no_api_key", "notes": "缺少 AMAP_WEB_KEY，未发送网络请求。",
            })
            reviews.append({
                "candidate_id": target["candidate_id"], "name": target["name"], "city": target["city"], "county": target["county"],
                "address": target["address"], "failure_reason": "missing_address" if not target["address"] else "api_error",
                "candidate_matches": "[]", "recommended_action": "配置合法地图 API 后重试；不得猜测坐标。",
            })
            continue

        attempts: list[dict[str, Any]] = []
        selected: dict[str, Any] | None = None
        failure_reason = "no_result"
        confidence = ""
        successful_query = target["geocoding_query"]
        request_type = "geocode" if target["address"] else "poi"
        all_matches: list[dict[str, Any]] = []
        queries = [target["address"]] if target["address"] else build_search_names(target)

        for variant_index, query in enumerate(queries, start=1):
            if counters["api_request_count"]:
                time.sleep(0.55)
            response = amap_call(request_type, query, target["city"], key)
            counters["api_request_count"] += 1
            attempts.append({
                "request_type": request_type,
                "query": query,
                "region": target["city"],
                "requested_at": utc_now(),
                "response": response,
            })
            request_ok = scalar(response.get("status")) == "1"
            requests.append({
                "candidate_id": target["candidate_id"], "name": target["name"], "entity_type": target["entity_type"],
                "node_type": target["node_type"], "city": target["city"], "county": target["county"],
                "priority_order": index, "request_type": request_type, "query": query, "region": target["city"],
                "query_variant": f"variant_{variant_index}", "request_status": "sent_ok" if request_ok else "api_error",
                "notes": "API 响应已按 candidate 缓存；未保存密钥。",
            })
            if not request_ok:
                failure_reason = "api_error"
                infocode = scalar(response.get("infocode"))
                if infocode not in {"", "10000", "10021", "LOCAL_ERROR"}:
                    api_usable = False
                break
            if request_type == "geocode":
                all_matches = score_geocodes(target, response)
                selected, failure_reason, confidence = choose_geocode(target, all_matches)
            else:
                all_matches = score_pois(target, build_search_names(target), [item["response"] for item in attempts])
                selected, failure_reason, confidence = choose_poi(target, all_matches)
            if selected:
                successful_query = query
                break
            time.sleep(0.12)

        timestamp = utc_now()
        if selected:
            result = apply_success(target, selected, confidence, successful_query, request_type, timestamp)
            results.append(result)
            final = {**result, "success": True, "request_type": request_type}
        else:
            target["geocoding_status"] = "manual_review" if failure_reason in {
                "multiple_matches", "name_mismatch", "region_mismatch", "organization_site_ambiguity"
            } else "failed"
            result = blank_result(target)
            result["geocoding_provider"] = "amap" if attempts else ""
            result["geocoding_timestamp"] = timestamp if attempts else ""
            result["geocoding_confidence"] = "manual_review" if target["geocoding_status"] == "manual_review" else "failed"
            results.append(result)
            action = {
                "multiple_matches": "人工比较候选 POI，不自动选择第一条。",
                "name_mismatch": "补充官方地址或设施别名后重试。",
                "region_mismatch": "核查行政区与地图返回城市，禁止跨市自动接受。",
                "organization_site_ambiguity": "核查具体设施地址，禁止使用母公司办公地址代替。",
                "api_error": "检查 API 权限、配额或网络后重试。",
            }.get(failure_reason, "补充官方地址或人工核验 POI。")
            reviews.append({
                "candidate_id": target["candidate_id"], "name": target["name"], "city": target["city"], "county": target["county"],
                "address": target["address"], "failure_reason": failure_reason,
                "candidate_matches": compact_matches(all_matches), "recommended_action": action,
            })
            final = {**result, "success": False, "failure_reason": failure_reason, "request_type": request_type}
        save_cache(target, attempts, final)

    return results, reviews, requests, counters


def validate_outputs(targets: list[dict[str, str]], results: list[dict[str, str]], reviews: list[dict[str, str]], key: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    target_ids = {row["candidate_id"] for row in targets}
    result_ids = {row["candidate_id"] for row in results}
    if len(targets) != len(target_ids) or target_ids != result_ids:
        errors.append("geocoding targets 与正式结果的 candidate_id 不一一对应。")
    if any(row["analysis_priority"] not in {"primary", "secondary"} for row in targets):
        errors.append("geocoding_targets.csv 含非 primary/secondary 记录。")

    successes = [row for row in results if row["longitude_raw"] and row["latitude_raw"]]
    for row in successes:
        try:
            lon, lat = float(row["longitude_raw"]), float(row["latitude_raw"])
        except ValueError:
            errors.append(f"{row['candidate_id']} 经纬度不是数值。")
            continue
        if not (104 <= lon <= 113 and 20 <= lat <= 27):
            errors.append(f"{row['candidate_id']} 坐标超出广西合理范围。")
        if row["coordinate_system_raw"] != COORDINATE_SYSTEM:
            errors.append(f"{row['candidate_id']} 缺少正确的原始坐标系标记。")

    coordinate_entities: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in successes:
        coordinate_entities[(row["longitude_raw"], row["latitude_raw"])].append(row)
    excessive = {coord: rows for coord, rows in coordinate_entities.items() if len(rows) >= 5}
    if excessive:
        warnings.append(f"发现 {len(excessive)} 个坐标对应至少 5 个不同 candidate，需检查是否为行政区中心点或泛化结果。")

    result_by_id = {row["candidate_id"]: row for row in results}
    for target in targets:
        result = result_by_id[target["candidate_id"]]
        if target["entity_type"] == "physical_site" and result["geocoding_match_name"]:
            parent = target.get("parent_organization", "")
            if parent and normalize_match_name(result["geocoding_match_name"]) == normalize_match_name(parent):
                errors.append(f"{target['candidate_id']} physical_site 错误匹配到母公司名称。")

    output_paths = [
        PROCESSED_DIR / "geocoding_targets.csv",
        PROCESSED_DIR / "geocoding_requests.csv",
        PROCESSED_DIR / "geocoded_supply_nodes.csv",
        PROCESSED_DIR / "geocoding_review.csv",
        PROCESSED_DIR / "geocoding_report.json",
        PROCESSED_DIR / "geocoding_report.md",
        *CACHE_DIR.glob("*.json"),
    ]
    if key:
        leaked = [str(path) for path in output_paths if path.is_file() and key.encode("utf-8") in path.read_bytes()]
        if leaked:
            errors.append("检测到 API Key 出现在输出文件；相关输出必须清理。")
    if reviews:
        warnings.append(f"{len(reviews)} 条记录需要人工复核或后续重试。")
    return errors, warnings


def build_report(targets: list[dict[str, str]], results: list[dict[str, str]], reviews: list[dict[str, str]], counters: dict[str, int], key_present: bool) -> dict[str, Any]:
    successes = [row for row in results if row["longitude_raw"] and row["latitude_raw"]]
    critical_by_name = {row["name"]: row for row in results}
    unresolved_critical = [name for name in CRITICAL_NAMES if not critical_by_name.get(name, {}).get("longitude_raw")]
    return {
        "target_count": len(targets),
        "nanning_target_count": sum(row["analysis_priority"] == "primary" for row in targets),
        "liuzhou_target_count": sum(row["analysis_priority"] == "secondary" for row in targets),
        "already_had_address_count": sum(bool(row["address"]) for row in targets),
        "address_enriched_count": sum(not row["address_original"] and bool(row["address_normalized"]) for row in successes),
        "geocoding_success_count": len(successes),
        "nanning_geocoding_success_count": sum(row["analysis_priority"] == "primary" for row in successes),
        "liuzhou_geocoding_success_count": sum(row["analysis_priority"] == "secondary" for row in successes),
        "geocoding_high_confidence_count": sum(row["geocoding_confidence"] == "high" for row in successes),
        "geocoding_medium_confidence_count": sum(row["geocoding_confidence"] == "medium" for row in successes),
        "manual_review_count": sum(row["geocoding_confidence"] == "manual_review" for row in results),
        "failed_count": sum(row["geocoding_confidence"] == "failed" for row in results),
        "physical_site_success_count": sum(row["entity_type"] == "physical_site" for row in successes),
        "organization_success_count": sum(row["entity_type"] == "organization" for row in successes),
        "provider_distribution": dict(Counter(row["geocoding_provider"] for row in successes if row["geocoding_provider"])),
        "coordinate_system_distribution": dict(Counter(row["coordinate_system_raw"] for row in successes if row["coordinate_system_raw"])),
        "api_request_count": counters["api_request_count"],
        "cache_hit_count": counters["cache_hit_count"],
        "api_key_configured": key_present,
        "unresolved_critical_nodes": unresolved_critical,
    }


def write_report_markdown(report: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    unresolved = report["unresolved_critical_nodes"]
    lines = [
        "# 南宁、柳州社会应急保供节点地理编码报告",
        "",
        "> 本轮只处理 analysis_priority=primary/secondary。未删除其他 candidates，未执行 CRS 转换、1 km 网格关联、洪涝分析或最终节点筛选。",
        "",
        "## 结果摘要",
        "",
        f"- 目标：{report['target_count']} 个，其中南宁 {report['nanning_target_count']} 个、柳州 {report['liuzhou_target_count']} 个。",
        f"- 原有明确地址：{report['already_had_address_count']} 个；通过地图 POI 新补地址：{report['address_enriched_count']} 个。",
        f"- 成功获得原始地图坐标：{report['geocoding_success_count']} 个，其中南宁 {report['nanning_geocoding_success_count']} 个、柳州 {report['liuzhou_geocoding_success_count']} 个。",
        f"- high confidence：{report['geocoding_high_confidence_count']} 个；medium confidence：{report['geocoding_medium_confidence_count']} 个。",
        f"- manual review：{report['manual_review_count']} 个；failed：{report['failed_count']} 个。",
        f"- physical_site 成功：{report['physical_site_success_count']} 个；organization 成功：{report['organization_success_count']} 个。",
        f"- API 请求：{report['api_request_count']} 次；成功缓存命中：{report['cache_hit_count']} 次。",
        "",
        "## 服务与坐标系",
        "",
        f"- 地图服务：{'高德 Web 服务 API' if report['api_key_configured'] else '未调用（缺少合法 API 配置）'}。",
        f"- provider 分布：{json.dumps(report['provider_distribution'], ensure_ascii=False)}。",
        f"- 原始坐标系分布：{json.dumps(report['coordinate_system_distribution'], ensure_ascii=False)}。",
        "- 高德国内地图服务坐标按 GCJ-02 保存为 `longitude_raw` / `latitude_raw`；未冒充 EPSG:4490，也未执行坐标转换。",
        "- API 原始响应逐 candidate 缓存在 `data/interim/geocoding_cache/`，缓存不含 API Key。",
        "",
        "## 尚未可靠定位的重点节点",
        "",
    ]
    lines.extend([f"- {name}" for name in unresolved] or ["无。"])
    lines.extend([
        "",
        "## 质量验证",
        "",
        f"- 错误：{len(errors)}；警告：{len(warnings)}。",
    ])
    lines.extend(f"- ERROR：{item}" for item in errors)
    lines.extend(f"- WARN：{item}" for item in warnings)
    lines.extend([
        "",
        "## 后续阶段判断",
        "",
        "只有在重点 physical_site 获得可靠坐标、人工复核项处理完毕后，才适合统一转换到项目 CRS。",
        "在 CRS 尚未统一且重点粮库仍有未定位记录时，不适合直接关联 1 km 网格。",
        "",
        "## 官方接口依据",
        "",
        "- 高德地理编码：https://lbs.amap.com/api/webservice/guide/api/georegeo/",
        "- 高德 POI 搜索：https://lbs.amap.com/api/webservice/guide/api/search/",
        "- 高德坐标系说明：https://lbs.amap.com/api/uri-api/guide/mobile-web/point",
        "",
    ])
    (PROCESSED_DIR / "geocoding_report.md").write_text("\n".join(lines), encoding="utf-8")


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="对南宁、柳州候选节点执行可缓存、可审计的地址地理编码。")
    parser.add_argument("--postprocess-only", action="store_true", help="不调用 API，仅重做安全降级、验证与报告。")
    args = parser.parse_args()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = load_env_value("AMAP_WEB_KEY")
    if args.postprocess_only:
        targets = read_csv(PROCESSED_DIR / "geocoding_targets.csv")
        results = read_csv(PROCESSED_DIR / "geocoded_supply_nodes.csv")
        reviews = read_csv(PROCESSED_DIR / "geocoding_review.csv")
        requests = read_csv(PROCESSED_DIR / "geocoding_requests.csv")
        prior_report = json.loads((PROCESSED_DIR / "geocoding_report.json").read_text(encoding="utf-8"))
        counters = {
            "api_request_count": int(prior_report.get("api_request_count", 0)),
            "cache_hit_count": int(prior_report.get("cache_hit_count", 0)),
        }
    else:
        targets = build_targets()
        results, reviews, requests, counters = run_geocoding(targets, key)
    enforce_result_safety(targets, results, reviews)

    write_csv(PROCESSED_DIR / "geocoding_targets.csv", targets, TARGET_FIELDS)
    write_csv(PROCESSED_DIR / "geocoding_requests.csv", requests, REQUEST_FIELDS)
    write_csv(PROCESSED_DIR / "geocoded_supply_nodes.csv", results, GEOCODED_FIELDS)
    write_csv(PROCESSED_DIR / "geocoding_review.csv", reviews, REVIEW_FIELDS)

    preliminary = build_report(targets, results, reviews, counters, bool(key))
    dump_json(PROCESSED_DIR / "geocoding_report.json", preliminary)
    write_report_markdown(preliminary, [], [])
    errors, warnings = validate_outputs(targets, results, reviews, key)
    report = {**preliminary, "validation_errors": errors, "validation_warnings": warnings, "validation_status": "FAIL" if errors else ("WARN" if warnings else "PASS")}
    dump_json(PROCESSED_DIR / "geocoding_report.json", report)
    write_report_markdown(report, errors, warnings)

    # 最终再做一次密钥泄露检查，控制台只打印计数与状态。
    final_errors, _ = validate_outputs(targets, results, reviews, key)
    if any("API Key" in item for item in final_errors):
        raise RuntimeError("API secret leak detected in outputs")
    print(
        f"targets={report['target_count']} success={report['geocoding_success_count']} "
        f"review={report['manual_review_count']} failed={report['failed_count']} "
        f"validation={report['validation_status']}"
    )


if __name__ == "__main__":
    main()
