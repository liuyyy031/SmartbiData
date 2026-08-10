from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TASK_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = TASK_ROOT / "DELIVERABLE_MANIFEST.json"


CORE_FILES = [
    ("README.md", "team_guide", "团队使用、复现与交付边界说明"),
    ("requirements.txt", "environment", "Python 解析与空间处理依赖"),
    ("广西社会应急保供节点_可用数据资源汇总.md", "source_catalog", "数据资源背景与来源汇总"),
    ("data/processed/raw_file_inventory.csv", "base_data", "55 个原始及网页附属文件清单"),
    ("data/processed/supply_source_records.csv", "base_data", "1566 条可追溯原始记录"),
    ("data/processed/supply_node_candidates.csv", "base_data_augmented", "当前候选节点主表，含人工证据新增 physical_site"),
    ("data/processed/duplicate_review.csv", "review", "保守去重后的疑似重复人工复核表"),
    ("data/processed/processing_report.json", "base_report", "基础 pipeline 机器报告"),
    ("data/processed/data_processing_report.md", "base_report", "基础 pipeline 可读报告"),
    ("data/manual/nanning_grain_physical_sites_address_evidence.csv", "manual_evidence", "13 条南宁粮食 physical_site 地址证据及来源 URL"),
    ("data/processed/nanning_grain_physical_sites.csv", "spatial_input", "13 个物理设施及其定位状态，7 条 spatial_ready"),
    ("data/processed/nanning_grain_geocoding_review.csv", "review", "6 个尚未可靠定位的南宁粮食 physical_site"),
    ("data/processed/nanning_grain_geocoding_report.json", "geocoding_report", "南宁 physical_site 地理编码机器报告"),
    ("data/processed/nanning_grain_geocoding_report.md", "geocoding_report", "南宁 physical_site 地理编码可读报告"),
    ("data/processed/nanning_grain_spatial_nodes.csv", "current_spatial_delivery", "7 个已纠偏并关联 1 km 网格的节点属性表"),
    ("data/processed/nanning_grain_spatial_nodes.geojson", "current_spatial_delivery", "7 个 EPSG:4490 点要素，便于交换和预览"),
    ("data/processed/nanning_grain_spatial_nodes.gpkg", "current_spatial_delivery", "推荐 GIS 交付，图层 grain_supply_nodes"),
    ("data/processed/administrative_mismatch.csv", "spatial_validation", "节点行政区与网格县区关系冲突；当前 0 条"),
    ("data/processed/nanning_grain_spatial_validation.json", "spatial_validation", "空间阶段机器验证及 SPATIAL_DATA_READY"),
    ("data/processed/nanning_grain_spatial_report.md", "spatial_validation", "空间阶段可读报告"),
]


SCRIPT_FILES = [
    ("scripts/pipeline_common.py", "code", "公共字段、路径与读写函数"),
    ("scripts/scan_raw_files.py", "code", "递归扫描原始文件"),
    ("scripts/extract_supply_records.py", "code", "从 PDF、WPS、HTML 等抽取 source records"),
    ("scripts/normalize_supply_records.py", "code", "安全标准化 source records"),
    ("scripts/build_supply_candidates.py", "code", "保守聚合候选节点"),
    ("scripts/validate_supply_data.py", "code", "基础数据验证与报告"),
    ("scripts/run_pipeline.py", "code", "基础 pipeline 入口"),
    ("scripts/geocode_supply_nodes.py", "code", "南宁与柳州首轮可审计地理编码"),
    ("scripts/geocode_core_sites.py", "code", "重点节点历史诊断"),
    ("scripts/process_manual_address_evidence.py", "code", "接入人工地址证据并生成 physical_site"),
    ("scripts/diagnose_door_number_geocoding.py", "code", "门牌级正逆地理编码复核"),
    ("scripts/coordinate_transform.py", "code", "显式 GCJ-02 正反转换"),
    ("scripts/build_nanning_grain_spatial_nodes.py", "code", "EPSG:4490 点输出与 1 km 网格关联"),
    ("scripts/build_delivery_manifest.py", "code", "生成并校验本交付清单"),
    ("scripts/convert_wps_ole_to_docx.ps1", "code", "旧式 WPS/OLE 只读转换辅助脚本"),
]


SUPPORTING_FILES = [
    ("data/processed/geocoding_targets.csv", "broad_geocoding", "南宁与柳州 86 个首轮地理编码目标"),
    ("data/processed/geocoded_supply_nodes.csv", "broad_geocoding", "首轮高德地理编码结果；保留 GCJ-02 原始坐标"),
    ("data/processed/geocoding_review.csv", "broad_geocoding", "首轮地理编码人工复核项"),
    ("data/processed/geocoding_report.json", "historical_report", "首轮 86 个目标的阶段报告，不代表当前 7 节点空间结论"),
    ("data/processed/geocoding_report.md", "historical_report", "首轮地理编码可读报告"),
    ("data/processed/address_evidence_matches.csv", "audit_support", "人工地址证据与 candidate 的匹配关系"),
    ("data/processed/door_number_geocode_candidates.csv", "audit_support", "门牌级候选结果"),
    ("data/processed/door_number_geocode_diagnostic.csv", "audit_support", "门牌级正逆地理编码诊断"),
    ("data/processed/nanning_grain_physical_sites.geojson", "spatial_support", "7 个 spatial_ready 设施点，EPSG:4490"),
    ("data/processed/nanning_grain_physical_sites.gpkg", "spatial_support", "7 个 spatial_ready 设施点，图层 nanning_grain_physical_sites"),
]


REQUIRED_CURRENT = {
    "README.md",
    "requirements.txt",
    "data/processed/raw_file_inventory.csv",
    "data/processed/supply_source_records.csv",
    "data/processed/supply_node_candidates.csv",
    "data/manual/nanning_grain_physical_sites_address_evidence.csv",
    "data/processed/nanning_grain_physical_sites.csv",
    "data/processed/nanning_grain_spatial_nodes.csv",
    "data/processed/nanning_grain_spatial_nodes.geojson",
    "data/processed/nanning_grain_spatial_nodes.gpkg",
    "data/processed/administrative_mismatch.csv",
    "data/processed/nanning_grain_spatial_validation.json",
    "data/processed/nanning_grain_spatial_report.md",
    *(path for path, _, _ in SCRIPT_FILES),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = csv.reader(stream)
        next(rows, None)
        return sum(1 for row in rows if any(cell.strip() for cell in row))


def geojson_feature_count(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    features = payload.get("features", []) if isinstance(payload, dict) else []
    return len(features) if isinstance(features, list) else 0


def gpkg_layers(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        layer_rows = connection.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features' ORDER BY table_name"
        ).fetchall()
        result: dict[str, int] = {}
        for (table_name,) in layer_rows:
            escaped = table_name.replace('"', '""')
            result[table_name] = int(connection.execute(f'SELECT COUNT(*) FROM "{escaped}"').fetchone()[0])
        return result


def describe(relative_path: str, category: str, purpose: str, required: bool) -> dict[str, Any]:
    path = TASK_ROOT / relative_path
    item: dict[str, Any] = {
        "path": relative_path,
        "category": category,
        "purpose": purpose,
        "required_for_current_delivery": required,
        "exists": path.is_file(),
    }
    if not path.is_file():
        return item
    stat = path.stat()
    item.update({
        "size_bytes": stat.st_size,
        "sha256": sha256(path),
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds"),
    })
    suffix = path.suffix.lower()
    if suffix == ".csv":
        item["row_count"] = csv_row_count(path)
    elif suffix in {".geojson", ".json"}:
        try:
            if suffix == ".geojson":
                item["feature_count"] = geojson_feature_count(path)
            else:
                json.loads(path.read_text(encoding="utf-8-sig"))
                item["json_valid"] = True
        except (json.JSONDecodeError, UnicodeDecodeError):
            item["json_valid"] = False
    elif suffix == ".gpkg":
        item["layers"] = gpkg_layers(path)
    return item


def load_json(relative_path: str) -> dict[str, Any]:
    return json.loads((TASK_ROOT / relative_path).read_text(encoding="utf-8-sig"))


def main() -> int:
    entries = [
        describe(path, category, purpose, path in REQUIRED_CURRENT)
        for path, category, purpose in CORE_FILES + SCRIPT_FILES + SUPPORTING_FILES
    ]
    missing_required = [item["path"] for item in entries if item["required_for_current_delivery"] and not item["exists"]]
    processing = load_json("data/processed/processing_report.json")
    nanning_geocoding = load_json("data/processed/nanning_grain_geocoding_report.json")
    spatial = load_json("data/processed/nanning_grain_spatial_validation.json")
    current_candidate_count = csv_row_count(TASK_ROOT / "data/processed/supply_node_candidates.csv")

    payload = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "task": "Task_11 广西社会应急保供节点",
        "delivery_ready": not missing_required and spatial.get("validation_status") == "PASS" and spatial.get("SPATIAL_DATA_READY") is True,
        "stage_status": {
            "base_pipeline": {
                "status": processing.get("validation_status"),
                "base_candidate_count": processing.get("candidate_count"),
                "current_augmented_candidate_count": current_candidate_count,
                "note": "基础 WARN 来自缺地址和疑似重复，并非解析失败；当前主表另含 5 个经人工证据新增的 physical_site。",
            },
            "nanning_physical_site_geocoding": {
                "status": nanning_geocoding.get("validation_status"),
                "physical_site_count": nanning_geocoding.get("physical_site_count"),
                "spatial_ready_count": nanning_geocoding.get("spatial_ready_count"),
                "READY_FOR_CRS": nanning_geocoding.get("READY_FOR_CRS"),
            },
            "nanning_coordinate_and_grid": {
                "status": spatial.get("validation_status"),
                "node_count": spatial.get("spatial_node_count"),
                "grid_matched_count": spatial.get("grid_matched_count"),
                "administrative_mismatch_count": spatial.get("administrative_mismatch_count"),
                "SPATIAL_DATA_READY": spatial.get("SPATIAL_DATA_READY"),
            },
        },
        "required_missing": missing_required,
        "artifacts": entries,
        "excluded_from_normal_delivery": [
            "data/raw/guangxi_reserve_companies_2024_file/：网页附属脚本、样式和图片，保留用于原始网页复现。",
            "data/interim/geocoding_cache/：高德原始响应缓存，不含 API Key；仅审计或离线复跑时交付。",
            "data/processed/_work/：QA 截图、转换副本与开发检查脚本。",
            "scripts/__pycache__/：Python 字节码缓存。",
            "data/processed/_normalized_source_records.csv 与 _validation_details.json：内部中间/诊断文件。",
        ],
        "external_runtime_dependencies": [
            "../Task_05/data/grid/gx_grid_1km.gpkg",
            "../Task_05/data/grid/gx_grid_county_relation.csv",
            "../Task_06/config/spatial_crs.json",
            "../.env 中可选的 AMAP_WEB_KEY（仅网络地理编码；不得进入交付文件）",
        ],
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "delivery_ready": payload["delivery_ready"],
        "artifact_count": len(entries),
        "missing_required_count": len(missing_required),
        "manifest": str(OUTPUT_PATH),
    }, ensure_ascii=False))
    return 0 if payload["delivery_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
