# 网页界面快照

UI及英雄、地图、段位本地图标取自 [lkevaer/ow_stats_query](https://github.com/lkevaer/ow_stats_query/commit/a4583252500c557dbe91fa9a882b043a136bcd9e) 的 `api_server/static/`。全部文件和SHA-256见 [MANIFEST.json](MANIFEST.json)，自动检查验证资源完整性。

此快照包含 v10 评分说明、顶部淡红色贡献提醒、灰色BOT标签、有限零阵亡KD以及空数据维护提示。评分数值由后端返回，前端不重复计算评分规则。

机器人专用处理集中在 `render.py`：移除输入、排序、查询当局和全员子表操作，仅展开查询玩家的逐场战绩，规则保持折叠。评分仍由后端计算；长图没有新增网页子表。图片仅从固定同源UI资源读取，英雄、地图、段位均有默认图兜底。

统计来源为 [Nexon官方](https://overwatch.nexon.com/hero/rate)，国服名称来源为国服官方英雄配置。游戏素材的权利不因代码采用GPL-3.0而改变，来源说明见网页仓库 `THIRD_PARTY.md`。
