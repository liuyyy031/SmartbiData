# Task_01：南宁市县级行政区划

## 1. 数据集说明

- **任务内容：** 南宁市县级行政区划边界。
- **行政单元数量：** 12个县级行政单元。
- **上游权威成果：** `Task_06` 标准化广西县级行政边界及统一坐标体系。
- **处理方式：** 从广西111个县级行政单元中按 `city_adcode=450100` 筛选，不重新采集、不修复几何、不建立第二套行政区划标准。
- **质量状态：** 运行 `scripts/export_nanning_boundary.py` 后，以 `reports/quality_report.json` 中的 `status=PASS` 为验收标准。

## 2. 为什么复用Task_06

Task_06已经完成广西县级边界的字段标准化、行政代码检查、几何有效性检查和统一分析投影选择。Task_01只负责形成南宁市专题交付，避免同一项目中出现两套边界、两套行政代码或不一致的坐标系。

本目录不重复保存原始行政区划文件。数据来源、处理链路和依赖关系见 `reports/data_lineage.md`。

## 3. 目录结构

```text
Task_01/
├── data/processed/
│   ├── nanning_county_boundary.gpkg
│   ├── nanning_county_boundary.geojson
│   └── nanning_county_boundary_projected.gpkg
├── reports/
│   ├── quality_report.json
│   └── data_lineage.md
├── scripts/
│   └── export_nanning_boundary.py
├── file_manifest.csv
├── SHA256SUMS.txt
└── README.md
```

## 4. 文件使用

- `nanning_county_boundary.gpkg`：EPSG:4490经纬度成果，推荐用于GIS交换、空间关联和后续标准化处理。
- `nanning_county_boundary.geojson`：EPSG:4490交换成果，适合SmartBI、网页展示和通用数据交换。
- `nanning_county_boundary_projected.gpkg`：广西CGCS2000区域Albers等积投影成果，单位为米，用于面积、距离、缓冲区、DEM裁剪和1 km网格分析。
- `quality_report.json`：记录来源、CRS、范围、字段、行政代码、几何质量和跨成果一致性检查。
- `file_manifest.csv` 与 `SHA256SUMS.txt`：交付文件清单和完整性校验值。

## 5. 输出字段

| 字段 | 含义 |
|---|---|
| `province_name` | 省级行政区名称 |
| `province_adcode` | 省级六位行政代码 |
| `city_name` | 地级市名称 |
| `city_adcode` | 地级市六位行政代码，本数据集固定为450100 |
| `county_name` | 县级行政单元名称 |
| `county_adcode` | 县级六位行政代码，推荐作为关联键 |
| `name` | 上游原始名称字段 |
| `adcode` | 从上游 `gb` 字段提取的县级行政代码 |
| `gb` | 上游保留字段 |
| `geometry` | 县级行政区面几何 |

行政关联必须优先使用 `county_adcode` 或 `adcode`，不要仅按中文名称连接。

## 6. 坐标系使用规则

- EPSG:4490成果的单位是度，不能直接计算米制距离、面积或缓冲区。
- 米制分析必须使用 `nanning_county_boundary_projected.gpkg`，其完整坐标系定义来自 `Task_06/config/spatial_crs.json`。
- 不要把米制成果擅自替换为WGS84/UTM 49N，也不要仅凭投影名称手工重建坐标系。

## 7. 复现方法

在仓库根目录执行：

```powershell
conda activate smartbi-gis
python Task_01/scripts/export_nanning_boundary.py
```

脚本只读取Task_06，并覆盖本目录中同名的派生成果、质量报告和校验清单，不修改Task_06或外部原始数据。

## 8. 适用范围与限制

- 本数据用于挑战杯洪涝应急辅助决策项目中的行政归属、裁剪、汇总和制图。
- 行政边界具有时间版本属性；如Task_06更新，必须重新运行本任务并重新检查12个行政代码。
- 本数据不表示街道、乡镇或村级边界，也不包含人口、经济、灾情或应急资源属性。
- 本任务只负责数据交付，不对行政区划法律效力作额外声明。
