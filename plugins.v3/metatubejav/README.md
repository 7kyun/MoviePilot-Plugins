# Metatube JAV 元数据

MoviePilot V3 插件，通过局域网 Metatube 服务为 JAV 资源提供搜索、识别、详情刮削和文件整理。

## 功能

- 按番号或标题搜索 Metatube 电影数据。
- 将 Metatube `MovieInfo` 映射为 MoviePilot V3 `MediaInfo`。
- 保留番号、标题、发行日期、演员、标签、制作商、评分、简介、时长和封面。
- 使用 `media_source=metatube-jav` 与 `media_id=<provider>:<番号>` 作为稳定媒体身份。
- 按 `番号 - 标题 (年份)/番号 - 标题.ext` 整理文件。
- 支持插件内目录监控，自动识别新加入的 JAV 视频并整理到目标目录。
- 清理文件系统非法字符，保留扩展名，目标冲突时自动追加 `-2`、`-3`。

## 版本与兼容性

这是 MoviePilot V3 插件，最低要求 MoviePilot `3.0.0`。插件放置在 `plugins.v3/metatubejav/`，不应复制到 V2 插件目录；V3 插件不能反向保证在 MoviePilot V2 中运行。

## 配置

在插件设置中填写：

- `Metatube URL`：例如 `http://192.168.6.205:19876`
- `API Token`：可选；无 Token 时留空
- 请求超时：默认 10 秒
- 监控目录：每行格式为 `监控方式#监控目录#目标目录#是否重命名`，例如 `fast#/downloads/jav#/media/JAV#true`。
- 转移方式为全局配置，支持 `move`、`copy`、`link`、`softlink`。
- 监控方式支持 `fast`（系统事件）和 `compatibility`（轮询，适合 SMB/NAS）。
- 立即运行一次：勾选后扫描并处理监控目录中已有文件，执行完成后自动关闭；平时仅处理新建/移动事件。
- 排除关键词：文件名命中任一关键词时跳过处理。
- 兼容模式轮询间隔：默认 10 秒。
- 转移方式支持 `move`、`copy`、`link`、`softlink`；仅匹配到 JAV 番号的视频会被处理。

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
