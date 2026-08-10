from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geocode_supply_nodes import (
    CACHE_DIR,
    COORDINATE_SYSTEM,
    amap_call,
    load_env_value,
    name_similarity,
    normalize_match_name,
    scalar,
    split_location,
)
from pipeline_common import (
    BOOL_FIELDS,
    CANDIDATE_FIELDS,
    PROCESSED_DIR,
    TASK_ROOT,
    normalize_address,
    normalize_name,
    read_csv,
    stable_id,
    truthy,
    unique_join,
    write_csv,
)


EVIDENCE_PATH = TASK_ROOT / "data" / "manual" / "nanning_grain_physical_sites_address_evidence.csv"
NORMALIZED_PATH = TASK_ROOT / "data" / "interim" / "address_evidence_normalized.csv"
MATCH_PATH = PROCESSED_DIR / "address_evidence_matches.csv"
SITE_PATH = PROCESSED_DIR / "nanning_grain_physical_sites.csv"
REVIEW_PATH = PROCESSED_DIR / "nanning_grain_geocoding_review.csv"
REPORT_JSON_PATH = PROCESSED_DIR / "nanning_grain_geocoding_report.json"
REPORT_MD_PATH = PROCESSED_DIR / "nanning_grain_geocoding_report.md"
MANUAL_SOURCE_FILE = "data/manual/nanning_grain_physical_sites_address_evidence.csv"

EXPECTED_EVIDENCE_COUNT = 13

EVIDENCE_FIELDS = [
    "evidence_id", "name", "normalized_name", "city", "county", "address",
    "normalized_address", "entity_type", "node_type", "physical_site_confirmed",
    "storage_confirmed", "address_precision", "evidence_level", "address_confidence",
    "geocode_ready", "geocode_query", "source_url", "source_note",
    "parent_organization", "parent_candidate_id", "site_relation", "match_type",
]

MATCH_FIELDS = [
    "evidence_id", "evidence_name", "matched_candidate_id", "matched_candidate_name",
    "match_type", "parent_candidate_id", "parent_organization", "site_relation",
    "address", "address_precision", "evidence_level", "address_confidence",
    "source_url", "source_note",
]

SITE_FIELDS = [
    "candidate_id", "name", "parent_candidate_id", "parent_organization", "site_relation",
    "city", "county", "address", "address_precision", "entity_type", "node_type",
    "physical_site_confirmed", "storage_confirmed", "evidence_level", "address_confidence",
    "longitude_raw", "latitude_raw", "coordinate_system_raw", "geocoding_status",
    "geocoding_confidence", "spatial_ready", "address_source", "address_evidence_id",
    "source_url", "source_note", "previous_location", "location_update_reason",
]

REVIEW_FIELDS = [
    "candidate_id", "name", "address", "address_precision", "evidence_level",
    "geocoding_query", "api_result", "failure_reason",
]

# These relationships are explicitly supported by the evidence names or the reserve-list hierarchy.
RELATION_RULES: dict[str, tuple[str, str]] = {
    "南宁市储备粮管理有限责任公司五象粮库": ("南宁市储备粮管理有限责任公司", "grain_storage_site"),
    "南宁市储备粮管理有限责任公司沙井粮库": ("南宁市储备粮管理有限责任公司", "grain_storage_site"),
    "横州市六景粮食储备中心库（良圻库区）": ("横州市六景粮食储备中心库", "grain_storage_site"),
    "马山县储备粮管理公司周鹿镇粮油网点19号仓库": ("马山县储备粮管理公司", "warehouse_site"),
    "隆安县粮食收储有限责任公司古潭仓储点": ("隆安县粮食收储有限责任公司", "warehouse_site"),
    "上林县安恒储备粮管理有限公司澄泰分公司1号仓库": ("上林县安恒储备粮管理有限公司澄泰分公司", "warehouse_site"),
    "上林县安恒储备粮管理有限公司三里分公司": ("上林县安恒储备粮管理有限公司", "branch_site"),
    "上林县安恒储备粮管理有限公司塘红分公司仓库": ("上林县安恒储备粮管理有限公司塘红分公司", "warehouse_site"),
    "上林县安恒储备粮管理有限公司乔贤分公司（原乔贤粮所）": ("上林县安恒储备粮管理有限公司", "branch_site"),
    "上林县安恒储备粮管理有限公司镇圩分公司（原镇圩粮所）": ("上林县安恒储备粮管理有限公司", "branch_site"),
}

EXISTING_NAME_ALIASES = {
    "上林县安恒储备粮管理有限公司乔贤分公司（原乔贤粮所）": "上林县安恒储备粮管理有限公司乔贤分公司",
    "上林县安恒储备粮管理有限公司镇圩分公司（原镇圩粮所）": "上林县安恒储备粮管理有限公司镇圩分公司",
}

NEW_SITE_NAMES = {
    "横州市六景粮食储备中心库（良圻库区）",
    "马山县储备粮管理公司周鹿镇粮油网点19号仓库",
    "隆安县粮食收储有限责任公司古潭仓储点",
    "上林县安恒储备粮管理有限公司澄泰分公司1号仓库",
    "上林县安恒储备粮管理有限公司塘红分公司仓库",
}

CORE_NAMES = [
    "南宁市储备粮管理有限责任公司五象粮库",
    "南宁市储备粮管理有限责任公司沙井粮库",
    "南宁市江丰粮食收储管理中心",
    "隆安县粮食收储有限责任公司古潭仓储点",
    "上林县安恒储备粮管理有限公司澄泰分公司1号仓库",
    "上林县安恒储备粮管理有限公司塘红分公司仓库",
    "广西壮族自治区南宁粮食储备库有限公司",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def cache_file(candidate_id: str, query: str, request_type: str) -> Path:
    digest = hashlib.sha256(normalize_address(query).encode("utf-8")).hexdigest()[:12]
    return CACHE_DIR / f"{candidate_id}_{request_type}_{digest}.json"


def load_or_request(
    candidate_id: str,
    request_type: str,
    query: str,
    city: str,
    key: str,
) -> tuple[dict[str, Any], bool, int]:
    path = cache_file(candidate_id, query, request_type)
    if path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("query") == query and cached.get("request_type") == request_type:
                return cached.get("response", {}), True, 0
        except (OSError, json.JSONDecodeError):
            pass

    response = amap_call(request_type, query, city, key)
    request_count = 1
    if scalar(response.get("status")) != "1":
        time.sleep(1.2)
        response = amap_call(request_type, query, city, key)
        request_count += 1
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "candidate_id": candidate_id,
        "provider": "amap",
        "coordinate_system_raw": COORDINATE_SYSTEM,
        "request_type": request_type,
        "query": query,
        "city": city,
        "requested_at": now_iso(),
        "response": response,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    time.sleep(0.55)
    return response, False, request_count


def normalize_evidence(rows: list[dict[str, str]], candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    by_name = {normalize_name(row.get("name")): row for row in candidates}
    normalized: list[dict[str, str]] = []
    for row in rows:
        name = row.get("name", "").strip()
        address = normalize_address(row.get("address", ""))
        parent_name, relation = RELATION_RULES.get(name, ("", "unknown"))
        existing_lookup = EXISTING_NAME_ALIASES.get(name, name)
        existing = by_name.get(normalize_name(existing_lookup))
        parent = by_name.get(normalize_name(parent_name)) if parent_name else None
        if name in NEW_SITE_NAMES:
            match_type = "parent_child_site" if parent else "new_physical_site"
        elif existing:
            match_type = "normalized_existing_candidate" if existing_lookup != name else "exact_existing_candidate"
        else:
            match_type = "manual_review"
        evidence_id = stable_id("addr_ev", normalize_name(name), row.get("city"), row.get("county"), address)
        normalized.append({
            **row,
            "evidence_id": evidence_id,
            "normalized_name": normalize_name(name),
            "normalized_address": address,
            "parent_organization": parent_name,
            "parent_candidate_id": parent.get("candidate_id", "") if parent else "",
            "site_relation": relation,
            "match_type": match_type,
        })
    return normalized


def default_candidate() -> dict[str, str]:
    row = {field: "" for field in CANDIDATE_FIELDS}
    for field in BOOL_FIELDS:
        row[field] = "false"
    return row


def add_manual_source(candidate: dict[str, str]) -> None:
    candidate["source_files"] = unique_join([candidate.get("source_files"), MANUAL_SOURCE_FILE])
    candidate["source_categories"] = unique_join([candidate.get("source_categories"), "manual_address_evidence"])


def build_or_update_candidates(
    candidates: list[dict[str, str]], evidence_rows: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, dict[str, str]]]:
    by_name = {normalize_name(row.get("name")): row for row in candidates}
    by_id = {row.get("candidate_id", ""): row for row in candidates}
    matches: list[dict[str, str]] = []
    evidence_to_candidate: dict[str, dict[str, str]] = {}

    for evidence in evidence_rows:
        name = evidence["name"]
        lookup_name = EXISTING_NAME_ALIASES.get(name, name)
        candidate = by_name.get(normalize_name(lookup_name))
        is_new_site = name in NEW_SITE_NAMES
        if is_new_site:
            stable_candidate_id = stable_id(
                "cand", normalize_name(name), evidence["city"], evidence["county"], evidence["normalized_address"]
            )
            candidate = by_id.get(stable_candidate_id) or by_name.get(normalize_name(name))
            if not candidate:
                candidate = default_candidate()
                candidate.update({
                    "candidate_id": stable_candidate_id,
                    "name": name,
                    "normalized_name": normalize_name(name),
                    "raw_names": name,
                    "province": "广西壮族自治区",
                    "city": evidence["city"],
                    "county": evidence["county"],
                    "analysis_priority": "primary",
                    "entity_type": "physical_site",
                    "node_type": evidence["node_type"],
                    "grain": "true",
                    "storage_capability": "true",
                    "government_reserve_related": "true",
                    "verified": "true",
                    "source_count": "0",
                    "evidence_level": evidence["evidence_level"],
                    "notes": "由人工核验的公开地址证据新增为独立 physical_site；未替代或删除组织主体。",
                })
                parent = by_id.get(evidence.get("parent_candidate_id", ""))
                if parent:
                    candidate["source_record_ids"] = parent.get("source_record_ids", "")
                    candidate["source_count"] = parent.get("source_count", "0")
                    candidate["source_files"] = parent.get("source_files", "")
                    candidate["source_categories"] = parent.get("source_categories", "")
                candidates.append(candidate)
                by_id[stable_candidate_id] = candidate
                by_name[normalize_name(name)] = candidate
        if not candidate:
            raise RuntimeError(f"无法安全匹配人工证据，需人工处理：{name}")

        previous_location = ""
        if (
            candidate.get("longitude_raw") and candidate.get("latitude_raw")
            and candidate.get("location_update_reason") != "manual_address_evidence"
        ):
            previous_location = f"{candidate['longitude_raw']},{candidate['latitude_raw']}"
        elif candidate.get("location_update_reason") == "manual_address_evidence":
            previous_location = candidate.get("previous_location", "")
        candidate.update({
            "province": "广西壮族自治区",
            "city": evidence["city"],
            "county": evidence["county"],
            "address": evidence["address"],
            "entity_type": "physical_site",
            "node_type": evidence["node_type"],
            "parent_entity_name": evidence.get("parent_organization", ""),
            "parent_candidate_id": evidence.get("parent_candidate_id", ""),
            "site_relation": evidence.get("site_relation", "unknown"),
            "storage_capability": "true",
            "government_reserve_related": "true",
            "verified": "true",
            "address_source": "manual_verified_public_evidence",
            "address_evidence_id": evidence["evidence_id"],
            "address_evidence_level": evidence["evidence_level"],
            "address_precision": evidence["address_precision"],
            "address_confidence": evidence["address_confidence"],
            "address_evidence_source_url": evidence["source_url"],
            "address_evidence_source_note": evidence["source_note"],
            "physical_site_confirmed": "true",
            "storage_confirmed": "true",
            "previous_location": previous_location,
            "location_update_reason": "manual_address_evidence",
        })
        if evidence["evidence_level"] == "A" or not candidate.get("evidence_level"):
            candidate["evidence_level"] = evidence["evidence_level"]
        if name != candidate["name"]:
            candidate["raw_names"] = unique_join([candidate.get("raw_names"), name])
        add_manual_source(candidate)
        evidence_to_candidate[evidence["evidence_id"]] = candidate
        matches.append({
            "evidence_id": evidence["evidence_id"],
            "evidence_name": name,
            "matched_candidate_id": candidate["candidate_id"],
            "matched_candidate_name": candidate["name"],
            "match_type": evidence["match_type"],
            "parent_candidate_id": evidence.get("parent_candidate_id", ""),
            "parent_organization": evidence.get("parent_organization", ""),
            "site_relation": evidence.get("site_relation", "unknown"),
            "address": evidence["address"],
            "address_precision": evidence["address_precision"],
            "evidence_level": evidence["evidence_level"],
            "address_confidence": evidence["address_confidence"],
            "source_url": evidence["source_url"],
            "source_note": evidence["source_note"],
        })
    return candidates, matches, evidence_to_candidate


def region_ok(evidence: dict[str, str], item: dict[str, Any]) -> bool:
    combined = "".join([
        scalar(item.get("province")), scalar(item.get("city")), scalar(item.get("district")),
        scalar(item.get("adname")), scalar(item.get("formatted_address")), scalar(item.get("address")),
    ])
    return evidence["city"] in combined and (not evidence["county"] or evidence["county"] in combined)


def house_number(address: str) -> str:
    match = re.search(r"([0-9]+(?:-[0-9]+)?号)", address)
    return match.group(1) if match else ""


def evaluate_geocode(evidence: dict[str, str], response: dict[str, Any]) -> tuple[dict[str, str] | None, str, str]:
    items = response.get("geocodes", []) if isinstance(response.get("geocodes"), list) else []
    valid: list[dict[str, str]] = []
    for item in items:
        lon, lat = split_location(scalar(item.get("location")))
        if lon and lat and region_ok(evidence, item):
            valid.append({
                "longitude": lon,
                "latitude": lat,
                "formatted_address": scalar(item.get("formatted_address")),
                "level": scalar(item.get("level")),
            })
    if not valid:
        if scalar(response.get("status")) != "1":
            return None, "api_error", ""
        return None, "no_result", ""
    if evidence["address_precision"] == "door_number":
        number = house_number(evidence["address"])
        exact_number = [item for item in valid if number and number in item["formatted_address"]]
        if exact_number:
            valid = exact_number
        # Amap may return a nearby different door number alongside one exact hit.
        # Only the uniquely matching exact address remains eligible.
        exact_address = [
            item for item in valid
            if normalize_address(evidence["address"]) in normalize_address(item["formatted_address"])
        ]
        if exact_address:
            valid = exact_address
    if len(valid) != 1:
        return None, "ambiguous_result", ""
    selected = valid[0]
    level = selected["level"]
    formatted = selected["formatted_address"]
    coarse = {"省", "市", "区县", "乡镇", "村庄", "道路"}
    precision = evidence["address_precision"]
    if level in {"省", "市", "区县"}:
        return None, "region_only", ""
    if level in {"乡镇", "村庄"}:
        return None, "town_centroid_only", ""
    if level == "道路":
        number = house_number(evidence["address"])
        if not number or number not in formatted:
            return None, "region_only", ""
    if precision == "door_number":
        number = house_number(evidence["address"])
        if level not in coarse or (number and number in formatted):
            return selected, "", "high"
        return None, "manual_review", ""
    if precision in {"street", "street_landmark"}:
        if level not in coarse:
            return selected, "", "medium"
        return None, "region_only", ""
    if precision in {"site_area", "site_town"}:
        if level in {"兴趣点", "门牌号"}:
            return selected, "", "medium"
        return None, "town_centroid_only", ""
    return None, "manual_review", ""


def evaluate_poi(evidence: dict[str, str], response: dict[str, Any]) -> tuple[dict[str, str] | None, str, str]:
    pois = response.get("pois", []) if isinstance(response.get("pois"), list) else []
    valid: list[dict[str, str]] = []
    precision = evidence["address_precision"]
    number = house_number(evidence["address"])
    parent_name = RELATION_RULES.get(evidence["name"], ("", ""))[0]
    landmark_tokens = [
        token for token in ("良圻", "周鹿粮所", "19号仓库", "三里街", "木山路口", "镇圩街")
        if token in evidence["geocode_query"]
    ]
    for item in pois:
        lon, lat = split_location(scalar(item.get("location")))
        name = scalar(item.get("name"))
        address = scalar(item.get("address"))
        combined = f"{name}{address}"
        if not lon or not lat or not region_ok(evidence, item):
            continue
        if parent_name and normalize_match_name(name) == normalize_match_name(parent_name):
            continue
        similarity = name_similarity(evidence["name"], name)
        if precision == "door_number":
            address_match = bool(number and number in combined)
            entity_match = similarity >= 0.62
            acceptable = address_match and entity_match
        else:
            landmark_match = any(token in combined for token in landmark_tokens)
            acceptable = landmark_match and similarity >= 0.45
        if acceptable:
            valid.append({
                "longitude": lon, "latitude": lat, "formatted_address": address,
                "level": "兴趣点", "match_name": name, "similarity": f"{similarity:.4f}",
            })
    if len(valid) == 1:
        confidence = "high" if precision == "door_number" and float(valid[0]["similarity"]) >= 0.90 else "medium"
        return valid[0], "", confidence
    if len(valid) > 1:
        return None, "ambiguous_result", ""
    return None, "no_result", ""


def compact_api_result(attempts: list[dict[str, Any]]) -> str:
    compact: list[dict[str, Any]] = []
    for attempt in attempts:
        response = attempt["response"]
        compact.append({
            "request_type": attempt["request_type"],
            "query": attempt["query"],
            "status": response.get("status", ""),
            "info": response.get("info", ""),
            "count": len(response.get("geocodes", response.get("pois", []))) if isinstance(response.get("geocodes", response.get("pois", [])), list) else 0,
        })
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def geocode_evidence(
    evidence_rows: list[dict[str, str]], evidence_to_candidate: dict[str, dict[str, str]], key: str
) -> tuple[list[dict[str, str]], list[dict[str, str]], int, int]:
    site_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []
    request_count = 0
    cache_hits = 0
    for evidence in evidence_rows:
        candidate = evidence_to_candidate[evidence["evidence_id"]]
        attempts: list[dict[str, Any]] = []
        selected: dict[str, str] | None = None
        failure_reason = "no_result"
        confidence = ""
        used_query = evidence["address"]
        geocode_failures: list[str] = []

        queries = [evidence["address"]]
        if evidence.get("geocode_query") and normalize_address(evidence["geocode_query"]) != normalize_address(evidence["address"]):
            queries.append(evidence["geocode_query"])
        for query in queries:
            response, hit, requests = load_or_request(candidate["candidate_id"], "geocode", query, evidence["city"], key)
            cache_hits += int(hit)
            request_count += requests
            attempts.append({"request_type": "geocode", "query": query, "response": response})
            selected, failure_reason, confidence = evaluate_geocode(evidence, response)
            if not selected:
                geocode_failures.append(failure_reason)
            used_query = query
            if selected:
                break

        if not selected and geocode_failures:
            failure_priority = {
                "ambiguous_result": 5,
                "town_centroid_only": 4,
                "region_only": 3,
                "manual_review": 2,
                "no_result": 1,
                "api_error": 0,
            }
            failure_reason = max(geocode_failures, key=lambda item: failure_priority.get(item, 0))

        # Geocoding remains primary. One strict POI fallback is allowed only after both
        # address queries fail; it must agree on region and either exact door number +
        # entity family, or a distinctive manually supplied landmark.
        if not selected:
            primary_failure_reason = failure_reason
            query = evidence["geocode_query"]
            response, hit, requests = load_or_request(candidate["candidate_id"], "poi", query, evidence["city"], key)
            cache_hits += int(hit)
            request_count += requests
            attempts.append({"request_type": "poi", "query": query, "response": response})
            selected, poi_failure_reason, confidence = evaluate_poi(evidence, response)
            failure_reason = poi_failure_reason if poi_failure_reason == "ambiguous_result" else primary_failure_reason
            used_query = query

        if selected:
            candidate.update({
                "longitude_raw": selected["longitude"],
                "latitude_raw": selected["latitude"],
                "coordinate_system_raw": COORDINATE_SYSTEM,
                "geocoding_status": "success",
                "geocoding_confidence": confidence,
                "spatial_ready": "true",
            })
        else:
            candidate.update({
                "longitude_raw": "",
                "latitude_raw": "",
                "coordinate_system_raw": "",
                "geocoding_status": "approximate_region_only" if failure_reason in {"region_only", "town_centroid_only"} else "manual_review",
                "geocoding_confidence": "manual_review",
                "spatial_ready": "false",
            })
            review_rows.append({
                "candidate_id": candidate["candidate_id"],
                "name": candidate["name"],
                "address": evidence["address"],
                "address_precision": evidence["address_precision"],
                "evidence_level": evidence["evidence_level"],
                "geocoding_query": used_query,
                "api_result": compact_api_result(attempts),
                "failure_reason": failure_reason,
            })

        site_rows.append({
            "candidate_id": candidate["candidate_id"],
            "name": candidate["name"],
            "parent_candidate_id": candidate.get("parent_candidate_id", ""),
            "parent_organization": candidate.get("parent_entity_name", ""),
            "site_relation": candidate.get("site_relation", "unknown"),
            "city": candidate["city"],
            "county": candidate["county"],
            "address": candidate["address"],
            "address_precision": evidence["address_precision"],
            "entity_type": candidate["entity_type"],
            "node_type": candidate["node_type"],
            "physical_site_confirmed": candidate["physical_site_confirmed"],
            "storage_confirmed": candidate["storage_confirmed"],
            "evidence_level": evidence["evidence_level"],
            "address_confidence": evidence["address_confidence"],
            "longitude_raw": candidate["longitude_raw"],
            "latitude_raw": candidate["latitude_raw"],
            "coordinate_system_raw": candidate["coordinate_system_raw"],
            "geocoding_status": candidate["geocoding_status"],
            "geocoding_confidence": candidate["geocoding_confidence"],
            "spatial_ready": candidate["spatial_ready"],
            "address_source": candidate["address_source"],
            "address_evidence_id": evidence["evidence_id"],
            "source_url": evidence["source_url"],
            "source_note": evidence["source_note"],
            "previous_location": candidate.get("previous_location", ""),
            "location_update_reason": "manual_address_evidence",
        })
    return site_rows, review_rows, request_count, cache_hits


def validate_and_report(
    evidence_rows: list[dict[str, str]], matches: list[dict[str, str]], site_rows: list[dict[str, str]],
    review_rows: list[dict[str, str]], request_count: int, cache_hits: int, key: str,
) -> dict[str, Any]:
    evidence_count = len(evidence_rows)
    existing_count = sum(row["match_type"] in {"exact_existing_candidate", "normalized_existing_candidate"} for row in matches)
    new_count = sum(row["match_type"] in {"parent_child_site", "new_physical_site"} for row in matches)
    success = [row for row in site_rows if row["geocoding_status"] == "success"]
    door_rows = [row for row in site_rows if row["address_precision"] == "door_number"]
    door_success = [row for row in door_rows if row["geocoding_status"] == "success"]
    street_count = sum(row["address_precision"] in {"street", "street_landmark"} for row in site_rows)
    region_count = sum(row["address_precision"] in {"site_area", "site_town"} for row in site_rows)
    spatial_ready_count = sum(truthy(row["spatial_ready"]) for row in site_rows)
    organization_mismatch = any(row["entity_type"] != "physical_site" for row in site_rows)
    ready_for_crs = spatial_ready_count >= 10 and len(door_success) >= max(1, len(door_rows) - 1) and not organization_mismatch

    output_paths = [NORMALIZED_PATH, MATCH_PATH, SITE_PATH, REVIEW_PATH, REPORT_JSON_PATH, REPORT_MD_PATH]
    cache_paths = list(CACHE_DIR.glob("cand_*_geocode_*.json")) + list(CACHE_DIR.glob("cand_*_poi_*.json"))
    secret_leak = False
    if key:
        for path in output_paths + cache_paths:
            if path.is_file() and key in path.read_text(encoding="utf-8-sig", errors="ignore"):
                secret_leak = True
                break
    coordinates_valid = all(
        70 <= float(row["longitude_raw"]) <= 140 and 0 <= float(row["latitude_raw"]) <= 60
        for row in success
    )
    traceable = all(row.get("address_evidence_id") and row.get("source_url") for row in site_rows)
    validation = "PASS"
    errors: list[str] = []
    if evidence_count != EXPECTED_EVIDENCE_COUNT:
        validation = "FAIL"
        errors.append(f"人工证据应为{EXPECTED_EVIDENCE_COUNT}条，实际为{evidence_count}条。")
    if secret_leak:
        validation = "FAIL"
        errors.append("输出或缓存中检测到 API Key。")
    if not coordinates_valid:
        validation = "FAIL"
        errors.append("存在经纬度范围异常。")
    if not traceable:
        validation = "FAIL"
        errors.append("存在无法追溯至人工证据与来源 URL 的节点。")
    if organization_mismatch:
        validation = "FAIL"
        errors.append("人工设施证据被写成非 physical_site。")
    if validation != "FAIL" and not ready_for_crs:
        validation = "WARN"
        errors.append("尚未满足 READY_FOR_CRS 阈值。")

    core_status = []
    by_name = {row["name"]: row for row in site_rows}
    for name in CORE_NAMES:
        row = by_name.get(name, {})
        core_status.append({
            "name": name,
            "geocoding_status": row.get("geocoding_status", "missing"),
            "geocoding_confidence": row.get("geocoding_confidence", ""),
            "spatial_ready": row.get("spatial_ready", "false"),
        })

    report = {
        "generated_at": now_iso(),
        "expected_evidence_records": EXPECTED_EVIDENCE_COUNT,
        "actual_evidence_records": evidence_count,
        "evidence_record_count": evidence_count,
        "existing_candidate_match_count": existing_count,
        "new_physical_site_count": new_count,
        "door_number_evidence_count": len(door_rows),
        "door_number_geocoding_success_count": len(door_success),
        "door_number_geocoding_failed_count": len(door_rows) - len(door_success),
        "street_level_evidence_count": street_count,
        "region_level_evidence_count": region_count,
        "geocoding_success_count": len(success),
        "high_confidence_count": sum(row["geocoding_confidence"] == "high" for row in success),
        "medium_confidence_count": sum(row["geocoding_confidence"] == "medium" for row in success),
        "manual_review_count": len(review_rows),
        "failed_count": len(review_rows),
        "spatial_ready_count": spatial_ready_count,
        "physical_site_count": sum(row["entity_type"] == "physical_site" for row in site_rows),
        "physical_site_located_count": len(success),
        "api_request_count": request_count,
        "cache_hit_count": cache_hits,
        "coordinate_system_distribution": dict(Counter(row["coordinate_system_raw"] for row in success)),
        "organization_physical_site_mismatch_count": int(organization_mismatch),
        "traceability_complete": traceable,
        "api_key_leak_detected": secret_leak,
        "core_node_status": core_status,
        "unlocated_nodes": [row["name"] for row in site_rows if row["geocoding_status"] != "success"],
        "READY_FOR_CRS": ready_for_crs,
        "validation_status": validation,
        "validation_notes": errors,
    }
    return report


def write_report_md(report: dict[str, Any]) -> None:
    core_lines = [
        f"- {row['name']}：{row['geocoding_status']} / {row['geocoding_confidence'] or '—'} / spatial_ready={row['spatial_ready']}"
        for row in report["core_node_status"]
    ]
    unlocated = report["unlocated_nodes"]
    lines = [
        "# 南宁粮食 physical_site 人工地址接入与地理编码报告",
        "",
        f"生成时间：{report['generated_at']}",
        "",
        "## 结论",
        "",
        f"13条人工地址证据已接入 {report['actual_evidence_records']}/{report['expected_evidence_records']} 条；匹配现有 candidate {report['existing_candidate_match_count']} 条，新增独立 physical_site {report['new_physical_site_count']} 条。",
        f"成功地理编码 {report['geocoding_success_count']} 条，其中 high {report['high_confidence_count']} 条、medium {report['medium_confidence_count']} 条；spatial_ready {report['spatial_ready_count']} 条。",
        f"READY_FOR_CRS = {str(report['READY_FOR_CRS']).lower()}；验证状态 = {report['validation_status']}。",
        "",
        "## 地址精度与定位",
        "",
        f"- 门牌号证据：{report['door_number_evidence_count']} 条，成功 {report['door_number_geocoding_success_count']} 条，失败 {report['door_number_geocoding_failed_count']} 条。",
        f"- 街道/地标级证据：{report['street_level_evidence_count']} 条。",
        f"- 库区/乡镇级证据：{report['region_level_evidence_count']} 条。",
        f"- 人工复核/失败：{report['manual_review_count']} 条。",
        "- 地图服务：高德 Web 服务；原始坐标系：GCJ-02。未执行项目 CRS 转换。",
        "",
        "## 核心节点逐条状态",
        "",
        *core_lines,
        "",
        "## 仍未可靠定位",
        "",
        *( [f"- {name}" for name in unlocated] if unlocated else ["- 无"] ),
        "",
        "## 安全与追溯验证",
        "",
        f"- candidate → address_evidence_id → source_url 追溯完整：{str(report['traceability_complete']).lower()}。",
        f"- organization / physical_site 错配数量：{report['organization_physical_site_mismatch_count']}。",
        f"- API Key 泄漏检测：{str(report['api_key_leak_detected']).lower()}。",
        "- 人工公开地址证据优先于历史 POI 推测；旧位置若存在，保存在 previous_location，更新原因为 manual_address_evidence。",
        "",
        "## CRS 阶段判断",
        "",
        "READY_FOR_CRS 仅表示这13个南宁粮食设施的原始 GCJ-02 位置具备进入独立坐标转换阶段的条件，不表示已完成 EPSG:4490、1 km 网格或洪涝分析。",
    ]
    if report["validation_notes"]:
        lines += ["", "## 验证提示", "", *[f"- {note}" for note in report["validation_notes"]]]
    REPORT_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if not EVIDENCE_PATH.is_file():
        raise FileNotFoundError(EVIDENCE_PATH)
    evidence_sha_before = hashlib.sha256(EVIDENCE_PATH.read_bytes()).hexdigest()
    raw_evidence = read_csv(EVIDENCE_PATH)
    if len(raw_evidence) != EXPECTED_EVIDENCE_COUNT:
        raise RuntimeError(f"人工证据记录数异常：应为{EXPECTED_EVIDENCE_COUNT}，实际为{len(raw_evidence)}")
    candidates = read_csv(PROCESSED_DIR / "supply_node_candidates.csv")
    normalized = normalize_evidence(raw_evidence, candidates)
    write_csv(NORMALIZED_PATH, normalized, EVIDENCE_FIELDS)

    candidates, matches, evidence_to_candidate = build_or_update_candidates(candidates, normalized)
    write_csv(MATCH_PATH, matches, MATCH_FIELDS)

    key = load_env_value("AMAP_WEB_KEY")
    if not key:
        raise RuntimeError("未配置 AMAP_WEB_KEY；已生成证据标准化及匹配结果，未进行网络地理编码。")
    site_rows, review_rows, request_count, cache_hits = geocode_evidence(normalized, evidence_to_candidate, key)
    candidates.sort(key=lambda row: row.get("candidate_id", ""))
    write_csv(PROCESSED_DIR / "supply_node_candidates.csv", candidates, CANDIDATE_FIELDS)
    write_csv(SITE_PATH, site_rows, SITE_FIELDS)
    write_csv(REVIEW_PATH, review_rows, REVIEW_FIELDS)

    report = validate_and_report(normalized, matches, site_rows, review_rows, request_count, cache_hits, key)
    REPORT_JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report_md(report)
    if hashlib.sha256(EVIDENCE_PATH.read_bytes()).hexdigest() != evidence_sha_before:
        raise RuntimeError("原始人工证据文件发生变化，已停止。")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["validation_status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
