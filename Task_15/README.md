# Task_15：南宁市坡度数据

## 1. 数据集说明

- **任务内容：** 南宁市30 m坡度表面、统一1 km网格坡度统计和县区坡度汇总。
- **唯一高程输入：** `Task_14/data/processed/nanning_dem_30m_albers.tif`。
- **计算方法：** GDAL Horn 3×3算法。
- **坡度单位：** 度（degree），不是百分比坡度。
- **空间范围：** 南宁市12个县级行政单元。
- **上游空间标准：** Task_01南宁市边界、Task_05统一1 km网格、Task_06广西CGCS2000区域Albers坐标系。

本任务不重复保存DEM，不从1 km平均高程反推坡度，也不复用Task_20中未入库的坡度文件。

## 2. 目录结构

```text
Task_15/
├── data/processed/
│   ├── nanning_slope_30m_albers.vrt
│   ├── nanning_slope_30m_albers_north.tif
│   ├── nanning_slope_30m_albers_south.tif
│   ├── nanning_slope_grid_1km.csv
│   └── nanning_slope_county_summary.csv
├── reports/
│   ├── build_report.json
│   ├── quality_report.json
│   └── data_lineage.md
├── scripts/
│   ├── build_nanning_slope.py
│   └── summarize_slope.py
├── file_manifest.csv
├── SHA256SUMS.txt
└── README.md
```

## 3. 主要成果

- `nanning_slope_30m_albers.vrt`：南宁市30 m坡度角统一入口，与Task_14 DEM完全同网格。
- `nanning_slope_30m_albers_north.tif`、`nanning_slope_30m_albers_south.tif`：因单个Float32坡度COG超过95 MB内部门槛而拆分的两个无缝COG，均为Float32、NoData=`-9999`。
- `nanning_slope_grid_1km.csv`：Task_05南宁市22,770个`grid_id`的坡度统计和三个平缓地形比例。
- `nanning_slope_county_summary.csv`：南宁市12县区坡度汇总，使用`county_adcode`关联。
- `quality_report.json`：栅格、网格、县区和完整性验收结果。

## 4. 坡度计算原则

1. 直接读取Task_14的30 m米制DEM，运行前校验上游质量状态和SHA256。
2. 使用Horn 3×3有限差分算法，水平与垂直单位比例固定为1。
3. 输出坡度角范围为0°至90°，不输出百分比坡度。
4. 不填洼、不平滑、不重采样，不改变基础高程。
5. 不启用边缘插值；3×3邻域不完整时中心像元保持NoData。
6. 输出保持DEM的CRS、范围、尺寸、30 m分辨率和像元对齐；VRT只负责无复制索引两个南北COG。

因此坡度有效像元会略少于DEM有效像元，尤其是行政边界附近。这是算法边界规则，不是数据丢失，也不应人工补0。

## 5. 统一网格字段

| 字段 | 含义 |
|---|---|
| `grid_id` | Task_05稳定1 km空间主键 |
| `center_lon`、`center_lat` | 网格中心经纬度 |
| `slope_min_deg`、`slope_max_deg` | 有效范围最小、最大坡度角 |
| `slope_mean_deg`、`slope_std_deg` | 有效范围平均坡度角和标准差 |
| `valid_pixel_count` | 有效30 m坡度像元数 |
| `valid_area_m2` | 有效像元近似面积 |
| `valid_coverage_ratio` | 有效像元面积与南宁市相交面积之比 |
| `slope_le_3deg_ratio` | 有效像元中坡度≤3°的比例 |
| `slope_le_5deg_ratio` | 有效像元中坡度≤5°的比例 |
| `slope_le_8deg_ratio` | 有效像元中坡度≤8°的比例 |
| `quality_flag` | 边界与覆盖质量标记 |

三个阈值比例的分母均为该统计区域内的有效坡度像元；没有有效像元时保留为空值，不写成0。边界网格可能关联多个县区，行政关系继续使用Task_05关系表。

## 6. 复现方法

在仓库根目录执行：

```powershell
conda activate smartbi-gis
python Task_15/scripts/build_nanning_slope.py
python Task_15/scripts/summarize_slope.py
```

脚本只读取Task_01、Task_05和Task_14；同名Task_15派生成果、报告和校验清单会被覆盖。

## 7. 使用限制

- 坡度质量继承ASTER GDEM V3及Task_14处理链路的分辨率、误差和垂直基准限制。
- 30 m是分析像元大小，不等于地形测量精度，不适用于工程设计或地质安全鉴定。
- `≤3°/≤5°/≤8°`比例是可供洪涝模型使用的地形特征，不应单独解释为洪涝风险或淹没概率。
- Task_20的8°阈值属于特定遥感识别流程；在其他模型中使用阈值时应重新论证。
- 后续更换DEM或坡度算法时必须建立新版本，不得静默覆盖而不更新数据血缘和质量报告。

## 8. 质量验收

最终验收以`reports/quality_report.json`中的`status=PASS`为准，至少检查：

- 输入DEM哈希和Task_14质量状态；
- 输出栅格的CRS、范围、尺寸、分辨率、NoData和COG结构；
- 坡度值域、NaN、Inf和独立Horn抽样复算误差；
- 22,770个唯一`grid_id`及12个唯一`county_adcode`；
- 三个阈值比例均处于0至1或为空；
- 文件清单和SHA256完整性。

当前验收结果：

- 完整坡度入口：7841×6745、30 m、Float32、NoData=`-9999`，有效像元24,503,021个；
- 坡度范围：0–74.605553°，全市像元平均坡度约12.110285°；
- 独立Horn复算：100个确定性样本，最大绝对差约`1.81×10⁻⁶°`；
- 分块交付：北块约44.08 MB、南块约58.42 MB，均为COG且低于95 MB；
- 统一网格：22,770个唯一`grid_id`，其中22,417格为`pass`、294格为`review_coverage_ratio`、59格为`no_valid_pixel_center`；
- 县区汇总：12个唯一`county_adcode`，全部具有有效坡度像元；
- 最终质量状态：`PASS`。
