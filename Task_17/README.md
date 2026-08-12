# Task_17：南宁市土地利用分析用地表覆盖数据

## 1. 数据集说明

- **比赛任务名称：** 土地利用数据。
- **实际数据类型：** GlobeLand30 2020地表覆盖分类产品，不是法定土地用途或土地权属数据。
- **原始图幅：** `N48_20_2020LC030`、`N49_20_2020LC030`。
- **发布/分发信息：** 自然资源部发布、国家基础地理信息中心分发；源MAT记录总体精度85.72%。
- **分类体系：** 10个一级地表覆盖类别，另有`0=无值`和`255=海水`。
- **空间范围：** 南宁市12个县级行政单元。
- **空间标准：** 输出对齐Task_14南宁市30 m广西Albers网格，并关联Task_05统一1 km网格。

## 2. 目录结构

```text
Task_17/
├── data/
│   ├── raw/globeland30_2020/
│   │   ├── N48_20_2020LC030/
│   │   └── N49_20_2020LC030/
│   └── processed/
│       ├── nanning_landcover_2020_30m_albers.tif
│       ├── landcover_class_lookup.csv
│       ├── nanning_landcover_grid_1km.csv
│       ├── nanning_landcover_grid_1km_long.csv
│       └── nanning_landcover_county_summary.csv
├── reports/
│   ├── source_inventory.csv
│   ├── source_validation_report.json
│   ├── overlap_analysis.json
│   ├── build_report.json
│   ├── quality_report.json
│   └── data_lineage.md
├── scripts/
│   ├── inspect_landcover_sources.py
│   ├── build_nanning_landcover.py
│   └── summarize_landcover.py
├── file_manifest.csv
├── SHA256SUMS.txt
└── README.md
```

## 3. 类别编码

| 编码 | 中文类别 | 英文类别 | 分析处理 |
|---:|---|---|---|
| 0 | 无值 | No Value | NoData |
| 10 | 耕地 | Cultivated Land | 正式类别 |
| 20 | 林地 | Forest | 正式类别 |
| 30 | 草地 | Grass Land | 正式类别 |
| 40 | 灌木地 | Shrubland | 正式类别 |
| 50 | 湿地 | Wetland | 正式类别 |
| 60 | 水体 | Water Body | 正式类别 |
| 70 | 苔原 | Tundra | 正式类别，南宁当前未出现 |
| 80 | 人造地表 | Artificial Surfaces | 正式类别 |
| 90 | 裸地 | Bareland | 正式类别 |
| 100 | 冰川和永久积雪 | Permanent Snow and Ice | 正式类别，南宁当前未出现 |
| 255 | 海水 | Sea | 排除类别 |

`landcover_class_lookup.csv`是从两个原始MAT元数据中人工核验后转录的UTF-8类别表。原始XLS完整保存在raw目录；当前Conda环境不安装旧版XLS插件，复现脚本通过固定编码集合核验栅格，不依赖本机Office。

## 4. 两幅图拼接原则

N48和N49分别采用EPSG:32648与EPSG:32649，UTM矩形范围在108°附近存在重叠。南宁市内重叠约3,389.62 km²，部分重叠像元类别不同，因此不能按文件顺序任意覆盖。

本任务采用与产品名义范围一致的确定性规则：

1. 两幅分类栅格分别以最近邻映射到Task_14同一30 m网格；
2. 目标像元中心经度小于108°时使用N48；
3. 目标像元中心经度大于等于108°时使用N49；
4. 按Task_01南宁市边界裁剪，边界外写0；
5. 南宁市边界内出现0、255或未知编码时构建失败，不静默填补。

## 5. 主要成果

- `nanning_landcover_2020_30m_albers.tif`：南宁市30 m Byte分类COG，NoData=0，带官方类别调色板。
- `nanning_landcover_grid_1km.csv`：22,770个`grid_id`的主导类别、有效覆盖和10类比例宽表。
- `nanning_landcover_grid_1km_long.csv`：每格固定10类的网格—类别长表，共227,700行。
- `nanning_landcover_county_summary.csv`：12县区×10类别汇总，共120行。
- `overlap_analysis.json`：N48/N49重叠区一致性、冲突率和类别转移矩阵。

实际构建结果为7,841列×6,745行，南宁市边界内共24,550,563个有效分类像元，内部无00、255或未知编码。N48/N49在目标网格上有3,683,627个双方均有效的重叠像元，共171,456个类别不同，冲突率为4.6545%。

| 类别 | 像元数 | 边界内有效像元占比 |
|---|---:|---:|
| 耕地 | 11,147,793 | 45.4075% |
| 林地 | 11,035,013 | 44.9481% |
| 草地 | 499,161 | 2.0332% |
| 灌木地 | 749 | 0.0031% |
| 湿地 | 2,880 | 0.0117% |
| 水体 | 603,779 | 2.4593% |
| 苔原 | 0 | 0% |
| 人造地表 | 1,259,711 | 5.1311% |
| 裸地 | 1,477 | 0.0060% |
| 冰川和永久积雪 | 0 | 0% |

## 6. 比例分母

- 宽表中的10类`*_ratio`：类别像元数/该格有效地表覆盖像元数。
- 长表中的`valid_pixel_ratio`：类别像元数/该格有效地表覆盖像元数。
- 长表中的`nanning_area_ratio`：类别像元近似面积/该格与南宁市相交面积。
- 县区表中的`valid_pixel_ratio`：类别像元数/该县区有效地表覆盖像元数。
- 县区表中的`county_area_ratio`：类别像元近似面积/县区矢量面积。

没有有效像元的极小边界网格保留记录，主导类别和比例为空，不伪造为0；有有效像元但某类别未出现时，该类别比例为0。

`valid_coverage_ratio`使用“像元中心落入边界的数量×900 m²”估算覆盖面积，而`nanning_area_m2`是精确几何相交面积，因此边界网格的比值可能略大于1；请结合`quality_flag`使用，不将其解释为概率。

## 7. 复现方法

在仓库根目录运行：

```powershell
conda activate smartbi-gis
python Task_17/scripts/inspect_landcover_sources.py
python Task_17/scripts/build_nanning_landcover.py
python Task_17/scripts/summarize_landcover.py
```

脚本只读取Task_01、Task_05、Task_14及Task_17原始包；同名Task_17派生成果、报告和校验清单会被覆盖。

## 8. 使用限制

- GlobeLand30属于遥感地表覆盖产品，不能代替自然资源确权、国土调查、规划审批或现场测量。
- 产品年代为2020；源影像索引包含2015—2017年的Landsat 8影像日期，不能表述为所有像元均由2020年单景影像分类。
- 源MAT记录总体精度85.72%，不代表南宁市每个类别或每个像元都具有相同精度。
- 30 m是像元大小，不等于定位或分类精度。
- 洪涝模型若合并类别，必须在下游另行记录规则，不得静默改写Task_17官方类别。

## 9. 质量验收

最终以`reports/quality_report.json`中的`status=PASS`为准，至少满足：

- 两个原始包共18文件，SHA256与入库原件一致；
- 两幅联合覆盖南宁市100%，12县区均完整覆盖；
- 主栅格与Task_14网格完全一致，最近邻、Byte、NoData=0、COG有效；
- 南宁市内部无0、255或未知编码；
- 网格宽表22,770行、长表227,700行、县区表120行且复合主键唯一；
- 类别像元、面积和比例通过守恒与值域检查；
- 所有交付文件通过SHA256复核。

本次验收的网格质量标记为：22,695条`pass`、43条`review_coverage_ratio`、29条`no_valid_pixel_center`和3条`small_boundary_sliver`。后三类是边界取样提示，已保留供下游审核，不属于分类编码失效。
