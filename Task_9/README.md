# elderly_home 说明

本文件夹存放广西南宁养老院/养老机构点位数据。

## 文件

```text
elderly_home_WGS84.csv
elderly_home_WGS84.jsonl
elderly_home_WGS84.gpkg
```

## 文件含义

这三个文件是同一批养老机构数据的不同格式：

- `elderly_home_WGS84.csv`：表格格式，适合 Excel、SmartBI 或普通数据检查。
- `elderly_home_WGS84.jsonl`：逐行 JSON 格式，适合程序读取。
- `elderly_home_WGS84.gpkg`：GeoPackage 空间格式，适合 QGIS 直接打开。

## 数据概况

```text
坐标系：WGS84 / EPSG:4326
记录数：91 条
```

## 主要字段

- `name`：养老机构名称。
- `longitude`：经度。
- `latitude`：纬度。
- `address`：地址。
- `district`：所在区县。
- `source`：坐标或信息来源。
- `养老机构床位数`：床位数。

## 使用建议

- 做设施暴露、重点人群设施受灾影响分析时，优先使用 `elderly_home_WGS84.gpkg` 或 `elderly_home_WGS84.csv`。
