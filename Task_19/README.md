# Task_19：南宁市历史洪涝事件数据库

## 1. 数据集说明

- **任务名称：** 历史洪涝记录。
- **研究范围：** 南宁市；同时保留可能影响南宁的周边气象、水文和邻近地区背景。
- **证据来源：** 2016—2023年《广西水旱灾害公报》8份PDF；2022年原始WPS作为来源凭证保留。
- **事件口径：** 以公报中可识别的独立洪涝过程为基本记录，不把关键词页数、年度受灾总数或台风编号直接当作事件数。
- **空间标准：** 县区代码和几何复用Task_01，县区频次图层为EPSG:4490。
- **成果性质：** 公报明确记载事件的可审计下限，不是南宁市全部洪涝事件全集。

## 2. 目录结构

```text
Task_19/
├── config/
│   └── nanning_flood_event_catalog.json
├── data/
│   ├── raw/bulletins/
│   └── processed/
│       ├── historical_flood_events.csv
│       ├── event_evidence.csv
│       ├── event_admin_relations.csv
│       ├── event_impacts.csv
│       ├── nanning_flood_frequency_by_year.csv
│       ├── nanning_flood_frequency_by_county.csv
│       └── nanning_flood_frequency_by_county.gpkg
├── reports/
│   ├── source_inventory.csv
│   ├── source_coverage.csv
│   ├── candidate_pages.csv
│   ├── nanning_neighboring_admins.csv
│   ├── source_validation_report.json
│   ├── curation_report.json
│   ├── quality_report.json
│   └── data_lineage.md
├── scripts/
│   ├── inspect_bulletins.py
│   ├── build_historical_flood_database.py
│   └── validate_task19.py
├── file_manifest.csv
├── SHA256SUMS.txt
└── README.md
```

## 3. 南宁相关性和计频规则

`nanning_relevance`分为四类：

| 取值 | 含义 | 计入南宁直接受灾频次 |
|---|---|---|
| `direct_affected` | 公报明确写明南宁受灾、为主要受灾区域或发生具体灾情 | 是 |
| `meteorological_influence` | 天气过程影响南宁，但没有足够证据证明南宁直接受灾 | 否 |
| `hydrologic_influence` | 上下游水文过程可能影响南宁，但没有直接受灾证据 | 否 |
| `nearby_context` | 南宁邻近地区灾情背景 | 否 |

当前人工确认30个事件，其中27个为`direct_affected`，3个为2020年台风气象影响背景。周边事件被保留是为了满足“南宁附近、影响到南宁也可标注”的需求，但不会抬高南宁直接受灾频次。

## 4. 主要成果

- `historical_flood_events.csv`：30个事件主表，一事件一行。
- `event_evidence.csv`：31条证据定位，包含原始文件、SHA256、PDF物理页、页内锚点和证据摘要。
- `event_admin_relations.csv`：33条事件—行政区关系，区分受灾、监测位置和气象影响。
- `event_impacts.csv`：86条人口、农作物、房屋及经济损失等指标；其中仅2条是可确认的南宁县区专属指标。
- `nanning_flood_frequency_by_year.csv`：2016—2025连续年度表。
- `nanning_flood_frequency_by_county.csv/.gpkg`：南宁12县区明确受灾记录下限。
- `nanning_neighboring_admins.csv`：依据Task_06边界计算的南宁邻接7个地级市和15个县级单元，供周边影响审核使用。

2016—2023年南宁直接受灾事件下限分别为5、5、6、2、1、4、1、3，共27个。2024年现有文件是水资源公报而不是水旱灾害公报，2025年缺少来源，两年频次保留为空值而不是0。

## 5. 县区统计解释

县区频次只统计同时满足以下条件的记录：

1. 事件属于`direct_affected`；
2. 公报明确点名南宁市下属县区；
3. 行政区关系为`affected`，而不是监测站点、河段或气象影响位置。

现有公报中只有2017年台风“天鸽”事件明确记录良庆区南晓镇受灾，因此良庆区为1次，其余11县区为0次。这里的0只表示“2016—2023年现有公报没有明确点名该县区受灾”，绝不表示当地没有发生洪涝。2018年邕宁区蒲庙河段超警被标注为`monitoring_location`，不计入邕宁区受灾频次。

## 6. 损失指标使用限制

- 公报常以多个地级市、县区和乡镇合计报告人口与损失，`impact_scope_level=multi_city`的值不得解释为南宁市损失。
- 不按人口、面积或任何权重把多市合计数向南宁市或县区拆分。
- 只有`is_nanning_specific=true`的值可作为南宁专属指标；当前仅有良庆区南晓镇受灾人口1.5万人、转移安置1130人两条。
- 监测值、降雨量和水位信息若后续加入，应继续与受灾损失分表或分类保存。

## 7. 复现方法

在仓库根目录使用`smartbi-gis`环境依次运行：

```powershell
python Task_19/scripts/inspect_bulletins.py
python Task_19/scripts/build_historical_flood_database.py
python Task_19/scripts/validate_task19.py
```

第一步检查9个原始文件、363个PDF页面并生成85个候选页；候选页只用于人工缩小阅读范围。第二步严格按人工目录生成成果并逐条验证证据锚点位于指定原页。第三步执行41项独立验收并重建文件清单和SHA256校验表。

## 8. 质量与适用限制

- 质量状态以`reports/quality_report.json`中的`status=PASS`为准。
- 事件数是基于现有年度公报的下限；公报未写入、只在地方材料出现或无法识别为独立过程的事件不在本表中。
- 年度公报的统计粒度和写法存在差异，跨年比较应结合`source_coverage_status`和证据表。
- 县区频次不适合直接作为真实灾害概率，可作为历史明确记录、风险建模证据和后续地方资料补录底表。
- 邻接清单只表达行政边界接触关系，不等于某次洪水实际传播路径。

