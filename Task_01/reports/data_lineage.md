# Task_01数据血缘说明

## 来源关系

Task_01是Task_06标准化行政区划成果的南宁市专题派生数据，不建立独立原始数据源。

| Task_01成果 | Task_06上游文件 | 筛选规则 | 坐标系 |
|---|---|---|---|
| `data/processed/nanning_county_boundary.gpkg` | `Task_06/data/boundary/processed/gx_county_boundary.gpkg` | `city_adcode == 450100` | EPSG:4490 |
| `data/processed/nanning_county_boundary.geojson` | `Task_06/data/boundary/processed/gx_county_boundary.gpkg` | `city_adcode == 450100` | EPSG:4490 |
| `data/processed/nanning_county_boundary_projected.gpkg` | `Task_06/data/boundary/processed/gx_county_boundary_projected.gpkg` | `city_adcode == 450100` | 广西CGCS2000区域Albers |

## 处理原则

1. Task_06上游文件保持只读。
2. 仅按行政代码筛选，不按中文名称模糊匹配。
3. 不修复、简化、平滑或人工编辑几何。
4. 不改变Task_06的属性字段及行政代码。
5. 经纬度成果和米制成果必须具有相同的12个县级行政代码。

## 版本更新

Task_06边界、字段或统一分析坐标系发生变化时，应重新运行导出脚本，并以新的质量报告和SHA256值替换旧成果。Task_01不得脱离Task_06单独维护行政边界版本。
