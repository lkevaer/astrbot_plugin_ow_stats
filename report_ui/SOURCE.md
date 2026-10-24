# 网页界面快照

以下文件取自 `lkevaer/ow_stats_query` 的 `api_server/static/`，提交为 [`f3ae59bed3daa7d8c918a591e0faad2e2bb06fdd`](https://github.com/lkevaer/ow_stats_query/commit/f3ae59bed3daa7d8c918a591e0faad2e2bb06fdd)。

| 文件 | Git blob SHA |
| --- | --- |
| `batch_rating.html` | `495f1055efa064e4531929f8fcd23265ec550158` |
| `batch_rating.css` | `fc6112f6b566f3f71b4805faf9d6a723cad67c8f` |
| `batch_rating.js` | `26c0ab97936d4ba6460522b47c029804ffb7fa6a` |
| `rating_account.js` | `6569ad7469750f71c31981b61171c08bdab0c10e` |
| `hero_rates.html` | `747fc416d6523ba1cca7cff486d849766790f7ef` |
| `hero_rates.css` | `312da9760b71dea323501450fefa6038ce0b4e32` |
| `hero_rates.js` | `70ea2014065f957067f83847990a2aa0f3cc327b` |
| `hero_rates_banner.png` | `0db867f896c8b05b4ba5d55600d409efe74b8c63` |

机器人专用调整集中在 `render.py`：逐场原始数值转为静态文本，移除网页操作按钮、评分提示与当局子表；仅展开查询玩家原有战绩。页脚和消息均使用 HTTPS 网页入口。韩服统计替换为静态筛选说明，禁用行与数据条动画，保留完整数据。这里只渲染服务返回的数据，不复制后端评分算法或每次抓取原站。

英雄统计数据与横幅来自 [Nexon 官方页面](https://overwatch.nexon.com/hero/rate)，国服名称对应 [国服官网英雄配置](https://ld5.res.netease.com/pc/zt/20241115153332/static/heroConfigs.json)。原项目采用 GPL-3.0，本仓库保留相同许可证及来源声明。
