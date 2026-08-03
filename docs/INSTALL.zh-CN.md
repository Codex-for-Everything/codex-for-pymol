# Codex for PyMOL 安装与使用

[English](INSTALL.md) | [简体中文](INSTALL.zh-CN.md)

[返回项目说明](README.zh-CN.md)

## 1. 检查 Codex

需要准备：

- 带 Qt 图形界面的 PyMOL 2.x 或 3.x；
- PyMOL 内置 Python 3.8 或更高版本；
- 已安装并登录的 `codex` CLI；
- 较新的 Codex CLI；如果当前版本缺少插件需要的接口，插件会明确提示。

插件不会向 PyMOL 的 Python 环境安装额外软件包。

安装插件前先检查 Codex。

macOS Terminal：

```bash
codex --version
```

Windows PowerShell：

```powershell
Get-Command codex
codex --version
```

在 macOS 上，插件还会检查 ChatGPT 桌面应用自带的 Codex；在 Windows 上，插件会检查 `PATH` 和常见的用户级安装位置，并支持 `codex.cmd` 启动器。

如有需要，可以在启动 PyMOL 前明确指定可执行文件：

```text
PYMOL_CODEX_EXECUTABLE=/absolute/path/to/codex
```

Windows 示例：

```powershell
$env:PYMOL_CODEX_EXECUTABLE = "C:\Tools\codex.exe"
```

也可以稍后在插件中点击 **选择 Codex…**。

## 2. 安装插件

### 安装发布版本

从对应的 GitHub Release 下载 `pymol_codex_plugin.zip`，不要解压。

在 PyMOL 中选择：

```text
Plugin → Plugin Manager → Install New Plugin → Choose file…
```

选择下载的 zip，然后重启 PyMOL。

### 从源码构建

在项目根目录运行对应平台的命令。

macOS：

```bash
python3 scripts/build_plugin.py
```

Windows PowerShell：

```powershell
py scripts/build_plugin.py
```

如果没有 `py`，但 `python` 已加入 `PATH`，可以改用 `python`。构建完成后，按照发布版相同的方式安装脚本生成的 `dist/pymol_codex_plugin.zip`。

## 3. 开始第一次对话

重启 PyMOL 后，主窗口底部应该自动出现 **Codex 助手**，并与 **PyMOL 控制台** 相邻。如果没有出现，请选择：

```text
Plugin → PyMOL Codex 助手
```

也可以在 PyMOL 命令行输入：

```text
codex_chat
```

如果旧版 PyMOL 没有提供兼容的主窗口接口，插件可能显示为独立窗口，而不是嵌入式标签。

每次启动 PyMOL 都会创建新的 Codex 对话。如果想在不重启 PyMOL 的情况下清空上下文，请点击 **新建对话**。

建议先尝试只读请求：

```text
检查当前对象、链、配体和残基数量，不要修改画面。
```

然后尝试可视化任务：

```text
加载 1FPU，找出主要有机配体，用 sticks 显示配体和周围 4 Å 的蛋白残基，
并调整到清楚的视角。
```

Codex 准备下载结构或打开本地结构文件时，PyMOL 会先请求你的确认。

## 4. 面板和键盘操作

| 控件 | 用途 |
| --- | --- |
| **发送** | 发送消息 |
| **停止** | 请求 Codex 停止当前处理 |
| **新建对话** | 开始一段全新对话 |
| **模型设置…** | 修改模型、推理强度或响应速度 |
| **启用不受限 Python（高风险）** | 允许经过单独批准的 Python 代码 |
| **撤销最新一轮的修改** | 恢复最近一个可用的 PyMOL 撤销点 |

- `Enter`：发送；
- `Ctrl+Enter` 或 `Shift+Enter`：插入换行；
- `Esc`：在主面板中不会关闭面板；在独立对话框中会取消该对话框。

聊天记录初始为四行高，输入框为两行高；内容过长时会在各自区域内滚动。拖动面板上方的分隔线可以调整高度。聊天记录会使用增加的空间，操作控件始终固定在底部。嵌入 PyMOL 时，颜色、字体和滚动条会跟随原生控制台。

状态行会显示 Codex 正在连接、就绪、处理、重试或等待操作。**停止** 和 **模型设置…** 只会在适合使用时启用。

## 5. 模型设置

打开 **模型设置…** 可以选择模型、推理强度和响应速度。选项来自当前 Codex 账号和所选模型，插件没有内置的固定模型列表。

真实默认项会标记 **（默认）**。基础响应速度显示为 **标准（默认）**；只有 Codex 实际提供 Fast 等额外速度时才会显示。推理强度或响应速度只有一个选项时，对应下拉框会禁用。

设置从下一条消息开始生效，并保存在本机。每次启动 PyMOL 后，插件都会先从当前 Codex 获取新列表，确认保存的选项仍然存在；已经不可用的选项会恢复为当前默认值。如果列表加载失败，仍可继续对话，此时使用 Codex 默认设置。

点击 **刷新模型列表** 可以重试。Codex 正在处理消息时，**模型设置…** 暂时禁用是正常现象。

## 6. 不受限 Python 与撤销

普通 PyMOL 工作应优先使用受控工具。只有受控工具无法完成任务时，才考虑启用 **启用不受限 Python（高风险）**。

不受限 Python 会在 PyMOL 内以你的操作系统权限运行，可能读取或修改文件、访问网络、启动程序、导致 PyMOL 崩溃，或者进入无法停止的状态。因此打开开关时需要确认，此后每个代码块还要再次批准；批准前会显示完整代码和 Codex 给出的原因。

如果开关关闭时 Codex 仍请求不受限 Python，插件会拒绝并请求停止当前处理。只有在理解风险且受控工具确实不够用时，才打开开关并重新发送请求。

切换到 **PyMOL 控制台**、隐藏或关闭 Codex 面板，或者退出 PyMOL 时，该开关会自动关闭。

一条用户请求第一次准备修改 PyMOL 前，插件会保存一个 `.pse` 撤销点。该请求中的受控修改和批准后的 Python 共用这一个撤销点；只读请求不会创建。

点击 **撤销最新一轮的修改** 会恢复最新的可用撤销点。只要更早的撤销点仍在，还可以继续撤销更早的修改请求。当前 PyMOL 进程最多保留五个。撤销不能恢复普通文件、网络活动、软件包或外部程序，重启 PyMOL 后也不会保留撤销历史。

## 7. 数据与隐私

发送给 Codex 的结构摘要和截图会成为模型对话的一部分。处理未公开或受监管的结构前，请先确认所在组织的数据政策。

插件会在 Qt 为当前用户提供的应用数据、缓存或临时目录中保存：

- 审计日志，其中可能包含消息、工具参数和结果、批准的代码以及本地路径；
- 最近 20 张截图；
- 当前 PyMOL 进程最近 5 个 `.pse` 撤销点。

审计文件达到 5 MiB 时轮转，并保留三个备份。常见凭据字段、Bearer token 和类似 API key 的文本会尽力脱敏，但这不是绝对保证。不要在提示词或批准执行的代码中放入密码、API key 或其他秘密。

在 macOS 等 POSIX 系统上，插件会尝试把这些目录和文件设为仅当前用户可访问。Windows 使用当前用户 Qt 数据目录继承的访问权限。正常退出时会清理撤销点。审计日志写入失败时，聊天记录会显示警告，但 PyMOL 工具结果仍会返回。

## 8. 常见问题

### 找不到 Codex

点击 **选择 Codex…**，选择真正的 Codex 可执行文件，不要选择 ChatGPT 应用本身。Windows 支持 `codex.exe` 和 `codex.cmd`。

### Codex 尚未登录

在 Terminal 或 PowerShell 中运行一次 `codex`，完成登录，然后重启 PyMOL。

### 插件无法检查 Codex 功能

创建对话前，插件会对当前 Codex 做一次简短的安全检查。如果无法确认可用功能，就不会启动后台服务。请运行：

```bash
codex features list
```

如果命令失败或一直不结束，请更新 Codex，或重新选择正确的可执行文件。

### 模型列表或请求超时

先确认 `codex` 可以在终端中正常工作，然后检查网络、系统代理、VPN、防火墙和 DNS。更换 Codex 或插件版本后请重启 PyMOL。

如果 `codex features list` 中存在 `respect_system_proxy`，可以运行：

```bash
codex doctor --summary --enable respect_system_proxy
```

模型列表加载失败不会阻止普通对话；在列表可用前，插件会使用 Codex 默认设置。

### 状态栏显示 Codex 正在重连

这表示响应流暂时中断，Codex 正在自动重试。如果随后收到正常回答，请求已经成功。只有最终失败才会作为错误加入聊天记录。

### 点击停止后 PyMOL 仍然卡住

**停止** 可以中断 Codex 回合，但不能安全终止已经在 PyMOL 内运行的任意 Python 或原生代码。等待无效时只能关闭 PyMOL，未保存的修改可能丢失；重启后请打开你自己保存的会话。插件的自动撤销历史属于旧 PyMOL 进程，重启后不可使用。

### 面板显示为独立窗口

只有能够访问兼容 Qt 主窗口和原生控制台 dock 时，插件才能嵌入 PyMOL。旧版或采用不同打包方式的 PyMOL 可能使用独立窗口作为回退。

## 开发检查

不启动 PyMOL 即可运行单元测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

使用 PyMOL 自带的 Python 运行真实运行时和 Qt 测试，再通过真实 GUI 启动器加载 dock 测试：

```bash
PYTHONPATH=src /path/to/pymol/python scripts/pymol_smoke.py
PYTHONPATH=src /path/to/pymol/python scripts/pymol_ui_smoke.py
PYTHONPATH=src /path/to/pymol/launcher -r scripts/pymol_dock_smoke.py
```

Windows PowerShell 请先设置 `$env:PYTHONPATH = "src"`，然后使用 PyMOL 安装目录中的对应可执行文件。
