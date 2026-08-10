# Task_6：广西统一坐标系数据

本目录负责广西县级行政边界标准化、统一米制计算坐标系选择，以及县界向该坐标系的重投影。成果供距离、面积、buffer、空间叠加和同级目录 `Task_5` 的统一 1 km 网格使用。

## 1. 直接使用

团队日常空间分析优先使用：

```text
data/boundary/processed/gx_county_boundary_projected.gpkg
```

该文件包含 111 个县级行政单元，属性字段与标准化边界一致，geometry 有效，坐标单位为 metre。

需要与国内 CGCS2000 经纬度数据交换时使用：

```text
data/boundary/processed/gx_county_boundary.gpkg
data/boundary/processed/gx_county_boundary.geojson
```

这两个文件的 CRS 为 EPSG:4490，单位是 degree，不能直接用于米制距离、面积、buffer 或 1 km 网格计算。

## 2. 目录结构

```text
Task_6/
├── config/
│   └── spatial_crs.json
├── data/boundary/
│   ├── raw/
│   │   ├── 广西壮族自治区_县.geojson
│   │   ├── 广西壮族自治区_市.geojson
│   │   └── 南宁市_县.geojson
│   └── processed/
│       ├── gx_county_boundary.gpkg
│       ├── gx_county_boundary.geojson
│       └── gx_county_boundary_projected.gpkg
├── reports/
│   ├── boundary_validation_report.json
│   ├── projection_comparison.csv
│   └── projection_evaluation_report.json
├── scripts/
│   ├── inspect_boundary.py
│   ├── standardize_boundary.py
│   ├── evaluate_projection.py
│   └── spatial_config.py
├── requirements.txt
└── README.md
```

根目录中的三个中文名 GeoJSON 是恢复项目时保留的原始副本；流水线实际读取 `data/boundary/raw/`，原始文件只读。

## 3. 统一分析 CRS

项目采用：

```text
Guangxi CGCS2000 Regional Albers Equal Area
```

| 参数 | 值 |
|---|---|
| Datum | China 2000 / CGCS2000 |
| Ellipsoid | CGCS2000（GRS80 参数） |
| Projection | Albers Equal Area |
| Unit | metre |
| Central meridian | 108.251719°E |
| Latitude of origin | 23.7025695°N |
| Standard parallel 1 | 21.9133551666667°N |
| Standard parallel 2 | 25.4917838333333°N |
| EPSG | 无，这是广西区域自定义 CRS |

PROJ 表达式：

```text
+proj=aea +lat_0=23.7025695 +lon_0=108.251719 +lat_1=21.9133551666667 +lat_2=25.4917838333333 +x_0=0 +y_0=0 +ellps=GRS80 +units=m +no_defs +type=crs
```

`config/spatial_crs.json` 中的完整 WKT 是权威定义。不要仅凭名称手工重建，也不要替换成 UTM 49N。

Python 使用示例：

```python
import json
from pathlib import Path

import geopandas as gpd
from pyproj import CRS

root = Path("Task_6")
config = json.loads((root / "config/spatial_crs.json").read_text(encoding="utf-8"))
analysis_crs = CRS.from_wkt(config["preferred_crs_input"]["analysis"])

source = gpd.read_file("your_data.geojson")
projected = source.to_crs(analysis_crs)
```

若输入数据没有 CRS，必须先查明真实 CRS。`set_crs()` 只声明坐标含义，不执行坐标转换，不能用它猜测或伪造 CRS。

## 4. 投影选择依据

实际比较了 8 个候选方案：

- WGS84 / UTM 48N；
- WGS84 / UTM 49N；
- CGCS2000 六度带中央经线 105°、111°；
- CGCS2000 三度带中央经线 108°、111°；
- 广西区域 Transverse Mercator；
- 广西区域 Albers Equal Area。

在广西内部 250 个确定性采样点上进行了 8 个方向、共 2,000 次真实 1 km geodesic 距离测试。推荐方案结果：

- 1 km 距离 P95 绝对误差：约 0.476668 m；
- 1 km 距离最大绝对误差：约 0.485032 m；
- 约 1 km² 区域最大相对面积误差：约 `2.1871e-9`；
- 广西整体面积相对误差：约 `3.8615e-8`；
- 保持 China 2000 datum，完整覆盖广西，单位为 metre。

详细候选参数和排名见：

```text
reports/projection_comparison.csv
reports/projection_evaluation_report.json
```

## 5. 边界字段

标准化和投影 GPKG 至少包含：

| 字段 | 含义 |
|---|---|
| `province_name` | 省级名称 |
| `province_adcode` | 省级六位行政代码 |
| `city_name` | 地级市名称 |
| `city_adcode` | 地级市代码 |
| `county_name` | 县级名称 |
| `county_adcode` | 县级六位行政代码，字符串 |
| `name` | 原始名称字段 |
| `adcode` | 从原 `gb` 提取的县级代码 |
| `gb` | 保留的原始字段 |
| `geometry` | 县级行政区 geometry |

行政关联应使用 `adcode`，不要只使用名称连接。

## 6. 已验证结果

- 原始县级单元：111；
- 地级市：14；
- 原始 CRS：EPSG:4490；
- geometry：111 个 MultiPolygon；
- 空 geometry：0；
- 无效 geometry：0；
- 重复行政代码：0；
- 111 个县全部成功匹配地级市；
- 南宁市局部文件：12 个县，数量、名称、代码与 geometry 一致；
- 标准化阶段未转换坐标、未修复 geometry；
- 投影后 feature 数仍为 111，属性字段未改变。

`boundary_validation_report.json` 和 `projection_evaluation_report.json` 的状态均为 `PASS`。

## 7. QGIS / ArcGIS

GPKG 中已经写入自定义 CRS。一般可直接加载：

```text
data/boundary/processed/gx_county_boundary_projected.gpkg
```

如果软件要求重新指定 CRS，请从 `config/spatial_crs.json` 复制完整 WKT。不要选择名称相似但参数不同的 CRS。

## 8. 环境与复现

建议使用 64 位 Python 3.11 或 3.12：

```powershell
cd Task_6
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

完整重建顺序：

```powershell
.\.venv\Scripts\python.exe scripts\standardize_boundary.py
.\.venv\Scripts\python.exe scripts\evaluate_projection.py
.\.venv\Scripts\python.exe scripts\spatial_config.py
```

这些命令会覆盖同名的 processed、config 和 reports 产物，但不会修改 `data/boundary/raw/`。重跑前应确认没有需要保留的人工修改。

## 9. 与 Task_5 的关系

同级目录 `../Task_5` 保存统一 1 km 网格。Task_5 的生成脚本读取本目录的：

```text
config/spatial_crs.json
data/boundary/processed/gx_county_boundary_projected.gpkg
```

因此不要单独修改这两个文件；若重新选择 CRS 或重新生成投影边界，必须重新运行 Task_5 并检查网格 ID 是否发生变化。

## 10. 不可随意修改

- 不覆盖 `data/boundary/raw/`；
- 不在 EPSG:4490 下计算米制距离或面积；
- 不把分析 CRS 偷换为 WGS84 UTM；
- 不静默修复 geometry；
- 不用县名或行号替代行政代码；
- 不修改 `spatial_crs.json` 后继续沿用旧网格。
