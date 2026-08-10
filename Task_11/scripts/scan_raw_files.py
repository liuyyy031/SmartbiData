from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from pipeline_common import (
    PROCESSED_DIR,
    RAW_DIR,
    TASK_ROOT,
    classify_source,
    detect_file_type,
    ensure_dirs,
    sha256_file,
    stable_id,
    write_csv,
)


INVENTORY_FIELDS = [
    "file_id",
    "file_name",
    "relative_path",
    "extension",
    "file_size_bytes",
    "sha256",
    "modified_time",
    "detected_file_type",
    "parse_status",
    "records_extracted",
    "source_category",
    "parse_error",
    "notes",
]


def sample_pdf_text(path: Path) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            chunks = []
            for page in pdf.pages[:2]:
                chunks.append((page.extract_text() or "")[:4000])
            return "\n".join(chunks)
    except Exception:
        return ""


def sample_html_text(path: Path) -> str:
    try:
        from lxml import html

        document = html.fromstring(path.read_bytes().decode("utf-8"))
        for node in document.xpath("//script|//style|//svg|//nav|//footer|//header|//aside"):
            node.drop_tree()
        return "\n".join(part.strip() for part in document.itertext() if part.strip())[:30000]
    except Exception:
        return ""


def is_saved_page_ancillary(path: Path) -> bool:
    try:
        relative_parts = path.relative_to(RAW_DIR).parts[:-1]
    except ValueError:
        return False
    return any(part.lower().endswith("_file") or part.lower().endswith("_files") for part in relative_parts)


def scan_raw_files() -> list[dict[str, object]]:
    ensure_dirs()
    paths = sorted(path for path in RAW_DIR.rglob("*") if path.is_file())
    rows: list[dict[str, object]] = []
    hash_groups: dict[str, list[str]] = defaultdict(list)

    for path in paths:
        rel = path.relative_to(TASK_ROOT).as_posix()
        digest = sha256_file(path)
        detected = detect_file_type(path)
        ancillary = is_saved_page_ancillary(path)
        if ancillary:
            sample = ""
            category, category_note = "other", "HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。"
        else:
            sample = sample_pdf_text(path) if detected == "pdf" else (sample_html_text(path) if detected == "html" else "")
            category, category_note = classify_source(path, detected, sample)
        stat = path.stat()
        row = {
            "file_id": stable_id("file", rel, digest),
            "file_name": path.name,
            "relative_path": rel,
            "extension": path.suffix.lower(),
            "file_size_bytes": stat.st_size,
            "sha256": digest,
            "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "detected_file_type": detected,
            "parse_status": "ancillary" if ancillary else "pending",
            "records_extracted": 0,
            "source_category": category,
            "parse_error": "",
            "notes": category_note,
        }
        rows.append(row)
        hash_groups[digest].append(path.name)

    for row in rows:
        duplicates = hash_groups[str(row["sha256"])]
        if len(duplicates) > 1:
            duplicate_note = "SHA-256 完全相同的原始文件: " + ", ".join(duplicates)
            row["notes"] = "；".join(filter(None, [str(row["notes"]), duplicate_note]))

    write_csv(PROCESSED_DIR / "raw_file_inventory.csv", rows, INVENTORY_FIELDS)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="递归扫描 data/raw 并生成原始文件清单。")
    parser.parse_args()
    rows = scan_raw_files()
    print(f"scanned_files={len(rows)}")


if __name__ == "__main__":
    main()
