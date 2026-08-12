#!/usr/bin/env python3
"""构建南宁市历史洪涝事件、证据、行政区关联和频次成果。"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unicodedata
from collections import Counter
from pathlib import Path

import geopandas as gpd
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "Task_19"
CATALOG = TASK / "config" / "nanning_flood_event_catalog.json"
INVENTORY = TASK / "reports" / "source_inventory.csv"
BOUNDARY = ROOT / "Task_01" / "data" / "processed" / "nanning_county_boundary.gpkg"
OUT = TASK / "data" / "processed"
REPORTS = TASK / "reports"

DATE_PRECISIONS = {"day", "range", "month", "approximate"}
HAZARDS = {"flood", "rainstorm_flood", "flash_flood", "waterlogging", "typhoon_flood", "mixed"}
RELEVANCES = {"direct_affected", "meteorological_influence", "hydrologic_influence", "nearby_context"}
ADMIN_LEVELS = {"city", "county", "township"}
RELATION_TYPES = {"affected", "monitoring_location", "meteorological_influence", "hydrologic_influence", "nearby_context"}
SCOPE_LEVELS = {"nanning_city", "nanning_county", "multi_city", "guangxi", "other"}
UNITS = {"person", "hectare", "room", "CNY", "site", "kilometer", "millimeter"}


def compact(value: str) -> str:
    """统一全角字符并去除空白，供证据锚点核验。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def locate_pdftotext() -> str:
    executable = shutil.which("pdftotext.exe") or shutil.which("pdftotext")
    if not executable:
        raise RuntimeError("未找到pdftotext，无法核验公报证据页。")
    return executable


def extract_page(pdf: Path, page: int, executable: str, cache: dict[str, list[str]]) -> str:
    """一次提取整份公报并按换页符缓存，避免Windows临时输出路径兼容问题。"""
    if pdf.name not in cache:
        completed = subprocess.run(
            [executable, "-enc", "UTF-8", "-layout", str(pdf), "-"],
            check=False,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"公报文本提取失败：{pdf.name}")
        pages = completed.stdout.decode("utf-8", errors="replace").split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        cache[pdf.name] = pages
    pages = cache[pdf.name]
    if page < 1 or page > len(pages):
        raise RuntimeError(f"证据页提取失败：{pdf.name}第{page}页")
    return pages[page - 1]


def validate_and_flatten() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    inventory = pd.read_csv(INVENTORY, dtype={"source_year": "int64"})
    pdf_inventory = inventory[inventory["format"].str.lower() == "pdf"].set_index("source_year")
    boundary = gpd.read_file(BOUNDARY)
    county_lookup = dict(zip(boundary["county_adcode"].astype(str), boundary["county_name"]))
    events, evidence_rows, admin_rows, impact_rows = [], [], [], []
    event_ids: set[str] = set()
    evidence_ids: set[str] = set()
    page_cache: dict[str, list[str]] = {}
    pdftotext = locate_pdftotext()

    for event in catalog["events"]:
        event_id = event["event_id"]
        if not re.fullmatch(r"NNFL_\d{4}_\d{3}", event_id) or event_id in event_ids:
            raise ValueError(f"事件编号无效或重复：{event_id}")
        event_ids.add(event_id)
        source_year = int(event["source_year"])
        if source_year != int(event_id[5:9]) or source_year != int(event["start_date"][:4]):
            raise ValueError(f"事件年份不一致：{event_id}")
        if event["date_precision"] not in DATE_PRECISIONS or event["hazard_type"] not in HAZARDS:
            raise ValueError(f"事件分类字段无效：{event_id}")
        relevance = event["nanning_relevance"]
        included = bool(event["included_in_nanning_frequency"])
        if relevance not in RELEVANCES or included != (relevance == "direct_affected"):
            raise ValueError(f"南宁相关性与计频标志冲突：{event_id}")
        if event["review_status"] != "confirmed":
            raise ValueError(f"事件尚未人工确认：{event_id}")
        if source_year not in pdf_inventory.index:
            raise ValueError(f"缺少{source_year}年PDF清单记录")
        source_record = pdf_inventory.loc[source_year]
        source_file = ROOT / str(source_record["relative_path"])
        local_evidence: set[str] = set()
        for evidence in event["evidence"]:
            evidence_id = evidence["evidence_id"]
            if evidence_id in evidence_ids:
                raise ValueError(f"证据编号重复：{evidence_id}")
            evidence_ids.add(evidence_id)
            local_evidence.add(evidence_id)
            page = int(evidence["pdf_page"])
            if page < 1 or page > int(source_record["pdf_pages"]):
                raise ValueError(f"证据页超出范围：{evidence_id}")
            page_text = extract_page(source_file, page, pdftotext, page_cache)
            if compact(evidence["anchor_text"]) not in compact(page_text):
                raise ValueError(f"证据锚点未在原文找到：{evidence_id} / {evidence['anchor_text']}")
            evidence_rows.append({
                "evidence_id": evidence_id,
                "event_id": event_id,
                "source_year": source_year,
                "source_file": source_record["relative_path"],
                "source_sha256": source_record["sha256"],
                "pdf_page": page,
                "printed_page": evidence.get("printed_page"),
                "evidence_kind": evidence["evidence_kind"],
                "anchor_text": evidence["anchor_text"],
                "evidence_summary": evidence["evidence_summary"],
            })
        for sequence, admin in enumerate(event.get("admins", []), start=1):
            if admin["evidence_id"] not in local_evidence:
                raise ValueError(f"行政区关联引用了其他事件证据：{event_id}")
            if admin["admin_level"] not in ADMIN_LEVELS or admin["relation_type"] not in RELATION_TYPES:
                raise ValueError(f"行政区关联枚举无效：{event_id}")
            adcode = None if admin.get("adcode") is None else str(admin["adcode"])
            if admin["admin_level"] == "city" and (adcode != "450100" or admin["admin_name"] != "南宁市"):
                raise ValueError(f"市级关联不是南宁市：{event_id}")
            if admin["admin_level"] == "county" and county_lookup.get(adcode) != admin["admin_name"]:
                raise ValueError(f"县区名称或代码不匹配Task_01：{event_id}")
            admin_rows.append({"relation_id": f"ADMIN_{event_id}_{sequence:02d}", "event_id": event_id, **admin})
        for sequence, impact in enumerate(event.get("impacts", []), start=1):
            if impact["evidence_id"] not in local_evidence or float(impact["value"]) < 0:
                raise ValueError(f"影响指标或证据引用无效：{event_id}")
            if impact["unit"] not in UNITS or impact["impact_scope_level"] not in SCOPE_LEVELS:
                raise ValueError(f"影响指标枚举无效：{event_id}")
            if impact["is_nanning_specific"] and impact["impact_scope_level"] not in {"nanning_city", "nanning_county"}:
                raise ValueError(f"南宁专属指标的空间范围错误：{event_id}")
            impact_rows.append({"impact_id": f"IMPACT_{event_id}_{sequence:02d}", "event_id": event_id, **impact})
        events.append({key: event[key] for key in [
            "event_id", "event_name", "start_date", "end_date", "date_precision", "hazard_type",
            "trigger_text", "location_text", "event_summary", "source_year", "nanning_relevance",
            "included_in_nanning_frequency", "review_status"
        ]})

    event_frame = pd.DataFrame(events).sort_values(["start_date", "event_id"])
    expected_order = event_frame.groupby("source_year")["start_date"].apply(list)
    if any(values != sorted(values) for values in expected_order):
        raise ValueError("同年事件未按时间排序")
    return event_frame, pd.DataFrame(evidence_rows), pd.DataFrame(admin_rows), pd.DataFrame(impact_rows)


def build_frequencies(events: pd.DataFrame, admins: pd.DataFrame) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    coverage = pd.read_csv(REPORTS / "source_coverage.csv")
    direct = events[events["included_in_nanning_frequency"]]
    direct_ids = set(direct["event_id"])
    affected_counties = admins[(admins["admin_level"] == "county") & (admins["relation_type"] == "affected") & admins["event_id"].isin(direct_ids)]
    yearly_rows = []
    for year in range(2016, 2026):
        status_row = coverage[coverage["year"] == year]
        status = status_row.iloc[0]["source_coverage_status"] if not status_row.empty else "missing"
        if status == "available":
            yearly_direct = direct[direct["source_year"] == year]
            yearly_context = events[(events["source_year"] == year) & ~events["included_in_nanning_frequency"]]
            county_event_count = affected_counties[affected_counties["event_id"].isin(yearly_direct["event_id"])]["event_id"].nunique()
            yearly_rows.append({
                "year": year, "source_coverage_status": status,
                "confirmed_event_count": len(yearly_direct),
                "direct_affected_event_count": len(yearly_direct),
                "context_event_count": len(yearly_context),
                "county_specific_event_count": county_event_count,
                "city_only_event_count": len(yearly_direct) - county_event_count,
                "count_semantics": "lower_bound_explicit_event_records",
            })
        else:
            yearly_rows.append({
                "year": year, "source_coverage_status": status,
                "confirmed_event_count": pd.NA, "direct_affected_event_count": pd.NA,
                "context_event_count": pd.NA, "county_specific_event_count": pd.NA,
                "city_only_event_count": pd.NA, "count_semantics": "not_observed_not_zero",
            })
    yearly = pd.DataFrame(yearly_rows)

    boundary = gpd.read_file(BOUNDARY).to_crs(4490)
    county_rows = []
    for _, county in boundary.iterrows():
        adcode = str(county["county_adcode"])
        relations = affected_counties[affected_counties["adcode"].astype(str) == adcode]
        event_years = sorted(events[events["event_id"].isin(relations["event_id"])]["source_year"].unique().tolist())
        county_rows.append({
            "county_adcode": adcode,
            "county_name": county["county_name"],
            "explicit_affected_event_count": relations["event_id"].nunique(),
            "source_year_count": len(event_years),
            "first_recorded_year": event_years[0] if event_years else pd.NA,
            "last_recorded_year": event_years[-1] if event_years else pd.NA,
            "frequency_semantics": "lower_bound_explicit_mentions",
            "zero_interpretation": "not_explicitly_named_in_available_bulletins",
            "geometry": county.geometry,
        })
    return yearly, gpd.GeoDataFrame(county_rows, crs=boundary.crs)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    events, evidence, admins, impacts = validate_and_flatten()
    yearly, counties = build_frequencies(events, admins)
    events.to_csv(OUT / "historical_flood_events.csv", index=False, encoding="utf-8-sig")
    evidence.to_csv(OUT / "event_evidence.csv", index=False, encoding="utf-8-sig")
    admins.to_csv(OUT / "event_admin_relations.csv", index=False, encoding="utf-8-sig")
    impacts.to_csv(OUT / "event_impacts.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(OUT / "nanning_flood_frequency_by_year.csv", index=False, encoding="utf-8-sig")
    counties.drop(columns="geometry").to_csv(OUT / "nanning_flood_frequency_by_county.csv", index=False, encoding="utf-8-sig")
    counties.to_file(OUT / "nanning_flood_frequency_by_county.gpkg", layer="county_flood_frequency", driver="GPKG")
    report = {
        "status": "PASS",
        "catalog_version": json.loads(CATALOG.read_text(encoding="utf-8"))["catalog_version"],
        "event_count": len(events),
        "direct_affected_event_count": int(events["included_in_nanning_frequency"].sum()),
        "context_event_count": int((~events["included_in_nanning_frequency"]).sum()),
        "evidence_count": len(evidence), "admin_relation_count": len(admins), "impact_count": len(impacts),
        "nanning_specific_impact_count": int(impacts["is_nanning_specific"].sum()),
        "county_count": len(counties),
        "explicitly_affected_county_count": int((counties["explicit_affected_event_count"] > 0).sum()),
        "yearly_direct_counts": {str(k): int(v) for k, v in Counter(events.loc[events["included_in_nanning_frequency"], "source_year"]).items()},
        "method_notes": [
            "只将明确表述南宁受灾或为主要受灾区域的独立事件计入南宁频次。",
            "气象、水文及邻近地区影响单独标注，不计入南宁直接受灾频次。",
            "多市合计指标不向南宁市或县区下分。",
            "县区零值表示现有公报未明确点名，不表示没有发生洪涝。",
            "2024—2025年因缺少相应水旱灾害公报而保留为空值，不按零次处理。",
        ],
    }
    (REPORTS / "curation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Task_19数据库构建完成：{len(events)}个事件，{len(evidence)}条证据，直接计频{report['direct_affected_event_count']}个。")


if __name__ == "__main__":
    main()
