# 网页界面快照

以下文件取自 `lkevaer/ow_stats_query` 的 `api_server/static/`，提交为 [`d37d07f71dd0b1517a08270bd079fe7f2c32d7ea`](https://github.com/lkevaer/ow_stats_query/commit/d37d07f71dd0b1517a08270bd079fe7f2c32d7ea)。

| 文件 | Git blob SHA |
| --- | --- |
| `batch_rating.html` | `6415e892bcd9c21135a58a1c11852f77316a7d13` |
| `batch_rating.css` | `ac37c94843d69db99a194a7218f197a97ad9941f` |
| `batch_rating.js` | `86a9f1426dfe2859c6a9631180d4c57c116328cc` |
| `rating_account.js` | `6569ad7469750f71c31981b61171c08bdab0c10e` |
| `hero_rates.html` | `0bec9af0fa239d774a726a31207292017941d671` |
| `hero_rates.css` | `6e38b930fbdcdc848890bd8407bb11ba5aba7734` |
| `hero_rates.js` | `4b701ed8bfe7f4cb007604adfae1d44c616a502b` |
| `hero_rates_banner.png` | `0db867f896c8b05b4ba5d55600d409efe74b8c63` |

机器人专用调整集中在 `render.py`：移除网页操作按钮，展开战绩详情，强化网页版入口；韩服统计替换为静态筛选说明。这里只渲染服务返回的数据，不复制后端评分算法或每次抓取原站。

英雄统计数据与横幅来自 [Nexon 官方页面](https://overwatch.nexon.com/hero/rate)，国服名称对应 [国服官网英雄配置](https://ld5.res.netease.com/pc/zt/20241115153332/static/heroConfigs.json)。原项目采用 GPL-3.0，本仓库保留相同许可证及来源声明。
