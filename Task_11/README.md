# Task_11：广西社会应急保供节点成果使用说明

## 一、当前成果可以做什么

当前已经完成：

- 55 个原始及网页附属文件的扫描和识别；
- 1566 条原始记录抽取；
- 1248 条当前候选节点整理；
- 南宁、柳州候选节点的首轮地址与地理编码处理；
- 13 个南宁粮食 physical_site 的人工地址补证；
- 7 个可靠 physical_site 的 GCJ-02 纠偏；
- 7 个节点与广西 1 km 网格的关联；
- 行政区交叉验证。

最终空间阶段状态：

```text
validation_status = PASS
SPATIAL_DATA_READY = true
坐标转换成功 = 7/7
1 km 网格匹配成功 = 7/7
行政区冲突 = 0
```

这里的 `PASS` 指已经可靠定位的 7 个南宁粮食 physical_site。它不表示全部 1248 个候选节点都已有坐标，也不表示已经完成最终节点筛选。

## 二、按使用目的选择文件

### 1. 需要直接进行 GIS 或空间分析

优先打开：

```text
data/processed/nanning_grain_spatial_nodes.gpkg
```

- 图层名：`grain_supply_nodes`
- 要素类型：点
- 要素数量：7
- 图层坐标系：`EPSG:4490`
- 每个节点已经带有 `grid_id`
- 7 个节点均通过行政区验证

也可以用：

```text
data/processed/nanning_grain_spatial_nodes.geojson
```

如果只需要属性表、经纬度或网格编号，可以使用：

```text
data/processed/nanning_grain_spatial_nodes.csv
```

### 2. 需要查看南宁粮食物理设施整理结果

使用：

```text
data/processed/nanning_grain_physical_sites.csv
```

该表共有 13 个 physical_site：

- 7 个 `spatial_ready=true`，已有可靠坐标并已进入正式空间节点表；
- 6 个仍需人工补充证据或复核，没有用乡镇、区县中心点伪造坐标。

未可靠定位的 6 个设施见：

```text
data/processed/nanning_grain_geocoding_review.csv
```

### 3. 需要查看全部候选节点

使用：

```text
data/processed/supply_node_candidates.csv
```

该表是当前候选节点主表，共 1248 条，包含：

- 南宁市 primary 候选；
- 柳州市 secondary 候选；
- 广西其他地区 reserve 候选；
- 广西以外 external 候选；
- 后续人工证据新增的 5 个独立 physical_site。

这张表是候选数据池，不是最终节点清单。不要因为记录缺地址、证据等级较低或属于其他地区而自行删除。

### 4. 需要核查某个节点来自哪里

基础候选按以下链条追溯：

```text
supply_node_candidates.csv 中的 source_record_ids
    ↓
supply_source_records.csv 中的 record_id
    ↓
raw_file_inventory.csv 中的 file_id
    ↓
data/raw/ 中的原始文件
```

对应文件：

```text
data/processed/supply_node_candidates.csv
data/processed/supply_source_records.csv
data/processed/raw_file_inventory.csv
data/raw/
```

南宁粮食 physical_site 的人工地址证据还可以通过以下文件核查：

```text
data/manual/nanning_grain_physical_sites_address_evidence.csv
data/processed/address_evidence_matches.csv
```

人工证据表保留了地址、证据等级、来源 URL 和证据说明。

### 5. 需要处理疑似重复或未定位记录

疑似重复候选：

```text
data/processed/duplicate_review.csv
```

该表共有 49 对记录。`keep_separate` 表示公司主体、分公司或具体粮库应继续分别保留；`manual_review` 表示不能仅凭名称相似自动合并。

首轮南宁、柳州地理编码人工复核项：

```text
data/processed/geocoding_review.csv
```

南宁粮食 physical_site 专项复核项：

```text
data/processed/nanning_grain_geocoding_review.csv
```

## 三、7 个可直接使用的空间节点

| 节点 | grid_id |
|---|---|
| 南宁市储备粮管理有限责任公司五象粮库 | `GX1K_R000187_C000413` |
| 南宁市储备粮管理有限责任公司沙井粮库 | `GX1K_R000199_C000401` |
| 南宁市邕宁区粮食储备库 | `GX1K_R000195_C000424` |
| 横州市六景粮食储备中心库（良圻库区） | `GX1K_R000199_C000470` |
| 上林县安恒储备粮管理有限公司澄泰分公司1号仓库 | `GX1K_R000269_C000442` |
| 上林县安恒储备粮管理有限公司塘红分公司仓库 | `GX1K_R000296_C000439` |
| 广西壮族自治区南宁粮食储备库有限公司 | `GX1K_R000199_C000401` |

沙井粮库与广西壮族自治区南宁粮食储备库有限公司位于同一个 1 km 网格，但仍是两个独立节点，不应合并。

## 四、空间节点表关键字段

| 字段 | 含义 | 使用建议 |
|---|---|---|
| `candidate_id` | 节点唯一标识 | 与候选主表连接时使用 |
| `name` | 节点正式名称 | 展示和核验使用 |
| `entity_type` | 实体层级 | 当前 7 个均为可定位设施节点 |
| `node_type` | 节点业务类型 | 当前主要为 `grain_depot` |
| `city`、`county` | 节点行政区 | 已与网格县区关系交叉验证 |
| `address` | 经证据核验的地址 | 不等同于未经核验的企业注册地址 |
| `longitude_raw`、`latitude_raw` | 高德返回的原始坐标 | 坐标系为 `GCJ02`，不要直接作为 EPSG:4490 使用 |
| `longitude_project`、`latitude_project` | 显式纠偏后的项目经纬度 | 对应 `EPSG:4490` |
| `coordinate_shift_m` | GCJ-02 纠偏距离 | 用于质量审计，不是节点间距离 |
| `grid_id` | 已关联的广西 1 km 网格编号 | 可直接与后续网格数据连接 |
| `grid_assignment_method` | 网格匹配方法 | 当前 7 条均为 `within` |
| `administrative_match` | 行政区交叉验证结果 | 当前 7 条均为 `true` |
| `spatial_ready` | 是否可进入后续空间分析 | 只使用 `true` 的记录 |

## 五、使用方法

### QGIS / ArcGIS（也可以直接传给ai让它来理解输出）

1. 添加 `data/processed/nanning_grain_spatial_nodes.gpkg`。
2. 选择 `grain_supply_nodes` 图层。
3. 软件应识别图层 CRS 为 `EPSG:4490`。
4. 使用 `name` 标注节点，使用 `node_type` 分类显示。
5. 后续获得 1 km 网格图层时，按 `grid_id` 连接即可，无需再次给节点分配网格。

### Excel / WPS 表格

CSV 文件采用 UTF-8 编码。建议通过“数据 → 从文本/CSV导入”打开，并选择 UTF-8，避免中文乱码。

- 查看全部候选：`supply_node_candidates.csv`
- 查看 13 个南宁粮食设施：`nanning_grain_physical_sites.csv`
- 查看 7 个正式空间节点：`nanning_grain_spatial_nodes.csv`
- 查看疑似重复：`duplicate_review.csv`
- 查看尚未定位设施：`nanning_grain_geocoding_review.csv`

### Python / R

读取 CSV 时使用 UTF-8 或 UTF-8-SIG。连接不同表时优先使用 `candidate_id`，不要用相似名称代替唯一标识。

读取 GeoPackage 时选择图层 `grain_supply_nodes`。不要对 `longitude_raw`、`latitude_raw` 再声明 EPSG:4490；正式几何已经使用纠偏后的项目经纬度生成。

## 六、报告应该怎么看

当前结论优先级如下：

1. `nanning_grain_spatial_validation.json`：7 个正式空间节点的最终机器验证；
2. `nanning_grain_spatial_report.md`：7 个空间节点的可读报告；
3. `nanning_grain_geocoding_report.json/.md`：13 个南宁粮食 physical_site 的地址与定位状态；
4. `processing_report.json`、`data_processing_report.md`：基础原始资料和候选节点处理情况。

基础处理报告中的 `WARN` 主要来自大量候选缺地址和 49 对疑似重复，不代表 7 个正式空间节点验证失败。

`geocoding_report.json/.md` 是首轮地理编码的过程报告，可能显示当时某些粮库尚未定位。查看当前状态时，应以名称中带 `nanning_grain_` 的专项报告和空间验证文件为准。
