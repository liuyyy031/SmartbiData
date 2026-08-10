from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


TASK_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = TASK_ROOT / "data" / "raw"
PROCESSED_DIR = TASK_ROOT / "data" / "processed"
WORK_DIR = PROCESSED_DIR / "_work"

SOURCE_RECORD_FIELDS = [
    "record_id",
    "source_file",
    "source_file_id",
    "source_category",
    "source_page",
    "source_table",
    "source_row",
    "source_title",
    "source_date",
    "raw_name",
    "raw_parent_organization",
    "raw_address",
    "raw_region",
    "raw_service_region",
    "raw_category",
    "raw_description",
    "raw_credit_code",
    "raw_capacity",
    "raw_capacity_unit",
    "raw_text",
    "parse_confidence",
    "parse_notes",
]

NORMALIZED_RECORD_FIELDS = SOURCE_RECORD_FIELDS + [
    "normalized_name",
    "canonical_name",
    "name_aliases",
    "normalized_address",
    "province",
    "city",
    "county",
    "service_region",
    "entity_type",
    "node_type",
    "node_subtype",
    "recognition_level",
    "grain",
    "oil",
    "processed_food",
    "fresh_food",
    "meat",
    "vegetable",
    "fruit",
    "aquatic_product",
    "dairy",
    "daily_goods",
    "storage_capability",
    "processing_capability",
    "distribution_capability",
    "retail_capability",
    "cold_chain_capability",
    "government_emergency_recognition",
    "government_reserve_related",
    "government_procurement_supplier",
    "evidence_level",
    "verified",
    "analysis_priority",
    "normalization_notes",
]

CANDIDATE_FIELDS = [
    "candidate_id",
    "name",
    "normalized_name",
    "raw_names",
    "province",
    "city",
    "county",
    "address",
    "service_region",
    "analysis_priority",
    "credit_code",
    "entity_type",
    "parent_entity_name",
    "parent_candidate_id",
    "site_relation",
    "node_type",
    "node_subtype",
    "recognition_level",
    "grain",
    "oil",
    "processed_food",
    "fresh_food",
    "meat",
    "vegetable",
    "fruit",
    "aquatic_product",
    "dairy",
    "daily_goods",
    "storage_capability",
    "processing_capability",
    "distribution_capability",
    "retail_capability",
    "cold_chain_capability",
    "storage_capacity",
    "processing_capacity",
    "distribution_capacity",
    "capacity_value",
    "capacity_unit",
    "government_emergency_recognition",
    "government_reserve_related",
    "government_procurement_supplier",
    "longitude",
    "latitude",
    "coordinate_source",
    "longitude_raw",
    "latitude_raw",
    "coordinate_system_raw",
    "geocoding_status",
    "geocoding_confidence",
    "spatial_ready",
    "address_source",
    "address_evidence_id",
    "address_evidence_level",
    "address_precision",
    "address_confidence",
    "address_evidence_source_url",
    "address_evidence_source_note",
    "physical_site_confirmed",
    "storage_confirmed",
    "previous_location",
    "location_update_reason",
    "source_count",
    "source_categories",
    "source_files",
    "source_record_ids",
    "evidence_level",
    "verified",
    "notes",
]

NODE_TYPES = {
    "emergency_support_center",
    "emergency_storage_transport",
    "emergency_processing",
    "emergency_distribution_center",
    "emergency_supply_outlet",
    "grain_reserve",
    "grain_depot",
    "military_grain_supply",
    "cold_chain_distribution_center",
    "agricultural_wholesale_market",
    "basket_supply_base",
    "government_procurement_supplier",
    "other",
}

EVIDENCE_LEVELS = {"A", "B", "C", "D"}
ENTITY_TYPES = {"organization", "physical_site", "market", "base", "outlet", "unknown"}
BOOL_FIELDS = [
    "grain",
    "oil",
    "processed_food",
    "fresh_food",
    "meat",
    "vegetable",
    "fruit",
    "aquatic_product",
    "dairy",
    "daily_goods",
    "storage_capability",
    "processing_capability",
    "distribution_capability",
    "retail_capability",
    "cold_chain_capability",
    "government_emergency_recognition",
    "government_reserve_related",
    "government_procurement_supplier",
]

GUANGXI_CITIES = [
    "南宁市", "柳州市", "桂林市", "梧州市", "北海市", "防城港市", "钦州市",
    "贵港市", "玉林市", "百色市", "贺州市", "河池市", "来宾市", "崇左市",
]

GUANGXI_COUNTIES = [
    "青秀区", "兴宁区", "江南区", "西乡塘区", "良庆区", "邕宁区", "武鸣区",
    "隆安县", "马山县", "上林县", "宾阳县", "横州市", "城中区", "鱼峰区",
    "柳南区", "柳北区", "柳江区", "柳城县", "鹿寨县", "融安县", "融水苗族自治县",
    "三江侗族自治县", "柳江县", "海城区", "银海区", "铁山港区", "合浦县", "港北区",
    "港南区", "覃塘区", "平南县", "桂平市", "右江区", "田阳区", "田东县",
    "平果市", "德保县", "靖西市", "那坡县", "凌云县", "乐业县", "田林县",
    "西林县", "隆林各族自治县", "恭城瑶族自治县", "灵山县", "象山区", "叠彩区",
    "秀峰区", "七星区", "雁山区", "临桂区", "全州县", "兴安县", "永福县",
    "灌阳县", "龙胜各族自治县", "资源县", "平乐县", "荔浦市", "金城江区",
    "宜州区", "罗城仫佬族自治县", "环江毛南族自治县", "南丹县", "天峨县",
    "凤山县", "东兰县", "巴马瑶族自治县", "都安瑶族自治县", "大化瑶族自治县",
]

COUNTY_TO_CITY = {
    **{item: "南宁市" for item in ["青秀区", "兴宁区", "江南区", "西乡塘区", "良庆区", "邕宁区", "武鸣区", "隆安县", "马山县", "上林县", "宾阳县", "横州市"]},
    **{item: "柳州市" for item in ["城中区", "鱼峰区", "柳南区", "柳北区", "柳江区", "柳城县", "鹿寨县", "融安县", "融水苗族自治县", "三江侗族自治县", "柳江县"]},
    **{item: "北海市" for item in ["海城区", "银海区", "铁山港区", "合浦县"]},
    **{item: "贵港市" for item in ["港北区", "港南区", "覃塘区", "平南县", "桂平市"]},
    **{item: "百色市" for item in ["右江区", "田阳区", "田东县", "平果市", "德保县", "靖西市", "那坡县", "凌云县", "乐业县", "田林县", "西林县", "隆林各族自治县"]},
    **{item: "桂林市" for item in ["恭城瑶族自治县", "象山区", "叠彩区", "秀峰区", "七星区", "雁山区", "临桂区", "全州县", "兴安县", "永福县", "灌阳县", "龙胜各族自治县", "资源县", "平乐县", "荔浦市"]},
    "灵山县": "钦州市",
}

PROVINCE_ALIASES = [
    "北京市", "天津市", "上海市", "重庆市", "河北省", "山西省", "辽宁省", "吉林省",
    "黑龙江省", "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省", "河南省",
    "湖北省", "湖南省", "广东省", "海南省", "四川省", "贵州省", "云南省", "陕西省",
    "甘肃省", "青海省", "台湾省", "内蒙古自治区", "广西壮族自治区", "西藏自治区",
    "宁夏回族自治区", "新疆维吾尔自治区", "香港特别行政区", "澳门特别行政区",
]


def ensure_dirs() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"[\u200b\ufeff]", "", text)
    text = re.sub(r"\s+", "", text)
    return text.strip()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\u200b\ufeff]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_name(value: Any) -> str:
    text = clean_cell(value)
    text = text.replace("【", "(").replace("】", ")")
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", "", text)
    return text


def parse_name_identity(value: Any) -> tuple[str, list[str]]:
    """Return the current/canonical name and only aliases explicitly stated by the source."""
    text = normalize_name(value)
    match = re.match(r"^(.+?)\((?:原名|原)\s*[:：]\s*(.+)\)$", text)
    if not match:
        return text, []
    canonical = match.group(1).strip()
    alias_text = match.group(2).strip()
    aliases = [item.strip() for item in re.split(r"[;；、]", alias_text) if item.strip()]
    return canonical, aliases


def normalize_address(value: Any) -> str:
    text = clean_cell(value)
    text = text.replace("【", "(").replace("】", ")")
    text = text.replace("（", "(").replace("）", ")")
    return text


def clean_credit_code(value: Any) -> str:
    text = clean_cell(value).upper()
    return re.sub(r"[^0-9A-Z]", "", text)


def stable_id(prefix: str, *parts: Any, length: int = 16) -> str:
    material = "\x1f".join(str(p) for p in parts)
    return f"{prefix}_{hashlib.sha1(material.encode('utf-8')).hexdigest()[:length]}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: serialize_value(row.get(key, "")) for key in fieldnames})


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def serialize_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return ";".join(str(v) for v in value if str(v))
    return value


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def unique_join(values: Iterable[Any], sep: str = ";") -> str:
    seen: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text not in seen:
            seen.append(text)
    return sep.join(seen)


def detect_file_type(path: Path) -> str:
    head = path.read_bytes()[:16]
    ext = path.suffix.lower()
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"PK\x03\x04") and ext == ".docx":
        return "docx_ooxml"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        if ext in {".doc", ".docx", ".wps"}:
            return "wps_ole_compound"
        return "ole_compound"
    if ext in {".csv", ".tsv"}:
        return ext.lstrip("_").lstrip(".")
    if ext in {".css"}:
        return "css"
    if ext in {".js"} or ".js." in path.name.lower():
        return "javascript"
    if ext in {".xlsx", ".xls", ".json", ".html", ".htm", ".txt", ".doc", ".wps"}:
        return ext.lstrip(".")
    if head.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        return "html"
    return "unknown"


def classify_source(path: Path, detected_type: str, sample_text: str = "") -> tuple[str, str]:
    name = path.name.lower()
    text = clean_text(sample_text)
    notes = ""
    if (
        "广西储备商品管理公司及其直属库名单" in text
        or "桂财税〔2024〕8号" in text
        or "reserve_companies_2024" in name
    ):
        return "grain_reserve", notes
    if "农业农村部定点市场名单" in text or "wholesale_market" in name:
        return "wholesale_market", notes
    procurement_content = (
        "中标供应商统一社会信用代码" in text
        or "入围供应商名称" in text
        or ("报价" in text and "社会" in text and "信用" in text)
    )
    if procurement_content or "food_suppliers" in name or "pingguo_" in name:
        if "national_emergency_grain" in name:
            notes = "文件名指向粮食应急企业，但实际内容为政府采购供应商表，以内容分类。"
        return "government_procurement", notes
    if "粮食应急保障企业" in text or "emergency_grain" in name:
        return "grain_emergency", notes
    if re.search(r"储备粮|粮库|储备库", text + name):
        return "grain_storage", notes
    if re.search(r"冷链|冷库", text + name):
        return "cold_chain", notes
    if re.search(r"菜篮子|稳产保供基地", text + name):
        return "basket_supply_base", notes
    return "unknown", notes


def parse_region(address: str, name: str = "", raw_region: str = "") -> tuple[str, str, str]:
    text = normalize_address(" ".join([raw_region or "", address or "", name or ""]))
    province = ""
    city = ""
    county = ""

    if "广西" in text or any(item in text for item in GUANGXI_CITIES):
        province = "广西壮族自治区"
    else:
        for item in PROVINCE_ALIASES:
            short = item.replace("壮族自治区", "").replace("回族自治区", "").replace("维吾尔自治区", "")
            short = short.replace("自治区", "").replace("特别行政区", "").replace("省", "").replace("市", "")
            if item in text or (len(short) >= 2 and short in text):
                province = item
                break

    for item in GUANGXI_CITIES:
        if item in text:
            city = item
            province = "广西壮族自治区"
            break
    if not city and province == "广西壮族自治区":
        for item in GUANGXI_CITIES:
            short = item[:-1]
            if len(short) >= 2 and short in text:
                city = item
                break
    for item in GUANGXI_COUNTIES:
        if item in text:
            county = item
            break

    # 自治区直属名单中的少数单位只在名称里写常用地名，不写完整县市名。
    # 仅收录行政归属明确且与本轮官方名称直接对应的安全别名。
    locality_aliases = {
        "五象": ("南宁市", ""),
        "黎塘": ("南宁市", "宾阳县"),
        "融安": ("柳州市", "融安县"),
        "田东": ("百色市", "田东县"),
    }
    if province == "广西壮族自治区" and not city:
        for alias, (alias_city, alias_county) in locality_aliases.items():
            if alias in text:
                city = alias_city
                county = county or alias_county
                break

    if county in COUNTY_TO_CITY:
        province = "广西壮族自治区"
        if not city:
            city = COUNTY_TO_CITY[county]
    normalized_entity_name = normalize_name(name)
    if normalized_entity_name.startswith("平果"):
        province = "广西壮族自治区"
        city = city or "百色市"
        county = county or "平果市"
    elif normalized_entity_name.startswith("百色"):
        province = "广西壮族自治区"
        city = city or "百色市"
    if province in {"北京市", "天津市", "上海市", "重庆市"} and not city:
        city = province

    return province, city, county


def analysis_priority(province: str, city: str) -> str:
    if city == "南宁市":
        return "primary"
    if city == "柳州市":
        return "secondary"
    if province == "广西壮族自治区":
        return "reserve"
    return "external"


def infer_entity_type(name: str, source_category: str) -> str:
    text = normalize_name(name)
    if source_category == "wholesale_market" or "批发市场" in text or "交易市场" in text:
        return "market"
    if "稳产保供基地" in text or text.endswith("基地"):
        return "base"
    if re.search(r"供应网点|门店|超市|便利店", text):
        return "outlet"
    if re.search(r"粮食储备库|储备粮库|粮库|储备库|直属库|中心库|库区", text):
        return "physical_site"
    if re.search(r"公司|集团|合作社|商行|经营部|厂$|中心$|研究院|邮政", text):
        return "organization"
    return "unknown"


def classify_node_type(name: str, raw_text: str, source_category: str) -> tuple[str, str, str]:
    text = normalize_name(name) + clean_cell(raw_text)
    if source_category == "wholesale_market":
        return "agricultural_wholesale_market", "农业农村部定点市场", ""
    if source_category == "cold_chain":
        return "cold_chain_distribution_center", "县级农产品冷链集配中心", ""
    if source_category == "basket_supply_base":
        return "basket_supply_base", "菜篮子稳产保供基地", ""
    if source_category == "government_procurement":
        return "government_procurement_supplier", "政府采购入围/中标供应商", "采购供应商身份不等同于实体仓储节点。"
    if source_category == "grain_reserve":
        recognition = "广西储备商品管理公司及其直属库名单（桂财税〔2024〕8号）"
        name_text = normalize_name(name)
        if re.search(r"军粮供应|军粮配送|军供站|军粮仓储|粮油军供", name_text):
            return "military_grain_supply", recognition, ""
        if re.search(r"粮食储备库|储备粮库|粮库|储备库|直属库|中心库|库区", name_text):
            return "grain_depot", recognition, ""
        if re.search(r"储备粮管理|粮食收储|粮油收储|粮食购销|粮油购销|粮食管理所|粮所|粮食储备中心|粮食和物资储备|粮食购储|储备管理", name_text):
            return "grain_reserve", recognition, "名单证明储备体系资格，但企业主体或管理机构名称不等同于具体物理粮库。"
        return "other", recognition, "属于储备商品管理公司及其直属库名单，但名称不足以安全判断为具体粮库或储备管理机构。"
    if source_category in {"grain_emergency", "grain_storage"}:
        if "军粮" in text:
            return "military_grain_supply", "国家级粮食应急保障企业", ""
        if re.search(r"粮食储备库|储备粮库|粮库|储备库|直属库|中心库", text):
            return "grain_depot", "国家级粮食应急保障企业", ""
        if re.search(r"储备粮管理|粮食收储|粮油购销", text):
            return "grain_reserve", "国家级粮食应急保障企业", ""
        if re.search(r"配送中心|配送", text):
            return "emergency_distribution_center", "国家级粮食应急保障企业", ""
        if re.search(r"物流|粮运|储运", text):
            return "emergency_storage_transport", "国家级粮食应急保障企业", ""
        if re.search(r"面粉|米业|油脂|食品|粮油|加工", text):
            return "emergency_processing", "国家级粮食应急保障企业", ""
        return "other", "国家级粮食应急保障企业", "官方名单未给出储运、加工、配送等具体子类，保守归为 other。"
    return "other", "", "来源信息不足，保守归为 other。"


def product_flags(raw_category: str, raw_text: str, source_category: str) -> dict[str, bool]:
    text = clean_cell(f"{raw_category}{raw_text}")
    flags = {
        "grain": bool(re.search(r"粮食|大米|米面|面粉|粮油|米粉|面食", text)),
        "oil": bool(re.search(r"食用油|油脂|粮油|米面油", text)),
        "processed_food": bool(re.search(r"副食品|调味|早餐|米粉|面包|糕点|豆制品|干货|奶制品|饮品|冷冻品|食品", text)),
        "meat": bool(re.search(r"畜肉|禽肉|鲜肉|肉类|肉及", text)),
        "vegetable": bool(re.search(r"蔬菜|时蔬|果蔬", text)),
        "fruit": bool(re.search(r"水果|果蔬", text)),
        "aquatic_product": bool(re.search(r"水产|海鲜", text)),
        "dairy": bool(re.search(r"奶制品|乳制品|牛奶", text)),
        "daily_goods": bool(re.search(r"日用品|日用百货|生活用品", text)),
    }
    if source_category in {"grain_emergency", "grain_reserve", "grain_storage"}:
        flags["grain"] = True
    if source_category == "wholesale_market":
        market_name = normalize_name(raw_text)
        flags["fresh_food"] = True
        if "粮油" in market_name:
            flags["grain"] = True
            flags["oil"] = True
        if re.search(r"水产|海鲜", market_name):
            flags["aquatic_product"] = True
        if re.search(r"果|水果", market_name):
            flags["fruit"] = True
        if re.search(r"菜|蔬菜", market_name):
            flags["vegetable"] = True
        if re.search(r"肉|畜禽|牛羊", market_name):
            flags["meat"] = True
    else:
        flags["fresh_food"] = any(flags[key] for key in ("meat", "vegetable", "fruit", "aquatic_product", "dairy"))
    return flags


def capability_flags(name: str, address: str, raw_text: str, source_category: str) -> dict[str, bool]:
    text = clean_cell(f"{name}{address}" if source_category == "grain_reserve" else f"{name}{address}{raw_text}")
    address_text = clean_cell(address)
    storage = bool(re.search(r"仓库|粮库|储备库|冷库|库房|仓储|直属库|中心库|库区", text))
    processing = bool(re.search(r"加工厂|加工中心|生产车间|厂房|食品厂|米粉厂|面粉|油脂加工", text))
    distribution = bool(re.search(r"配送中心|配送有限公司|食品配送|餐饮配送|物流中心|物流集团|粮运物流", text))
    retail = bool(re.search(r"供应网点|门店|超市|便利店|零售", text))
    cold_chain = bool(re.search(r"冷链中心|冷链物流|冷库", text))
    if source_category == "wholesale_market":
        distribution = True
    # “冷冻品类”只表示供应品类，不能据此推断冷链设施能力。
    if "冷冻品类" in text and not re.search(r"冷链|冷库", address_text + normalize_name(name)):
        cold_chain = False
    return {
        "storage_capability": storage,
        "processing_capability": processing,
        "distribution_capability": distribution,
        "retail_capability": retail,
        "cold_chain_capability": cold_chain,
    }


def infer_evidence_level(source_category: str, name: str, address: str, raw_text: str) -> str:
    text = clean_cell(f"{name}{address}{raw_text}")
    if source_category == "wholesale_market":
        return "A"
    if source_category == "grain_reserve":
        return "A"
    if source_category in {"grain_emergency", "grain_storage"}:
        if re.search(r"粮库|储备库|配送中心|应急保障中心", text):
            return "A"
        return "B"
    if source_category == "government_procurement":
        if re.search(r"仓库|粮库|储备库|配送中心|冷库|厂房|加工厂|物流中心", clean_cell(address)):
            return "B"
        return "C"
    if source_category in {"cold_chain", "basket_supply_base"}:
        return "A"
    return "D"


def select_mode(values: Iterable[str]) -> str:
    cleaned = [clean_text(v) for v in values if clean_text(v)]
    if not cleaned:
        return ""
    counts = Counter(cleaned)
    return sorted(counts, key=lambda item: (-counts[item], -len(item), item))[0]


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
