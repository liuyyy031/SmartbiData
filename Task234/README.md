# 广西洪涝灾害多源空间数据统一（Task234）

本目录已完成两项基础工作：

1. 为广西全域选定并固化统一的米制计算坐标系；
2. 在该坐标系下生成统一、稳定的 1 km × 1 km 空间网格。

团队成员通常不需要重新运行脚本，直接使用 `data/` 中的成果即可。所有关键参数都保存在 `config/`，所有质量结果都保存在 `reports/`。

## 1. 五分钟快速使用

### 1.1 做全区米制空间分析

使用：

```text
data/boundary/processed/gx_county_boundary_projected.gpkg
```

它包含 111 个县级行政单元，坐标单位为 metre，适用于距离、面积、缓冲区、叠加分析和网格关联。

### 1.2 以 1 km 网格统一多源数据

使用：

```text
data/grid/gx_grid_1km.gpkg
```

图层名为 `gx_grid_1km`，共有 238,998 个完整正方形网格。以 `grid_id` 作为跨表、跨时相和跨数据源的唯一空间键。

### 1.3 按县或按市汇总网格结果

使用：

```text
data/grid/gx_grid_county_relation.csv
```

该表保存每个网格与县级行政区的真实相交面积。边界网格可能对应多个县，不能只依赖主县字段做精确统计。

### 1.4 对接仍为经纬度的数据

保存原始或国内 CGCS2000 数据时使用：

```text
data/boundary/processed/gx_county_boundary.gpkg
data/boundary/processed/gx_county_boundary.geojson
```

它们的 CRS 为 EPSG:4490，单位是 degree。EPSG:4490 只适合存储和交换，不要直接用于米制距离、面积、buffer 或 1 km 网格分析。

## 2. 目录结构

```text
Task234/
├── config/
│   ├── spatial_crs.json              # 唯一的分析 CRS 定义
│   └── spatial_grid.json             # 唯一的网格原点、分辨率及 ID 规则
├── data/
│   ├── boundary/
│   │   ├── raw/                       # 只读原始 GeoJSON
│   │   └── processed/
│   │       ├── gx_county_boundary.gpkg
│   │       ├── gx_county_boundary.geojson
│   │       └── gx_county_boundary_projected.gpkg
│   └── grid/
│       ├── gx_grid_1km.gpkg
│       └── gx_grid_county_relation.csv
├── reports/
│   ├── boundary_validation_report.json
│   ├── projection_comparison.csv
│   ├── projection_evaluation_report.json
│   └── grid_validation_report.json
├── scripts/
│   ├── inspect_boundary.py
│   ├── standardize_boundary.py
│   ├── evaluate_projection.py
│   ├── spatial_config.py
│   └── generate_grid.py
├── requirements.txt
└── README.md
```

根目录中的三个中文名 GeoJSON 是找回项目时保留的原始文件副本；流水线实际读取 `data/boundary/raw/` 中的只读副本。

## 3. 统一分析坐标系

推荐并已实际采用的 CRS：

```text
Guangxi CGCS2000 Regional Albers Equal Area
```

主要参数：

| 项目 | 值 |
|---|---|
| Datum | China 2000 / CGCS2000 |
| Ellipsoid | CGCS2000（GRS80 参数） |
| 投影 | Albers Equal Area |
| 单位 | metre |
| 中央经线 | 108.251719°E |
| 原点纬度 | 23.7025695°N |
| 第一标准纬线 | 21.9133551666667°N |
| 第二标准纬线 | 25.4917838333333°N |
| EPSG 编号 | 无；这是面向广西实际范围的自定义 CRS |

PROJ 定义：

```text
+proj=aea +lat_0=23.7025695 +lon_0=108.251719 +lat_1=21.9133551666667 +lat_2=25.4917838333333 +x_0=0 +y_0=0 +ellps=GRS80 +units=m +no_defs +type=crs
```

不要根据名称手工重建 CRS，也不要替换成 UTM 49N。程序和新数据应优先读取 `config/spatial_crs.json` 中的完整 WKT；WKT 是本项目分析 CRS 的权威定义。

Python 读取方式：

```python
import json
from pathlib import Path

import geopandas as gpd
from pyproj import CRS

root = Path("Task234")
config = json.loads(
    (root / "config/spatial_crs.json").read_text(encoding="utf-8")
)
analysis_crs = CRS.from_wkt(config["preferred_crs_input"]["analysis"])

source = gpd.read_file("your_data.geojson")
source_projected = source.to_crs(analysis_crs)
```

如果输入没有 CRS，必须先查明其真实 CRS，不能猜测或直接 `set_crs()` 为分析 CRS。

## 4. 为什么使用该 CRS

脚本实际比较了 8 个候选方案：WGS84 UTM 48N、WGS84 UTM 49N、4 个广西附近的 CGCS2000 高斯-克吕格方案、自定义区域 Transverse Mercator 和自定义区域 Albers Equal Area。

最终方案具备以下特点：

- 保持 China 2000 datum；
- 以 metre 为单位，覆盖广西完整实际范围；
- 等面积投影，适合网格与县域面积权重；
- 250 个确定性采样点、8 个方向共 2,000 次 1 km 距离测试中，P95 误差约 0.476668 m，最大误差约 0.485032 m；
- 约 1 km² 小区域的最大相对面积误差约 `2.1871e-9`；
- 广西整体面积相对误差约 `3.8615e-8`。

完整候选、参数、采样与误差位置见：

- `reports/projection_comparison.csv`
- `reports/projection_evaluation_report.json`

## 5. 统一网格定义

| 项目 | 值 |
|---|---|
| 网格尺寸 | 1,000 m × 1,000 m |
| 单格平面面积 | 1,000,000 m² |
| 全局原点 | X = -400,000 m，Y = -300,000 m |
| 原点对齐粒度 | 100,000 m |
| geometry 策略 | 保留完整正方形，不按广西边界裁剪 |
| 保留规则 | 与广西整体边界存在正面积相交 |
| 网格数量 | 238,998 |
| 完全国内网格 | 233,985 |
| 边界网格 | 5,013 |

网格编号规则：

```text
GX1K_R{row_token}_C{col_token}
```

非负行列号使用 6 位补零，负数使用 `N` 加 6 位绝对值，例如：

```text
GX1K_R000003_C000488
```

只要 `config/spatial_crs.json` 和 `config/spatial_grid.json` 不变，同一位置的 `grid_id` 就保持稳定。不要重新选择原点，也不要为不同数据源分别创建另一套 1 km 网格。

## 6. 主网格字段

`data/grid/gx_grid_1km.gpkg` 的字段如下：

| 字段 | 含义 |
|---|---|
| `grid_id` | 全项目唯一且稳定的网格键 |
| `row`, `col` | 相对固定原点的全局行列号 |
| `center_x`, `center_y` | 分析 CRS 下的网格中心坐标，单位 metre |
| `center_lon`, `center_lat` | 网格中心的 EPSG:4490 经度、纬度，仅用于定位展示 |
| `grid_area_m2` | 完整正方形面积，固定为 1,000,000 m² |
| `guangxi_area_m2` | 网格内实际属于广西的面积 |
| `coverage_ratio` | `guangxi_area_m2 / grid_area_m2` |
| `is_boundary_cell` | 是否为广西边界网格 |
| `primary_county_adcode` | 与该格相交面积最大的县代码 |
| `primary_county_name` | 与该格相交面积最大的县名称 |
| `primary_county_ratio` | 主县相交面积占完整网格面积的比例 |
| `geometry` | 未裁剪的 1 km 完整正方形 |

`primary_county_*` 是便捷标签，适合制图、索引或明确要求“一格只归一个县”的模型。涉及县域精确汇总时必须使用关系表。

## 7. 网格—县级关系表

`data/grid/gx_grid_county_relation.csv` 共 256,051 行，字段如下：

| 字段 | 含义 |
|---|---|
| `grid_id` | 连接主网格的键 |
| `county_adcode`, `county_name` | 相交县代码和名称 |
| `city_adcode`, `city_name` | 所属地级市代码和名称 |
| `intersection_area_m2` | 网格与该县的相交面积 |
| `grid_area_ratio` | 相交面积 / 1,000,000 m² |
| `guangxi_area_ratio` | 相交面积 / 该格的广西范围面积 |

当前共有：

- 16,812 个跨县网格；
- 5,592 个跨市网格；
- 111 个县、14 个地级市全部出现。

对某个网格指标 `value` 做县级面积加权汇总时，可将网格表与关系表按 `grid_id` 连接，再使用：

```text
weighted_value = value × intersection_area_m2
county_mean = sum(weighted_value) / sum(intersection_area_m2)
```

对于总量型指标是否按面积分摊，取决于指标语义，不能统一套用。例如降水均值通常可按面积加权，站点观测值则应先确定插值或代表范围。

## 8. 新数据如何接入统一网格

### 8.1 矢量数据

1. 确认输入真实 CRS；
2. 重投影到 `config/spatial_crs.json` 的 analysis WKT；
3. 与 `gx_grid_1km.gpkg` 做 spatial join 或 intersection；
4. 输出表中保留 `grid_id`；
5. 不要新建另一套网格。

点位恰好落在格线时，`intersects` 可能匹配多个格。需要唯一归属时，应规定半开区间行列算法，或明确使用固定的边界选择规则。

### 8.2 栅格数据

1. 保留原始栅格；
2. 将分析副本重投影到统一 analysis CRS；
3. 输出像元大小设为 1,000 m；
4. 像元边界按固定原点 `(-400000, -300000)` 的 1,000 m 整数倍对齐；
5. 连续变量使用合适的连续重采样，分类变量通常使用 nearest；
6. 结果以 `grid_id` 入表，不依赖临时行号。

项目网格是矢量分析基准，不等于要求所有栅格只保留一个像元值。重采样方法应由数据类型、空间分辨率和研究目的决定并记录。

### 8.3 时间序列数据

推荐长表结构：

```text
grid_id | timestamp | variable | value | source | quality_flag
```

空间键始终用 `grid_id`，时间字段采用明确时区和统一格式。不要将行政区名称作为主连接键。

## 9. QGIS / ArcGIS 使用

在 QGIS 中可直接拖入两个 GPKG：

```text
data/boundary/processed/gx_county_boundary_projected.gpkg
data/grid/gx_grid_1km.gpkg
```

自定义 CRS 已写入 GeoPackage。若软件要求选择 CRS，请从 `config/spatial_crs.json` 复制完整 WKT，不要选择名称相似但参数不同的 CRS。

网格量较大，首次渲染可能较慢。建议：

- 关闭网格填充，仅显示细边线；
- 设置比例尺可见范围；
- 按 `is_boundary_cell` 或行政字段过滤；
- 不要为了提高显示速度覆盖原始 GPKG，可另建显示副本或使用图层简化选项。

CSV 关系表没有 geometry，应通过 `grid_id` 与网格图层连接。

## 10. 已完成的质量验证

### 边界

- 县级单元：111；
- 地级市：14；
- 原始 CRS：EPSG:4490；
- geometry：111 个 MultiPolygon，空 0、无效 0；
- 重复行政代码：0；
- 111 个县全部成功归属地级市；
- 南宁市局部数据：12 个县，数量、名称、代码和 geometry 基本一致；
- 未执行 geometry repair，标准化阶段未转换坐标。

### 投影

- 投影后县级单元：111；
- 单位：metre；
- 空 geometry：0；
- 无效 geometry：0；
- 属性字段保持不变。

### 网格

- 候选格：460,884；
- 保留格：238,998；
- 关系记录：256,051；
- 重复 `grid_id`：0；
- 无效或空 geometry：0；
- 所有 geometry 均为 1 km 完整 Polygon；
- 广西面积守恒绝对误差：约 0.005127 m²；
- 广西面积守恒相对误差：约 `2.1679e-14`；
- 111 个县的关系表面积守恒检查全部通过。

三阶段报告状态均为 `PASS`。详细数据见 `reports/`，不要只依赖 README 中的摘要。

## 11. Python 环境与完整复现

建议使用 64 位 Python 3.11 或 3.12。Windows PowerShell 示例：

```powershell
cd Task234
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

从原始文件完整重建的执行顺序：

```powershell
.\.venv\Scripts\python.exe scripts\standardize_boundary.py
.\.venv\Scripts\python.exe scripts\evaluate_projection.py
.\.venv\Scripts\python.exe scripts\spatial_config.py
.\.venv\Scripts\python.exe scripts\generate_grid.py
```

各脚本职责：

- `standardize_boundary.py`：字段标准化、行政层级与边界质量验证；
- `evaluate_projection.py`：发现并评估候选 CRS，生成推荐投影边界；
- `spatial_config.py`：把最终 CRS 固化成其他脚本可复用的配置；
- `generate_grid.py`：依据固定配置生成完整方格和县级关系表；
- `inspect_boundary.py`：只读检查原始县级数据。

完整重建会覆盖同名的 processed、grid、config 和 reports 产物，但不会修改 `data/boundary/raw/`。重跑前应确认团队没有对生成文件做未保存的人工编辑。

## 12. 交付压缩包建议

交给其他成员时至少包含：

```text
README.md
requirements.txt
config/
data/boundary/processed/
data/grid/
reports/
scripts/
```

如果需要可复现原始处理，再包含 `data/boundary/raw/`。不需要打包 `.venv/`、`__pycache__/` 或 `.pyc`；接收者应根据 `requirements.txt` 创建自己的环境。

建议把 Task234 正式加入 Git 并提交。仅存在于未跟踪目录中的文件会被 `git clean -fd` 永久删除；`.gitignore` 只能保护被忽略的环境文件，不能代替对成果文件的提交或外部备份。

## 13. 不可随意修改的约束

- 不修改或覆盖 `data/boundary/raw/`；
- 不在 EPSG:4490 下计算米制距离、面积和 buffer；
- 不把 analysis CRS 偷换为 WGS84 UTM 或其他近似 CRS；
- 不修改 `spatial_grid.json` 的原点、格长和 ID 规则；
- 不裁剪主网格 geometry；
- 不把 `primary_county_*` 当作跨县面积关系的完整替代；
- 不使用县名、记录行号或文件顺序代替 `grid_id` / `adcode`；
- 不静默修复 geometry；发现异常应先记录并重新验证。

## 14. 当前阶段未包含

本目录只提供统一边界、统一计算 CRS 和统一 1 km 网格。尚未包含遥感 TIF、降水、站点、洪水范围、暴露度、风险模型、数据库或 API。后续数据都应先按本 README 对齐 CRS 和 `grid_id`，再进入洪涝分析流程。
