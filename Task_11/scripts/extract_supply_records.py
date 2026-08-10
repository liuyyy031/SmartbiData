from __future__ import annotations

import argparse
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from pipeline_common import (
    PROCESSED_DIR,
    RAW_DIR,
    SOURCE_RECORD_FIELDS,
    TASK_ROOT,
    WORK_DIR,
    clean_cell,
    clean_credit_code,
    clean_text,
    detect_file_type,
    ensure_dirs,
    parse_region,
    read_csv,
    stable_id,
    write_csv,
)
from scan_raw_files import INVENTORY_FIELDS, scan_raw_files


def pdf_source_date(metadata: dict[str, Any] | None) -> str:
    raw = str((metadata or {}).get("CreationDate", ""))
    match = re.search(r"D:(\d{4})(\d{2})(\d{2})", raw)
    if not match:
        return ""
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def region_text(address: str, name: str = "", raw_region: str = "") -> str:
    province, city, county = parse_region(address, name, raw_region)
    return "/".join(item for item in (province, city, county) if item)


def make_record(
    inventory: dict[str, str],
    *,
    page: Any,
    table: Any,
    row: Any,
    title: str,
    date: str,
    name: str,
    parent_organization: str = "",
    address: str = "",
    raw_region: str = "",
    service_region: str = "",
    category: str = "",
    description: str = "",
    credit_code: str = "",
    capacity: str = "",
    capacity_unit: str = "",
    raw_text: str = "",
    confidence: float = 0.95,
    notes: str = "",
) -> dict[str, Any]:
    cleaned_name = clean_text(name).replace("\n", "")
    cleaned_address = clean_text(address).replace("\n", "")
    cleaned_category = clean_text(category).replace("\n", "")
    cleaned_description = clean_text(description)
    cleaned_code = clean_credit_code(credit_code)
    record_id = stable_id(
        "rec",
        inventory["file_id"],
        page,
        table,
        row,
        cleaned_name,
        cleaned_category,
        cleaned_code,
    )
    return {
        "record_id": record_id,
        "source_file": inventory["relative_path"],
        "source_file_id": inventory["file_id"],
        "source_category": inventory["source_category"],
        "source_page": page,
        "source_table": table,
        "source_row": row,
        "source_title": title,
        "source_date": date,
        "raw_name": cleaned_name,
        "raw_parent_organization": clean_text(parent_organization).replace("\n", ""),
        "raw_address": cleaned_address,
        "raw_region": raw_region or region_text(cleaned_address, cleaned_name),
        "raw_service_region": service_region,
        "raw_category": cleaned_category,
        "raw_description": cleaned_description,
        "raw_credit_code": cleaned_code,
        "raw_capacity": clean_text(capacity),
        "raw_capacity_unit": clean_text(capacity_unit),
        "raw_text": clean_text(raw_text),
        "parse_confidence": f"{confidence:.2f}",
        "parse_notes": clean_text(notes),
    }


def parse_beihai_pdf(path: Path, inventory: dict[str, str]) -> list[dict[str, Any]]:
    import pdfplumber

    rows: list[dict[str, Any]] = []
    with pdfplumber.open(str(path)) as pdf:
        date = pdf_source_date(pdf.metadata)
        for page_number, page in enumerate(pdf.pages, start=1):
            for table_number, table in enumerate(page.extract_tables() or [], start=1):
                for row_number, row in enumerate(table, start=1):
                    if len(row) < 5 or not re.fullmatch(r"\d+", clean_cell(row[0])):
                        continue
                    seq, category, name, address, code = row[:5]
                    raw_text = (
                        f"序号: {clean_cell(seq)}；标项名称: {clean_text(category)}；"
                        f"中标供应商名称: {clean_text(name)}；中标供应商地址: {clean_text(address)}；"
                        f"统一社会信用代码: {clean_text(code)}"
                    )
                    rows.append(
                        make_record(
                            inventory,
                            page=page_number,
                            table=table_number,
                            row=row_number,
                            title="北海市批量食品供应商入围名单",
                            date=date,
                            name=name,
                            address=address,
                            service_region="北海市",
                            category=category,
                            credit_code=code,
                            raw_text=raw_text,
                            confidence=0.99,
                            notes="按 PDF 表格行批量抽取；地址视为供应商登记/联系地址，不自动认定为仓储节点。",
                        )
                    )
    return rows


def parse_guigang_pdf(path: Path, inventory: dict[str, str]) -> list[dict[str, Any]]:
    import pdfplumber

    rows: list[dict[str, Any]] = []
    with pdfplumber.open(str(path)) as pdf:
        date = pdf_source_date(pdf.metadata)
        for page_number, page in enumerate(pdf.pages, start=1):
            for table_number, table in enumerate(page.extract_tables() or [], start=1):
                for row_number, row in enumerate(table, start=1):
                    if len(row) < 6 or not re.fullmatch(r"\d+", clean_cell(row[0])):
                        continue
                    seq, category, quote, name, address, code = row[:6]
                    raw_text = (
                        f"序号: {clean_cell(seq)}；标项名称: {clean_text(category)}；"
                        f"报价: {clean_text(quote)}；中标供应商名称: {clean_text(name)}；"
                        f"中标供应商地址: {clean_text(address)}；统一社会信用代码: {clean_text(code)}"
                    )
                    note_parts = ["按 PDF 表格行批量抽取；地址视为供应商登记/联系地址，不自动认定为仓储节点。"]
                    if path.name == "national_emergency_grain_enterprises_batch2.pdf":
                        note_parts.append("该文件内容与 guigang_food_suppliers_310.pdf 完全相同，且与文件名描述不符。")
                    rows.append(
                        make_record(
                            inventory,
                            page=page_number,
                            table=table_number,
                            row=row_number,
                            title="贵港市食品供应商中标名单（310条）",
                            date=date,
                            name=name,
                            address=address,
                            service_region="贵港市",
                            category=category,
                            description=f"报价: {clean_text(quote)}",
                            credit_code=code,
                            raw_text=raw_text,
                            confidence=0.99,
                            notes=" ".join(note_parts),
                        )
                    )
    return rows


def parse_pingguo_pdf(path: Path, inventory: dict[str, str]) -> list[dict[str, Any]]:
    import pdfplumber

    rows: list[dict[str, Any]] = []
    fixed_category = "鲜肉类" if "meat" in path.name else "生鲜时蔬、水果类"
    title = f"平果市公办学校食堂食品框架协议入围供应商（{fixed_category}）"
    with pdfplumber.open(str(path)) as pdf:
        date = pdf_source_date(pdf.metadata)
        for page_number, page in enumerate(pdf.pages, start=1):
            for table_number, table in enumerate(page.extract_tables() or [], start=1):
                for row_number, row in enumerate(table, start=1):
                    if len(row) < 5 or not re.fullmatch(r"\d+", clean_cell(row[0])):
                        continue
                    seq, name, product, specification, quote = row[:5]
                    raw_text = (
                        f"序号: {clean_cell(seq)}；入围供应商名称: {clean_text(name)}；"
                        f"入围产品名称: {clean_text(product)}；规格/服务标准: {clean_text(specification)}；"
                        f"入围单价: {clean_text(quote)}"
                    )
                    rows.append(
                        make_record(
                            inventory,
                            page=page_number,
                            table=table_number,
                            row=row_number,
                            title=title,
                            date=date,
                            name=name,
                            service_region="百色市/平果市",
                            category=fixed_category,
                            description=f"{clean_text(product)}；{clean_text(specification)}；入围单价: {clean_text(quote)}",
                            raw_text=raw_text,
                            confidence=0.97,
                            notes="PDF 表格未提供地址和统一社会信用代码；服务项目所在地为平果市，不能据此推断企业所在地。",
                        )
                    )
    return rows


def parse_wholesale_pdf(path: Path, inventory: dict[str, str]) -> list[dict[str, Any]]:
    import pdfplumber

    rows: list[dict[str, Any]] = []
    current_region = ""
    with pdfplumber.open(str(path)) as pdf:
        date = pdf_source_date(pdf.metadata)
        for page_number, page in enumerate(pdf.pages, start=1):
            for table_number, table in enumerate(page.extract_tables() or [], start=1):
                for row_number, row in enumerate(table, start=1):
                    if len(row) < 2:
                        continue
                    left, right = clean_cell(row[0]), clean_text(row[1]).replace("\n", "")
                    if not re.fullmatch(r"\d+", left):
                        if left and re.fullmatch(r"\d+家", clean_cell(right)):
                            current_region = left
                        continue
                    raw_text = f"序号: {left}；市场名称: {right}；省级分组: {current_region}"
                    rows.append(
                        make_record(
                            inventory,
                            page=page_number,
                            table=table_number,
                            row=row_number,
                            title="农业农村部定点市场名单",
                            date=date,
                            name=right,
                            raw_region=current_region,
                            category="农业农村部定点农产品批发市场",
                            description="农业农村部定点市场",
                            raw_text=raw_text,
                            confidence=0.98,
                            notes="按 PDF 两列表格抽取；原文件未提供详细地址和坐标。",
                        )
                    )
    return rows


def parse_national_emergency_pdf(path: Path, inventory: dict[str, str]) -> list[dict[str, Any]]:
    import pdfplumber

    rows: list[dict[str, Any]] = []
    with pdfplumber.open(str(path)) as pdf:
        date = pdf_source_date(pdf.metadata) or "2022-09-29"
        for page_number, page in enumerate(pdf.pages, start=1):
            for line_number, line in enumerate((page.extract_text() or "").splitlines(), start=1):
                match = re.match(r"^\s*(\d+)[.．、]\s*(.+?)\s*$", line)
                if not match:
                    continue
                seq, name = match.groups()
                raw_text = f"序号: {seq}；企业名称: {name}；名单性质: 第二批国家级粮食应急保障企业名单"
                rows.append(
                    make_record(
                        inventory,
                        page=page_number,
                        table="正文编号名单",
                        row=seq,
                        title="第二批国家级粮食应急保障企业名单",
                        date=date,
                        name=name,
                        raw_region=region_text("", name),
                        service_region="全国",
                        category="国家级粮食应急保障企业",
                        description="2022 年第二批国家级粮食应急保障企业认定名单",
                        raw_text=raw_text,
                        confidence=0.99,
                        notes="按 PDF 文本层中的编号名单逐条抽取；原文件未提供地址和具体功能子类。",
                    )
                )
    return rows


def infer_parent_organization(name: str) -> str:
    normalized = clean_cell(name)
    match = re.match(r"^(.+?(?:有限责任公司|有限公司|管理公司))(.+)$", normalized)
    if not match:
        return ""
    parent, suffix = match.groups()
    if re.search(r"分公司|粮库|储备库|直属库|中心库|库区|管理所", suffix):
        return parent
    return ""


def parse_reserve_html(path: Path, inventory: dict[str, str]) -> list[dict[str, Any]]:
    from lxml import html

    document = html.fromstring(path.read_bytes().decode("utf-8"))
    for node in document.xpath("//script|//style|//svg|//nav|//footer|//header|//aside|//noscript"):
        node.drop_tree()
    containers = document.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' richContent ')]")
    target = next(
        (container for container in containers if "广西储备商品管理公司及其直属库名单" in "".join(container.itertext())),
        None,
    )
    if target is None:
        raise ValueError("HTML 正文中未定位到“广西储备商品管理公司及其直属库名单”")

    paragraph_texts = [clean_text("".join(paragraph.itertext())).replace("\n", "") for paragraph in target.xpath(".//p")]
    rows: list[dict[str, Any]] = []
    started = False
    current_section = ""
    for paragraph_index, paragraph in enumerate(paragraph_texts, start=1):
        compact = clean_cell(paragraph)
        if not compact:
            continue
        if "广西储备商品管理公司及其直属库名单" in compact:
            started = True
            continue
        if not started:
            continue
        if "广西储备肉管理公司" in compact or "广西肉类储备管理公司" in compact:
            break

        section_match = re.match(r"^\([一二三四五六七八九十]+\)(自治区直属|[^()]+市)$", compact)
        if section_match:
            current_section = section_match.group(1)
            continue

        record_match = re.match(r"^(\d+)[.．、](.+)$", compact)
        if not record_match or not current_section:
            continue
        seq, name = record_match.groups()
        raw_region = "广西壮族自治区/自治区直属" if current_section == "自治区直属" else f"广西壮族自治区/{current_section}"
        parent = infer_parent_organization(name)
        raw_text = (
            f"名单: 广西储备商品管理公司及其直属库名单；文号: 桂财税〔2024〕8号；"
            f"章节: {current_section}；序号: {seq}；单位名称: {name}"
        )
        rows.append(
            make_record(
                inventory,
                page="",
                table="广西储备商品管理公司及其直属库名单",
                row=seq,
                title="广西壮族自治区储备商品管理公司及其直属库名单",
                date="2024",
                name=name,
                parent_organization=parent,
                raw_region=raw_region,
                category="储备商品管理公司及其直属库",
                description=f"桂财税〔2024〕8号；章节：{current_section}",
                raw_text=raw_text,
                confidence=0.99,
                notes=f"使用 lxml 从 HTML 正文容器按“行政区标题 + 序号 + 单位名称”结构抽取；原正文段落序号 {paragraph_index}。",
            )
        )
    return rows


def convert_wps_ole(path: Path) -> Path:
    output = WORK_DIR / f"{path.stem}_converted.docx"
    if output.exists() and output.read_bytes()[:2] == b"PK":
        return output
    script = Path(__file__).with_name("convert_wps_ole_to_docx.ps1")
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-SourcePath",
        str(path),
        "-OutputPath",
        str(output),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=90)
    if completed.returncode != 0 or not output.exists():
        raise RuntimeError(f"WPS/OLE 转 DOCX 失败: {completed.stderr.strip() or completed.stdout.strip()}")
    return output


def parse_grain_document(path: Path, inventory: dict[str, str]) -> list[dict[str, Any]]:
    from docx import Document

    detected = detect_file_type(path)
    parse_path = convert_wps_ole(path) if detected == "wps_ole_compound" else path
    document = Document(str(parse_path))
    if not document.tables:
        raise ValueError("文档中未发现可解析表格")
    rows: list[dict[str, Any]] = []
    for table_number, table in enumerate(document.tables, start=1):
        for row_number, row in enumerate(table.rows, start=1):
            cells = [clean_text(cell.text) for cell in row.cells]
            if len(cells) < 2 or not re.fullmatch(r"\d+", clean_cell(cells[0])):
                continue
            seq, name = cells[:2]
            raw_region = region_text("", name)
            raw_text = f"序号: {seq}；企业名称: {name}；名单性质: 通过评估的第二批国家级粮食应急保障企业"
            rows.append(
                make_record(
                    inventory,
                    page="",
                    table=table_number,
                    row=row_number,
                    title="通过评估的第二批国家级粮食应急保障企业名单",
                    date="2025",
                    name=name,
                    raw_region=raw_region,
                    service_region="全国",
                    category="国家级粮食应急保障企业",
                    description="通过重新评估的第二批国家级粮食应急保障企业",
                    raw_text=raw_text,
                    confidence=0.99,
                    notes=f"原文件扩展名为 {path.suffix}，文件签名为 WPS/OLE 复合文档；只读转换为临时标准 DOCX 后抽取。来源年份由文件名推断。",
                )
            )
    return rows


def parse_file(path: Path, inventory: dict[str, str]) -> list[dict[str, Any]]:
    name = path.name
    if name == "beihai_food_suppliers.pdf":
        return parse_beihai_pdf(path, inventory)
    if name == "guigang_food_suppliers_310.pdf":
        return parse_guigang_pdf(path, inventory)
    if name == "national_emergency_grain_enterprises_batch2.pdf" and inventory["source_category"] == "government_procurement":
        return parse_guigang_pdf(path, inventory)
    if inventory["source_category"] == "grain_emergency" and detect_file_type(path) == "pdf":
        return parse_national_emergency_pdf(path, inventory)
    if name in {"pingguo_meat_suppliers.pdf", "pingguo_vegetable_fruit_suppliers.pdf"}:
        return parse_pingguo_pdf(path, inventory)
    if inventory["source_category"] == "wholesale_market" and path.suffix.lower() == ".pdf":
        return parse_wholesale_pdf(path, inventory)
    if inventory["source_category"] == "grain_emergency" and detect_file_type(path) in {"docx_ooxml", "wps_ole_compound"}:
        return parse_grain_document(path, inventory)
    if inventory["source_category"] == "grain_reserve" and detect_file_type(path) == "html":
        return parse_reserve_html(path, inventory)
    raise ValueError(f"暂未实现的文件格式/内容组合: {detect_file_type(path)} / {inventory['source_category']}")


def extract_all() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ensure_dirs()
    inventory_rows = scan_raw_files()
    all_records: list[dict[str, Any]] = []

    for item in inventory_rows:
        inventory = {key: str(value) for key, value in item.items()}
        path = TASK_ROOT / inventory["relative_path"]
        if item.get("parse_status") == "ancillary":
            continue
        try:
            records = parse_file(path, inventory)
            if not records:
                raise ValueError("解析完成但未抽取到任何记录")
            all_records.extend(records)
            item["parse_status"] = "parsed"
            item["records_extracted"] = len(records)
            item["parse_error"] = ""
            content_note = f"成功抽取 {len(records)} 条原始记录。"
            item["notes"] = "；".join(filter(None, [str(item.get("notes", "")), content_note]))
        except Exception as exc:
            item["parse_status"] = "failed"
            item["records_extracted"] = 0
            item["parse_error"] = f"{type(exc).__name__}: {exc}"
            item["notes"] = "；".join(filter(None, [str(item.get("notes", "")), "解析失败，未静默跳过。"] ))

    write_csv(PROCESSED_DIR / "raw_file_inventory.csv", inventory_rows, INVENTORY_FIELDS)
    write_csv(PROCESSED_DIR / "supply_source_records.csv", all_records, SOURCE_RECORD_FIELDS)
    return inventory_rows, all_records


def main() -> None:
    parser = argparse.ArgumentParser(description="从 data/raw 的 PDF/WPS/DOCX 中抽取原始供应记录。")
    parser.parse_args()
    inventory, records = extract_all()
    failed = sum(1 for row in inventory if row["parse_status"] == "failed")
    print(f"files={len(inventory)} failed={failed} raw_records={len(records)}")


if __name__ == "__main__":
    main()
