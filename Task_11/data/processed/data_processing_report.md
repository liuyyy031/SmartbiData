# 广西社会应急保供节点原始数据处理报告

> 本报告只覆盖原始资料识别、抽取、标准化、保守去重与质量验证。未进行最终节点筛选、洪涝路径计算、1 km 网格关联或地图 API 地理编码。

## 处理结果摘要

- data/raw 递归发现：55 个文件；成功解析 8 个主数据文件；网页附属资源 47 个；失败 0 个。
- 原始记录层：1566 条 source records。
- 保守聚合后：1243 个 candidates；合并的重复出现记录数为 323。
- 南宁市 primary：67 个；柳州市 secondary：19 个。
- 桂财税〔2024〕8号 HTML：共 366 条；南宁 38/38，柳州 16/16，自治区直属 18 条。
- 南宁新增储备体系分类：grain_depot=7、grain_reserve=31、military_grain_supply=0；柳州分别为 4、7、3。
- 第二批国家级粮食应急保障企业名单正确识别：True；SHA-256 重复原始文件组：0。
- 广西其他地区 reserve：458 个；广西以外或当前无法确认为广西的 external：699 个。
- 地址完整：125 个；信用代码完整：125 个；已有坐标：0 个。
- 验证结论：**WARN**。

## 原始文件与抽取情况

| 文件 | 实际类型 | 来源类别 | 状态 | 抽取记录 | 说明 |
|---|---|---|---|---:|---|
| beihai_food_suppliers.pdf | pdf | government_procurement | parsed | 52 | 成功抽取 52 条原始记录。 |
| guangxi_reserve_companies_2024.html | html | grain_reserve | parsed | 366 | 成功抽取 366 条原始记录。 |
| 2052.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| ABUIABAEGAAg-fKWvQYouar0mQEwggM4Qg.png | png | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| ABUIABAEGAAg_b34kgYonqTi7wQwmwI4oAI.png | png | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| ABUIwsTiCxADGAAgjJassQYo0uPE7QUwgAU4dw.gif | gif | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| ABUIwsTiCxADGAAgjJassQYo1NbJ5AYwgAU4sgE.gif | gif | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| ABUIwsTiCxADGAAgjJassQYojeLB9wEwgAU4yAE.gif | gif | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| ABUIwsTiCxADGAAgjJassQYomPyUlgYwgAU45AI.gif | gif | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| ABUIwsTiCxADGAAgjJassQYonIH21QEwgAU4dw.gif | gif | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| ABUIwsTiCxAEGAAgjJassQYoqNj-4AYwuAg4gA8.png | png | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| base2.min.css | css | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| bizShared.min.css | css | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| bizShared.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| comMethods.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| crash.html | html | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| detail2.min.css | css | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| fkNav.min.css | css | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| fkTheme.min.css | css | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| fontsIco.min.css | css | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| frontend.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| hawkEye.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| imageEffect.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| index.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| jquery-core.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| jquery-mousewheel.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| jquery-ui-core.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| jzcusstyle.jsp | unknown | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| jzRequest.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| jzUtils.min(1).js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| jzUtils.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| login.min.css | css | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| module.min.css | css | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| module.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| newSearchBoxStyle.min.css | css | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| outerChain.jsp | unknown | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| partitionSite.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| photoSlide.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| polyfill.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| push.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| qrCode(1).jsp | png | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| qrCode.jsp | png | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| site.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| siteBase2.min.css | css | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| svg.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| themeMixin.min.css | css | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| validateCode.jsp | jpeg | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| vue-2.7.14.min.js.下载 | javascript | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| webRightBar.min.css | css | other | ancillary | 0 | HTML 完整网页保存产生的附属资源；已登记但不作为独立节点来源解析。 |
| guigang_food_suppliers_310.pdf | pdf | government_procurement | parsed | 310 | 成功抽取 310 条原始记录。 |
| moa_designated_wholesale_markets_2024.pdf | pdf | wholesale_market | parsed | 663 | 成功抽取 663 条原始记录。 |
| national_emergency_grain_enterprises_2025_reassessment.wps | wps_ole_compound | grain_emergency | parsed | 46 | 成功抽取 46 条原始记录。 |
| national_emergency_grain_enterprises_batch2.pdf | pdf | grain_emergency | parsed | 51 | 成功抽取 51 条原始记录。 |
| pingguo_meat_suppliers.pdf | pdf | government_procurement | parsed | 40 | 成功抽取 40 条原始记录。 |
| pingguo_vegetable_fruit_suppliers.pdf | pdf | government_procurement | parsed | 38 | 成功抽取 38 条原始记录。 |

### 解析失败文件

无。全部原始文件均成功生成记录；WPS/OLE 文件经只读转换后解析。

## node_type 分布

| 类别 | 数量 |
|---|---:|
| agricultural_wholesale_market | 663 |
| grain_reserve | 223 |
| government_procurement_supplier | 163 |
| other | 81 |
| grain_depot | 58 |
| emergency_processing | 28 |
| military_grain_supply | 26 |
| emergency_storage_transport | 1 |

## evidence_level 分布

| 类别 | 数量 |
|---|---:|
| A | 1030 |
| C | 146 |
| B | 67 |

## 缺地址记录

共有 1118 个 candidate 缺地址。完整清单位于 `geocoding_pending.csv` 中 `geocoding_status=missing_address` 的记录。按来源组合统计如下：

| 来源类别组合 | 数量 |
|---|---:|
| wholesale_market | 663 |
| grain_reserve | 366 |
| grain_emergency | 51 |
| government_procurement | 38 |

前 30 条示例：

| candidate_id | 名称 | 所在地解析 |
|---|---|---|
| cand_dcc920b6c18eefab | 东莞市太粮米业有限公司 | // |
| cand_101d0e2c28b6012d | 个旧市大红屯粮食购销有限公司 | // |
| cand_a1cf75cc4bd6dd88 | 中国邮政集团有限公司 | // |
| cand_8cc1df99536db614 | 五常市乔府大院农业股份有限公司 | // |
| cand_81c4b7f8c4561e69 | 光明农业发展(集团)有限公司 | // |
| cand_e6c335c93672eb99 | 发达面粉集团股份有限公司 | // |
| cand_8f48238345939eb9 | 喀什天山面粉有限公司 | // |
| cand_d10dd91b1cf759fd | 固始县豫申粮油工贸有限公司 | // |
| cand_a16da0615e7d4a72 | 固安县参花面粉有限公司 | // |
| cand_91e48d5e21ade1ce | 宏盛粮油集团股份有限公司 | // |
| cand_98f3cf1d03ba9d88 | 宜昌粮食集团有限公司 | // |
| cand_e5bcae05358eb0d3 | 宝鸡祥和面粉有限责任公司 | // |
| cand_7723b2aab95018f3 | 康师傅方便面投资(中国)有限公司 | // |
| cand_7bc4f2f54bf6d8f9 | 德州军粮食品产业集团有限公司 | // |
| cand_f854ac602ba4c807 | 成都粮食集团有限公司 | // |
| cand_5c2b9b41788f059f | 成都红旗连锁股份有限公司 | // |
| cand_252446ca8e8039c2 | 松原市巨大粮油食品有限公司 | // |
| cand_e97f0dc9c2ff7486 | 株洲市湘东仙竹米业有限责任公司 | // |
| cand_41bb1a66d5db2d05 | 渭南长安花粮油有限公司 | // |
| cand_b06c42b8fa1ee5bf | 益海嘉里金龙鱼食品股份有限公司 | // |
| cand_9aeea2776d55194c | 福州恒丰米业有限公司 | // |
| cand_9d608911c917421c | 绵阳仙特米业有限公司 | // |
| cand_f53056adc9a0dbc2 | 莆田市利源米业有限公司 | // |
| cand_e5962a1e813e5148 | 营口禾丰源米业有限公司 | // |
| cand_6efecf212d20108c | 鄱阳湖生态农业股份有限公司 | // |
| cand_ecf5e7263a38946e | 金光食品(宁波)有限公司 | // |
| cand_adba4378970afa36 | 金沙河集团有限公司 | // |
| cand_d3ea247530cd6e95 | 青岛天祥食品集团有限公司 | // |
| cand_1915ddf771adcf36 | 香驰控股有限公司 | // |
| cand_b55d5a0ff2a6f329 | 上海农产品中心批发市场经营管理有限公司 | 上海市/上海市/ |

## 地理编码待办

共有 1243 个 candidate 没有完整经纬度：missing_address=1118，pending=125。
本阶段未调用任何地图 API，也未用城市或县区中心点填充伪坐标。

## 疑似重复与实体层级复核

`duplicate_review.csv` 共列出 49 对。只有信用代码完全一致且实体层级一致、或标准化名称完全一致且实体层级一致的记录已自动聚合；公司主体与具体粮库、市场、基地、网点保持分离。

| 名称 1 | 名称 2 | 原因 | 建议 |
|---|---|---|---|
| 宁夏中卫四季鲜农产品综合批发市场 | 宁夏四季鲜农产品综合批发市场 | high_name_similarity=0.933 | manual_review |
| 福建福州民天实业有限公司海峡果品批发市场 | 福建福州民天实业有限公司海峡蔬菜批发市场 | high_name_similarity=0.900 | manual_review |
| 贵州贵阳农产品物流园 | 贵州贵阳地利农产品物流园 | high_name_similarity=0.909 | manual_review |
| 上林县安恒储备粮管理有限公司 | 上林县安恒储备粮管理有限公司三里分公司 | organization_name_contains_specific_site_name | keep_separate |
| 上林县安恒储备粮管理有限公司 | 上林县安恒储备粮管理有限公司乔贤分公司 | organization_name_contains_specific_site_name | keep_separate |
| 上林县安恒储备粮管理有限公司 | 上林县安恒储备粮管理有限公司塘红万福分公司 | organization_name_contains_specific_site_name | keep_separate |
| 上林县安恒储备粮管理有限公司 | 上林县安恒储备粮管理有限公司塘红分公司 | organization_name_contains_specific_site_name | keep_separate |
| 上林县安恒储备粮管理有限公司 | 上林县安恒储备粮管理有限公司大丰分公司 | organization_name_contains_specific_site_name | keep_separate |
| 上林县安恒储备粮管理有限公司 | 上林县安恒储备粮管理有限公司巷贤分公司 | organization_name_contains_specific_site_name | keep_separate |
| 上林县安恒储备粮管理有限公司 | 上林县安恒储备粮管理有限公司明亮分公司 | organization_name_contains_specific_site_name | keep_separate |
| 上林县安恒储备粮管理有限公司 | 上林县安恒储备粮管理有限公司澄泰分公司 | organization_name_contains_specific_site_name | keep_separate |
| 上林县安恒储备粮管理有限公司 | 上林县安恒储备粮管理有限公司澄泰金鼓分公司 | organization_name_contains_specific_site_name | keep_separate |
| 上林县安恒储备粮管理有限公司 | 上林县安恒储备粮管理有限公司白圩分公司 | organization_name_contains_specific_site_name | keep_separate |
| 上林县安恒储备粮管理有限公司 | 上林县安恒储备粮管理有限公司白圩狮螺分公司 | organization_name_contains_specific_site_name | keep_separate |
| 上林县安恒储备粮管理有限公司 | 上林县安恒储备粮管理有限公司西燕分公司 | organization_name_contains_specific_site_name | keep_separate |
| 上林县安恒储备粮管理有限公司 | 上林县安恒储备粮管理有限公司镇圩分公司 | organization_name_contains_specific_site_name | keep_separate |
| 上林县安恒储备粮管理有限公司乔贤分公司 | 上林县安恒储备粮管理有限公司巷贤分公司 | high_name_similarity=0.947 | manual_review |
| 上林县安恒储备粮管理有限公司塘红万福分公司 | 上林县安恒储备粮管理有限公司塘红分公司 | high_name_similarity=0.950 | manual_review |
| 上林县安恒储备粮管理有限公司澄泰分公司 | 上林县安恒储备粮管理有限公司澄泰金鼓分公司 | high_name_similarity=0.950 | manual_review |
| 上林县安恒储备粮管理有限公司白圩分公司 | 上林县安恒储备粮管理有限公司白圩狮螺分公司 | high_name_similarity=0.950 | manual_review |
| 上林县安恒储备粮管理有限公司白圩分公司 | 上林县安恒储备粮管理有限公司镇圩分公司 | high_name_similarity=0.947 | manual_review |
| 上林县安恒储备粮管理有限公司白圩狮螺分公司 | 上林县安恒储备粮管理有限公司镇圩分公司 | high_name_similarity=0.900 | manual_review |
| 南宁市储备粮管理有限责任公司 | 南宁市储备粮管理有限责任公司五象粮库 | organization_name_contains_specific_site_name | keep_separate |
| 南宁市储备粮管理有限责任公司 | 南宁市储备粮管理有限责任公司沙井粮库 | organization_name_contains_specific_site_name | keep_separate |
| 南宁市储备粮管理有限责任公司 | 南宁市邕宁区储备粮管理有限责任公司 | high_name_similarity=0.903 | manual_review |
| 广西南宁福象粮油有限公司 | 广西福象粮油有限公司 | high_name_similarity=0.909 | manual_review |
| 广西康然生态农业有限公司 | 广西桂然生态农业有限公司 | high_name_similarity=0.917 | manual_review |
| 隆安县储备粮管理公司 | 融安县储备粮管理公司 | high_name_similarity=0.900 | manual_review |
| 广西平果先优创供应链管理有限公司 | 广西平果创益供应链管理有限公司 | high_name_similarity=0.903 | manual_review |
| 广西全州国家粮食储备库 | 广西梧州国家粮食储备库 | high_name_similarity=0.909 | manual_review |

仅展示前 30 对；完整 49 对见 `duplicate_review.csv`。

## 验证结果

### 警告

- 1118 个 candidate 缺少地址；主要来自仅含名称的官方名单或未提供地址的采购表。
- 49 对疑似重复或组织/设施层级关系需要人工复核。

## 当前数据的突出问题

1. 桂财税〔2024〕8号 HTML 能证明名单内单位的储备体系身份，但名单主体没有提供地址、坐标、仓容、库存或实时可调拨量；章节只能安全支持地级市归属。
2. 自治区直属单位不能仅凭章节定位地级市；只有名称或其他来源能明确定位时才进入 primary/secondary，其余保留为 reserve。
3. 第二批国家级粮食应急保障企业名单提供 51 个企业名称，2025 重新评估名单提供后续证据；仅对来源明确写出的“原名”关系合并，仍普遍缺少具体设施地址和能力细分。
4. 农业农村部定点市场名单提供全国市场名称但没有地址与坐标；广西市场详细落点需后续官方地址补证。
5. 采购供应商地址可能只是登记或联系地址。只有原文明确出现仓库、粮库、配送中心、冷库、厂房等词时才标记相应能力。
6. 网页保存目录中的脚本、样式和图片已进入 inventory 并标记为 ancillary，不作为独立业务数据源抽取。
7. 所有候选均未猜测坐标、仓容、库存或供应量；缺地址记录仍是进入地理编码前最主要的补证工作。

## 追溯与复现

每个 candidate 的 `source_record_ids` 指向 `supply_source_records.csv`；每条 source record 的 `source_file_id` 和 `source_file` 再指向 `raw_file_inventory.csv` 与 data/raw 实际文件。验证脚本已检查完整链路。

复现命令：

```powershell
python scripts/run_pipeline.py
```

若在全新环境处理旧式 WPS/OLE 文件，需要安装 WPS Office 并可用 `kwps.Application` COM；否则该文件会明确记为 failed，不会导致其他文件处理中止。

## 建议的下一步（本阶段不执行）

当前已具备进入“地址补全与可审计地理编码”阶段的数据基础。建议先为南宁、柳州粮库和储备企业补齐官方地址与设施层级证据，再调用明确授权的地图服务；仍不应开始最终节点筛选。
