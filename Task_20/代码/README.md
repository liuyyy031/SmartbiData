# 遥感处理代码说明

环境：conda 环境 `flood`（Python 3.11 + rasterio / geopandas / scikit-image / scipy / matplotlib / gdal）。
创建命令：
```
conda create -n flood python=3.11 rasterio geopandas scikit-image scipy matplotlib pandas gdal -c conda-forge -y
```

## 执行顺序

| 步骤 | 脚本 | 说明 |
|---|---|---|
| 1 | download_ftp.py | FTP 递归下载（断点续传）|
| 2 | extract_all.sh | 解压 → rasterio 校验 → 清理压缩包 |
| 3 | inspect_metadata.py | 生成《影像清单表》 |
| 4 | run_all_sar.py | 批量调用 extract_water_sar.py，逐景 SAR 水体提取（Lee 滤波 + 多类 Otsu 阈值 + 形态学清理），已完成的自动跳过 |
| 5 | build_date_mosaics.py | 掩膜重投影到 10 m UTM 网格、按日期拼接、坡度>8° 剔除山体阴影（坡度来自 data/processed/slope_grid.tif，由 data/dem 下 Copernicus DEM 生成） |
| 6 | change_detect.py | 变化检测：灾前水体 / 新增淹没（MMU 1 ha）/ 消退分析 + 面积统计 |
| 7 | make_maps.py | 渲染三张交付图件（山体阴影底图 + 叠加 + 比例尺/指北针/图例） |
| 8 | qa_zoom.py | 热点区抽查对比图（用法：python qa_zoom.py 经度 纬度 半径km 输出.png）|
| 9 | export_vectors.py | 结果矢量化导出 shp/geojson |

辅助：flood_core.py（核心函数库）、preview_mask.py（单景叠加预览）。

数据流向：data/raw → data/extracted → data/results（单景掩膜）→ data/processed（网格产品）→ data/results/final（最终栅格）→ deliverables（交付物）。
