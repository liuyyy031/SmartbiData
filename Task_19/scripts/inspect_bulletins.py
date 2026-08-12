"""检查Task_19原始公报，并生成按页的南宁洪涝候选索引。
自动提取只用于缩小人工复核范围，不直接判定历史事件。
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import geopandas as gpd


EXPECTED_PAGES = {
    2016: 47,
    2017: 50,
    2018: 39,
    2019: 40,
    2020: 41,
    2021: 46,
    2022: 48,
    2023: 52,
}
EXPECTED_RAW_FILES = {
    "2016年广西水旱灾害公报.pdf": (38260241, "3a92739690880cd1b6e58cb86aed497e90b08630fd790453db4548f909af0eb2"),
    "2017年广西水旱灾害公报.pdf": (20209418, "dfc5abadf9ba353343a732c7aef9ea720982959d8ca09dabf9893805cb272247"),
    "2018年广西水旱灾害公报.pdf": (5417628, "f2b7674212fbbc9f3246a32844af6e97737da9b750d52e8b07182a21f0287bf3"),
    "2019年广西水旱灾害公报.pdf": (7669993, "534a0adadbbace47c67c657983e7b7fad1ab852e36ef11d65f94e75fd98fb5b0"),
    "2020年广西水旱灾害公报.pdf": (4080574, "04da8cb5e782ea610c26a840bb4c5b5d290eec3770fa5e58bbca135cbda9e66b"),
    "2021年广西水旱灾害公报.pdf": (1290029, "bdc154d7223c6eddde98d3b6541450a905f05f58d2b2f4e54aa1ccebe519833c"),
    "2022年广西水旱灾害公报.pdf": (2784580, "08eaa928e726a4c03893085c78d3ffcabb332ab038e7cba1d184f6ca04e8b411"),
    "2022年广西水旱灾害公报.wps": (3879424, "52b32b10149bc794018b576299e2066139f38971c8ef81994853865e09a6490a"),
    "2023年广西水旱灾害公报.pdf": (4717234, "ad0621399d76c42f145334486eb5671c181447676cd8e454df7ad2f3f07337cf"),
}
HAZARD_KEYWORDS = (
    "洪涝", "洪水", "暴雨", "山洪", "内涝", "受灾", "台风",
    "强降雨", "超警", "死亡", "转移", "损失", "淹没",
)


class BulletinInspectionError(RuntimeError):
    """Task_19原始公报检查失败。"""


def sha256_file(path: Path) -> str:
    """以分块方式计算文件SHA256。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_executable(name: str) -> str:
    """优先查找Windows原生exe，避免命中无效包装脚本。"""
    for candidate in (f"{name}.exe", name):
        located = shutil.which(candidate)
        if located and Path(located).suffix.lower() != ".cmd":
            return located
    raise BulletinInspectionError(f"未找到可用的{name}可执行文件")


def run_tool(arguments: list[str]) -> str:
    """以参数列表执行PDF工具，不通过shell拼接。"""
    completed = subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    return completed.stdout


def pdf_metadata(pdfinfo: str, path: Path) -> dict[str, Any]:
    """读取PDF页数和加密状态。"""
    output = run_tool([pdfinfo, str(path)])
    metadata: dict[str, str] = {}
    for line in output.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
    if "Pages" not in metadata:
        raise BulletinInspectionError(f"{path.name}缺少PDF页数信息")
    return {
        "pages": int(metadata["Pages"]),
        "encrypted": metadata.get("Encrypted", "unknown"),
    }


def extract_pages(pdftotext: str, path: Path, expected_pages: int) -> list[str]:
    """一次提取PDF文本并按物理页拆分。"""
    output = run_tool([pdftotext, "-enc", "UTF-8", "-layout", str(path), "-"])
    pages = output.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    if len(pages) != expected_pages:
        raise BulletinInspectionError(
            f"{path.name}文本分页数{len(pages)}与PDF页数{expected_pages}不一致"
        )
    return pages


def compact_text(value: str) -> str:
    """将版面空白压缩为可审核的单行文本。"""
    return re.sub(r"\s+", " ", value).strip()


def evidence_snippet(page_text: str, limit: int = 180) -> str:
    """从首个“南宁”附近取短摘录。"""
    text = compact_text(page_text)
    index = text.find("南宁")
    if index < 0:
        return text[:limit]
    start = max(0, index - limit // 3)
    return text[start:start + limit]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    """以UTF-8 BOM输出SmartBI友好CSV。"""
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    """执行原始公报检查和候选页生成。"""
    repository = Path(__file__).resolve().parents[2]
    task_root = repository / "Task_19"
    raw_root = task_root / "data" / "raw" / "bulletins"
    reports_root = task_root / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)

    actual_names = {path.name for path in raw_root.iterdir() if path.is_file()}
    if actual_names != set(EXPECTED_RAW_FILES):
        missing = sorted(set(EXPECTED_RAW_FILES) - actual_names)
        extra = sorted(actual_names - set(EXPECTED_RAW_FILES))
        raise BulletinInspectionError(f"原始文件集合异常；缺失={missing}，多余={extra}")

    pdfinfo = find_executable("pdfinfo")
    pdftotext = find_executable("pdftotext")
    inventory: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    total_pages = 0
    total_text_characters = 0

    for name in sorted(EXPECTED_RAW_FILES):
        path = raw_root / name
        expected_size, expected_hash = EXPECTED_RAW_FILES[name]
        size = path.stat().st_size
        digest = sha256_file(path)
        if size != expected_size or digest != expected_hash:
            raise BulletinInspectionError(f"{name}的大小或SHA256与入库记录不一致")

        year = int(name[:4])
        row: dict[str, Any] = {
            "source_year": year,
            "relative_path": path.relative_to(repository).as_posix(),
            "format": path.suffix.lower().lstrip("."),
            "size_bytes": size,
            "sha256": digest,
            "pdf_pages": "",
            "encrypted": "",
            "text_characters": "",
            "nanning_hits": "",
            "candidate_page_count": "",
            "role": "canonical_pdf" if path.suffix.lower() == ".pdf" else "original_wps_provenance",
        }
        if path.suffix.lower() == ".pdf":
            metadata = pdf_metadata(pdfinfo, path)
            if metadata["pages"] != EXPECTED_PAGES[year]:
                raise BulletinInspectionError(
                    f"{name}页数{metadata['pages']}与预期{EXPECTED_PAGES[year]}不一致"
                )
            if not str(metadata["encrypted"]).lower().startswith("no"):
                raise BulletinInspectionError(f"{name}存在加密，无法稳定提取")
            pages = extract_pages(pdftotext, path, metadata["pages"])
            full_text = "".join(pages)
            if len(compact_text(full_text)) < 1000:
                raise BulletinInspectionError(f"{name}文本层过少，需要OCR或人工复核")

            year_candidate_count = 0
            for page_number, page_text in enumerate(pages, start=1):
                page_keywords = [word for word in HAZARD_KEYWORDS if word in page_text]
                if "南宁" not in page_text or not page_keywords:
                    continue
                year_candidate_count += 1
                candidates.append({
                    "source_year": year,
                    "source_file": path.relative_to(repository).as_posix(),
                    "pdf_page": page_number,
                    "nanning_hit_count": page_text.count("南宁"),
                    "matched_keywords": "|".join(page_keywords),
                    "candidate_excerpt": evidence_snippet(page_text),
                    "review_status": "candidate_not_event",
                })

            row.update({
                "pdf_pages": metadata["pages"],
                "encrypted": metadata["encrypted"],
                "text_characters": len(full_text),
                "nanning_hits": full_text.count("南宁"),
                "candidate_page_count": year_candidate_count,
            })
            total_pages += metadata["pages"]
            total_text_characters += len(full_text)
        inventory.append(row)

    if total_pages != sum(EXPECTED_PAGES.values()):
        raise BulletinInspectionError("八年PDF页数总和异常")

    coverage = []
    for year in range(2016, 2026):
        if year <= 2023:
            status = "available"
            source_file = f"Task_19/data/raw/bulletins/{year}年广西水旱灾害公报.pdf"
            count_policy = "derive_from_confirmed_events"
            note = "可用水旱灾害公报"
        elif year == 2024:
            status = "excluded_wrong_bulletin_type"
            source_file = ""
            count_policy = "null"
            note = "现有文件是水资源公报，不代替水旱灾害公报"
        else:
            status = "missing"
            source_file = ""
            count_policy = "null"
            note = "未入库该年水旱灾害公报"
        coverage.append({
            "year": year,
            "source_coverage_status": status,
            "canonical_source_file": source_file,
            "event_count_policy": count_policy,
            "note": note,
        })

    county_path = repository / "Task_06" / "data" / "boundary" / "processed" / "gx_county_boundary_projected.gpkg"
    counties = gpd.read_file(county_path)
    counties["city_adcode"] = counties["city_adcode"].astype(str)
    nanning_geometry = counties.loc[counties["city_adcode"] == "450100", "geometry"].union_all()
    neighbors = counties.loc[counties["city_adcode"] != "450100"].copy()
    neighbors = neighbors.loc[neighbors.geometry.distance(nanning_geometry) <= 100].copy()
    neighbors = neighbors.sort_values(["city_adcode", "county_adcode"])
    neighboring_rows = [
        {
            "city_name": row.city_name,
            "city_adcode": str(row.city_adcode),
            "county_name": row.county_name,
            "county_adcode": str(row.county_adcode),
            "adjacency_type": "shares_boundary_with_nanning",
            "derivation_source": county_path.relative_to(repository).as_posix(),
        }
        for row in neighbors.itertuples()
    ]
    expected_neighbor_cities = {
        "防城港市", "钦州市", "贵港市", "百色市", "河池市", "来宾市", "崇左市",
    }
    if {row["city_name"] for row in neighboring_rows} != expected_neighbor_cities:
        raise BulletinInspectionError("南宁相邻设区市集合与预期不一致")

    write_csv(
        reports_root / "source_inventory.csv",
        inventory,
        [
            "source_year", "relative_path", "format", "size_bytes", "sha256",
            "pdf_pages", "encrypted", "text_characters", "nanning_hits",
            "candidate_page_count", "role",
        ],
    )
    write_csv(
        reports_root / "candidate_pages.csv",
        candidates,
        [
            "source_year", "source_file", "pdf_page", "nanning_hit_count",
            "matched_keywords", "candidate_excerpt", "review_status",
        ],
    )
    write_csv(
        reports_root / "source_coverage.csv",
        coverage,
        [
            "year", "source_coverage_status", "canonical_source_file",
            "event_count_policy", "note",
        ],
    )
    write_csv(
        reports_root / "nanning_neighboring_admins.csv",
        neighboring_rows,
        [
            "city_name", "city_adcode", "county_name", "county_adcode",
            "adjacency_type", "derivation_source",
        ],
    )

    report = {
        "task": "Task_19",
        "raw_file_count": len(inventory),
        "pdf_file_count": len(EXPECTED_PAGES),
        "wps_provenance_file_count": 1,
        "raw_total_size_bytes": sum(row["size_bytes"] for row in inventory),
        "pdf_page_count": total_pages,
        "text_character_count": total_text_characters,
        "candidate_page_count": len(candidates),
        "neighboring_city_count": len(expected_neighbor_cities),
        "neighboring_county_count": len(neighboring_rows),
        "available_years": list(range(2016, 2024)),
        "excluded_or_missing_years": [2024, 2025],
        "event_interpretation": "候选页不等于确认事件，必须人工复核",
        "status": "PASS",
    }
    (reports_root / "source_validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Task_19源检查完成：{len(inventory)}个原始文件，"
        f"{total_pages}页PDF，{len(candidates)}个候选页，状态PASS。"
    )


if __name__ == "__main__":
    main()
