# Task_14数据血缘说明

## 原始来源

Task_14保存通过地理空间数据云（GSCloud）获取的7个ASTER GDEM V3原始ZIP。每个压缩包包含一个`_dem.tif`高程层和一个`_num.tif`质量辅助层。仓库外的解压TIFF仅用于前期检查，不属于Task_14交付，避免与ZIP重复占用空间。

源GeoTIFF记录水平坐标系EPSG:4326，但没有可机器识别的垂直坐标系标签。本任务仅转换水平坐标系，所有高程数值沿用源产品含义，不进行垂直基准转换。

## 空间依赖

| 用途 | 上游文件 | 使用方式 |
|---|---|---|
| 南宁市裁剪边界 | `Task_01/data/processed/nanning_county_boundary_projected.gpkg` | 只读，边界外设为NoData |
| 分析坐标系 | `Task_06/config/spatial_crs.json` | 读取完整广西Albers WKT |
| 统一1 km网格 | `Task_05/data/grid/gx_grid_1km.gpkg` | 保留既有`grid_id` |
| 网格—县级关系 | `Task_05/data/grid/gx_grid_county_relation.csv` | 筛选南宁市并计算相交面积 |
| 县区汇总边界 | `Task_01/data/processed/nanning_county_boundary_projected.gpkg` | 按`county_adcode`汇总 |

## 处理链路

```text
7个ASTER ZIP
  → ZIP与栅格元数据校验
  → DEM层安全提取到任务临时目录并拼接
  → Task_06广西Albers、30 m双线性重投影
  → Task_01南宁市边界裁剪
  → 压缩分析DEM
  → Task_05统一1 km网格统计
  → 12县区汇总
```

## 与Task_20的关系

Task_20方法说明提到Copernicus DEM及坡度掩膜，但仓库内没有相应原始DEM、坡度栅格或完整中间成果。Task_14不复制或改写Task_20结果；后续如需重新运行Task_20，应明确记录改用ASTER DEM所产生的数据源变化。

## 禁止的静默处理

- 不进行洼地填充、水文改造或人工修高程。
- 不把`_num.tif`值直接解释为高程或风险等级。
- 不另建1 km网格或修改Task_05的`grid_id`。
- 不修改Task_01、Task_05、Task_06和Task_20上游文件。
