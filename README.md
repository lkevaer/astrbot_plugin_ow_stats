# 守望评分 · AstrBot 高清长图机器人

复用 [lkevaer/ow_stats_query](https://github.com/lkevaer/ow_stats_query) 的评分和 OCR 接口，提供独立 AstrBot 插件。无需大模型，支持 QQ 官方机器人 WebSocket、OneBot 和 AstrBot WebChat。

## 指令与作用

群聊先 @机器人，再输入指令。

| 指令 | 行为 |
| --- | --- |
| `/help`、`/帮助` | 查看本机器人的全部指令、作用和图片查询用法 |
| `/韩服数据 坦克`、`/韩服数据 输出`、`/韩服数据 辅助` | 查询韩服大师、竞技职责预选、所有地图、PC的英雄统计，按胜率从高到低返回完整中文长图 |
| `/绑定 昵称#12345` | 为当前发送者绑定或换绑默认战网ID |
| `/解绑` | 解除自己的绑定，保留其他群友绑定 |
| `/查询` | 查询自己绑定账号的近12场竞技评分 |
| `/查询 昵称#12345` | 临时查询指定账号的近12场竞技，不修改绑定 |
| `/查询休闲` | 查询自己绑定账号的近12场休闲评分 |
| `/查询休闲 昵称#12345` | 临时查询指定账号的近12场休闲，不修改绑定 |
| `/查询 ID1#12345 ID2#67890` | 多人查询、去重；自动加入已绑定的本人，最多10人 |
| `/查询` 并附一张名单截图 | 使用现有 OCR 识别完整ID后评分，自动加入本人并去重 |
| `/查询 图片` | 等待同一发送者在同一会话2分钟内发送一张截图；普通图片不会自动触发查询 |
| `/查询休闲` 附截图、或 `/查询休闲 图片` 后发送截图 | 使用相同图片识别流程查询近12场休闲 |

`/查询` 默认固定为竞技，`/查询休闲` 查询休闲，两种模式各取最近12场。两者都支持绑定账号、临时ID、多人名单、同条消息附图和两分钟内跟随截图。未绑定且不提供目标时，会提示输入ID或发送截图。旧写法 `/查询 休闲 昵称#12345`、`/查询 休闲 图片` 继续兼容。

`/help` 与 `/帮助` 返回同一份守望评分指令说明，并优先于 AstrBot 通用帮助处理，避免一次返回两份帮助。

绑定使用平台提供的真实发送者标识，按机器人实例隔离，保存到 `AstrBot/data/plugin_data/astrbot_plugin_ow_stats/bindings.sqlite3`。沿用旧插件的数据路径，升级时可直接保留。绑定只设置默认查询目标，不验证账号所有权。OCR 有疑项时暂停评分并提示核对，不擅自猜测。

## 返回图片

- 使用网页现有 HTML、CSS、JS 展示同一份服务返回数据，不在机器人中另算分。
- 汇总、分档、段位、MVP/CARRY/SVP/SMURF，以及每位玩家的逐场详情全部保留并展开。
- 自动按所有表格实际宽度扩展画布，输出单张 **2×像素密度的无损 PNG 长图**；不缩图、不转 JPEG。具体尺寸随人数和数据变化。
- 按短视口截图并逐段编码 PNG，避免在内存中创建整张长图画布，适用于小内存服务器。
- 去掉网页上传/粘贴截图、ID输入、网页账号绑定、复制和导出按钮。
- “完整评分参考”保持折叠，不把完整规则展开到图片中。
- 页脚突出显示“访问 lkevaer.xyz”和“进入网页版查询当局所有人评分评级”。战绩回复附本次网页结果链接；网页每场最左侧提供“查询当局”，自动提交完整10人或12人名单，机器人长图不显示网页按钮。

消息平台或客户端可能另行处理图片，查看时选择原图可保留插件输出的分辨率。

网页 UI 随插件一起保存，因此绘图不依赖公开首页是否登录、浏览器绑定数据或网页可用性。版本来源见 [report_ui/SOURCE.md](report_ui/SOURCE.md)。API 服务仍需正常运行且具有有效的上游账号授权。

韩服数据复用查询服务的 `/api/hero-rates` 缓存，不在每次机器人指令时重新抓取原站。默认组合预先同步；同一组合的角色与细分位置共用本地缓存。网页保留原站全部筛选项，新组合首次建立缓存，之后每24小时自动更新；刷新失败时保留上次数据并注明时间。英雄名称对应国服官网，UI保留原站的横幅、英雄头像、选取率/胜率/禁用率三列和彩色数据条。

## 安装到现有 AstrBot

1. 使用 Python 3.12 和 AstrBot 4.29.1（支持范围 `>=4.29.1,<5`）。
2. 在插件管理中从本仓库安装，或将本仓库放到 `AstrBot/data/plugins/astrbot_plugin_ow_stats`。
3. 使用 AstrBot 的 Python 安装依赖：`python -m pip install -r requirements.txt`。
4. Linux 运行 `python -m playwright install --with-deps chromium`，并安装 `fonts-noto-cjk`；Windows 可复用 Edge，或运行 `python -m playwright install chromium`。
5. 插件设置的 `api_url` 默认 `https://lkevaer.xyz`。服务要求访问码时，填写其 `OW_SERVER_API_KEY`。QQ AppID/AppSecret 仍在 AstrBot 的平台配置中设置。
6. 重新加载插件后，在测试会话发送 `/帮助` 查看用法，再测试绑定和两种查询模式。

服务器部署、数据迁移和容器方案见 [DEPLOYMENT.md](DEPLOYMENT.md)。仓库不包含账号凭据或绑定数据库。

## 本地检查和排版预览

在仓库根目录，使用能导入 AstrBot 的 Python 环境执行：

```sh
python -m unittest discover -s tests -t .. -v
python -m ruff check .
python -m ruff format --check .
```

核心和渲染测试只需要本仓库依赖；真实指令过滤器测试还需要 AstrBot。测试不会连接 QQ 或发送群消息。

```sh
python preview.py --players 5 --output output/preview-5players.png
```

预览使用标注为示例的合成数据，可离线生成长图。

## 来源

评分服务来自 [DustEater/ow_stats_query](https://github.com/DustEater/ow_stats_query) 及 [lkevaer/ow_stats_query](https://github.com/lkevaer/ow_stats_query) 的定制版本；此仓库延续之前的本地 `astrbot_plugin_ow_stats`。遵循 [GPL-3.0](LICENSE)。
