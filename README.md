# AI Pulse

一个本地运行的 Windows AI 用量监控桌面应用。用同一个面板查看不同 AI 编程工具的 Token 用量、API 额度折算、请求记录与速度趋势。应用源码 MIT 开源。

## v0.2 界面更新

界面迁移到 Qt 原生高 DPI 渲染。取消为适应屏幕而整体缩小界面的处理，字体和图表按显示器缩放比例绘制。采用中性深色灰阶界面与沉浸式深色窗口边框、五列指标卡（含 API 额度与人民币折算）、矢量曲线与悬停提示、软件 / 模型分布和请求明细表格。小屏幕使用滚动区域，不压缩文字。

Qt 依赖采用开放目录形式打包，请保留 EXE 同级的 `_internal` 文件夹；不要只复制 EXE。

## 功能

- 原生桌面窗口，中性深色界面（自动覆盖 Windows 11 蓝色活动边框），支持窗口缩放。
- 按软件、今天 / 近 7 天 / 全部记录筛选。
- 输出 / 输入 / 思考 / 缓存读取 Token、最近请求与加权平均速度。
- 本地 Token 用量自动折算为官方公开 API 美元额度（`$`）与人民币金额（`¥`），直观展示各软件、各模型与单次请求的等效额度及缓存节省金额，支持自定义汇率与模型单价。
- 每 3 秒检查本地记录，增量读取新增行，支持暂停。
- **Codex 额度**：读取 Codex 日志中官方记录的 5 小时 / 每周额度已用百分比与重置时间，显示剩余额度。
- **预算提醒**：可设每日 / 每月人民币预算，达到 80% 与 100% 时托盘通知，手机页面同步显示。
- **每日历史与项目分布**：近 30 天每日折算额度柱状图；按工作目录（Codex / Claude Code / WorkBuddy 日志中的 cwd）统计各项目用量。
- **后台运行**：关闭窗口后最小化到系统托盘继续统计；可选开机自动启动（写入当前用户的启动项，无需管理员权限）。重复打开程序时会唤出已运行的窗口。
- 修改记录目录，导入标准 JSONL，导出含折算额度与项目目录的 CSV。
- 可选“手机查看”：在手机浏览器中查看同样的统计，支持通过 Cloudflare 通道在外网访问（默认关闭）。
- 无遥测、无需 API Key；未开启手机查看时完全离线运行。

## 额度、预算与后台运行

- **Codex 额度**：数值来自 Codex 写入本地日志的最近一次额度快照（每次请求后更新），卡片提示快照时间；重置时间已过时显示为已重置。剩余不足 10% 时托盘提醒。Claude Code 等其他软件的日志没有官方额度数据，因此不显示剩余百分比。
- **预算**：在“设置 → 常规与预算”中填写每日 / 每月预算（人民币，按折算额度计算，留空不限制）。每个预算周期内 80% 与 100% 各提醒一次。
- **托盘**：默认关闭窗口即最小化到托盘，右键托盘图标可暂停同步或退出；可在“设置 → 常规与预算”中关闭此行为。勾选“开机自动启动”后登录 Windows 时程序会直接在托盘中运行，配合手机查看可随时在外面查看。

## 手机查看

点击工具栏“手机查看”，勾选“开启手机查看”后保存，用手机扫描弹出的二维码即可打开手机版页面（也可“添加到主屏幕”当作 App 使用）。页面每 5 秒刷新，支持按软件和时间范围筛选。

- **外网访问**：勾选“外网访问”后，程序启动 `cloudflared` 建立 Cloudflare 通道，生成 `https://….trycloudflare.com` 地址，手机在任何网络下都能打开。需先安装 cloudflared（`winget install --id Cloudflare.cloudflared`），程序会自动识别；也可在高级设置中填写路径。
- **地址变化**：免费的临时通道每次启动程序都会分配新地址，需要重新扫码。如需固定地址，可在 Cloudflare 控制台创建通道并绑定自己的域名，把通道令牌和外网地址填到高级设置中。
- **访问密钥**：链接中的 `k=` 是随机生成的访问密钥，没有密钥无法查看任何数据。请不要分享链接；如已泄露，点“重置密钥”使旧链接全部失效。
- **传输内容**：只传输 Token 数、模型名、时间、速度、折算额度、Codex 额度、预算与项目文件夹名（不含完整路径），不包含提示词或回答。电脑关机或程序退出后手机页面会显示“电脑可能已离线”。
- 默认只监听本机 `127.0.0.1`；勾选“允许同一局域网的设备直接访问”后才监听局域网地址（Windows 防火墙可能会询问）。

## 支持范围（v0.2.0）

| 软件 | 本地接入 | Token 用量 | 速度 |
| --- | --- | --- | --- |
| Codex | `~/.codex/sessions/**/*.jsonl` | 支持新版 usage 记录与旧版累计事件 | 有起止事件时估算请求耗时速度 |
| Claude Code / 桌面端 Code 会话 | `~/.claude/projects/**/*.jsonl` 等 | 支持 assistant message usage，同一 message 去重 | 有起止事件时估算请求耗时速度 |
| Reasonix | `%APPDATA%/reasonix/stats/*.jsonl` | 支持 prompt/completion/reasoning/cache_hit 与账单估值 | 原始 stats 未给出单次耗时，显示不可用 |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | 读取 steps.metadata 中的 ModelUsageStats protobuf 字段 | 有步骤起止时间时估算；自动从伴随日志读取模型名 |
| WorkBuddy | `~/.workbuddy/projects/**/*.jsonl` | 支持 providerData.usage，用 messageId 去重 | 有起止事件时估算请求耗时速度 |

各工具格式会变化；这里支持的是上表记录格式，不是对任意 AI 软件都自动抓取。Claude 普通网页聊天也不属于 Claude Code 日志覆盖范围。界面会如实显示已接入、待记录或未找到。空范围总量为 0 表示没有可统计记录，不代表对应软件实际消耗为零。

### 统计口径

Token 数来自本地记录，未按文字长度猜测。思考 Token 通常是输出 Token 的子集，不重复相加。Claude 输入包含普通输入、缓存读取和缓存写入。

**速度不是模型纯解码速度**。Codex 根据任务或工具返回起点（后续请求按工具输出或上一响应时间）到 usage 事件时间估算；Claude 与 WorkBuddy 根据请求开始前最近的 user / api-request / function_call_result 事件到该 messageId 完成时间估算（固定每个 messageId 的起始时间，不受流式过程中穿插的工具结果干扰）。可能包含排队、网络、工具执行和等待，界面以 `≈` 标识。平均速度为有耗时请求的输出 Token 总和除以其耗时总和，不把无耗时请求纳入。跨软件重叠请求按各自耗时求和，并非墙钟吞吐量。导入的 duration_ms 按来源提供的数值计算。

Antigravity 的字段编号根据应用自带协议定义核对，只读取 metadata 计量信息；速度采用步骤有效起点（started_at 早于结束时间时取 started_at，否则取步骤创建起点 created_at）到 finished_generating_at（缺失时 completed_at）。数据库以只读模式访问并读取 WAL 更新。格式不匹配时显示待记录或读取异常，不按字节值猜测用量。

**Antigravity 模型名**：`steps.metadata` 中仅记录占位枚举编号（如 `1401`），程序会自动读取同会话 `brain/<会话ID>/.system_generated/logs/transcript.jsonl` 中的模型切换事件（`Model Selection`）还原真实模型名，并在缺失日志时复用已识别的编号映射。若伴随日志被清理，也可在“设置 → 反重力 → 模型名称”中按 `编号 = 名称` 手动补充或覆盖。

**API 额度与费用折算**：内置 OpenAI / Codex、Claude、Gemini、DeepSeek、Kimi、GLM、Qwen 等常用模型公开 API 单价（美元 / 百万 Token），按普通输入、缓存读取、缓存写入（Claude）与输出 Token 分别折算（Antigravity 的普通输入与缓存读取字段独立计费；Reasonix 含有完整 `valuation_usd` 时优先采用原始估值；思考 Token 已含在输出内，不重复计费）。可在“设置 → API 计费”自定义美元兑人民币汇率与任意模型单价。会员订阅或赠金渠道的实际扣费以各平台账单为准。

## 直接运行

Windows 用户双击发行包中的 `AI-Pulse.exe`，无需安装 Python。首次扫描大量历史文件可能需要一些时间，界面仍可响应。默认显示今天；没有今日记录时切换到“全部记录”。

配置只存于 `%LOCALAPPDATA%/AI-Pulse/settings.json`。程序不会修改源软件日志。卸载前如开启过开机自动启动，请先在“设置 → 常规与预算”中取消勾选（或删除注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 下的 `AI Pulse` 项），然后从托盘退出并删除程序；如需重置设置，再手动删除上述配置目录。

## 从源码运行

需要 Python 3.11+。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

测试与打包：

```powershell
python -m unittest discover -s tests -v
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean AI-Pulse.spec
```

## 通用导入协议

其他软件可通过导出程序或插件产生以下 JSONL。每行一个请求，UTF-8 编码并以换行结尾。在桌面程序中选择所属软件后导入文件；持续追加会自动更新。同一软件内 `id` 必须全局唯一，相同 id 的记录更新该请求。

```json
{"schema":"ai-pulse/v1","id":"unique-request-id","timestamp":"2026-10-30T10:00:00+08:00","model":"example-model","duration_ms":2000,"usage":{"input_tokens":1000,"output_tokens":100,"reasoning_output_tokens":20,"cached_input_tokens":500}}
```

`timestamp` 须使用带时区 ISO 8601；`duration_ms` 与 `cost_usd` 可省略，缺失 `duration_ms` 时不计算速度。输入 / 输出 / 思考 / 缓存均为非负整数。`reasoning_output_tokens` 是输出的子集。导入接口不是对目标软件的自动抓取，需由数据提供方产生真实记录。

## 数据与隐私

本地解析器只将模型名、时间、计量、工作目录路径、Codex 额度快照与内部去重 ID 保留在内存中，不持久化提示词、回答或会话正文。未开启手机查看时不上传任何内容；开启后仅向持有访问密钥的手机页面提供上述统计数据，外网访问经由 Cloudflare 通道转发。程序不读取各 AI 软件的认证文件。手机查看的访问密钥保存在本机 `settings.json` 中。CSV 由用户主动导出，只包含统计字段；请自行决定是否分享。源日志包含正文，因此解析时会短暂读取包含正文的 JSON 行，但正文不会进入展示、缓存或导出。

## 贡献适配器

适配逻辑位于 `pulse/collector.py` 的 `consume`。请先确认数据来源的计量口径，为去重、部分写入、截断、缺失耗时添加合成测试。提交示例时使用人工构造数据，勿提交真实会话、凭证或个人目录。当前无自动更新机制。

## 第三方组件

应用使用未修改的 Qt / PySide6 动态库。其许可、上游源码位置和替换方式见 [THIRD_PARTY.md](THIRD_PARTY.md)。系统字体由本机 Windows 提供，发行包不包含微软字体。
