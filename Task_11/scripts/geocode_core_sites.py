from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, defaultdict
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
    utc_now,
)
from pipeline_common import PROCESSED_DIR, TASK_ROOT, read_csv, write_csv


CORE_NAMES = [
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
    "融安县储备粮管理公司",
]

SEARCH_ALIASES = {
    "南宁市储备粮管理有限责任公司五象粮库": ["五象粮库", "南宁五象粮库"],
    "南宁市储备粮管理有限责任公司沙井粮库": ["沙井粮库", "南宁沙井粮库"],
    "南宁市邕宁区粮食储备库": ["邕宁区粮食储备库", "邕宁粮库"],
    "南宁市江丰粮食收储管理中心": ["江丰粮食收储管理中心", "南宁江丰粮食收储"],
    "横州市六景粮食储备中心库": ["六景粮食储备中心库", "六景粮库", "横州六景粮库"],
    "马山县储备粮管理公司": ["马山储备粮管理公司", "马山粮库"],
    "隆安县储备粮管理公司": ["隆安储备粮管理公司", "隆安粮库"],
    "上林县安恒储备粮管理有限公司": ["上林安恒储备粮", "安恒储备粮管理公司"],
    "广西壮族自治区五象粮食储备库有限公司": ["自治区五象粮库", "五象粮食储备库", "广西五象粮库"],
    "广西壮族自治区南宁粮食储备库有限公司": ["自治区南宁粮库", "南宁粮食储备库", "广西南宁粮食储备库"],
    "柳州市五里卡粮库有限公司": ["五里卡粮库", "柳州五里卡粮库"],
    "广西柳州黄村粮食储备库有限公司": ["黄村粮食储备库", "黄村粮库", "柳州黄村粮库"],
    "广西壮族自治区柳州粮食储备库有限公司": ["自治区柳州粮库", "柳州粮食储备库", "广西柳州粮食储备库"],
    "柳城县金稻香粮食收储有限责任公司": ["柳城金稻香粮食收储", "金稻香粮食收储"],
    "柳州市柳江区柳粮粮油有限公司": ["柳江柳粮粮油", "柳粮粮油"],
    "融水苗族自治县储备粮管理公司": ["融水储备粮管理公司", "融水粮库"],
    "三江侗族自治县粮食购销和储备粮管理中心": ["三江粮食购销储备中心", "三江储备粮管理中心", "三江粮库"],
    "融安县储备粮管理公司": ["融安储备粮管理公司", "融安粮库"],
}

QUERY_OVERRIDES = {
    "南宁市储备粮管理有限责任公司五象粮库": [
        "南宁市储备粮管理有限责任公司五象粮库", "五象粮库", "五象粮库 南宁", "南宁 五象 粮库", "南宁市 五象粮库",
    ],
    "横州市六景粮食储备中心库": [
        "横州市六景粮食储备中心库", "六景粮食储备中心库", "六景粮库", "横州 六景 粮库", "六景粮库 南宁",
    ],
}

FACILITY_TERMS = ("粮库", "储备库", "中心库", "直属库", "库区", "粮食储备", "粮食仓储")

CORE_FIELDS = [
    "candidate_id", "name", "normalized_name", "search_aliases", "city", "county",
    "entity_type", "node_type", "address", "longitude_raw", "latitude_raw",
    "coordinate_system_raw", "matched_poi_name", "matched_poi_address", "successful_query",
    "match_score", "geocoding_confidence", "address_source", "geocoding_provider", "status",
    "previous_geocoding_status", "previous_location", "new_geocoding_status", "new_location",
    "upgrade_reason", "queries_attempted", "source_files", "source_record_ids", "evidence_level",
]

POI_REVIEW_FIELDS = [
    "candidate_id", "candidate_name", "query", "poi_name", "poi_address", "poi_district",
    "poi_city", "poi_location", "name_similarity", "region_match", "alias_match",
    "match_score", "recommended_decision",
]

RESEARCH_FIELDS = [
    "candidate_id", "name", "city", "county", "entity_type", "node_type", "current_address",
    "queries_attempted", "best_poi_name", "best_poi_address", "best_poi_location",
    "best_similarity", "failure_reason", "research_keywords", "recommended_next_step",
]


def build_queries(name: str, city: str) -> list[str]:
    if name in QUERY_OVERRIDES:
        return QUERY_OVERRIDES[name]
    aliases = SEARCH_ALIASES[name]
    queries = [name, *aliases]
    if aliases:
        queries.extend([f"{aliases[0]} {city}", f"{city.replace('市', '')} {aliases[-1]}"])
    return list(dict.fromkeys(query.strip() for query in queries if query.strip()))[:5]


def cache_file(candidate_id: str, query: str, region: str) -> Path:
    digest = hashlib.sha256(f"{query}|{region}".encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{candidate_id}__q_{digest}.json"


def legacy_response(candidate_id: str, query: str, region: str) -> dict[str, Any] | None:
    path = CACHE_DIR / f"{candidate_id}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for attempt in payload.get("attempts", []):
        if scalar(attempt.get("request_type")) != "poi":
            continue
        if normalize_match_name(scalar(attempt.get("query"))) != normalize_match_name(query):
            continue
        attempt_region = scalar(attempt.get("region"))
        if attempt_region and attempt_region != region and attempt_region not in {"南宁市", "柳州市"}:
            continue
        response = attempt.get("response")
        if isinstance(response, dict):
            return response
    return None


def load_or_request(
    candidate_id: str,
    query: str,
    region: str,
    key: str,
    counters: dict[str, int],
) -> dict[str, Any]:
    path = cache_file(candidate_id, query, region)
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload.get("response"), dict):
                counters["cache_hit_count"] += 1
                return payload["response"]
        except (OSError, json.JSONDecodeError):
            pass

    response = legacy_response(candidate_id, query, region)
    source = "legacy_candidate_cache"
    if response is not None:
        counters["cache_hit_count"] += 1
    else:
        source = "amap_api"
        if counters["api_request_count"]:
            time.sleep(0.55)
        response = amap_call("poi", query, region, key)
        counters["api_request_count"] += 1
        if scalar(response.get("infocode")) == "10021":
            time.sleep(1.5)
            response = amap_call("poi", query, region, key)
            counters["api_request_count"] += 1

    payload = {
        "candidate_id": candidate_id,
        "query": query,
        "query_hash": path.stem.rsplit("__q_", 1)[-1],
        "region": region,
        "provider": "amap",
        "coordinate_system_raw": COORDINATE_SYSTEM,
        "cache_source": source,
        "cached_at": utc_now(),
        "response": response,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return response


def candidate_match_key(poi: dict[str, Any]) -> str:
    return "|".join((scalar(poi.get("id")), scalar(poi.get("name")), scalar(poi.get("location"))))


def score_poi(target: dict[str, str], query: str, poi: dict[str, Any]) -> dict[str, Any]:
    name = scalar(poi.get("name"))
    address = scalar(poi.get("address"))
    city = scalar(poi.get("cityname"))
    district = scalar(poi.get("adname"))
    full_address = "".join(part for part in (scalar(poi.get("pname")), city, district, address) if part)
    location = scalar(poi.get("location"))
    lon, lat = split_location(location)
    location = f"{lon},{lat}" if lon and lat else ""

    normalized_poi = normalize_match_name(name)
    normalized_name = normalize_match_name(target["name"])
    alias_norms = {normalize_match_name(alias) for alias in target["search_aliases"]}
    standard_exact = normalized_poi == normalized_name
    alias_exact = normalized_poi in alias_norms
    similarity = max(
        [name_similarity(target["name"], name)]
        + [name_similarity(alias, name) for alias in target["search_aliases"]]
    )

    combined_region = f"{city}{district}{full_address}"
    city_match = target["city"] in combined_region
    county_match = not target["county"] or target["county"] in combined_region
    county_conflict = bool(target["county"] and district and target["county"] not in combined_region)
    facility_match = any(term in name for term in FACILITY_TERMS)
    parent_only = bool(
        target.get("parent_entity_name")
        and normalized_poi == normalize_match_name(target["parent_entity_name"])
    )
    hierarchy_conflict = bool(
        ("分公司" in name) != ("分公司" in target["name"])
        and (normalize_match_name(target["name"]) in normalized_poi or normalized_poi in normalize_match_name(target["name"]))
    )

    score = 0
    if standard_exact:
        score += 50
    elif alias_exact:
        score += 40
    elif similarity >= 0.82:
        score += 30
    elif similarity >= 0.65:
        score += 15
    if city_match:
        score += 20
    if county_match and target["county"]:
        score += 15
    if facility_match:
        score += 10
    if county_conflict:
        score -= 30

    hard_reject = not city_match or not location
    ambiguity = parent_only or hierarchy_conflict or county_conflict
    if target["entity_type"] == "physical_site" and not facility_match:
        ambiguity = True

    return {
        "query": query,
        "poi_name": name,
        "poi_address": full_address,
        "poi_district": district,
        "poi_city": city,
        "poi_location": location,
        "name_similarity": round(similarity, 4),
        "city_match": city_match,
        "county_match": county_match,
        "county_conflict": county_conflict,
        "region_match": city_match and not county_conflict,
        "alias_match": alias_exact,
        "standard_exact": standard_exact,
        "facility_match": facility_match,
        "parent_only": parent_only,
        "hierarchy_conflict": hierarchy_conflict,
        "match_score": score,
        "hard_reject": hard_reject,
        "ambiguity": ambiguity,
    }


def strong_match(target: dict[str, str], match: dict[str, Any]) -> bool:
    if match["hard_reject"] or match["ambiguity"]:
        return False
    if target["entity_type"] == "physical_site":
        return bool(
            match["facility_match"]
            and match["region_match"]
            and (match["standard_exact"] or match["alias_match"] or match["name_similarity"] >= 0.82)
            and match["match_score"] >= 70
        )
    return bool(
        match["region_match"]
        and (match["standard_exact"] or match["alias_match"] or match["name_similarity"] >= 0.88)
        and match["match_score"] >= 70
    )


def confidence_for(match: dict[str, Any]) -> str:
    if match["standard_exact"] or match["alias_match"]:
        return "high"
    return "medium"


def compact_join(values: list[str]) -> str:
    return ";".join(dict.fromkeys(value for value in values if value))


def build_research_keywords(target: dict[str, str]) -> list[str]:
    aliases = target["search_aliases"]
    keywords = [f"{target['name']} 地址"]
    if aliases:
        keywords.append(f"{aliases[0]} 项目 地址 {target['city']}")
    if target["county"]:
        keywords.append(f"{target['county']} 粮库 地址")
    return list(dict.fromkeys(keywords))


def main() -> None:
    candidates = read_csv(PROCESSED_DIR / "supply_node_candidates.csv")
    previous = {row["candidate_id"]: row for row in read_csv(PROCESSED_DIR / "geocoded_supply_nodes.csv")}
    candidate_by_name = {row["name"]: row for row in candidates}
    missing = [name for name in CORE_NAMES if name not in candidate_by_name]
    if missing:
        raise RuntimeError("重点 candidate 缺失: " + "、".join(missing))

    key = load_env_value("AMAP_WEB_KEY")
    if not key:
        raise RuntimeError("缺少 AMAP_WEB_KEY；已停止网络地理编码。")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    counters = {"api_request_count": 0, "cache_hit_count": 0}
    targets: list[dict[str, Any]] = []
    all_scored: dict[str, list[dict[str, Any]]] = {}

    for name in CORE_NAMES:
        candidate = candidate_by_name[name]
        target = {
            **candidate,
            "search_aliases": SEARCH_ALIASES[name],
            "queries": build_queries(name, candidate["city"]),
        }
        targets.append(target)
        best_by_poi: dict[str, dict[str, Any]] = {}
        region = candidate["county"] or candidate["city"]
        for query in target["queries"]:
            response = load_or_request(candidate["candidate_id"], query, region, key, counters)
            for poi in response.get("pois", []) if isinstance(response.get("pois"), list) else []:
                scored = score_poi(target, query, poi)
                key_value = candidate_match_key(poi)
                current = best_by_poi.get(key_value)
                if current is None or scored["match_score"] > current["match_score"]:
                    best_by_poi[key_value] = scored
        all_scored[candidate["candidate_id"]] = sorted(
            best_by_poi.values(),
            key=lambda row: (-row["match_score"], -row["name_similarity"], row["poi_name"]),
        )

    selections: dict[str, dict[str, Any] | None] = {}
    selection_reasons: dict[str, str] = {}
    for target in targets:
        matches = all_scored[target["candidate_id"]]
        strong = [match for match in matches if strong_match(target, match)]
        if not strong:
            selections[target["candidate_id"]] = None
            if not matches:
                selection_reasons[target["candidate_id"]] = "no_result"
            elif any(match["parent_only"] or match["hierarchy_conflict"] for match in matches[:5]):
                selection_reasons[target["candidate_id"]] = "organization_site_ambiguity"
            elif any(match["region_match"] for match in matches[:5]):
                selection_reasons[target["candidate_id"]] = "name_mismatch"
            else:
                selection_reasons[target["candidate_id"]] = "region_mismatch"
            continue
        top = strong[0]
        close = [match for match in strong[1:] if top["match_score"] - match["match_score"] < 10 and match["poi_location"] != top["poi_location"]]
        if close:
            selections[target["candidate_id"]] = None
            selection_reasons[target["candidate_id"]] = "multiple_matches"
        else:
            selections[target["candidate_id"]] = top
            selection_reasons[target["candidate_id"]] = ""

    # 同一 POI 不能自动赋给两个名单主体，尤其是两个“五象粮库”candidate。
    location_to_ids: dict[str, list[str]] = defaultdict(list)
    for candidate_id, selected in selections.items():
        if selected:
            location_to_ids[selected["poi_location"]].append(candidate_id)
    for ids in location_to_ids.values():
        if len(ids) > 1:
            for candidate_id in ids:
                selections[candidate_id] = None
                selection_reasons[candidate_id] = "cross_candidate_ambiguity"

    core_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    research_rows: list[dict[str, Any]] = []
    for target in targets:
        candidate_id = target["candidate_id"]
        matches = all_scored[candidate_id]
        selected = selections[candidate_id]
        reason = selection_reasons[candidate_id]
        previous_row = previous.get(candidate_id, {})
        previous_location = ",".join(part for part in (previous_row.get("longitude_raw", ""), previous_row.get("latitude_raw", "")) if part)

        if selected:
            status = "located"
            confidence = confidence_for(selected)
            lon, lat = selected["poi_location"].split(",", 1)
            upgrade_reason = "多查询/别名策略获得唯一强匹配 POI；名称、行政区和实体层级检查通过。"
        else:
            plausible = [
                match for match in matches[:5]
                if match["region_match"]
                and (
                    match["match_score"] >= 50
                    or (match["facility_match"] and match["name_similarity"] >= 0.60)
                )
            ]
            indirect_facility_evidence = any(
                match["region_match"] and match["facility_match"] and match["name_similarity"] >= 0.60
                for match in matches[:5]
            )
            status = "manual_review" if (
                reason in {"multiple_matches", "organization_site_ambiguity", "cross_candidate_ambiguity"}
                or len(plausible) >= 2
                or indirect_facility_evidence
            ) else "research_pending"
            confidence = "manual_review" if status == "manual_review" else "failed"
            lon = lat = ""
            upgrade_reason = "未达到自动接受阈值；保留候选 POI 并等待地址补证。"

        core_rows.append({
            "candidate_id": candidate_id,
            "name": target["name"],
            "normalized_name": target["normalized_name"],
            "search_aliases": compact_join(target["search_aliases"]),
            "city": target["city"],
            "county": target["county"],
            "entity_type": target["entity_type"],
            "node_type": target["node_type"],
            "address": selected["poi_address"] if selected else target.get("address", ""),
            "longitude_raw": lon,
            "latitude_raw": lat,
            "coordinate_system_raw": COORDINATE_SYSTEM if selected else "",
            "matched_poi_name": selected["poi_name"] if selected else "",
            "matched_poi_address": selected["poi_address"] if selected else "",
            "successful_query": selected["query"] if selected else "",
            "match_score": selected["match_score"] if selected else "",
            "geocoding_confidence": confidence,
            "address_source": "map_poi" if selected else "unknown",
            "geocoding_provider": "amap",
            "status": status,
            "previous_geocoding_status": previous_row.get("geocoding_confidence", "failed"),
            "previous_location": previous_location,
            "new_geocoding_status": confidence,
            "new_location": f"{lon},{lat}" if lon and lat else "",
            "upgrade_reason": upgrade_reason,
            "queries_attempted": compact_join(target["queries"]),
            "source_files": target["source_files"],
            "source_record_ids": target["source_record_ids"],
            "evidence_level": target["evidence_level"],
        })

        for match in matches[:5]:
            if selected is match:
                decision = "accept"
            elif match["hard_reject"] or match["match_score"] < 50:
                decision = "reject"
            else:
                decision = "manual_review"
            review_rows.append({
                "candidate_id": candidate_id,
                "candidate_name": target["name"],
                "query": match["query"],
                "poi_name": match["poi_name"],
                "poi_address": match["poi_address"],
                "poi_district": match["poi_district"],
                "poi_city": match["poi_city"],
                "poi_location": match["poi_location"],
                "name_similarity": match["name_similarity"],
                "region_match": match["region_match"],
                "alias_match": match["alias_match"],
                "match_score": match["match_score"],
                "recommended_decision": decision,
            })

        if not selected:
            best = matches[0] if matches else {}
            research_rows.append({
                "candidate_id": candidate_id,
                "name": target["name"],
                "city": target["city"],
                "county": target["county"],
                "entity_type": target["entity_type"],
                "node_type": target["node_type"],
                "current_address": target.get("address", ""),
                "queries_attempted": compact_join(target["queries"]),
                "best_poi_name": best.get("poi_name", ""),
                "best_poi_address": best.get("poi_address", ""),
                "best_poi_location": best.get("poi_location", ""),
                "best_similarity": best.get("name_similarity", ""),
                "failure_reason": reason,
                "research_keywords": compact_join(build_research_keywords(target)),
                "recommended_next_step": "使用新的官方地址资料核实设施名称和详细地址；本轮不自动联网检索。",
            })

    write_csv(PROCESSED_DIR / "core_site_geocoding.csv", core_rows, CORE_FIELDS)
    write_csv(PROCESSED_DIR / "poi_match_review.csv", review_rows, POI_REVIEW_FIELDS)
    write_csv(PROCESSED_DIR / "address_research_pending.csv", research_rows, RESEARCH_FIELDS)

    located = [row for row in core_rows if row["status"] == "located"]
    physical = [row for row in core_rows if row["entity_type"] == "physical_site"]
    physical_located = [row for row in located if row["entity_type"] == "physical_site"]
    multi_query_success = [row for row in located if row["successful_query"] != row["name"]]
    alias_norms_by_name = {name: {normalize_match_name(alias) for alias in aliases} for name, aliases in SEARCH_ALIASES.items()}
    alias_success = [row for row in located if normalize_match_name(row["successful_query"]) in alias_norms_by_name[row["name"]]]
    ready_for_crs = len(physical_located) > len(physical) / 2 and not any(
        row["failure_reason"] in {"organization_site_ambiguity", "cross_candidate_ambiguity"} for row in research_rows
    )
    used_cache_files = [
        cache_file(target["candidate_id"], query, target["county"] or target["city"])
        for target in targets
        for query in target["queries"]
    ]
    cached_sources: list[str] = []
    for path in used_cache_files:
        try:
            cached_sources.append(scalar(json.loads(path.read_text(encoding="utf-8")).get("cache_source")))
        except (OSError, json.JSONDecodeError):
            continue
    distinct_api_query_count = sum(source == "amap_api" for source in cached_sources)
    legacy_cache_migration_count = sum(source == "legacy_candidate_cache" for source in cached_sources)

    report = {
        "core_target_count": len(core_rows),
        "physical_site_target_count": len(physical),
        "located_count": len(located),
        "physical_site_located_count": len(physical_located),
        "physical_site_high_confidence_count": sum(row["geocoding_confidence"] == "high" for row in physical_located),
        "physical_site_medium_confidence_count": sum(row["geocoding_confidence"] == "medium" for row in physical_located),
        "manual_review_count": sum(row["status"] == "manual_review" for row in core_rows),
        "research_pending_count": sum(row["status"] == "research_pending" for row in core_rows),
        "nanning_core_located_count": sum(row["status"] == "located" and row["city"] == "南宁市" for row in core_rows),
        "liuzhou_core_located_count": sum(row["status"] == "located" and row["city"] == "柳州市" for row in core_rows),
        "multi_query_success_count": len(multi_query_success),
        "alias_query_success_count": len(alias_success),
        "api_request_count": max(counters["api_request_count"], distinct_api_query_count),
        "cache_hit_count": counters["cache_hit_count"],
        "distinct_api_query_cache_count": distinct_api_query_count,
        "legacy_cache_migration_count": legacy_cache_migration_count,
        "coordinate_system_raw": COORDINATE_SYSTEM,
        "unresolved_nodes": [row["name"] for row in core_rows if row["status"] != "located"],
        "organization_physical_site_confusion_detected": any(
            row["failure_reason"] in {"organization_site_ambiguity", "cross_candidate_ambiguity"} for row in research_rows
        ),
        "READY_FOR_CRS": ready_for_crs,
    }

    # API Key 泄露、区域、坐标和实体混淆终检。
    errors: list[str] = []
    if len(core_rows) != 18 or len({row["candidate_id"] for row in core_rows}) != 18:
        errors.append("重点 candidate 不是18个唯一实体。")
    if any(row["coordinate_system_raw"] != COORDINATE_SYSTEM for row in located):
        errors.append("成功结果缺少 GCJ02 原始坐标系标记。")
    if any(not (104 <= float(row["longitude_raw"]) <= 113 and 20 <= float(row["latitude_raw"]) <= 27) for row in located):
        errors.append("成功结果存在广西范围外坐标。")
    if any(
        row["entity_type"] == "physical_site"
        and target.get("parent_entity_name")
        and row["matched_poi_name"] == target.get("parent_entity_name")
        for row, target in zip(core_rows, targets)
    ):
        errors.append("physical_site 错误匹配母公司。")
    if len({row["new_location"] for row in located}) != len(located):
        errors.append("不同重点 candidate 异常共享相同坐标。")

    report["validation_errors"] = errors
    report["validation_status"] = "FAIL" if errors else ("WARN" if report["unresolved_nodes"] else "PASS")
    (PROCESSED_DIR / "core_site_geocoding_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    scoring_lines = [
        "- 标准名称完全一致：+50；别名完全一致：+40；名称高度相似：+30。",
        "- city 一致：+20；county 一致：+15；POI 名称含粮库/储备库等设施词：+10。",
        "- city 不一致或无有效坐标：直接 reject；county 明显冲突：-30。",
        "- physical_site 只匹配到公司主体、缺设施词、存在多个接近结果或跨 candidate 共用 POI 时，不自动接受。",
    ]
    lines = [
        "# 重点粮食储备节点地址补证与二次定位报告",
        "",
        "> 本轮仅处理指定18个重点节点。未执行GCJ-02到项目CRS转换、1 km网格关联、最终筛选或洪涝分析。",
        "",
        "## 结果摘要",
        "",
        f"- 重点节点：{report['core_target_count']} 个，其中 physical_site {report['physical_site_target_count']} 个。",
        f"- 成功定位：{report['located_count']} 个；南宁 {report['nanning_core_located_count']} 个，柳州 {report['liuzhou_core_located_count']} 个。",
        f"- physical_site 成功：{report['physical_site_located_count']} 个；high={report['physical_site_high_confidence_count']}，medium={report['physical_site_medium_confidence_count']}。",
        f"- manual_review：{report['manual_review_count']} 个；research_pending：{report['research_pending_count']} 个。",
        f"- 多 query 新增成功：{report['multi_query_success_count']} 个；别名 query 成功：{report['alias_query_success_count']} 个。",
        f"- API 请求：{report['api_request_count']}；缓存命中：{report['cache_hit_count']}。",
        f"- 原始坐标系：{COORDINATE_SYSTEM}；未写入EPSG:4490。",
        "",
        "## 可解释评分规则",
        "",
        *scoring_lines,
        "",
        "## 仍无法可靠定位的节点",
        "",
        *([f"- {name}" for name in report["unresolved_nodes"]] or ["无。"]),
        "",
        "## 实体层级检查",
        "",
        f"- 是否发现需要拦截的 organization / physical_site 混淆：{report['organization_physical_site_confusion_detected']}。",
        "- 被拦截的相似主体、同名粮库或共用POI只进入人工复核，不写入正式坐标。",
        "",
        "## 阶段结论",
        "",
        f"READY_FOR_CRS = {'true' if report['READY_FOR_CRS'] else 'false'}",
        "",
        f"验证状态：{report['validation_status']}；错误数：{len(errors)}。",
        "",
    ]
    (PROCESSED_DIR / "core_site_geocoding_report.md").write_text("\n".join(lines), encoding="utf-8")

    output_paths = [
        PROCESSED_DIR / "core_site_geocoding.csv",
        PROCESSED_DIR / "poi_match_review.csv",
        PROCESSED_DIR / "address_research_pending.csv",
        PROCESSED_DIR / "core_site_geocoding_report.json",
        PROCESSED_DIR / "core_site_geocoding_report.md",
        *CACHE_DIR.glob("*__q_*.json"),
    ]
    leaked = [path for path in output_paths if path.is_file() and key.encode("utf-8") in path.read_bytes()]
    if leaked:
        for path in leaked:
            path.unlink(missing_ok=True)
        raise RuntimeError("API secret leak detected; affected outputs removed")
    if errors:
        raise RuntimeError("; ".join(errors))
    print(
        f"core_targets={len(core_rows)} located={len(located)} physical_located={len(physical_located)} "
        f"manual={report['manual_review_count']} research={report['research_pending_count']} "
        f"ready_for_crs={str(ready_for_crs).lower()}"
    )


if __name__ == "__main__":
    main()
