# Metatube JAV 元数据

MoviePilot V3 插件，通过自身目录监控调用局域网 Metatube，为 JAV 资源执行识别、刮削和文件整理。

## 功能

- 仅扫描插件配置的目录，不注册 MoviePilot 全局媒体源或识别 provider。
- 将 Metatube `MovieInfo` 映射为 MoviePilot V3 `MediaInfo`。
- 保留番号、标题、发行日期、演员、标签、制作商、评分、简介、时长和封面。
- 使用 `media_source=metatube-jav` 与 `media_id=<provider>:<番号>` 作为稳定媒体身份。
- 整理完成后默认调用 MoviePilot 刮削链，写入 NFO 并下载 Metatube 提供的海报和背景图。
- 支持独立的 JAV 刮削任务，可按目录定期扫描或立即执行一次。
- 按 `番号 - 标题 (年份)/番号 - 标题.ext` 整理文件。
- 支持插件内目录监控，自动识别新加入的 JAV 视频并整理到目标目录。
- 清理文件系统非法字符，保留扩展名，目标冲突时自动追加 `-2`、`-3`。

## 版本与兼容性

这是 MoviePilot V3 插件，最低要求 MoviePilot `3.0.0`。插件放置在 `plugins.v3/metatubejav/`，不应复制到 V2 插件目录；V3 插件不能反向保证在 MoviePilot V2 中运行。

## 配置

插件卡片点击后直接进入配置页；本插件不提供独立详情面板。

在插件设置中填写：

- `Metatube URL`：例如 `http://192.168.6.205:19876`
- `API Token`：可选；无 Token 时留空
- 请求超时：默认 10 秒
- 监控目录支持换行批量配置，每行格式为 `处理模式#监控目录#目标目录#转移方式#是否重命名#覆盖模式`，例如 `fast#/downloads/jav#/media/JAV#link#true#never`。
- 转移方式支持 `move`、`copy`、`link`、`softlink`；覆盖模式支持 `never`、`always`、`by_size`、`latest`。
- 处理模式支持 `fast`（性能模式）和 `compatibility`（兼容模式，适合 SMB/NAS）。两者是 MoviePilot 目录监控的性能选择，不是转移方式。
- 立即运行一次：勾选后扫描并处理监控目录中已有文件，执行完成后自动关闭；平时仅处理新建/移动事件。
- 排除关键词：文件名命中任一关键词时跳过处理。
- 兼容模式轮询间隔：默认 10 秒。
- 转移方式支持 `move`、`copy`、`link`、`softlink`；仅匹配到 JAV 番号的视频会被处理。
- 独立刮削：在第二个配置表单中填写刮削监控目录（每行一个），选择是否覆盖已有元数据和图片；可配置 Cron 周期，留空时每 7 天执行一次。刮削仅处理可识别到 JAV 番号的视频，支持单独配置排除目录。

也支持环境变量：

```env
METATUBE_URL=http://metatube:8080
METATUBE_TOKEN=
METATUBE_TIMEOUT=10
```

## Metatube API

插件使用 Metatube SDK v1.4 的路由：

```text
GET /v1/movies/search?q=<keyword>&fallback=true
GET /v1/movies/<provider>/<id>?lazy=true
```

例如详情身份为 `JavBus:SSNI-999` 时，provider 是 `JavBus`，id 是 `SSNI-999`。

## 开发验证

插件核心逻辑不依赖额外 Python 包。仓库根目录可运行：

```bash
python3 -m compileall -q plugins.v3/metatubejav
```
