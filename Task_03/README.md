# Task 03：居民点（settlements）

## 数据集说明

- 任务/数据集：Task_03，居民点（`settlements`）。
- 记录数：19745 条。
- 数据来源：[Geofabrik / OpenStreetMap](https://download.geofabrik.de/asia/china/guangxi.html)。
- 获取日期：2026-07-26；来源快照日期：not_recorded。
- 许可与署名：数据 © OpenStreetMap contributors，依据 [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/) 提供；使用、再发布或派生时应保留相应署名与许可义务。
- 已批准的 `fclass`：village, hamlet, town, city。包内仅应包含这些类别。

## 文件使用

- `data/processed/settlements.gpkg`：GIS 空间数据，坐标参考系为 EPSG:4490；如文件名带 `.zip`，请先解压后再在 GIS 软件中打开内部 `.gpkg`。
- `data/processed/settlements.csv`：供 SmartBI 导入的属性/空间表，编码为 UTF-8 BOM，`geometry` 字段为 WKT；如文件名带 `.zip`，请先解压后导入内部 `.csv`。
- `data/relations/settlements_district_links.csv`：要素与区县的关联表，用 `record_id` 和 `district_code` 关联；编码为 UTF-8 BOM。
- `reports/quality_summary.json`：记录数、类别分布、几何与名称检查，以及来源校验信息。
- `file_manifest.csv` 与 `SHA256SUMS.txt`：交付文件清单及完整性校验值。

## 输出字段

- 空间数据与 SmartBI CSV 字段：source_layer, source_fid, osm_id, fclass, record_id, source_crs, district_code, data_source, data_type, dedup_status, dedup_reason, settlement_name, settlement_type, population, longitude, latitude, geometry, source_record_id, record_id_origin, boundary_version, boundary_status, code_validation_status, province, city, district。
- 区县关联表字段：dataset_name, record_id, district_code, relation_type, join_status。

## Task_06 区县边界与关联规则

- 边界版本：smartbidata_task06_20260810；边界状态：team_shared；行政区划代码校验状态：team_shared_source。
- 点要素仅在区县面内（`within`）时关联；线、面等非点要素按相交（`intersects`）关联。
- 跨区县要素不会被切分、复制或强行归入单一区县：主数据的 `district_code` 保持为空，关联表保留每个相交区县的一行记录，并以 `join_status=matched_multiple` 标识。边界上的点要素如无法唯一判定，同样保留为空并供人工复核。

## 适用范围与限制

- 居民点表示 OSM 中已制图的聚落/地名要素，不等同于人口、户数、建筑物数量或实际居住状态。
- 本交付不作任何灾害、风险、受灾范围、损失或应急能力结论。
- 未从来源数据推造床位、容量、服务能力、开放/关闭、运营状态等字段或结论；需要此类信息时，应另行使用有明确来源和日期的权威业务数据。
