# 南宁粮食 physical_site 门牌号地理编码复核报告

生成时间：2026-08-10T21:27:17+08:00

## 本轮结论

本轮仅复核4个明确门牌号节点。spatial_ready 从 5 增至 7，救回 2 个。
当前成功节点共 7 个：high 5 个，medium 2 个。
READY_FOR_CRS = true；验证状态 = PASS。

## 4个门牌号节点

- 南宁市储备粮管理有限责任公司沙井粮库：success / high / spatial_ready=true。唯一门牌强匹配候选通过逆地理行政区/道路复核。
- 南宁市邕宁区粮食储备库：success / medium / spatial_ready=true。唯一门牌强匹配候选通过逆地理行政区/道路复核。
- 南宁市江丰粮食收储管理中心：approximate_region_only / manual_review / spatial_ready=false。未找到目标区县+道路+门牌号完整匹配的精细候选；仅保留区域诊断，不写入坐标。
- 隆安县粮食收储有限责任公司古潭仓储点：approximate_region_only / manual_review / spatial_ready=false。未找到目标区县+道路+门牌号完整匹配的精细候选；仅保留区域诊断，不写入坐标。

## 诊断规则

- 先用纯结构化地址并传 city=南宁市；只有无法形成唯一强匹配时才使用“地址+简短设施名”。
- 多候选不再直接判歧义；按 city、district、township、street、number、level 逐项评分。
- 只有唯一满足目标区县、道路和门牌号的精细候选才进入逆地理验证。
- POI 兜底使用项目县级边界数据提供的区县 adcode，并启用 citylimit=true。
- 拟接受位置必须通过逆地理行政区和道路验证；乡镇中心点不会进入 spatial_ready。

## 仍未可靠定位

- 南宁市江丰粮食收储管理中心
- 马山县储备粮管理公司周鹿镇粮油网点19号仓库
- 隆安县粮食收储有限责任公司古潭仓储点
- 上林县安恒储备粮管理有限公司三里分公司
- 上林县安恒储备粮管理有限公司乔贤分公司
- 上林县安恒储备粮管理有限公司镇圩分公司

## 坐标与后续边界

所有成功坐标均保留为高德 GCJ-02 原始坐标。本轮未执行 EPSG:4490/项目 CRS 转换，也未关联1 km网格。

南宁核心粮食 physical_site 已形成第一批可用于空间网格分析的高可信节点集；下一阶段仍需先单独完成坐标系统一。
