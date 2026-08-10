# data/processed 文件说明

本目录存放 Task_11 已生成的结构化数据、地理编码结果、空间成果和质量检查文件。

## 正式数据与当前成果

| 文件 | 用途 |
|---|---|
| `raw_file_inventory.csv` | 原始文件清单，记录文件名、路径、类型、大小、来源分类和解析状态。 |
| `supply_source_records.csv` | 原始记录层，共1566条；保留原始名称、地址、类别、原文片段及来源页码/表格位置，用于追溯。 |
| `supply_node_candidates.csv` | 当前候选节点主表，共1248条；包含标准化名称、地区、实体类型、节点类型、能力标签、来源和分析优先级。不是最终筛选名单。 |
| `duplicate_review.csv` | 疑似重复、公司主体与具体设施层级关系的人工复核表；不得仅凭名称相似自动合并。 |
| `processing_report.json` | 基础处理统计和验证状态，包括原始文件数、记录数、候选数、地区分布、节点类型和警告。 |
| `address_evidence_matches.csv` | 13条人工地址证据与已有或新增 candidate 的匹配关系，用于追踪地址补证过程。 |
| `nanning_grain_physical_sites.csv / .geojson / .gpkg` | 南宁粮食 physical_site 成果。CSV含13个设施及其定位状态；GeoJSON/GPKG仅包含其中7个 `spatial_ready=true` 的设施点。GPKG图层名为 `nanning_grain_physical_sites`。 |
| `nanning_grain_geocoding_review.csv` | 仍未获得可靠坐标的6个南宁粮食 physical_site，保留失败原因和人工复核信息。 |
| `nanning_grain_geocoding_report.json` | 南宁13个粮食 physical_site 的专项地理编码统计；当前专项验证状态为 `PASS`，其中7个可进入空间阶段。 |
| `nanning_grain_spatial_nodes.csv / .geojson / .gpkg` | 当前最主要的空间交付成果：7个已完成GCJ-02纠偏、EPSG:4490点输出和1 km网格关联的节点。GPKG图层名为 `grain_supply_nodes`。 |
| `nanning_grain_spatial_validation.json` | 7个空间节点的最终机器验证；记录转换成功数、网格匹配数、行政区冲突和 `SPATIAL_DATA_READY`。 |
| `administrative_mismatch.csv` | 节点行政区与网格县区关系冲突表；当前只有表头，表示冲突为0条。 |

## 南宁、柳州首轮地理编码成果

| 文件 | 用途 |
|---|---|
| `geocoded_supply_nodes.csv` | 南宁67个、柳州19个候选的首轮地理编码结果；成功结果保留高德GCJ-02原始坐标。它不是最终7节点空间成果。 |
| `geocoding_review.csv` | 首轮地理编码中需要人工复核或后续补证的记录，包括无结果、多结果、名称或行政区不匹配等原因。 |
| `geocoding_pending.csv` | 全量候选的地址或地理编码待办状态，用于识别缺地址、待定位记录；不应作为正式空间节点表使用。 |
| `geocoding_report.json` | 86个南宁、柳州候选的首轮地理编码统计。该报告反映较早阶段，当前南宁粮食节点状态应以 `nanning_grain_*` 文件为准。 |

## 过程与诊断文件

以下文件用于开发核验或解释处理过程，普通团队成员通常不需要使用，部分已由 `.gitignore` 排除：

| 文件 | 用途 |
|---|---|
| `geocoding_targets.csv` | 首轮地理编码的86个目标及搜索条件，是过程输入表。 |
| `geocoding_requests.csv` | 首轮地理编码构造的地址/POI请求和请求状态，不包含API Key。 |
| `core_site_geocoding.csv` | 人工地址证据接入前，对18个重点粮食节点进行二次定位的历史诊断结果。已被后续南宁专项成果替代。 |
| `core_site_geocoding_report.json` | 上述18个重点节点历史诊断的统计报告，不代表当前最终状态。 |
| `poi_match_review.csv` | 重点节点多查询、别名查询和POI评分的人工复核结果。 |
| `address_research_pending.csv` | 重点节点中当时仍需继续检索地址证据的清单。 |
| `door_number_geocode_candidates.csv` | 4个门牌级复核目标的候选坐标集合。 |
| `door_number_geocode_diagnostic.csv` | 门牌级候选的正向、POI和逆地理编码诊断明细，用于解释最终接受或拒绝原因。 |
| `_normalized_source_records.csv` | 基础 pipeline 的内部标准化中间表；正式使用请读取 `supply_source_records.csv` 和 `supply_node_candidates.csv`。 |
| `_validation_details.json` | 基础数据验证的内部错误/警告详情。 |

## 使用建议

1. 做GIS或后续空间分析：使用 `nanning_grain_spatial_nodes.gpkg`。
2. 查看7个空间节点属性或网格编号：使用 `nanning_grain_spatial_nodes.csv`。
3. 查看13个南宁粮食物理设施及定位状态：使用 `nanning_grain_physical_sites.csv`。
4. 查看全量候选数据池：使用 `supply_node_candidates.csv`。
5. 核查来源：按 `candidate_id`、`source_record_ids` 连接 `supply_source_records.csv` 和 `raw_file_inventory.csv`。
6. 查看尚未解决的问题：使用 `nanning_grain_geocoding_review.csv`、`geocoding_review.csv` 和 `duplicate_review.csv`。

注：不要把GCJ-02原始坐标直接当作EPSG:4490，不要把企业注册地址自动视为仓库地址，也不要把1248条候选记录理解为已经确认的最终应急节点。
