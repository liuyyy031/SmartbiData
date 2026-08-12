# Task_14：南宁市DEM高程数据

## 1. 数据集说明

- **任务内容：** 南宁市连续高程表面、统一1 km网格高程统计和县区高程汇总。
- **原始数据：** ASTER Global Digital Elevation Model Version 3（ASTER GDEM V3）。
- **获取渠道：** 地理空间数据云（GSCloud）批量下载。
- **原始瓦片：** 7个一度瓦片，每个ZIP包含`_dem.tif`高程层和`_num.tif`质量辅助层。
- **空间范围：** 完整覆盖南宁市12个县级行政单元。
- **上游空间标准：** Task_01南宁市边界、Task_05统一1 km网格、Task_06广西CGCS2000区域Albers坐标系。

## 2. 目录结构

```text
Task_14/
├── data/
│   ├── raw/aster_gdem_v3/              # 7个原始ZIP
│   └── processed/
│       ├── nanning_dem_30m_albers.tif
│       ├── nanning_dem_grid_1km.csv
│       └── nanning_dem_county_summary.csv
├── reports/
│   ├── source_tile_inventory.csv
│   ├── source_validation_report.json
│   ├── build_report.json
│   ├── quality_report.json
│   └── data_lineage.md
├── scripts/
│   ├── inspect_dem_sources.py
│   ├── build_nanning_dem.py
│   └── summarize_dem.py
├── file_manifest.csv
├── SHA256SUMS.txt
└── README.md
```

## 3. 主要成果

- `nanning_dem_30m_albers.tif`：30 m南宁市分析DEM，广西Albers投影，单位为米，边界外NoData为`-9999`，供Task_15坡度和其他空间分析使用。
- `nanning_dem_grid_1km.csv`：与Task_05一致的南宁市22,770个`grid_id`高程统计，可用于SmartBI和模型输入。
- `nanning_dem_county_summary.csv`：南宁市12县区高程统计，使用`county_adcode`关联。
- `_num.tif`：保留在原始ZIP内，仅用于来源质量辅助统计，不作为高程值或风险指标。

## 4. 高程处理原则

1. 7个原始ZIP保持原样，不在仓库内重复保存解压TIFF。
2. DEM连续变量重投影采用双线性重采样。
3. 输出分辨率为30 m，像元网格按投影坐标30 m整数倍固定。
4. 南宁市边界外设为NoData，不填洼、不平滑、不修改原始地形。
5. 坡度、坡向等地形派生量由Task_15负责，不在Task_14中生成。
6. 不把Task_20方法说明中缺失的Copernicus DEM当作本任务数据来源。
7. 源GeoTIFF仅声明水平坐标系EPSG:4326，未提供可机器识别的垂直坐标系；本任务不执行垂直基准转换。

## 5. 网格统计字段

| 字段 | 含义 |
|---|---|
| `grid_id` | Task_05稳定1 km空间主键 |
| `center_lon`、`center_lat` | 网格中心经纬度 |
| `nanning_area_m2` | 网格与南宁市相交面积 |
| `elevation_min_m` | 有效范围最低高程 |
| `elevation_max_m` | 有效范围最高高程 |
| `elevation_mean_m` | 有效范围平均高程 |
| `elevation_std_m` | 有效范围高程标准差 |
| `valid_pixel_count` | 有效30 m像元数 |
| `valid_area_m2` | 有效像元近似面积 |
| `valid_coverage_ratio` | 有效像元面积与南宁市相交面积之比 |
| `quality_flag` | 统计质量标记 |

边界网格可能对应多个县区，县区关系应继续使用Task_05关系表，不要把一个网格强制归入单一县区。

## 6. 复现方法

在仓库根目录执行：

```powershell
conda activate smartbi-gis
python Task_14/scripts/inspect_dem_sources.py
python Task_14/scripts/build_nanning_dem.py
python Task_14/scripts/summarize_dem.py
```

脚本只读取Task_01、Task_05、Task_06和Task_14原始ZIP；同名Task_14派生成果、报告和校验清单会被覆盖。

## 7. 使用限制

- ASTER GDEM属于全球遥感DEM，不能代替测绘级高程、工程测量或现场水准数据。
- 输出高程沿用源产品的高程含义；使用者不得将其误称为厘米级或米级实测精度。
- 仓库文件没有编码垂直CRS，涉及绝对高程基准的正式说明应另行引用ASTER GDEM V3产品文档，不应根据水平EPSG代码推断。
- 30 m是分析像元大小，不等于高程精度。
- 后续更换DEM来源时必须建立新版本，不得静默覆盖而不更新数据血缘和质量报告。

## 8. 当前质量结果

- 原始ZIP：7个，全部通过完整性检查；7块共享边缘高程逐像元一致。
- 南宁市覆盖率：100%，未发现源DEM内部`-9999`或小于-500 m异常值。
- 分析DEM：7841×6745像元，30 m、int16、NoData=`-9999`、COG布局，文件约24.19 MB。
- 南宁市有效高程范围：1–1737 m。
- 统一网格：22,770个唯一`grid_id`，其中22,695格质量标记为`pass`。
- 边界质量标记：29个极小边界格没有有效30 m像元中心，43格因像元面积近似导致覆盖率需复核，另有3个面积小于一个30 m像元的边界碎片；这些记录均被保留，没有插值或伪造高程。
- 县区汇总：12个县级行政单元全部具有有效高程像元。
