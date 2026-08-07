# SAISENT 4.0

一个控制面板，将预先准备好的文本粘贴到当前在这台机器上运行的代理会话中。

把文本放入正确会话的队列 — SAISENT 激活代理窗口，切换到该会话的标签页，一次操作粘贴文本并按回车。

## 快速开始

```
START_SAISENT.bat
```

需要 Windows 上的 Python 3.11+。

## 使用方法

1. **代理。** 顶行 — 复选框：Claude Code、Freebuff、Antigravity、CodeNomad。
   勾选一个代理，其会话就出现在左侧面板中。
2. **实时会话。** 左侧显示真正在运行的内容：会话名称、标签页编号、活动传感器和项目。列表不会自动刷新，除非你启用"每 N 秒" — 默认只能通过**刷新**按钮手动刷新。
3. **标签页。** SAISENT 根据会话的启动顺序猜测标签页编号。猜错了？在 `SAISENT.json` 的 `tabs` 键下手动填入编号（会话键形如 `<agent>:<id>`，例如 `{ "tabs": { "claude-code:abc123": 3 } }`）。`0` = 完全不切换标签页。
4. **文本。** 在右下角输入（或粘贴），按**入队**（或 Ctrl+Enter）。**全部入队** 将同一段文本放入每个实时会话 — 取代旧的"CTRL+2、文本、CTRL+3、文本"宏。
5. **队列。** 行的顺序 = 发送顺序。用鼠标拖动一行，或用**上**/**下**按钮移动。每个会话都有自己的队列。双击一行（或**编辑**按钮）把提示词拉回文本框；**保存编辑** 原地重写，**取消** 丢弃。编辑已发送的提示词会将其退回队列 — 行中的文本已不再是会话收到的内容。**复制** 在其正下方放置一份副本。
6. **发送。** **发送此队列** — 仅所选会话。**全部发送** — 依次发送所有队列。**试运行** 不发送任何内容，只在日志中显示计划。真实发送会先要求确认并列出会话。

## 撤销发送

发送后，**撤销**按钮会显示 30 秒。它把最后发送的提示词作为 `pending` 退回队列 — 除非会话已处理它（已确认送达）。

## 计划与限制

在"发送"组中：

- **发送时间 (HH:MM)** — 空表示"立即"。有时间时，队列等待该时间的下一次到来（今天，如果已过则为明天）并在状态栏显示倒计时。
- **等待速率限制重置** — 在每个提示词之前，SAISENT 读取代理自己的文本。如果它说"limit reached"，队列就等待并在限制解除时自动恢复。不会向锁定的门发送任何提示词。
- **检查限制** — 立即重新扫描。
- 右侧的状态字段显示实时状态：`limits: all agents free` 或 `claude-code: LIMITED until 09:22 (1h 05m remaining)`，红色。倒计时每秒从缓存跳动一次；只有读取过期或指定的重置时间到来时才触碰磁盘。

重置时间取自代理自己的话。如果代理没有说明，SAISENT 就写"reset time not stated"，而不是编造像"+5 小时"这样的占位符。

### 限制何时重置

如果代理从不说明重置时间，SAISENT 回退到每个代理的规则：

| 代理 | 规则 | 含义 |
|---|---|---|
| Freebuff | `daily 10:00` | 每天 10:00 重置 |
| CodeNomad | `daily 03:00` | 每天 03:00 重置 |
| Claude Code | `rolling 5h` | 在最后发送的提示词之后 5 小时 |
| Antigravity | 仅代理的话 | 无规则 — 它说明了什么，就是什么 |

规则绝不覆盖代理说明的时间；代理是自己配额的权威。任何规则都可以在 `SAISENT.json` 的 `quota_plans` 下覆盖，例如 `{ "quota_plans": { "claude-code": "rolling 3h" } }`。

## 为什么下一个不发送

发送严格按顺序进行，在第一个真正的错误处停止。原因出现在状态栏（`stopped: window not found: ...`）、列表中的提示词行和日志中。其余保持 `pending` — 它们不会丢失。

提示词之间有一个 `gap_ms` 暂停（默认 1500 ms），状态显示 `Waiting N.Ns before next`。如果提示词已发送但会话没有动静，它被标记为**未确认**并留在队列中。"已发送"只应用于已确认的送达。

## 活动传感器

"传感器"列回答"我现在能输入吗"。

- `busy` — 会话在不到 20 秒前写入其存储（代理正处于回合中间）；
- `idle` — 安静超过 20 秒，输入字段空闲。

它从哪里来：

| 代理 | 来源 | 传感器 |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + 转录 | 转录中的最后写入时间 |
| Freebuff | `<project>/.freebuff/desktop-v2.db`、`threads` 表 | `turn_state` 字段 |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | 数据库及其 `-wal` 的 mtime |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | 转录中的最后写入时间 |

存活是一个单独的检查，而不是"磁盘上的文件是新的"：

- **Claude Code** — `~/.claude/sessions/<pid>.json` 中的 PID 存活。文件在会话关闭后仍存在；PID 不会。
- **Freebuff** — `Freebuff.exe` 在运行。数据库在应用退出后仍保持线程 `open`。
- **Antigravity** — `Antigravity.exe` 在运行**且**对话是新的。仅凭新还不够：此存储永久保存所有对话，而关闭的编辑器过去会用无法触及的会话塞满列表。
- **CodeNomad** — 数据库行未归档（`time_archived IS NULL`）。只有当前打开的会话是活动的。

## 送达地址 — "地址"列

侧边栏准确显示每个会话将被如何击中：

| 值 | 方法 | 可靠性 |
|---|---|---|
| `cdp:28194` | 通过代理的调试器粘贴 | 精确：前后读取字段，不窃取焦点 |
| `CTRL+3` | 在代理窗口中切换标签页 | 良好，如果标签页编号正确 |
| `blind` | 没有端口，没有标签页编号 | 提示词落入当前打开的聊天 |

没有窗口标题包含会话名称 — `claude.exe` 叫"Claude"，Antigravity 叫"Antigravity"，Freebuff 叫"Freebuff Desktop"。因此按窗口寻址是不可能的，`blind` 的意思正如其字面所说。

### CDP — 可靠路径

如果代理以 `--remote-debugging-port` 启动，SAISENT 通过调试器发送，既不动焦点也不动键盘。这意味着：

- 文本直接粘贴到输入字段，而不是"任意地方"；
- 粘贴**前**读取字段：如果那里有半截消息，发送会拒绝而不是追加到别人的句子后面；
- 粘贴**后**读取字段：如果没落进去，就不发送。

CDP 拒绝绝不会回退到盲打按键。精确的传输方式刚刚说明时机不对；在上面猛敲按键正是毁掉别人聊天的做法。

端口从代理的 `DevToolsActivePort` 读取，但仅凭一个文件不够 — 它会从上一次启动遗留下来。SAISENT 在每次探测前都会真正连接到端口。

为代理启用调试器（重启会杀死它正在做的事 — SAISENT 自己从不这样做）：

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### 页面选择器（实时 DOM，2026-08-05）

| 代理 | 端口 | 输入字段 | 对话框列表 |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | 无 | — | — |

Antigravity 已验证：16 个按钮，标签与 SAISENT 显示的项目名称完全一致（`_SAIPEN`、`_FastPrompter`、`SAISENT`、…）— 按名称选择对话框工作精确。

CodeNomad 是 OpenCode 之上的 Electron；数据文件夹仍叫 `Plasticity`。DOM 中的会话列表只包含**当前打开的项目的**会话；来自其他项目的会话不会被渲染，SAISENT 找不到它 — 发送会拒绝而不是盲目击中打开的聊天。

在 `SAISENT.json` 中覆盖任何配置文件键：

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

会话从 `~/.local/share/opencode/opencode.db` 的 `session` 表读取：名称 = `title`，项目 = `directory`，已归档的按 `time_archived` 过滤，传感器按 `time_updated`。这里唯一一个会话列表是普通列的代理 — 没有 protobuf，没有解析。

存活 — `CodeNomad.exe` 在运行。没有标签页编号：通过调试器按名称寻址。

## 为什么不按窗口标题

每个 `claude.exe` 窗口都叫"Claude"。会话名称从不出现在标题中，因此按窗口寻址是不可能的 — 名称、项目和 PID 来自磁盘；窗口只用于焦点。

## 送达确认

Chromium 不响应 `WM_GETTEXT`，因此通过 Win32 读取"是否落进字段"是不可能的 — 这些代理的旧回读总是返回"未确认"。相反，SAISENT 等待活动传感器监视的同一个文件移动。移动了？已送达。在分配的时间内没有移动？提示词被标记为已发送但未确认，这在日志中可见。这不被视为错误：代理可能只是还没开始其回合。

发送在第一个真正的错误处停止（找不到窗口、焦点丢失、剪贴板忙）。后续提示词留在队列中 — 不会丢失，也不会盲目发送。

## 导出与导入

**导出**和**导入**按钮以 JSONL 格式保存/加载队列。每一行都带有其会话键，自包含。导入合并而不丢失数据 — 重复项（相同键 + 文本）会被跳过。

## 程序旁边的文件

| 文件 | 内容 |
|---|---|
| `SAISENT.json` | 设置：代理、标签页编号、超时、窗口几何 |
| `SAISENT_QUEUES.json` | 每个会话的队列，重启后仍存在 |
| `SAISENT.log` | 发送历史日志 |

队列永远不会自动清理。如果会话从列表消失但还有未发送的项，队列会保留：代理会被重启，而静默丢弃的队列比文件里多余的一行更糟。

## 隐藏设置

在程序关闭时编辑 `SAISENT.json`：

- `gap_ms` — 一批内提示词之间的暂停（默认 1500）；
- `settle_ms` — 切换标签页后和粘贴后的暂停（400）；
- `confirm_seconds` — 等待送达确认的时间（10）；
- `busy_seconds` — 传感器"busy/idle"阈值（20）；
- `freebuff_roots` — 搜索 `.freebuff/desktop-v2.db` 的根目录，例如 `["V:\\___VAC\\__K\\__CODE"]`；搜索深度限制为 3；
- `submit` — 用于发送的按键，默认 `ENTER`。

## 限制

- 标签页通过 `Ctrl+1..Ctrl+9` 寻址。第十个会话不可达 — `Ctrl+10` 不存在，SAISENT 会拒绝而不是猜测。
- 标签页编号是基于启动顺序的猜测。第一次运行请使用**试运行**，然后在无关紧要的会话上进行。
- Antigravity 不以文本形式存储对话名称：列表显示从元数据提取的工作文件夹名称。

## 测试

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
