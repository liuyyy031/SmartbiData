#!/usr/bin/env python3
"""独立验收Task_19成果，并生成质量报告、文件清单和SHA256校验表。"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "Task_19"
PROCESSED = TASK / "data" / "processed"
REPORTS = TASK / "reports"
EXPECTED_YEAR_COUNTS = {2016: 5, 2017: 5, 2018: 6, 2019: 2, 2020: 1, 2021: 4, 2022: 1, 2023: 3}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str, checks: list[dict[str, str]]) -> None:
    status = "PASS" if condition else "FAIL"
    checks.append({"check": message, "status": status})
    if not condition:
        raise AssertionError(message)


def validate() -> dict[str, object]:
    checks: list[dict[str, str]] = []
    events = pd.read_csv(PROCESSED / "historical_flood_events.csv", dtype={"event_id": str})
    evidence = pd.read_csv(PROCESSED / "event_evidence.csv", dtype={"event_id": str, "evidence_id": str})
    admins = pd.read_csv(PROCESSED / "event_admin_relations.csv", dtype={"event_id": str, "adcode": str})
    impacts = pd.read_csv(PROCESSED / "event_impacts.csv", dtype={"event_id": str})
    yearly = pd.read_csv(PROCESSED / "nanning_flood_frequency_by_year.csv")
    counties = pd.read_csv(PROCESSED / "nanning_flood_frequency_by_county.csv", dtype={"county_adcode": str})
    county_map = gpd.read_file(PROCESSED / "nanning_flood_frequency_by_county.gpkg")
    task01 = gpd.read_file(ROOT / "Task_01" / "data" / "processed" / "nanning_county_boundary.gpkg")

    require(len(events) == 30 and events["event_id"].is_unique, "30个事件且event_id唯一", checks)
    require(int(events["included_in_nanning_frequency"].sum()) == 27, "直接受灾计频事件为27个", checks)
    require((events["nanning_relevance"] == "meteorological_influence").sum() == 3, "气象影响背景事件为3个", checks)
    require(((events["nanning_relevance"] == "direct_affected") == events["included_in_nanning_frequency"]).all(), "计频标志与相关性口径一致", checks)
    require(events["review_status"].eq("confirmed").all(), "全部事件已人工确认", checks)
    require(len(evidence) == 31 and evidence["evidence_id"].is_unique, "31条唯一证据", checks)
    require(set(evidence["event_id"]) == set(events["event_id"]), "每个事件均有证据且外键有效", checks)
    require(set(admins["event_id"]).issubset(set(events["event_id"])), "行政区关联外键有效", checks)
    require(set(impacts["event_id"]).issubset(set(events["event_id"])), "影响指标外键有效", checks)
    require((impacts["value"] >= 0).all(), "影响指标均为非负值", checks)
    require(int(impacts["is_nanning_specific"].sum()) == 2, "南宁专属影响指标仅2条", checks)
    require((impacts.loc[impacts["is_nanning_specific"], "impact_scope_level"].isin(["nanning_city", "nanning_county"])).all(), "南宁专属指标空间范围合规", checks)

    observed = events[events["included_in_nanning_frequency"]].groupby("source_year").size().to_dict()
    require(observed == EXPECTED_YEAR_COUNTS, "2016—2023年直接受灾频次符合人工目录", checks)
    require(yearly["year"].tolist() == list(range(2016, 2026)), "年度频次连续覆盖2016—2025年", checks)
    unavailable = yearly[yearly["year"].isin([2024, 2025])]
    require(unavailable["direct_affected_event_count"].isna().all(), "2024—2025年缺失资料保持空值而非零值", checks)
    require(yearly.loc[yearly["year"] == 2020, "context_event_count"].iloc[0] == 3, "2020年3个气象影响事件未混入直接频次", checks)

    require(len(counties) == 12 and len(county_map) == 12, "CSV与GPKG均含南宁12个县区", checks)
    require(set(counties["county_adcode"]) == set(task01["county_adcode"].astype(str)), "县区代码与Task_01完全一致", checks)
    require(county_map.crs is not None and county_map.crs.to_epsg() == 4490, "县区频次GPKG使用EPSG:4490", checks)
    require(county_map.geometry.notna().all() and county_map.geometry.is_valid.all(), "县区频次几何完整有效", checks)
    nonzero = counties[counties["explicit_affected_event_count"] > 0]
    require(len(nonzero) == 1 and nonzero.iloc[0]["county_adcode"] == "450108" and nonzero.iloc[0]["explicit_affected_event_count"] == 1, "仅良庆区有1次明确县区受灾记录", checks)
    require(counties.loc[counties["explicit_affected_event_count"] == 0, "zero_interpretation"].eq("not_explicitly_named_in_available_bulletins").all(), "县区零值不解释为未发生灾害", checks)

    inventory = pd.read_csv(REPORTS / "source_inventory.csv")
    for _, record in inventory.iterrows():
        raw = ROOT / record["relative_path"]
        require(raw.exists() and raw.stat().st_size == int(record["size_bytes"]), f"原始文件大小一致：{raw.name}", checks)
        require(sha256_file(raw) == record["sha256"], f"原始文件SHA256一致：{raw.name}", checks)
    source_hashes = dict(zip(inventory["relative_path"], inventory["sha256"]))
    require(evidence.apply(lambda row: source_hashes.get(row["source_file"]) == row["source_sha256"], axis=1).all(), "证据表来源哈希可追溯", checks)

    return {
        "status": "PASS",
        "check_count": len(checks),
        "checks": checks,
        "summary": {
            "event_count": len(events), "direct_affected_event_count": 27,
            "context_event_count": 3, "evidence_count": len(evidence),
            "admin_relation_count": len(admins), "impact_count": len(impacts),
            "county_count": len(counties), "source_file_count": len(inventory),
        },
        "interpretation_constraints": [
            "结果是公报明确记载的下限，不代表全部历史洪涝事件。",
            "多市合计损失不得解释为南宁市损失。",
            "县区零频次只表示现有公报未明确点名。",
            "周边或气象影响事件不得计入南宁直接受灾频次。",
        ],
    }


def write_inventory() -> None:
    excluded = {"file_manifest.csv", "SHA256SUMS.txt"}
    files = sorted(path for path in TASK.rglob("*") if path.is_file() and path.name not in excluded)
    with (TASK / "file_manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["relative_path", "size_bytes", "sha256"], lineterminator="\n")
        writer.writeheader()
        for path in files:
            writer.writerow({
                "relative_path": path.relative_to(TASK).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    checksum_files = files + [TASK / "file_manifest.csv"]
    lines = [f"{sha256_file(path)}  {path.relative_to(TASK).as_posix()}" for path in checksum_files]
    (TASK / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    report = validate()
    (REPORTS / "quality_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_inventory()
    print(f"Task_19验收完成：{report['check_count']}项检查全部PASS。")


if __name__ == "__main__":
    main()
