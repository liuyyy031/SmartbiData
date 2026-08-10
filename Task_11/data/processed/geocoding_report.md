# 南宁、柳州社会应急保供节点地理编码报告

> 本轮只处理 analysis_priority=primary/secondary。未删除其他 candidates，未执行 CRS 转换、1 km 网格关联、洪涝分析或最终节点筛选。

## 结果摘要

- 目标：86 个，其中南宁 67 个、柳州 19 个。
- 原有明确地址：20 个；通过地图 POI 新补地址：10 个。
- 成功获得原始地图坐标：26 个，其中南宁 23 个、柳州 3 个。
- high confidence：7 个；medium confidence：19 个。
- manual review：59 个；failed：1 个。
- physical_site 成功：0 个；organization 成功：23 个。
- API 请求：91 次；成功缓存命中：8 次。

## 服务与坐标系

- 地图服务：高德 Web 服务 API。
- provider 分布：{"amap": 26}。
- 原始坐标系分布：{"GCJ02": 26}。
- 高德国内地图服务坐标按 GCJ-02 保存为 `longitude_raw` / `latitude_raw`；未冒充 EPSG:4490，也未执行坐标转换。
- API 原始响应逐 candidate 缓存在 `data/interim/geocoding_cache/`，缓存不含 API Key。

## 尚未可靠定位的重点节点

- 南宁市储备粮管理有限责任公司五象粮库
- 南宁市储备粮管理有限责任公司沙井粮库
- 南宁市邕宁区粮食储备库
- 南宁市江丰粮食收储管理中心
- 横州市六景粮食储备中心库
- 马山县储备粮管理公司
- 隆安县储备粮管理公司
- 上林县安恒储备粮管理有限公司
- 广西壮族自治区五象粮食储备库有限公司
- 广西壮族自治区南宁粮食储备库有限公司
- 柳州市五里卡粮库有限公司
- 广西柳州黄村粮食储备库有限公司
- 广西壮族自治区柳州粮食储备库有限公司
- 柳城县金稻香粮食收储有限责任公司
- 柳州市柳江区柳粮粮油有限公司
- 融水苗族自治县储备粮管理公司
- 三江侗族自治县粮食购销和储备粮管理中心
- 融安县储备粮管理公司

## 质量验证

- 错误：0；警告：1。
- WARN：60 条记录需要人工复核或后续重试。

## 后续阶段判断

只有在重点 physical_site 获得可靠坐标、人工复核项处理完毕后，才适合统一转换到项目 CRS。
在 CRS 尚未统一且重点粮库仍有未定位记录时，不适合直接关联 1 km 网格。

## 官方接口依据

- 高德地理编码：https://lbs.amap.com/api/webservice/guide/api/georegeo/
- 高德 POI 搜索：https://lbs.amap.com/api/webservice/guide/api/search/
- 高德坐标系说明：https://lbs.amap.com/api/uri-api/guide/mobile-web/point
