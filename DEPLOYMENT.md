# 未来部署到 lk：独立机器人项目

此仓库包含 AstrBot 插件和可选的独立容器方案。战绩网页服务继续使用 `lkevaer/ow_stats_query`；此插件通过 HTTP 调用该服务，不需要再部署一套评分数据库。

当前交付只保存代码与部署配置。lk 上已有的网页服务无需为本插件修改。

## 已有 AstrBot

将插件仓库安装到 `AstrBot/data/plugins/astrbot_plugin_ow_stats`，使用同一个 Python 环境安装本仓库 `requirements.txt`，安装 Chromium 与中文字体后重载插件。详见 [README.md](README.md)。

若已有同名旧插件，请在停止 AstrBot 后备份原插件目录，再用本版源码替换；保留 `data/config` 与 `data/plugin_data`。不要同时加载两份注册了相同指令的旧、新插件。

## 新建独立容器

服务器需要 Docker 和 Docker Compose。将仓库放到独立目录，例如 `/opt/astrbot_ow_stats`：

```sh
git clone https://github.com/lkevaer/astrbot_plugin_ow_stats.git /opt/astrbot_ow_stats
cd /opt/astrbot_ow_stats
docker compose up -d --build
```

镜像基于官方 `soulter/astrbot:v4.29.1`，增加 Chromium、中文字体和插件。构建需要联网下载依赖与浏览器。`compose.yaml` 只将管理界面映射至服务器本机 `127.0.0.1:6185`，QQ 官方 WebSocket 通过出站连接工作。

从自己电脑建立端口转发后，访问本机 `http://127.0.0.1:6185` 管理机器人：

```sh
ssh -L 6185:127.0.0.1:6185 lk
```

在 AstrBot 的机器人设置配置 QQ 官方 WebSocket 平台；在插件设置填写：

| 字段 | 配置 |
| --- | --- |
| `api_url` | `https://lkevaer.xyz`，或容器可访问的现有战绩服务地址 |
| `api_key` | 现有战绩服务的 `OW_SERVER_API_KEY`；未启用访问码时留空 |
| `default_mode` | `competitive`；可选 `leisure` |
| `timeout_seconds` | 默认300秒 |

战绩服务只监听宿主机回环地址时，另一个容器不能直接用 `127.0.0.1:41888` 访问它；使用 HTTPS 站点或将两个服务加入同一 Docker 网络后配置服务名。

QQ AppSecret、战绩服务访问码和网易大神 Token 是不同凭据，各自留在对应服务的私有配置中。

## 迁移本地已有绑定

停止源 AstrBot，将其 `data/plugin_data/astrbot_plugin_ow_stats/` 复制到新容器挂载的同名路径。需要沿用平台配置和其他机器人设置时，可迁移整个 AstrBot `data/`，同时保留正确的平台实例ID，以继续使用原来的发送者绑定。停止后复制可确保 SQLite 及其 WAL 状态一致。

宿主机 `./data` 挂载到 `/AstrBot/data`；更新镜像会刷新插件源码，账号配置和绑定数据库保留在此目录。

## 验证与更新

```sh
docker compose ps
docker compose logs --tail=80 astrbot
```

确认插件加载成功，然后在测试会话依次验证 `/绑定 昵称#12345`、`/查询`、`/查询 图片`、`/解绑`。查看收到的原图，检查最后一位玩家的第12场详情及底部规则链接。

更新前保存 `./data` 的备份，再拉取仓库的新版本并重建：

```sh
git pull --ff-only
docker compose up -d --build
```

保留原目录及 `./data`。如需固定版本，可切换到此仓库的 `v2.0.0` 标签。WebUI 内更新插件可能需要相同版本的浏览器依赖；容器方式统一通过镜像重建更新。
