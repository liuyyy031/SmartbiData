from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pipeline_common import (
    EVIDENCE_LEVELS,
    NODE_TYPES,
    PROCESSED_DIR,
    TASK_ROOT,
    dump_json,
    normalize_name,
    read_csv,
)


def count_distribution(rows: list[dict[str, str]], field: str) -> dict[str, int]:
    counts = Counter(row.get(field, "") or "(blank)" for row in rows)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def sample(values: list[Any], limit: int = 20) -> list[Any]:
    return values[:limit]


def has_source_category(row: dict[str, str], category: str) -> bool:
    return category in {item for item in row.get("source_categories", "").split(";") if item}


def validate() -> tuple[dict[str, Any], list[str], list[str]]:
    inventory = read_csv(PROCESSED_DIR / "raw_file_inventory.csv")
    records = read_csv(PROCESSED_DIR / "supply_source_records.csv")
    candidates = read_csv(PROCESSED_DIR / "supply_node_candidates.csv")
    duplicate_review = read_csv(PROCESSED_DIR / "duplicate_review.csv")

    errors: list[str] = []
    warnings: list[str] = []

    record_ids = [row.get("record_id", "") for row in records]
    candidate_ids = [row.get("candidate_id", "") for row in candidates]
    if len(record_ids) != len(set(record_ids)):
        errors.append("record_id 不唯一。")
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("candidate_id 不唯一。")
    if any(not value for value in record_ids):
        errors.append("存在空 record_id。")
    if any(not value for value in candidate_ids):
        errors.append("存在空 candidate_id。")

    empty_source_names = [row.get("record_id", "") for row in records if not row.get("raw_name", "").strip()]
    empty_candidate_names = [row.get("candidate_id", "") for row in candidates if not row.get("name", "").strip()]
    if empty_source_names or empty_candidate_names:
        errors.append(f"名称为空：source={len(empty_source_names)}，candidate={len(empty_candidate_names)}。")

    malformed_codes = []
    for row in records:
        code = row.get("raw_credit_code", "").strip().upper()
        if code and not re.fullmatch(r"[0-9A-HJ-NPQRTUWXY]{18}", code):
            malformed_codes.append((row.get("record_id", ""), code))
    if malformed_codes:
        warnings.append(f"发现 {len(malformed_codes)} 条统一社会信用代码格式异常，示例: {sample(malformed_codes, 5)}")

    missing_addresses = [row for row in candidates if not row.get("address", "").strip()]
    if missing_addresses:
        warnings.append(f"{len(missing_addresses)} 个 candidate 缺少地址；主要来自仅含名称的官方名单或未提供地址的采购表。")

    county_without_city = [row.get("candidate_id", "") for row in candidates if row.get("county") and not row.get("city")]
    if county_without_city:
        warnings.append(f"{len(county_without_city)} 个 candidate 已识别县区但未识别地级市，需后续人工地址标准化。")

    invalid_coordinates = []
    for row in candidates:
        lon = row.get("longitude", "").strip()
        lat = row.get("latitude", "").strip()
        if not lon and not lat:
            continue
        try:
            lon_value, lat_value = float(lon), float(lat)
            if not (-180 <= lon_value <= 180 and -90 <= lat_value <= 90):
                invalid_coordinates.append(row.get("candidate_id", ""))
        except ValueError:
            invalid_coordinates.append(row.get("candidate_id", ""))
    if invalid_coordinates:
        errors.append(f"{len(invalid_coordinates)} 个 candidate 经纬度超出范围或不是数值。")

    bad_node_types = sorted({row.get("node_type", "") for row in candidates if row.get("node_type", "") not in NODE_TYPES})
    bad_evidence = sorted({row.get("evidence_level", "") for row in candidates if row.get("evidence_level", "") not in EVIDENCE_LEVELS})
    if bad_node_types:
        errors.append(f"node_type 存在非标准枚举: {bad_node_types}")
    if bad_evidence:
        errors.append(f"evidence_level 存在非标准枚举: {bad_evidence}")

    inventory_by_id = {row.get("file_id", ""): row for row in inventory}
    missing_source_files = []
    source_file_id_mismatch = []
    for row in records:
        source_path = TASK_ROOT / row.get("source_file", "")
        if not source_path.is_file():
            missing_source_files.append(row.get("record_id", ""))
        inventory_row = inventory_by_id.get(row.get("source_file_id", ""))
        if not inventory_row or inventory_row.get("relative_path") != row.get("source_file"):
            source_file_id_mismatch.append(row.get("record_id", ""))
    if missing_source_files:
        errors.append(f"{len(missing_source_files)} 条 source record 指向不存在的原始文件。")
    if source_file_id_mismatch:
        errors.append(f"{len(source_file_id_mismatch)} 条 source record 的 source_file_id 无法与 inventory 对应。")

    records_by_id = {row.get("record_id", ""): row for row in records}
    trace_missing: list[str] = []
    traced_record_ids: set[str] = set()
    for candidate in candidates:
        linked = [item for item in candidate.get("source_record_ids", "").split(";") if item]
        if not linked or any(item not in records_by_id for item in linked):
            trace_missing.append(candidate.get("candidate_id", ""))
        traced_record_ids.update(linked)
    if trace_missing:
        errors.append(f"{len(trace_missing)} 个 candidate 无法完整追溯到 source record。")
    unlinked_records = sorted(set(record_ids) - traced_record_ids)
    if unlinked_records:
        errors.append(f"{len(unlinked_records)} 条 source record 未进入任何 candidate。")

    code_names: dict[str, set[str]] = defaultdict(set)
    for row in records:
        code = row.get("raw_credit_code", "").strip().upper()
        if code:
            code_names[code].add(normalize_name(row.get("raw_name", "")))
    conflicting_codes = {code: names for code, names in code_names.items() if len(names) > 1}
    if conflicting_codes:
        warnings.append(f"{len(conflicting_codes)} 个信用代码对应多个标准化名称，需核查名称变更、分支机构或抽取误差。")

    parsed_files = [row for row in inventory if row.get("parse_status") == "parsed"]
    failed_files = [row for row in inventory if row.get("parse_status") == "failed"]
    parse_errors = [
        {"file_id": row.get("file_id"), "file_name": row.get("file_name"), "error": row.get("parse_error")}
        for row in failed_files
    ]
    sha_groups: dict[str, list[str]] = defaultdict(list)
    for row in inventory:
        if row.get("sha256"):
            sha_groups[row["sha256"]].append(row.get("relative_path", ""))
    duplicate_raw_file_groups = [
        {"sha256": sha256, "files": sorted(files)}
        for sha256, files in sorted(sha_groups.items())
        if len(files) > 1
    ]
    if duplicate_raw_file_groups:
        warnings.append(f"原始目录仍存在 {len(duplicate_raw_file_groups)} 组 SHA-256 完全相同文件。")
    if failed_files:
        warnings.append(f"{len(failed_files)} 个原始文件解析失败，详见 parse_errors。")
    if duplicate_review:
        warnings.append(f"{len(duplicate_review)} 对疑似重复或组织/设施层级关系需要人工复核。")

    reserve_html_files = [
        row for row in inventory
        if "guangxi_reserve_companies_2024" in row.get("file_name", "").lower()
        and row.get("detected_file_type") == "html"
        and row.get("source_category") == "grain_reserve"
    ]
    reserve_html_ids = {row.get("file_id", "") for row in reserve_html_files}
    reserve_records = [row for row in records if row.get("source_file_id", "") in reserve_html_ids]
    nanning_reserve_records = [row for row in reserve_records if row.get("raw_region", "").endswith("南宁市")]
    liuzhou_reserve_records = [row for row in reserve_records if row.get("raw_region", "").endswith("柳州市")]
    direct_reserve_records = [row for row in reserve_records if "自治区直属" in row.get("raw_region", "")]

    if not reserve_html_files or any(row.get("parse_status") != "parsed" for row in reserve_html_files):
        errors.append("guangxi_reserve_companies_2024 HTML 未成功识别并解析。")
    if len(nanning_reserve_records) != 38:
        warnings.append(f"南宁储备名单应为 38 条，实际为 {len(nanning_reserve_records)} 条。")
    if len(liuzhou_reserve_records) != 16:
        warnings.append(f"柳州储备名单应为 16 条，实际为 {len(liuzhou_reserve_records)} 条。")

    candidate_names = {row.get("name", ""): row for row in candidates}
    expected_sites = [
        "南宁市储备粮管理有限责任公司五象粮库",
        "南宁市储备粮管理有限责任公司沙井粮库",
        "南宁市邕宁区粮食储备库",
        "横州市六景粮食储备中心库",
        "柳州市五里卡粮库有限公司",
        "广西柳州黄村粮食储备库有限公司",
    ]
    missing_expected_sites = [name for name in expected_sites if name not in candidate_names]
    if missing_expected_sites:
        errors.append("储备名单典型节点缺失: " + "、".join(missing_expected_sites))

    company = candidate_names.get("南宁市储备粮管理有限责任公司")
    wuxiang = candidate_names.get("南宁市储备粮管理有限责任公司五象粮库")
    shajing = candidate_names.get("南宁市储备粮管理有限责任公司沙井粮库")
    if not company or not wuxiang or not shajing or len({row["candidate_id"] for row in (company, wuxiang, shajing) if row}) != 3:
        errors.append("南宁市储备粮管理公司主体与五象、沙井粮库未保持为三个独立 candidate。")
    elif company.get("entity_type") != "organization" or any(row.get("entity_type") != "physical_site" for row in (wuxiang, shajing)):
        errors.append("南宁市储备粮管理公司主体或旗下粮库的 entity_type 不符合组织/设施层级。")

    shanglin = [row for row in candidates if row.get("name", "").startswith("上林县安恒储备粮管理有限公司")]
    if len(shanglin) < 14 or len({row.get("candidate_id") for row in shanglin}) != len(shanglin):
        errors.append(f"上林县安恒主体及分公司疑似被错误合并，当前独立 candidate 为 {len(shanglin)} 个。")

    reserve_record_ids = {row.get("record_id", "") for row in reserve_records}
    untraced_reserve_candidates = []
    for row in candidates:
        linked = {item for item in row.get("source_record_ids", "").split(";") if item}
        if has_source_category(row, "grain_reserve") and not linked.intersection(reserve_record_ids):
            untraced_reserve_candidates.append(row.get("candidate_id", ""))
    if untraced_reserve_candidates:
        errors.append(f"{len(untraced_reserve_candidates)} 个 grain_reserve 来源 candidate 未追溯到新增 HTML。")

    batch_files = [row for row in inventory if row.get("file_name") == "national_emergency_grain_enterprises_batch2.pdf"]
    guigang_files = [row for row in inventory if row.get("file_name") == "guigang_food_suppliers_310.pdf"]
    batch_records = [row for row in records if row.get("source_file_id") in {item.get("file_id") for item in batch_files}]
    correct_national_emergency_file_detected = bool(
        batch_files
        and guigang_files
        and batch_files[0].get("sha256") != guigang_files[0].get("sha256")
        and batch_files[0].get("source_category") == "grain_emergency"
        and batch_files[0].get("parse_status") == "parsed"
        and len(batch_records) == 51
    )
    if not correct_national_emergency_file_detected:
        errors.append("第二批国家级粮食应急保障企业名单未按正确内容识别为 51 条 grain_emergency 记录。")

    nanning_html_candidates = [row for row in candidates if row.get("city") == "南宁市" and has_source_category(row, "grain_reserve")]
    liuzhou_html_candidates = [row for row in candidates if row.get("city") == "柳州市" and has_source_category(row, "grain_reserve")]

    validation_status = "FAIL" if errors else ("WARN" if warnings else "PASS")
    report = {
        "raw_file_count": len(inventory),
        "parsed_file_count": len(parsed_files),
        "failed_file_count": len(failed_files),
        "ancillary_file_count": sum(row.get("parse_status") == "ancillary" for row in inventory),
        "raw_record_count": len(records),
        "candidate_count": len(candidates),
        "primary_nanning_count": sum(row.get("analysis_priority") == "primary" for row in candidates),
        "secondary_liuzhou_count": sum(row.get("analysis_priority") == "secondary" for row in candidates),
        "reserve_guangxi_count": sum(row.get("analysis_priority") == "reserve" for row in candidates),
        "external_count": sum(row.get("analysis_priority") == "external" for row in candidates),
        "node_type_distribution": count_distribution(candidates, "node_type"),
        "evidence_level_distribution": count_distribution(candidates, "evidence_level"),
        "records_with_address": sum(bool(row.get("address", "").strip()) for row in candidates),
        "records_with_credit_code": sum(bool(row.get("credit_code", "").strip()) for row in candidates),
        "records_with_coordinates": sum(bool(row.get("longitude", "").strip()) and bool(row.get("latitude", "").strip()) for row in candidates),
        "duplicate_merged_count": max(0, len(records) - len(candidates)),
        "duplicate_review_count": len(duplicate_review),
        "reserve_html_record_count": len(reserve_records),
        "expected_nanning_reserve_records": 38,
        "nanning_reserve_record_count": len(nanning_reserve_records),
        "expected_liuzhou_reserve_records": 16,
        "liuzhou_reserve_record_count": len(liuzhou_reserve_records),
        "autonomous_region_direct_record_count": len(direct_reserve_records),
        "nanning_grain_depot_count": sum(row.get("node_type") == "grain_depot" for row in nanning_html_candidates),
        "nanning_grain_reserve_count": sum(row.get("node_type") == "grain_reserve" for row in nanning_html_candidates),
        "nanning_military_grain_count": sum(row.get("node_type") == "military_grain_supply" for row in nanning_html_candidates),
        "liuzhou_grain_depot_count": sum(row.get("node_type") == "grain_depot" for row in liuzhou_html_candidates),
        "liuzhou_grain_reserve_count": sum(row.get("node_type") == "grain_reserve" for row in liuzhou_html_candidates),
        "liuzhou_military_grain_count": sum(row.get("node_type") == "military_grain_supply" for row in liuzhou_html_candidates),
        "correct_national_emergency_file_detected": correct_national_emergency_file_detected,
        "duplicate_raw_file_groups": duplicate_raw_file_groups,
        "parse_errors": parse_errors,
        "validation_errors": errors,
        "validation_warnings": warnings,
        "validation_status": validation_status,
    }
    dump_json(PROCESSED_DIR / "processing_report.json", report)
    dump_json(
        PROCESSED_DIR / "_validation_details.json",
        {
            "malformed_credit_codes": malformed_codes,
            "empty_source_names": empty_source_names,
            "empty_candidate_names": empty_candidate_names,
            "county_without_city": county_without_city,
            "invalid_coordinates": invalid_coordinates,
            "missing_source_files": missing_source_files,
            "source_file_id_mismatch": source_file_id_mismatch,
            "candidate_trace_missing": trace_missing,
            "unlinked_source_records": unlinked_records,
            "credit_code_name_conflicts": {key: sorted(value) for key, value in conflicting_codes.items()},
        },
    )
    return report, errors, warnings


def markdown_table_distribution(title: str, distribution: dict[str, int]) -> list[str]:
    lines = [f"## {title}", "", "| 类别 | 数量 |", "|---|---:|"]
    lines.extend(f"| {key} | {value} |" for key, value in distribution.items())
    lines.append("")
    return lines


def generate_markdown_report(report: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    inventory = read_csv(PROCESSED_DIR / "raw_file_inventory.csv")
    candidates = read_csv(PROCESSED_DIR / "supply_node_candidates.csv")
    geocoding = read_csv(PROCESSED_DIR / "geocoding_pending.csv")
    duplicates = read_csv(PROCESSED_DIR / "duplicate_review.csv")

    lines = [
        "# 广西社会应急保供节点原始数据处理报告",
        "",
        "> 本报告只覆盖原始资料识别、抽取、标准化、保守去重与质量验证。未进行最终节点筛选、洪涝路径计算、1 km 网格关联或地图 API 地理编码。",
        "",
        "## 处理结果摘要",
        "",
        f"- data/raw 递归发现：{report['raw_file_count']} 个文件；成功解析 {report['parsed_file_count']} 个主数据文件；网页附属资源 {report['ancillary_file_count']} 个；失败 {report['failed_file_count']} 个。",
        f"- 原始记录层：{report['raw_record_count']} 条 source records。",
        f"- 保守聚合后：{report['candidate_count']} 个 candidates；合并的重复出现记录数为 {report['duplicate_merged_count']}。",
        f"- 南宁市 primary：{report['primary_nanning_count']} 个；柳州市 secondary：{report['secondary_liuzhou_count']} 个。",
        f"- 桂财税〔2024〕8号 HTML：共 {report['reserve_html_record_count']} 条；南宁 {report['nanning_reserve_record_count']}/38，柳州 {report['liuzhou_reserve_record_count']}/16，自治区直属 {report['autonomous_region_direct_record_count']} 条。",
        f"- 南宁新增储备体系分类：grain_depot={report['nanning_grain_depot_count']}、grain_reserve={report['nanning_grain_reserve_count']}、military_grain_supply={report['nanning_military_grain_count']}；柳州分别为 {report['liuzhou_grain_depot_count']}、{report['liuzhou_grain_reserve_count']}、{report['liuzhou_military_grain_count']}。",
        f"- 第二批国家级粮食应急保障企业名单正确识别：{report['correct_national_emergency_file_detected']}；SHA-256 重复原始文件组：{len(report['duplicate_raw_file_groups'])}。",
        f"- 广西其他地区 reserve：{report['reserve_guangxi_count']} 个；广西以外或当前无法确认为广西的 external：{report['external_count']} 个。",
        f"- 地址完整：{report['records_with_address']} 个；信用代码完整：{report['records_with_credit_code']} 个；已有坐标：{report['records_with_coordinates']} 个。",
        f"- 验证结论：**{report['validation_status']}**。",
        "",
        "## 原始文件与抽取情况",
        "",
        "| 文件 | 实际类型 | 来源类别 | 状态 | 抽取记录 | 说明 |",
        "|---|---|---|---|---:|---|",
    ]
    for row in inventory:
        notes = row.get("notes", "").replace("|", "\\|")
        parse_error = row.get("parse_error", "").replace("|", "\\|")
        explanation = "；".join(filter(None, [notes, parse_error]))
        lines.append(
            f"| {row.get('file_name')} | {row.get('detected_file_type')} | {row.get('source_category')} | "
            f"{row.get('parse_status')} | {row.get('records_extracted')} | {explanation} |"
        )
    lines.extend(["", "### 解析失败文件", ""])
    failed = [row for row in inventory if row.get("parse_status") == "failed"]
    if failed:
        lines.extend(f"- `{row.get('file_name')}`：{row.get('parse_error')}" for row in failed)
    else:
        lines.append("无。全部原始文件均成功生成记录；WPS/OLE 文件经只读转换后解析。")
    lines.append("")

    lines.extend(markdown_table_distribution("node_type 分布", report["node_type_distribution"]))
    lines.extend(markdown_table_distribution("evidence_level 分布", report["evidence_level_distribution"]))

    missing_address = [row for row in candidates if not row.get("address", "").strip()]
    missing_by_source = Counter(row.get("source_categories", "") for row in missing_address)
    lines.extend([
        "## 缺地址记录",
        "",
        f"共有 {len(missing_address)} 个 candidate 缺地址。完整清单位于 `geocoding_pending.csv` 中 `geocoding_status=missing_address` 的记录。按来源组合统计如下：",
        "",
        "| 来源类别组合 | 数量 |",
        "|---|---:|",
    ])
    lines.extend(f"| {key or '(blank)'} | {value} |" for key, value in missing_by_source.most_common())
    lines.extend(["", "前 30 条示例：", "", "| candidate_id | 名称 | 所在地解析 |", "|---|---|---|"])
    for row in missing_address[:30]:
        lines.append(f"| {row.get('candidate_id')} | {row.get('name')} | {row.get('province')}/{row.get('city')}/{row.get('county')} |")
    lines.append("")

    geocode_counts = Counter(row.get("geocoding_status", "") for row in geocoding)
    lines.extend([
        "## 地理编码待办",
        "",
        f"共有 {len(geocoding)} 个 candidate 没有完整经纬度：" + "，".join(f"{key}={value}" for key, value in geocode_counts.items()) + "。",
        "本阶段未调用任何地图 API，也未用城市或县区中心点填充伪坐标。",
        "",
        "## 疑似重复与实体层级复核",
        "",
        f"`duplicate_review.csv` 共列出 {len(duplicates)} 对。只有信用代码完全一致且实体层级一致、或标准化名称完全一致且实体层级一致的记录已自动聚合；公司主体与具体粮库、市场、基地、网点保持分离。",
        "",
        "| 名称 1 | 名称 2 | 原因 | 建议 |",
        "|---|---|---|---|",
    ])
    for row in duplicates[:30]:
        lines.append(
            f"| {row.get('name_1')} | {row.get('name_2')} | {row.get('similarity_reason')} | {row.get('recommended_action')} |"
        )
    if len(duplicates) > 30:
        lines.append(f"\n仅展示前 30 对；完整 {len(duplicates)} 对见 `duplicate_review.csv`。")
    lines.append("")

    lines.extend(["## 验证结果", ""])
    if errors:
        lines.append("### 错误")
        lines.append("")
        lines.extend(f"- {item}" for item in errors)
        lines.append("")
    if warnings:
        lines.append("### 警告")
        lines.append("")
        lines.extend(f"- {item}" for item in warnings)
        lines.append("")
    if not errors and not warnings:
        lines.append("全部验证项通过。")
        lines.append("")

    lines.extend([
        "## 当前数据的突出问题",
        "",
        "1. 桂财税〔2024〕8号 HTML 能证明名单内单位的储备体系身份，但名单主体没有提供地址、坐标、仓容、库存或实时可调拨量；章节只能安全支持地级市归属。",
        "2. 自治区直属单位不能仅凭章节定位地级市；只有名称或其他来源能明确定位时才进入 primary/secondary，其余保留为 reserve。",
        "3. 第二批国家级粮食应急保障企业名单提供 51 个企业名称，2025 重新评估名单提供后续证据；仅对来源明确写出的“原名”关系合并，仍普遍缺少具体设施地址和能力细分。",
        "4. 农业农村部定点市场名单提供全国市场名称但没有地址与坐标；广西市场详细落点需后续官方地址补证。",
        "5. 采购供应商地址可能只是登记或联系地址。只有原文明确出现仓库、粮库、配送中心、冷库、厂房等词时才标记相应能力。",
        "6. 网页保存目录中的脚本、样式和图片已进入 inventory 并标记为 ancillary，不作为独立业务数据源抽取。",
        "7. 所有候选均未猜测坐标、仓容、库存或供应量；缺地址记录仍是进入地理编码前最主要的补证工作。",
        "",
        "## 追溯与复现",
        "",
        "每个 candidate 的 `source_record_ids` 指向 `supply_source_records.csv`；每条 source record 的 `source_file_id` 和 `source_file` 再指向 `raw_file_inventory.csv` 与 data/raw 实际文件。验证脚本已检查完整链路。",
        "",
        "复现命令：",
        "",
        "```powershell",
        "python scripts/run_pipeline.py",
        "```",
        "",
        "若在全新环境处理旧式 WPS/OLE 文件，需要安装 WPS Office 并可用 `kwps.Application` COM；否则该文件会明确记为 failed，不会导致其他文件处理中止。",
        "",
        "## 建议的下一步（本阶段不执行）",
        "",
        "当前已具备进入“地址补全与可审计地理编码”阶段的数据基础。建议先为南宁、柳州粮库和储备企业补齐官方地址与设施层级证据，再调用明确授权的地图服务；仍不应开始最终节点筛选。",
        "",
    ])
    (PROCESSED_DIR / "data_processing_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="验证候选节点追溯链、字段枚举、地址、信用代码与坐标。")
    parser.parse_args()
    report, errors, warnings = validate()
    generate_markdown_report(report, errors, warnings)
    print(
        f"validation_status={report['validation_status']} errors={len(errors)} warnings={len(warnings)} "
        f"candidates={report['candidate_count']}"
    )


if __name__ == "__main__":
    main()
