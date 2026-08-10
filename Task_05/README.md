# Task_5：广西统一空间网格数据

本目录保存广西全域统一的 1 km × 1 km 空间网格及网格—县级行政区关系。所有后续遥感、降水、洪水范围、暴露度和风险指标应优先对齐本套网格，并使用稳定的 `grid_id` 作为空间主键。

统一计算坐标系和投影县界保存在同级目录 `../Task_6`。

## 1. 直接使用

主网格：

```text
data/grid/gx_grid_1km.gpkg
```

图层名：`gx_grid_1km`，共有 238,998 个完整正方形网格。

网格—县级关系：

```text
data/grid/gx_grid_county_relation.csv
```

关系表共有 256,051 行。边界网格可能对应多个县，县级精确汇总应使用该表，不要只使用主网格中的 `primary_county_*` 字段。

## 2. 目录结构

```text
Task_5/
├── config/
│   └── spatial_grid.json
├── data/grid/
│   ├── gx_grid_1km.gpkg
│   └── gx_grid_county_relation.csv
├── reports/
│   └── grid_validation_report.json
├── scripts/
│   └── generate_grid.py
├── requirements.txt
└── README.md
```

依赖的统一 CRS 和县界位于：

```text
../Task_6/config/spatial_crs.json
../Task_6/data/boundary/processed/gx_county_boundary_projected.gpkg
```

## 3. 网格定义

| 项目 | 值 |
|---|---|
| 网格尺寸 | 1,000 m × 1,000 m |
| 完整格面积 | 1,000,000 m² |
| 全局原点 | X = -400,000 m，Y = -300,000 m |
| 原点对齐粒度 | 100,000 m |
| CRS | Task_6 中的 Guangxi CGCS2000 Regional Albers Equal Area |
| geometry 策略 | 保留完整正方形，不按广西边界裁剪 |
| 保留规则 | 与广西整体边界存在正面积相交 |
| 保留网格 | 238,998 |
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

只要 Task_6 的分析 CRS及 `config/spatial_grid.json` 的原点、格长不变，同一位置的 `grid_id` 就保持稳定。

## 4. 主网格字段

| 字段 | 含义 |
|---|---|
| `grid_id` | 全项目唯一且稳定的空间键 |
| `row`, `col` | 相对固定原点的全局行列号 |
| `center_x`, `center_y` | 分析 CRS 下的中心坐标，单位 metre |
| `center_lon`, `center_lat` | EPSG:4490 下的中心经纬度，仅用于定位展示 |
| `grid_area_m2` | 完整正方形面积，固定为 1,000,000 m² |
| `guangxi_area_m2` | 网格内实际属于广西的面积 |
| `coverage_ratio` | `guangxi_area_m2 / grid_area_m2` |
| `is_boundary_cell` | 是否为广西边界网格 |
| `primary_county_adcode` | 与该格相交面积最大的县代码 |
| `primary_county_name` | 主县名称 |
| `primary_county_ratio` | 主县相交面积占完整格面积的比例 |
| `geometry` | 未裁剪的 1 km 完整正方形 |

`primary_county_*` 适合制图、快速索引或明确要求“一格只归一个县”的任务，不是完整的跨县关系。

## 5. 网格—县级关系字段

| 字段 | 含义 |
|---|---|
| `grid_id` | 连接主网格的键 |
| `county_adcode`, `county_name` | 相交县代码和名称 |
| `city_adcode`, `city_name` | 所属地级市代码和名称 |
| `intersection_area_m2` | 网格与该县的实际相交面积 |
| `grid_area_ratio` | 相交面积 / 1,000,000 m² |
| `guangxi_area_ratio` | 相交面积 / 该格的广西范围面积 |

当前关系覆盖 111 个县和 14 个地级市，其中：

- 跨县网格：16,812；
- 跨市网格：5,592。

县级面积加权均值示意：

```text
weighted_value = value × intersection_area_m2
county_mean = sum(weighted_value) / sum(intersection_area_m2)
```

总量型指标是否按面积比例分摊，应根据指标含义决定并记录。

## 6. 新数据对齐方法

### 矢量数据

1. 确认输入的真实 CRS；
2. 重投影到 `../Task_6/config/spatial_crs.json` 中的完整 analysis WKT；
3. 与 `gx_grid_1km.gpkg` 做 spatial join 或 intersection；
4. 输出数据必须保留 `grid_id`；
5. 不要针对新数据另建另一套 1 km 网格。

### 栅格数据

1. 保留原始栅格；
2. 将分析副本重投影到 Task_6 的 analysis CRS；
3. 像元大小设为 1,000 m；
4. 像元边界按固定原点 `(-400000, -300000)` 的 1,000 m 整数倍对齐；
5. 连续变量和分类变量分别选择合理的重采样方式；
6. 结果最终以 `grid_id` 入表。

### 时间序列数据

推荐长表：

```text
grid_id | timestamp | variable | value | source | quality_flag
```

不要使用县名、临时行号或文件顺序代替 `grid_id`。

## 7. QGIS / ArcGIS

直接加载：

```text
data/grid/gx_grid_1km.gpkg
```

网格较大，建议关闭填充、使用细边线，并设置比例尺可见范围。CSV 关系表没有 geometry，需要用 `grid_id` 与网格图层连接。

自定义 CRS 已写入 GPKG。如果 GIS 软件要求指定 CRS，应从 `../Task_6/config/spatial_crs.json` 复制完整 WKT。

## 8. 质量结果

- 候选完整方格：460,884；
- 最终保留网格：238,998；
- 关系记录：256,051；
- 重复 `grid_id`：0；
- 空或无效 geometry：0；
- 所有 geometry 均为 1 km 完整 Polygon；
- 广西面积守恒绝对误差：约 0.005127 m²；
- 广西面积守恒相对误差：约 `2.1679e-14`；
- 111 个县的面积守恒检查全部通过；
- `reports/grid_validation_report.json` 状态为 `PASS`。
