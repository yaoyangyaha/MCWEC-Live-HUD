# MCWEC-Live-HUD

一个用于 Minecraft 基岩版的赛车的实时直播 HUD。
（目前实现旗语控制和live timing）

Features：

- 使用 Python 作为服务端
- Minecraft 基岩版 WebSocket 接入
- 基于过线顺序的实时排名逻辑
- 可直接在 OBS 浏览器源中使用的透明网页组件
- 类似 F1 转播左侧排位塔台的 HUD 布局
- 最快圈高亮、进站提示、旗语状态 UI（有一些特效）
- 自动 FINAL LAP 提示
- 自定义赛事 LOGO 图片，名称，赛道
- 一站式快速部署

## 如何启动🤓

```bash
pip install -r requirements.txt
python main.py
```

默认使用的地址：

- HUD 页面: `http://127.0.0.1:8765/`
- 浏览器 WS: `ws://127.0.0.1:8765/ws/hud`
- Minecraft WS: `ws://127.0.0.1:8766`

## .env 配置🤓

现在可以直接编辑项目根目录下的 [.env](F:\code\MCWEC-Live-HUD\.env)：

```env
MCWEC_TITLE=MCWEC Live Timing
MCWEC_SESSION=RACE
MCWEC_TRACK_NAME=Minecraft Circuit
MCWEC_TOTAL_LAPS=20
```

可配置项：

- `MCWEC_TITLE` 侧栏赛事标题
- `MCWEC_SESSION` 会话标签，例如 `RACE`、`QUALIFYING`、`SPRINT`
- `MCWEC_TRACK_NAME` 赛道名称
- `MCWEC_TOTAL_LAPS` 总圈数（用于计算剩余圈数）
- `MCWEC_JAVA_LOG_DIR` Java 版客户端日志目录（可选），会跟随读取 `latest.log` 并解析包含 `[HUD]` 的行
- `MCWEC_JAVA_LOG_FILE` Java 日志文件名（可选，默认 `latest.log`）

项目也附带了一个示例文件 [\.env.example](F:\code\MCWEC-Live-HUD\.env.example)。

## FINAL LAP🤓

当前版本会自动根据领跑车的圈数判断最后一圈：

- 也就是当 `remaining_laps == 1` 时自动显示 `FINAL LAP`
- 中央会出现更醒目的状态横幅
- 左侧栏的剩余圈数会显示为 `FL` 标识

## 自定义 LOGO🤓

把你的赛事 LOGO 图片放到 `static` 目录，文件名用以下任意一个即可：

- `static/logo.png`
- `static/logo.webp`
- `static/logo.jpg`
- `static/logo.jpeg`
- `static/logo.svg`

检测到图片后，前端会自动优先显示该图片；如果没有，则回退到默认图形标识。

## Minecraft 接入方式🤓

让运行服务的一个玩家使用以下指令：

```mcfunction
/connect ws://127.0.0.1:8766
```

服务端会自动订阅 `PlayerMessage` 事件来实时改变情况。

## 过线事件格式🤓

当前内置支持通过聊天消息或者命令方块使用 `tellraw` 命令桥接检测圈速事件。
⚠️注意！消息需要以 `[HUD]` 开头。

JSON 格式：

```text
[HUD] {"player":"Steve","lap":3,"lap_time_ms":84521,"total_time_ms":251203}
```

键值格式：

```text
[HUD] player=Steve lap=3 lap_time_ms=84521 total_time_ms=251203
```

## 比赛控制相关事件🤓🤓

除了圈速，本项目也支持旗语和进站事件。

旗语：

```text
[HUD] type=flag flag=green
[HUD] type=flag flag=yellow message=Sector_yellow
[HUD] type=flag flag=red message=Session_stopped
[HUD] type=flag flag=sc
[HUD] type=flag flag=vsc
```

说明：

- `flag=green` 绿旗
- `flag=yellow` 黄旗
- `flag=red` 红旗
- `flag=sc` 安全车
- `flag=vsc` 虚拟安全车

进站：

```text
[HUD] type=pit player=Steve action=in
[HUD] type=pit player=Steve action=out
```

说明：

- `action=in` 进入维修区
- `action=out` 驶出维修区

通用提示：

```text
[HUD] type=notice title=Race_Control message=Restart_under_investigation
```

## HTTP 调试接口🤓

发送测试事件：

```bash
curl -X POST http://127.0.0.1:8765/api/event ^
  -H "Content-Type: application/json" ^
  -d "{\"player\":\"Steve\",\"lap\":1,\"lap_time_ms\":84521,\"total_time_ms\":84521}"
```

发送旗语：

```bash
curl -X POST http://127.0.0.1:8765/api/event ^
  -H "Content-Type: application/json" ^
  -d "{\"type\":\"flag\",\"flag\":\"yellow\",\"message\":\"Incident on track\"}"
```

发送进站：

```bash
curl -X POST http://127.0.0.1:8765/api/event ^
  -H "Content-Type: application/json" ^
  -d "{\"type\":\"pit\",\"player\":\"Steve\",\"action\":\"in\"}"
```

重置比赛：

```bash
curl -X POST http://127.0.0.1:8765/api/reset
```

向 Minecraft 发送命令：

```bash
curl -X POST http://127.0.0.1:8765/api/command ^
  -H "Content-Type: application/json" ^
  -d "{\"command\":\"say HUD online\"}"
```

## 如何在 OBS 作为插件使用🤓

在 OBS 中添加“浏览器”来源，URL 填写：

```text
http://127.0.0.1:8765/
```

如果 OBS 运行在别的机器上，就填运行此 Python 服务的那台电脑的局域网IP即可。

### 大功告成！🎉

## 尾声😋

本项目遵循`MIT License`\
感谢各位的支持！欢迎大家fork项目、提交Issue和PR！

### 贡献者：
<a href="https://github.com/yaoyangyaha/MCWEC-Live-HUD/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=yaoyangyaha/MCWEC-Live-HUD"  alt="Contributors"/>
</a>

部分功能测试：[手犮缶雚王](https://space.bilibili.com/1615189713)

### Buy Me A Coffee~
[ClickMe](https://afdian.com/a/YAOYANGYAHA666)
