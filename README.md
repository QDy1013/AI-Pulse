# AI Pulse

一个本地运行的 Windows AI 用量监控桌面应用。用同一个面板查看不同 AI 编程工具的 Token 用量、请求记录与速度趋势。应用源码 MIT 开源。

## v0.2 界面更新

界面迁移到 Qt 原生高 DPI 渲染。取消为适应屏幕而整体缩小界面的处理，字体和图表按显示器缩放比例绘制。使用更清楚的字号与对比度、四列指标卡、矢量曲线与悬停提示、软件输出分布和更宽松的请求表格。小屏幕使用滚动区域，不压缩文字。

Qt 依赖采用开放目录形式打包，请保留 EXE 同级的 `_internal` 文件夹；不要只复制 EXE。

## 功能

- 原生桌面窗口，深色界面，支持窗口缩放。
- 按软件、今天 / 近 7 天 / 全部记录筛选。
- 输出 / 输入 / 思考 / 缓存读取 Token、最近请求与加权平均速度。
- 每 3 秒检查本地记录，增量读取新增行，支持暂停。
- 修改记录目录，导入标准 JSONL，导出 CSV。
- 完全离线运行，无遥测、无联网服务、无需 API Key。

## 支持范围（v0.2.0）

| 软件 | 本地接入 | Token 用量 | 速度 |
| --- | --- | --- | --- |
| Codex | `~/.codex/sessions/**/*.jsonl` | 支持新版 usage 记录与旧版累计事件 | 有起止事件时估算请求耗时速度 |
| Claude Code / 桌面端 Code 会话 | `~/.claude/projects/**/*.jsonl` 等 | 支持 assistant message usage，同一 message 去重 | 有起止事件时估算请求耗时速度 |
| Reasonix | `%APPDATA%/reasonix/stats/*.jsonl` | 支持 prompt/completion/reasoning/cache_hit | 原始 stats 未给出单次耗时，显示不可用 |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | 读取 steps.metadata 中的 ModelUsageStats protobuf 字段 | 有步骤起止时间时估算；自动从伴随日志读取模型名 |
| WorkBuddy | `~/.workbuddy/projects/**/*.jsonl` | 支持 providerData.usage，用 messageId 去重 | 有起止事件时估算请求耗时速度 |

各工具格式会变化；这里支持的是上表记录格式，不是对任意 AI 软件都自动抓取。Claude 普通网页聊天也不属于 Claude Code 日志覆盖范围。界面会如实显示已接入、待记录或未找到。空范围总量为 0 表示没有可统计记录，不代表对应软件实际消耗为零。

### 统计口径

Token 数来自本地记录，未按文字长度猜测。思考 Token 通常是输出 Token 的子集，不重复相加。Claude 输入包含普通输入、缓存读取和缓存写入。

**速度不是模型纯解码速度**。Codex 根据任务或工具返回起点（后续请求按工具输出或上一响应时间）到 usage 事件时间估算；Claude 与 WorkBuddy 根据请求开始前最近的 user / api-request / function_call_result 事件到该 messageId 完成时间估算（固定每个 messageId 的起始时间，不受流式过程中穿插的工具结果干扰）。可能包含排队、网络、工具执行和等待，界面以 `≈` 标识。平均速度为有耗时请求的输出 Token 总和除以其耗时总和，不把无耗时请求纳入。跨软件重叠请求按各自耗时求和，并非墙钟吞吐量。导入的 duration_ms 按来源提供的数值计算。

Antigravity 的字段编号根据应用自带协议定义核对，只读取 metadata 计量信息；速度采用步骤有效起点（started_at 早于结束时间时取 started_at，否则取步骤创建起点 created_at）到 finished_generating_at（缺失时 completed_at）。数据库以只读模式访问并读取 WAL 更新。格式不匹配时显示待记录或读取异常，不按字节值猜测用量。

**Antigravity 模型名**：`steps.metadata` 中仅记录占位枚举编号（如 `1401`），程序会自动读取同会话 `brain/<会话ID>/.system_generated/logs/transcript.jsonl` 中的模型切换事件（`Model Selection`）还原真实模型名，并在缺失日志时复用已识别的编号映射。若伴随日志被清理，也可在“数据源 → 反重力 → 模型名称”中按 `编号 = 名称` 手动补充或覆盖。

## 直接运行

Windows 用户双击发行包中的 `AI-Pulse.exe`，无需安装 Python。首次扫描大量历史文件可能需要一些时间，界面仍可响应。默认显示今天；没有今日记录时切换到“全部记录”。

配置只存于 `%LOCALAPPDATA%/AI-Pulse/settings.json`。程序不会修改源软件日志。卸载只需关闭并删除程序；如需重置设置，再手动删除上述配置目录。

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

`timestamp` 须使用带时区 ISO 8601；`duration_ms` 可省略，缺失时不计算速度。输入 / 输出 / 思考 / 缓存均为非负整数。`reasoning_output_tokens` 是输出的子集。导入接口不是对目标软件的自动抓取，需由数据提供方产生真实记录。

## 数据与隐私

本地解析器只将模型名、时间、计量与内部去重 ID 保留在内存中，不持久化提示词、回答或会话正文。运行时不上传任何内容，不读取认证文件。CSV 由用户主动导出，只包含统计字段；请自行决定是否分享。源日志包含正文，因此解析时会短暂读取包含正文的 JSON 行，但正文不会进入展示、缓存或导出。

## 贡献适配器

适配逻辑位于 `pulse/collector.py` 的 `consume`。请先确认数据来源的计量口径，为去重、部分写入、截断、缺失耗时添加合成测试。提交示例时使用人工构造数据，勿提交真实会话、凭证或个人目录。当前无自动更新机制。

## 第三方组件

应用使用未修改的 Qt / PySide6 动态库。其许可、上游源码位置和替换方式见 [THIRD_PARTY.md](THIRD_PARTY.md)。系统字体由本机 Windows 提供，发行包不包含微软字体。
