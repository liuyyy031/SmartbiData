from __future__ import annotations

import argparse
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pipeline_common import (
    BOOL_FIELDS,
    CANDIDATE_FIELDS,
    PROCESSED_DIR,
    analysis_priority,
    normalize_address,
    normalize_name,
    parse_region,
    read_csv,
    select_mode,
    stable_id,
    truthy,
    unique_join,
    write_csv,
)


DUPLICATE_FIELDS = [
    "candidate_id_1",
    "candidate_id_2",
    "name_1",
    "name_2",
    "address_1",
    "address_2",
    "credit_code_1",
    "credit_code_2",
    "similarity_reason",
    "recommended_action",
]

GEOCODING_FIELDS = [
    "candidate_id",
    "name",
    "province",
    "city",
    "county",
    "address",
    "geocoding_status",
    "notes",
]

NODE_TYPE_PRIORITY = {
    "grain_depot": 1,
    "grain_reserve": 2,
    "military_grain_supply": 3,
    "emergency_support_center": 4,
    "emergency_storage_transport": 5,
    "emergency_processing": 6,
    "emergency_distribution_center": 7,
    "emergency_supply_outlet": 8,
    "cold_chain_distribution_center": 9,
    "agricultural_wholesale_market": 10,
    "basket_supply_base": 11,
    "government_procurement_supplier": 12,
    "other": 99,
}


def valid_credit_code(code: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Z]{18}", (code or "").strip().upper()))


def identity_key(row: dict[str, str], unique_code_by_name: dict[tuple[str, str], str] | None = None) -> str:
    code = row.get("raw_credit_code", "").strip().upper()
    entity_type = row.get("entity_type", "unknown")
    if valid_credit_code(code):
        # 同一信用代码下仍按实体层级分组，防止公司主体与具体设施误合并。
        return f"credit:{code}:{entity_type}"
    normalized_name = row.get("_identity_name", "") or row.get("normalized_name", "") or normalize_name(row.get("raw_name", ""))
    if unique_code_by_name and normalized_name:
        linked_code = unique_code_by_name.get((normalized_name, entity_type), "")
        if linked_code:
            return f"credit:{linked_code}:{entity_type}"
    if normalized_name:
        return f"name:{normalized_name}:{entity_type}"
    return f"record:{row.get('record_id', '')}"


def address_score(address: str) -> tuple[int, int]:
    text = normalize_address(address)
    facility = bool(re.search(r"仓库|粮库|储备库|配送中心|冷库|厂房|加工厂|物流中心|工业园|产业园", text))
    return (1 if facility else 0, len(text))


def select_address(rows: list[dict[str, str]]) -> str:
    addresses = [row.get("raw_address", "") for row in rows if row.get("raw_address", "")]
    if not addresses:
        return ""
    counts = {address: addresses.count(address) for address in set(addresses)}
    return sorted(addresses, key=lambda address: (-address_score(address)[0], -counts[address], -len(address), address))[0]


def select_node_type(rows: list[dict[str, str]]) -> str:
    values = [row.get("node_type", "other") for row in rows]
    return sorted(values, key=lambda value: (NODE_TYPE_PRIORITY.get(value, 999), value))[0]


def aggregate_candidate(key: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    names = [row.get("raw_name", "") for row in rows]
    current_names = [row.get("canonical_name", "") for row in rows if row.get("name_aliases", "")]
    name = select_mode(current_names) or select_mode(row.get("canonical_name", "") for row in rows) or select_mode(names)
    normalized_name = normalize_name(name)
    address = select_address(rows)
    raw_regions = [row.get("raw_region", "") for row in rows]
    province, city, county = parse_region(address, name, select_mode(raw_regions))
    if not province:
        province = select_mode(row.get("province", "") for row in rows)
    if not city:
        city = select_mode(row.get("city", "") for row in rows)
    if not county:
        county = select_mode(row.get("county", "") for row in rows)

    codes = [row.get("raw_credit_code", "").upper() for row in rows if valid_credit_code(row.get("raw_credit_code", ""))]
    credit_code = select_mode(codes)
    evidence = sorted((row.get("evidence_level", "D") for row in rows), key=lambda x: ("ABCD".find(x), x))[0]
    node_type = select_node_type(rows)
    source_categories = unique_join(row.get("source_category", "") for row in rows)
    source_files = unique_join(row.get("source_file", "") for row in rows)
    source_record_ids = unique_join(row.get("record_id", "") for row in rows)
    services = unique_join(row.get("service_region", "") for row in rows)
    entity_type = select_mode(row.get("entity_type", "unknown") for row in rows) or "unknown"
    parent_entity_name = unique_join(row.get("raw_parent_organization", "") for row in rows)

    note_parts: list[str] = []
    for row in rows:
        for note in (row.get("normalization_notes", ""), row.get("parse_notes", "")):
            if note and note not in note_parts:
                note_parts.append(note)
    distinct_addresses = list(dict.fromkeys(row.get("raw_address", "") for row in rows if row.get("raw_address", "")))
    if len(distinct_addresses) > 1:
        note_parts.append(f"同一候选实体在来源中出现 {len(distinct_addresses)} 个不同地址；当前优先保留设施语义更明确或出现频率更高的地址，其他地址仍保留在原始记录层。")
    if "government_procurement" in source_categories:
        note_parts.append("采购供应商地址不自动视为仓库地址；仅在原文出现仓库、粮库、配送中心、冷库、厂房等明确词时标记相应能力。")

    candidate: dict[str, Any] = {
        "candidate_id": stable_id("cand", key),
        "name": name,
        "normalized_name": normalized_name,
        "raw_names": unique_join(names),
        "province": province,
        "city": city,
        "county": county,
        "address": address,
        "service_region": services,
        "analysis_priority": analysis_priority(province, city),
        "credit_code": credit_code,
        "entity_type": entity_type,
        "parent_entity_name": parent_entity_name,
        "node_type": node_type,
        "node_subtype": unique_join(row.get("node_subtype", "") for row in rows),
        "recognition_level": unique_join(row.get("recognition_level", "") for row in rows),
        "storage_capacity": unique_join(row.get("raw_capacity", "") for row in rows if row.get("storage_capability") == "true"),
        "processing_capacity": unique_join(row.get("raw_capacity", "") for row in rows if row.get("processing_capability") == "true"),
        "distribution_capacity": unique_join(row.get("raw_capacity", "") for row in rows if row.get("distribution_capability") == "true"),
        "capacity_value": unique_join(row.get("raw_capacity", "") for row in rows),
        "capacity_unit": unique_join(row.get("raw_capacity_unit", "") for row in rows),
        "longitude": "",
        "latitude": "",
        "coordinate_source": "",
        "source_count": len(rows),
        "source_categories": source_categories,
        "source_files": source_files,
        "source_record_ids": source_record_ids,
        "evidence_level": evidence,
        "verified": all(truthy(row.get("verified", "")) for row in rows),
        "notes": " ".join(note_parts),
    }
    for field in BOOL_FIELDS:
        candidate[field] = any(truthy(row.get(field, "")) for row in rows)
    return candidate


def build_duplicate_review(candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    review: list[dict[str, str]] = []
    for index, left in enumerate(candidates):
        name_1 = normalize_name(left.get("name", ""))
        address_1 = normalize_address(left.get("address", ""))
        code_1 = str(left.get("credit_code", ""))
        for right in candidates[index + 1 :]:
            name_2 = normalize_name(right.get("name", ""))
            address_2 = normalize_address(right.get("address", ""))
            code_2 = str(right.get("credit_code", ""))
            reasons: list[str] = []
            action = "manual_review"

            if code_1 and code_2 and code_1 == code_2:
                reasons.append("same_credit_code_but_separate_entity_level")
                action = "keep_separate" if left.get("entity_type") != right.get("entity_type") else "manual_review"

            facility_suffix = re.compile(r"粮库|储备库|配送中心|物流中心|分公司|基地|市场|门店|网点|厂")
            if name_1 and name_2 and name_1 == name_2:
                reasons.append("same_normalized_name_but_not_auto_merged")
                action = "keep_separate" if left.get("entity_type") != right.get("entity_type") else "manual_review"

            if name_1 and name_2 and (name_1 in name_2 or name_2 in name_1) and name_1 != name_2:
                longer = name_2 if len(name_2) > len(name_1) else name_1
                shorter = name_1 if len(name_1) < len(name_2) else name_2
                suffix = longer.replace(shorter, "", 1)
                if facility_suffix.search(suffix):
                    reasons.append("organization_name_contains_specific_site_name")
                    action = "keep_separate"

            if address_1 and address_2 and len(address_1) >= 8 and address_1 == address_2 and name_1 != name_2:
                reasons.append("same_normalized_address_different_name")

            if name_1 and name_2 and name_1 != name_2 and min(len(name_1), len(name_2)) >= 6:
                ratio = SequenceMatcher(None, name_1, name_2).ratio()
                if ratio >= 0.90:
                    reasons.append(f"high_name_similarity={ratio:.3f}")

            if not reasons:
                continue
            review.append(
                {
                    "candidate_id_1": str(left["candidate_id"]),
                    "candidate_id_2": str(right["candidate_id"]),
                    "name_1": str(left.get("name", "")),
                    "name_2": str(right.get("name", "")),
                    "address_1": str(left.get("address", "")),
                    "address_2": str(right.get("address", "")),
                    "credit_code_1": code_1,
                    "credit_code_2": code_2,
                    "similarity_reason": ";".join(reasons),
                    "recommended_action": action,
                }
            )
    return review


def build_all() -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    normalized_path = PROCESSED_DIR / "_normalized_source_records.csv"
    if not normalized_path.exists():
        raise FileNotFoundError("缺少 _normalized_source_records.csv，请先运行 normalize_supply_records.py")
    rows = read_csv(normalized_path)

    # 仅使用来源中明确写出的“原名”关系合并名称；不以模糊相似度自动合并。
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(item: tuple[str, str]) -> tuple[str, str]:
        parent.setdefault(item, item)
        if parent[item] != item:
            parent[item] = find(parent[item])
        return parent[item]

    def union(left: tuple[str, str], right: tuple[str, str]) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for row in rows:
        entity_type = row.get("entity_type", "unknown")
        current = row.get("normalized_name", "")
        if not current:
            continue
        find((current, entity_type))
        for alias in row.get("name_aliases", "").split(";"):
            normalized_alias = normalize_name(alias)
            if normalized_alias:
                union((current, entity_type), (normalized_alias, entity_type))

    for row in rows:
        entity_type = row.get("entity_type", "unknown")
        normalized_name = row.get("normalized_name", "")
        if normalized_name:
            row["_identity_name"] = find((normalized_name, entity_type))[0]

    codes_by_name: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        code = row.get("raw_credit_code", "").strip().upper()
        if valid_credit_code(code):
            key = (row.get("_identity_name", "") or row.get("normalized_name", ""), row.get("entity_type", "unknown"))
            if key[0]:
                codes_by_name[key].add(code)
    unique_code_by_name = {key: next(iter(codes)) for key, codes in codes_by_name.items() if len(codes) == 1}
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[identity_key(row, unique_code_by_name)].append(row)

    candidates = [aggregate_candidate(key, group) for key, group in sorted(grouped.items())]
    candidates.sort(key=lambda row: (row["analysis_priority"], row["province"], row["city"], row["normalized_name"], row["candidate_id"]))
    duplicate_review = build_duplicate_review(candidates)
    geocoding = [
        {
            "candidate_id": row["candidate_id"],
            "name": row["name"],
            "province": row["province"],
            "city": row["city"],
            "county": row["county"],
            "address": row["address"],
            "geocoding_status": "pending" if row["address"] else "missing_address",
            "notes": "等待后续地址标准化与地理编码；本阶段未调用地图 API，也未使用城市中心点伪造坐标。",
        }
        for row in candidates
        if not row.get("longitude") or not row.get("latitude")
    ]

    write_csv(PROCESSED_DIR / "supply_node_candidates.csv", candidates, CANDIDATE_FIELDS)
    write_csv(PROCESSED_DIR / "duplicate_review.csv", duplicate_review, DUPLICATE_FIELDS)
    write_csv(PROCESSED_DIR / "geocoding_pending.csv", geocoding, GEOCODING_FIELDS)
    return candidates, duplicate_review, geocoding


def main() -> None:
    parser = argparse.ArgumentParser(description="按信用代码、标准名称和实体层级保守聚合候选节点。")
    parser.parse_args()
    candidates, review, geocoding = build_all()
    print(f"candidates={len(candidates)} duplicate_review={len(review)} geocoding_pending={len(geocoding)}")


if __name__ == "__main__":
    main()
