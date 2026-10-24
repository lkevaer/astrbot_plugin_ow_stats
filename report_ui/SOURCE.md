# 网页界面快照

以下四个文件原样取自 `lkevaer/ow_stats_query` 的 `api_server/static/`，提交为 [`c977c6fa80dd52d7d75a3af75209b0852bdf3df8`](https://github.com/lkevaer/ow_stats_query/commit/c977c6fa80dd52d7d75a3af75209b0852bdf3df8)，对应可部署版本 `deploy-2026.10.24`。

| 文件 | Git blob SHA |
| --- | --- |
| `batch_rating.html` | `45937c5a06a225af5c568d29ce96c362a121d407` |
| `batch_rating.css` | `96d3383e3a332bf10f89ab11402133a024619c39` |
| `batch_rating.js` | `a4cc30c0784ed98c70183b52000a080991479d25` |
| `rating_account.js` | `6569ad7469750f71c31981b61171c08bdab0c10e` |

机器人专用的展示调整集中在仓库根目录的 `render.py`，不会修改网页快照中的评分展示函数。这里只渲染服务返回的数据，没有复制后端评分算法。将来同步网页UI时，替换这四个文件并重新运行渲染测试。

原项目采用 GPL-3.0，本仓库保留相同许可证及来源声明。
