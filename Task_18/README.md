# builtup 说明

本文件夹存放建设用地/不透水面相关数据的共享版本。

## 文件

```text
builtup_grid_0p02deg.csv
esa_worldcover_2021_nanning_bbox.vrt
```

## 文件含义

- `builtup_grid_0p02deg.csv`：基于 ESA WorldCover 2021 汇总得到的 0.02 度网格统计表，共 45,000 行。
- `esa_worldcover_2021_nanning_bbox.vrt`：QGIS 可打开的轻量栅格索引，引用原始 WorldCover 两个瓦片。

## 主要字段

`builtup_grid_0p02deg.csv` 中常用字段：

- `grid_id`：网格编号。
- `lon`、`lat`：网格中心点经纬度。
- `builtup_ratio`：网格内建设用地像元占比。WorldCover 类别值为 50。
- `water_ratio`：网格内永久水体像元占比。WorldCover 类别值为 80。
- `cropland_ratio`：网格内耕地像元占比。WorldCover 类别值为 40。
- `builtup_pixel_count`：网格内建设用地像元数量。
- `valid_pixel_count`：网格内有效像元数量。

## 使用建议

- 做建设用地受淹、城市化程度或不透水面等影响分析时，优先使用 `builtup_grid_0p02deg.csv`。
- `esa_worldcover_2021_nanning_bbox.vrt` 不是独立完整栅格文件，上传共享时可以只传 CSV；如果要在本机 QGIS 里看彩色土地覆盖图，可以打开 VRT。
- QGIS 中黑色区域多半是 NoData 或显示样式问题，一般不影响表格统计结果。
