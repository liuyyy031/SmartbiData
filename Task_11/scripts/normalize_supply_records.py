from __future__ import annotations

import argparse
import re
from pathlib import Path

from pipeline_common import (
    BOOL_FIELDS,
    NORMALIZED_RECORD_FIELDS,
    PROCESSED_DIR,
    analysis_priority,
    capability_flags,
    classify_node_type,
    infer_entity_type,
    infer_evidence_level,
    normalize_address,
    normalize_name,
    parse_name_identity,
    parse_region,
    product_flags,
    read_csv,
    write_csv,
)


def normalize_record(row: dict[str, str]) -> dict[str, object]:
    name = row.get("raw_name", "")
    address = row.get("raw_address", "")
    raw_text = row.get("raw_text", "")
    source_category = row.get("source_category", "unknown")
    canonical_name, name_aliases = parse_name_identity(name)
    normalized_name = normalize_name(canonical_name)
    normalized_address = normalize_address(address)
    province, city, county = parse_region(address, name, row.get("raw_region", ""))
    entity_type = infer_entity_type(name, source_category)
    node_type, recognition_level, type_note = classify_node_type(name, raw_text, source_category)
    products = product_flags(row.get("raw_category", ""), raw_text, source_category)
    capabilities = capability_flags(name, address, raw_text, source_category)
    evidence = infer_evidence_level(source_category, name, address, raw_text)

    note_parts = [type_note]
    if source_category == "government_procurement":
        if address:
            note_parts.append("采购资料中的地址按企业登记/联系地址处理，不自动等同于仓库或配送节点地址。")
        else:
            note_parts.append("采购资料未提供企业地址；服务项目区域与企业所在地严格分开。")
    if not city and province == "广西壮族自治区":
        note_parts.append("可确认位于广西，但当前证据不足以安全确定地级市。")
    if not province:
        note_parts.append("当前原始记录未提供可安全解析的省级所在地。")
    if source_category == "grain_emergency" and node_type == "other":
        note_parts.append("保留国家级粮食应急保障企业身份，不凭名称猜测具体功能分类。")

    normalized: dict[str, object] = dict(row)
    normalized.update(
        {
            "canonical_name": canonical_name,
            "name_aliases": ";".join(name_aliases),
            "normalized_name": normalized_name,
            "normalized_address": normalized_address,
            "province": province,
            "city": city,
            "county": county,
            "service_region": row.get("raw_service_region", ""),
            "entity_type": entity_type,
            "node_type": node_type,
            "node_subtype": row.get("raw_category", ""),
            "recognition_level": recognition_level,
            **products,
            **capabilities,
            "government_emergency_recognition": source_category in {"grain_emergency", "grain_storage"},
            "government_reserve_related": source_category == "grain_reserve"
            or bool(re.search(r"储备粮|储备库|粮库|军粮", f"{name}{raw_text}")),
            "government_procurement_supplier": source_category == "government_procurement",
            "evidence_level": evidence,
            "verified": True,
            "analysis_priority": analysis_priority(province, city),
            "normalization_notes": " ".join(part for part in note_parts if part),
        }
    )
    for field in BOOL_FIELDS:
        normalized.setdefault(field, False)
    return normalized


def normalize_all() -> list[dict[str, object]]:
    source_path = PROCESSED_DIR / "supply_source_records.csv"
    if not source_path.exists():
        raise FileNotFoundError("缺少 supply_source_records.csv，请先运行 extract_supply_records.py")
    rows = read_csv(source_path)
    normalized = [normalize_record(row) for row in rows]
    write_csv(PROCESSED_DIR / "_normalized_source_records.csv", normalized, NORMALIZED_RECORD_FIELDS)
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="安全标准化原始供应记录，不删除原始字段。")
    parser.parse_args()
    rows = normalize_all()
    print(f"normalized_records={len(rows)}")


if __name__ == "__main__":
    main()
