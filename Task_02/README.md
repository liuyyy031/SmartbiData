# population 说明

本文件夹存放人口数据的共享版本。

## 文件

```text
worldpop_2020_population_nanning_bbox.tif
population_grid_0p02deg.csv
```

## 文件含义

- `worldpop_2020_population_nanning_bbox.tif`：WorldPop 2020 人口栅格，已裁剪到当前南宁研究范围。
- `population_grid_0p02deg.csv`：按 0.02 度网格汇总后的人口表，共 45,000 行。

## 范围和坐标

```text
坐标系：WGS84 / EPSG:4326
范围：105-111E, 21-24N
```

## 主要字段

`population_grid_0p02deg.csv` 中常用字段：

- `grid_id`：网格编号。
- `lon`、`lat`：网格中心点经纬度。
- `xmin`、`ymin`、`xmax`、`ymax`：网格边界。
- `population_sum`：该网格内人口合计。

## 使用建议

- 做人口暴露、受灾人口估算时，优先使用 `population_grid_0p02deg.csv`。
