# river 说明

本文件夹存放河流水文/水系相关数据的共享版本。

## 文件

```text
hydrosheds_dem_nanning_bbox.tif
hydrosheds_acc_nanning_bbox.tif
dem_acc_grid_0p02deg.csv
osm_nanning_waterways.gpkg
hydrosheds_dem_nanning_bbox.vrt
hydrosheds_acc_nanning_bbox.vrt
```

## 文件含义

- `hydrosheds_dem_nanning_bbox.tif`：DEM 高程栅格，用于分析地势、低洼区、坡度等。
- `hydrosheds_acc_nanning_bbox.tif`：ACC 汇流累积栅格，用于判断汇水通道和潜在积水易发区。
- `dem_acc_grid_0p02deg.csv`：DEM 和 ACC 的 0.02 度网格统计表，共 45,000 行。
- `osm_nanning_waterways.gpkg`：OSM 水系线，已裁剪到当前研究范围内，共 1,949 条线。
- `hydrosheds_dem_nanning_bbox.vrt`、`hydrosheds_acc_nanning_bbox.vrt`：本地处理时使用的轻量索引文件。

## 范围和坐标

```text
坐标系：WGS84 / EPSG:4326
DEM/ACC 范围：105-111E, 21-24N
```

## 主要字段

`dem_acc_grid_0p02deg.csv` 中常用字段：

- `grid_id`：网格编号。
- `dem_mean_m`：网格内平均高程，单位为米。
- `dem_min_m`：网格内最低高程，单位为米。
- `dem_max_m`：网格内最高高程，单位为米。
- `acc_mean`：网格内平均汇流累积值。
- `acc_max`：网格内最大汇流累积值。

`osm_nanning_waterways.gpkg` 中常用字段：

- `fclass`：水系类型，如 river、stream、canal、drain。
- `name`：水系名称，若 OSM 中有记录。
- `osm_id`：OSM 编号。

## 使用建议

- DEM 和 ACC 是栅格数据，不是河流线。
- 河流线请使用 `osm_nanning_waterways.gpkg`。
