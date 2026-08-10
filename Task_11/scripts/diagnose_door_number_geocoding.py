from __future__ import annotations

import copy
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
    AMAP_POI_URL,
    load_env_value,
    name_similarity,
    request_json,
    scalar,
    split_location,
)
from pipeline_common import CANDIDATE_FIELDS as PIPELINE_CANDIDATE_FIELDS, PROCESSED_DIR, TASK_ROOT, read_csv, truthy, write_csv


AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_REGEOCODE_URL = "https://restapi.amap.com/v3/geocode/regeo"
SITE_PATH = PROCESSED_DIR / "nanning_grain_physical_sites.csv"
REVIEW_PATH = PROCESSED_DIR / "nanning_grain_geocoding_review.csv"
REPORT_JSON_PATH = PROCESSED_DIR / "nanning_grain_geocoding_report.json"
REPORT_MD_PATH = PROCESSED_DIR / "nanning_grain_geocoding_report.md"
CANDIDATE_OUTPUT_PATH = PROCESSED_DIR / "door_number_geocode_candidates.csv"
DIAGNOSTIC_PATH = PROCESSED_DIR / "door_number_geocode_diagnostic.csv"
EVIDENCE_PATH = TASK_ROOT / "data" / "manual" / "nanning_grain_physical_sites_address_evidence.csv"
COUNTY_BOUNDARY_PATH = TASK_ROOT.parent / "Task_06" / "data" / "boundary" / "raw" / "南宁市_县.geojson"

TARGET_NAMES = [
    "南宁市储备粮管理有限责任公司沙井粮库",
    "南宁市邕宁区粮食储备库",
    "南宁市江丰粮食收储管理中心",
    "隆安县粮食收储有限责任公司古潭仓储点",
]

SHORT_NAMES = {
    "南宁市储备粮管理有限责任公司沙井粮库": "沙井粮库",
    "南宁市邕宁区粮食储备库": "邕宁区粮食储备库",
    "南宁市江丰粮食收储管理中心": "江丰粮食收储管理中心",
    "隆安县粮食收储有限责任公司古潭仓储点": "古潭仓储点",
}

CANDIDATE_FIELDS = [
    "candidate_id", "name", "query", "request_type", "candidate_index",
    "formatted_address", "returned_name", "province", "city", "district",
    "township", "street", "number", "adcode", "location", "level",
]

DIAGNOSTIC_FIELDS = CANDIDATE_FIELDS + [
    "expected_address", "expected_city", "expected_county", "expected_town",
    "expected_street", "expected_number", "city_match", "district_match",
    "town_match", "street_match", "number_match", "match_score", "decision",
    "decision_reason", "reverse_formatted_address", "reverse_city",
    "reverse_district", "reverse_township", "reverse_street", "reverse_number",
    "reverse_city_match", "reverse_district_match", "reverse_street_match",
    "reverse_number_match", "reverse_validation",
]

REVIEW_FIELDS = [
    "candidate_id", "name", "address", "address_precision", "evidence_level",
    "geocoding_query", "api_result", "failure_reason",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_component(value: Any) -> str:
    text = scalar(value)
    return re.sub(r"[\s（）()·,，.。]", "", text)


def parse_expected(evidence: dict[str, str]) -> dict[str, str]:
    address = evidence["address"]
    remainder = address
    for prefix in (evidence.get("province", ""), evidence["city"], evidence["county"]):
        if prefix:
            remainder = remainder.replace(prefix, "", 1)
    town_match = re.match(r"^(.+?(?:镇|乡))", remainder)
    town = town_match.group(1) if town_match else ""
    if town:
        remainder = remainder[len(town):]
    street_match = re.match(r"^(.+?(?:大道|路|街|道))", remainder)
    street = street_match.group(1) if street_match else ""
    number_match = re.search(r"(\d+(?:-\d+)?号)", address)
    return {
        "expected_address": address,
        "expected_city": evidence["city"],
        "expected_county": evidence["county"],
        "expected_town": town,
        "expected_street": street,
        "expected_number": number_match.group(1) if number_match else "",
    }


def load_county_adcodes() -> dict[str, str]:
    if not COUNTY_BOUNDARY_PATH.is_file():
        raise FileNotFoundError(f"缺少项目区划数据：{COUNTY_BOUNDARY_PATH}")
    geojson = json.loads(COUNTY_BOUNDARY_PATH.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        name, gb = scalar(props.get("name")), scalar(props.get("gb"))
        if name and gb.startswith("156") and len(gb) == 9:
            mapping[name] = gb[3:]
    return mapping


def cache_path(candidate_id: str, request_type: str, query: str, region: str) -> Path:
    material = f"{request_type}|{query}|{region}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
    return CACHE_DIR / f"{candidate_id}_doorreview_{request_type}_{digest}.json"


def find_legacy_cache(candidate_id: str, request_type: str, query: str, region: str) -> dict[str, Any] | None:
    for path in CACHE_DIR.glob(f"{candidate_id}_{request_type}_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("request_type") == request_type and payload.get("query") == query and scalar(payload.get("city")) == region:
            return payload
    return None


def request_cached(
    candidate_id: str, request_type: str, query: str, region: str, key: str
) -> tuple[dict[str, Any], bool, int]:
    path = cache_path(candidate_id, request_type, query, region)
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("query") == query and payload.get("region") == region:
                return payload.get("response", {}), True, 0
        except (OSError, json.JSONDecodeError):
            pass
    legacy = find_legacy_cache(candidate_id, request_type, query, region)
    if legacy:
        return legacy.get("response", {}), True, 0

    if request_type == "geocode":
        response = request_json(AMAP_GEOCODE_URL, {"address": query, "city": region, "output": "JSON"}, key)
    elif request_type == "poi":
        response = request_json(
            AMAP_POI_URL,
            {"keywords": query, "city": region, "citylimit": "true", "offset": "20", "page": "1", "extensions": "all", "output": "JSON"},
            key,
        )
    elif request_type == "regeocode":
        response = request_json(
            AMAP_REGEOCODE_URL,
            {"location": query, "radius": "100", "extensions": "all", "roadlevel": "0", "output": "JSON"},
            key,
        )
    else:
        raise ValueError(request_type)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "candidate_id": candidate_id,
        "provider": "amap",
        "coordinate_system_raw": COORDINATE_SYSTEM,
        "request_type": request_type,
        "query": query,
        "region": region,
        "requested_at": now_iso(),
        "response": response,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    time.sleep(0.55)
    return response, False, 1


def base_candidate_row(
    candidate_id: str, name: str, query: str, request_type: str, index: int,
    item: dict[str, Any], expected: dict[str, str],
) -> dict[str, Any]:
    if request_type == "geocode":
        formatted = scalar(item.get("formatted_address"))
        province = scalar(item.get("province"))
        city = scalar(item.get("city"))
        district = scalar(item.get("district"))
        township = scalar(item.get("township"))
        street = scalar(item.get("street"))
        number = scalar(item.get("number"))
        adcode = scalar(item.get("adcode"))
        location = scalar(item.get("location"))
        level = scalar(item.get("level"))
        returned_name = scalar(item.get("building", {}).get("name")) if isinstance(item.get("building"), dict) else ""
    else:
        province = scalar(item.get("pname"))
        city = scalar(item.get("cityname"))
        district = scalar(item.get("adname"))
        township = ""
        address = scalar(item.get("address"))
        formatted = f"{province}{city}{district}{address}"
        street = expected["expected_street"] if expected["expected_street"] in address else ""
        number = expected["expected_number"] if expected["expected_number"] in address else ""
        adcode = scalar(item.get("adcode"))
        location = scalar(item.get("location"))
        level = "POI"
        returned_name = scalar(item.get("name"))
    return {
        "candidate_id": candidate_id,
        "name": name,
        "query": query,
        "request_type": request_type,
        "candidate_index": index,
        "formatted_address": formatted,
        "returned_name": returned_name,
        "province": province,
        "city": city,
        "district": district,
        "township": township,
        "street": street,
        "number": number,
        "adcode": adcode,
        "location": location,
        "level": level,
    }


def score_row(row: dict[str, Any], expected: dict[str, str]) -> dict[str, Any]:
    formatted = normalize_component(row["formatted_address"])
    city_match = normalize_component(row["city"]) == normalize_component(expected["expected_city"])
    district_match = normalize_component(row["district"]) == normalize_component(expected["expected_county"])
    town_match = not expected["expected_town"] or (
        normalize_component(row["township"]) == normalize_component(expected["expected_town"])
        or normalize_component(expected["expected_town"]) in formatted
    )
    street_match = bool(expected["expected_street"]) and (
        normalize_component(row["street"]) == normalize_component(expected["expected_street"])
        or normalize_component(expected["expected_street"]) in formatted
    )
    number_match = bool(expected["expected_number"]) and normalize_component(row["number"]) == normalize_component(expected["expected_number"])
    fine_level = row["level"] in {"门址", "门牌号", "建筑物", "兴趣点", "POI"}
    score = 0
    score += 20 if city_match else 0
    score += 30 if district_match else 0
    score += 10 if expected["expected_town"] and town_match else 0
    score += 30 if street_match else 0
    score += 40 if number_match else 0
    score += 20 if fine_level else 0
    reject_reason = ""
    if not city_match:
        reject_reason = "city_mismatch"
    elif not district_match:
        reject_reason = "district_mismatch"
    elif row["level"] in {"省", "市", "区县", "乡镇", "村庄", "道路"}:
        reject_reason = "coarse_level"
    elif not street_match or not number_match:
        reject_reason = "incomplete_street_number_match"
    elif row["request_type"] == "poi" and name_similarity(row["name"], row["returned_name"]) < 0.55:
        reject_reason = "poi_name_mismatch"
    result = {
        **row,
        **expected,
        "city_match": city_match,
        "district_match": district_match,
        "town_match": town_match,
        "street_match": street_match,
        "number_match": number_match,
        "match_score": score,
        "decision": "eligible_strong" if not reject_reason else "reject",
        "decision_reason": "district+street+number完整匹配且为精细级别" if not reject_reason else reject_reason,
    }
    return result


def geocode_rows(
    candidate_id: str, name: str, query: str, response: dict[str, Any], expected: dict[str, str]
) -> list[dict[str, Any]]:
    items = response.get("geocodes", []) if isinstance(response.get("geocodes"), list) else []
    return [score_row(base_candidate_row(candidate_id, name, query, "geocode", i, item, expected), expected) for i, item in enumerate(items, 1)]


def poi_rows(
    candidate_id: str, name: str, query: str, response: dict[str, Any], expected: dict[str, str]
) -> list[dict[str, Any]]:
    items = response.get("pois", []) if isinstance(response.get("pois"), list) else []
    return [score_row(base_candidate_row(candidate_id, name, query, "poi", i, item, expected), expected) for i, item in enumerate(items, 1)]


def unique_eligible(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if row["decision"] != "eligible_strong":
            continue
        key = (row["location"], row["district"], row["street"], row["number"])
        unique.setdefault(key, row)
    return list(unique.values())


def parse_reverse(response: dict[str, Any]) -> dict[str, str]:
    regeocode = response.get("regeocode", {}) if isinstance(response.get("regeocode"), dict) else {}
    component = regeocode.get("addressComponent", {}) if isinstance(regeocode.get("addressComponent"), dict) else {}
    street_number = component.get("streetNumber", {}) if isinstance(component.get("streetNumber"), dict) else {}
    return {
        "reverse_formatted_address": scalar(regeocode.get("formatted_address")),
        "reverse_city": scalar(component.get("city")),
        "reverse_district": scalar(component.get("district")),
        "reverse_township": scalar(component.get("township")),
        "reverse_street": scalar(street_number.get("street")),
        "reverse_number": scalar(street_number.get("number")),
    }


def apply_reverse_validation(row: dict[str, Any], reverse: dict[str, str]) -> bool:
    expected = row
    formatted = normalize_component(reverse["reverse_formatted_address"])
    city_match = (
        normalize_component(reverse["reverse_city"]) == normalize_component(expected["expected_city"])
        or normalize_component(expected["expected_city"]) in formatted
    )
    district_match = normalize_component(reverse["reverse_district"]) == normalize_component(expected["expected_county"])
    street_match = (
        normalize_component(reverse["reverse_street"]) == normalize_component(expected["expected_street"])
        or normalize_component(expected["expected_street"]) in formatted
    )
    reverse_number = normalize_component(reverse["reverse_number"])
    number_match = (
        not reverse_number
        or reverse_number == normalize_component(expected["expected_number"])
        or normalize_component(expected["expected_number"]) in formatted
    )
    valid = city_match and district_match and street_match and number_match
    row.update({
        **reverse,
        "reverse_city_match": city_match,
        "reverse_district_match": district_match,
        "reverse_street_match": street_match,
        "reverse_number_match": number_match,
        "reverse_validation": "pass" if valid else "fail",
        "decision": "accepted" if valid else "reject",
        "decision_reason": "正向门牌强匹配且逆地理行政区/道路复核通过" if valid else "reverse_geocode_mismatch",
    })
    return valid


def concise_response(rows: list[dict[str, Any]]) -> str:
    compact = [
        {
            "query": row["query"], "request_type": row["request_type"], "candidate_index": row["candidate_index"],
            "formatted_address": row["formatted_address"], "returned_name": row["returned_name"],
            "district": row["district"], "township": row["township"], "street": row["street"],
            "number": row["number"], "location": row["location"], "level": row["level"],
            "match_score": row["match_score"], "decision": row["decision"], "decision_reason": row["decision_reason"],
        }
        for row in rows
    ]
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def update_report(
    site_rows: list[dict[str, str]], target_results: list[dict[str, Any]], api_requests: int, cache_hits: int,
    secret_leak: bool,
) -> dict[str, Any]:
    report = json.loads(REPORT_JSON_PATH.read_text(encoding="utf-8")) if REPORT_JSON_PATH.is_file() else {}
    success_rows = [row for row in site_rows if row["geocoding_status"] == "success"]
    review_rows = [row for row in site_rows if row["geocoding_status"] != "success"]
    before_ready = 5
    after_ready = sum(truthy(row["spatial_ready"]) for row in site_rows)
    rescued = sum(item["before_spatial_ready"] == "false" and item["after_spatial_ready"] == "true" for item in target_results)
    invalid_success = any(
        row["entity_type"] != "physical_site" or row["coordinate_system_raw"] != "GCJ02"
        for row in success_rows
    )
    ready = after_ready >= 7 and rescued >= 2 and not invalid_success and not secret_leak
    report.update({
        "generated_at": now_iso(),
        "before_spatial_ready": before_ready,
        "after_spatial_ready": after_ready,
        "spatial_ready_count": after_ready,
        "geocoding_success_count": len(success_rows),
        "physical_site_located_count": len(success_rows),
        "high_confidence_count": sum(row["geocoding_confidence"] == "high" for row in success_rows),
        "medium_confidence_count": sum(row["geocoding_confidence"] == "medium" for row in success_rows),
        "manual_review_count": len(review_rows),
        "failed_count": len(review_rows),
        "door_number_geocoding_success_count": sum(row["address_precision"] == "door_number" and row["geocoding_status"] == "success" for row in site_rows),
        "door_number_geocoding_failed_count": sum(row["address_precision"] == "door_number" and row["geocoding_status"] != "success" for row in site_rows),
        "coordinate_system_distribution": dict(Counter(row["coordinate_system_raw"] for row in success_rows)),
        "door_number_review_target_count": len(target_results),
        "door_number_rescued_count": rescued,
        "door_number_review_api_request_count": api_requests,
        "door_number_review_cache_hit_count": cache_hits,
        "door_number_review_results": target_results,
        "api_key_leak_detected": secret_leak,
        "unlocated_nodes": [row["name"] for row in review_rows],
        "READY_FOR_CRS": ready,
        "validation_status": "FAIL" if secret_leak else ("PASS" if ready else "WARN"),
        "validation_notes": [] if ready else (["输出或缓存中检测到 API Key。"] if secret_leak else ["本轮后仍未形成至少7个可用节点或门牌号救回少于2个。"]),
    })
    existing_core = {row.get("name"): row for row in report.get("core_node_status", [])}
    by_name = {row["name"]: row for row in site_rows}
    for name, item in existing_core.items():
        if name in by_name:
            item.update({
                "geocoding_status": by_name[name]["geocoding_status"],
                "geocoding_confidence": by_name[name]["geocoding_confidence"],
                "spatial_ready": by_name[name]["spatial_ready"],
            })
    report["core_node_status"] = list(existing_core.values())
    return report


def write_report_md(report: dict[str, Any]) -> None:
    target_lines = []
    for item in report["door_number_review_results"]:
        target_lines.append(
            f"- {item['name']}：{item['final_status']} / {item['final_confidence']} / "
            f"spatial_ready={item['after_spatial_ready']}。{item['reason']}"
        )
    unlocated = report.get("unlocated_nodes", [])
    lines = [
        "# 南宁粮食 physical_site 门牌号地理编码复核报告",
        "",
        f"生成时间：{report['generated_at']}",
        "",
        "## 本轮结论",
        "",
        f"本轮仅复核4个明确门牌号节点。spatial_ready 从 {report['before_spatial_ready']} 增至 {report['after_spatial_ready']}，救回 {report['door_number_rescued_count']} 个。",
        f"当前成功节点共 {report['geocoding_success_count']} 个：high {report['high_confidence_count']} 个，medium {report['medium_confidence_count']} 个。",
        f"READY_FOR_CRS = {str(report['READY_FOR_CRS']).lower()}；验证状态 = {report['validation_status']}。",
        "",
        "## 4个门牌号节点",
        "",
        *target_lines,
        "",
        "## 诊断规则",
        "",
        "- 先用纯结构化地址并传 city=南宁市；只有无法形成唯一强匹配时才使用“地址+简短设施名”。",
        "- 多候选不再直接判歧义；按 city、district、township、street、number、level 逐项评分。",
        "- 只有唯一满足目标区县、道路和门牌号的精细候选才进入逆地理验证。",
        "- POI 兜底使用项目县级边界数据提供的区县 adcode，并启用 citylimit=true。",
        "- 拟接受位置必须通过逆地理行政区和道路验证；乡镇中心点不会进入 spatial_ready。",
        "",
        "## 仍未可靠定位",
        "",
        *([f"- {name}" for name in unlocated] if unlocated else ["- 无"]),
        "",
        "## 坐标与后续边界",
        "",
        "所有成功坐标均保留为高德 GCJ-02 原始坐标。本轮未执行 EPSG:4490/项目 CRS 转换，也未关联1 km网格。",
    ]
    if report["READY_FOR_CRS"]:
        lines += ["", "南宁核心粮食 physical_site 已形成第一批可用于空间网格分析的高可信节点集；下一阶段仍需先单独完成坐标系统一。"]
    REPORT_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    key = load_env_value("AMAP_WEB_KEY")
    if not key:
        raise RuntimeError("未配置 AMAP_WEB_KEY，无法执行本轮正向/逆向地理编码复核。")
    evidence_rows = read_csv(EVIDENCE_PATH)
    evidence_by_name = {row["name"]: row for row in evidence_rows if row["name"] in TARGET_NAMES}
    site_rows = read_csv(SITE_PATH)
    site_by_name = {row["name"]: row for row in site_rows}
    if set(evidence_by_name) != set(TARGET_NAMES) or not set(TARGET_NAMES).issubset(site_by_name):
        raise RuntimeError("4个目标节点在证据表或核心设施表中不完整。")
    non_target_before = {row["candidate_id"]: copy.deepcopy(row) for row in site_rows if row["name"] not in TARGET_NAMES}
    county_adcodes = load_county_adcodes()
    api_requests = 0
    cache_hits = 0
    all_geocode_candidates: list[dict[str, Any]] = []
    all_diagnostics: list[dict[str, Any]] = []
    target_results: list[dict[str, Any]] = []

    for name in TARGET_NAMES:
        evidence = evidence_by_name[name]
        site = site_by_name[name]
        expected = parse_expected(evidence)
        candidate_id = site["candidate_id"]
        candidate_diagnostics: list[dict[str, Any]] = []

        query_a = evidence["address"]
        response, hit, requests = request_cached(candidate_id, "geocode", query_a, "南宁市", key)
        cache_hits += int(hit)
        api_requests += requests
        rows_a = geocode_rows(candidate_id, name, query_a, response, expected)
        all_geocode_candidates.extend([{key: row.get(key, "") for key in CANDIDATE_FIELDS} for row in rows_a])
        candidate_diagnostics.extend(rows_a)
        eligible = unique_eligible(candidate_diagnostics)

        if not eligible:
            query_b = f"{evidence['address']} {SHORT_NAMES[name]}"
            response, hit, requests = request_cached(candidate_id, "geocode", query_b, "南宁市", key)
            cache_hits += int(hit)
            api_requests += requests
            rows_b = geocode_rows(candidate_id, name, query_b, response, expected)
            all_geocode_candidates.extend([{key: row.get(key, "") for key in CANDIDATE_FIELDS} for row in rows_b])
            candidate_diagnostics.extend(rows_b)
            eligible = unique_eligible(candidate_diagnostics)

        if not eligible:
            county_adcode = county_adcodes.get(evidence["county"], "")
            if not county_adcode:
                raise RuntimeError(f"项目区划数据缺少 {evidence['county']} adcode")
            query_poi = SHORT_NAMES[name]
            response, hit, requests = request_cached(candidate_id, "poi", query_poi, county_adcode, key)
            cache_hits += int(hit)
            api_requests += requests
            rows_poi = poi_rows(candidate_id, name, query_poi, response, expected)
            candidate_diagnostics.extend(rows_poi)
            eligible = unique_eligible(candidate_diagnostics)

        # This focused stage has a documented baseline: all four targets were
        # spatial_ready=false while the 13-row table had five ready nodes.
        # Keep that baseline stable so reruns remain idempotent and comparable.
        before_ready = "false"
        accepted: dict[str, Any] | None = None
        failure_status = "approximate_region_only"
        reason = "未找到目标区县+道路+门牌号完整匹配的精细候选；仅保留区域诊断，不写入坐标。"
        if len(eligible) == 1:
            proposed = eligible[0]
            reverse_response, hit, requests = request_cached(candidate_id, "regeocode", proposed["location"], "", key)
            cache_hits += int(hit)
            api_requests += requests
            reverse = parse_reverse(reverse_response)
            if apply_reverse_validation(proposed, reverse):
                accepted = proposed
                reason = "唯一门牌强匹配候选通过逆地理行政区/道路复核。"
            else:
                failure_status = "manual_review"
                reason = "正向候选强匹配，但逆地理结果与目标行政区或道路不一致。"
        elif len(eligible) > 1:
            failure_status = "manual_review"
            reason = "存在两个以上不同坐标的道路+门牌号强匹配候选，未自动选择。"

        for row in candidate_diagnostics:
            if accepted and row is not accepted and row["decision"] == "eligible_strong":
                row["decision"] = "not_selected"
                row["decision_reason"] = "另一唯一候选通过逆地理验证"
            elif not accepted and len(eligible) > 1 and row["decision"] == "eligible_strong":
                row["decision"] = "manual_review"
                row["decision_reason"] = "多个强匹配候选无法自动区分"
        all_diagnostics.extend(candidate_diagnostics)

        if accepted:
            lon, lat = split_location(accepted["location"])
            confidence = "medium" if evidence["evidence_level"] == "B" else "high"
            site.update({
                "longitude_raw": lon,
                "latitude_raw": lat,
                "coordinate_system_raw": COORDINATE_SYSTEM,
                "geocoding_status": "success",
                "geocoding_confidence": confidence,
                "spatial_ready": "true",
            })
        else:
            site.update({
                "longitude_raw": "",
                "latitude_raw": "",
                "coordinate_system_raw": "",
                "geocoding_status": failure_status,
                "geocoding_confidence": "manual_review",
                "spatial_ready": "false",
            })
        target_results.append({
            "candidate_id": candidate_id,
            "name": name,
            "before_spatial_ready": before_ready,
            "after_spatial_ready": site["spatial_ready"],
            "final_status": site["geocoding_status"],
            "final_confidence": site["geocoding_confidence"],
            "selected_location": f"{site['longitude_raw']},{site['latitude_raw']}" if site["longitude_raw"] else "",
            "reason": reason,
        })

    if any(row != non_target_before[row["candidate_id"]] for row in site_rows if row["name"] not in TARGET_NAMES):
        raise RuntimeError("检测到4个目标以外的核心设施记录发生变化。")

    write_csv(CANDIDATE_OUTPUT_PATH, all_geocode_candidates, CANDIDATE_FIELDS)
    write_csv(DIAGNOSTIC_PATH, all_diagnostics, DIAGNOSTIC_FIELDS)
    write_csv(SITE_PATH, site_rows, list(site_rows[0].keys()))

    candidates = read_csv(PROCESSED_DIR / "supply_node_candidates.csv")
    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    allowed_fields = ["longitude_raw", "latitude_raw", "coordinate_system_raw", "geocoding_status", "geocoding_confidence", "spatial_ready"]
    for result in target_results:
        source = site_by_name[result["name"]]
        target = candidate_by_id[result["candidate_id"]]
        for field in allowed_fields:
            target[field] = source[field]
    write_csv(PROCESSED_DIR / "supply_node_candidates.csv", candidates, PIPELINE_CANDIDATE_FIELDS)

    old_reviews = read_csv(REVIEW_PATH)
    kept_reviews = [row for row in old_reviews if row["name"] not in TARGET_NAMES]
    diagnostics_by_name = {name: [row for row in all_diagnostics if row["name"] == name] for name in TARGET_NAMES}
    for result in target_results:
        if result["final_status"] == "success":
            continue
        site = site_by_name[result["name"]]
        kept_reviews.append({
            "candidate_id": result["candidate_id"],
            "name": result["name"],
            "address": site["address"],
            "address_precision": site["address_precision"],
            "evidence_level": site["evidence_level"],
            "geocoding_query": evidence_by_name[result["name"]]["address"],
            "api_result": concise_response(diagnostics_by_name[result["name"]]),
            "failure_reason": "town_centroid_only" if result["final_status"] == "approximate_region_only" else "ambiguous_result",
        })
    write_csv(REVIEW_PATH, kept_reviews, REVIEW_FIELDS)

    output_paths = [CANDIDATE_OUTPUT_PATH, DIAGNOSTIC_PATH, SITE_PATH, REVIEW_PATH, REPORT_JSON_PATH, REPORT_MD_PATH]
    cache_paths = list(CACHE_DIR.glob("*_doorreview_*.json"))
    secret_leak = any(key in path.read_text(encoding="utf-8-sig", errors="ignore") for path in output_paths + cache_paths if path.is_file())
    report = update_report(site_rows, target_results, api_requests, cache_hits, secret_leak)
    REPORT_JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report_md(report)
    if secret_leak:
        raise RuntimeError("输出或缓存中检测到 API Key。")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
