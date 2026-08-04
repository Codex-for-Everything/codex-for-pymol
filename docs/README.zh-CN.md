# Codex for PyMOL

[English](../README.md) | [简体中文](README.zh-CN.md)

Codex for PyMOL 会在 PyMOL 中加入一个 Codex 聊天面板。你可以直接用自然语言描述想做的事情，让 Codex 检查当前结构、整理视图、突出显示残基、测量距离，以及完成其他常见 PyMOL 工作，而不必自己编写 PML 命令。

这是独立的社区项目，不是 PyMOL 或 OpenAI 的官方产品。

> **Vibe Coding 声明：** 本项目完全通过与 Codex 协作进行 Vibe Coding 创建，包括实现、测试、文档和自动发布流程；相关成果按照本仓库所述的验证流程进行了检查。

详细指南：[English](INSTALL.md) | [简体中文](INSTALL.zh-CN.md)

> **Windows 用户请注意：** 0.3.2 及更早版本包含 Windows 专属问题，可能导致按钮文字几乎不可见，或者无法发现、启动部分 Codex CLI 安装，尤其是 npm 的 `.cmd` 启动器。Windows 用户请安装 0.4.0 或更高版本。

## 可以做什么

- 检查已经加载的对象、链、残基、配体、选择和当前视角；
- 在获得确认后下载结构或打开本地结构文件；
- 显示、隐藏、着色、选择、居中、调整视角、添加标签和测量距离；
- 把 PyMOL 截图返回给 Codex，让它检查画面效果；
- 为近期每一轮实际修改 PyMOL 的用户请求保留一个撤销点；
- 只有在用户明确启用并逐次批准后才运行不受限 Python；
- 从当前 Codex 账号读取可用模型、推理强度和响应速度，不使用内置的固定选项表。

## 运行要求

- 带 Qt 图形界面的 PyMOL 2.x 或 3.x；
- PyMOL 内置 Python 3.8 或更高版本；
- 一个较新且已登录的 Codex 可执行文件；Windows 与 macOS 的要求不同，见下表。

| 平台 | 本插件需要的 Codex |
| --- | --- |
| **Windows** | **必须安装独立的 [Codex CLI](https://developers.openai.com/codex/cli/)**，并确认 PowerShell 可以运行 `codex --version`。只安装 ChatGPT/Codex 桌面 App 不够 |
| **macOS** | 二选一：安装独立 Codex CLI；或者安装内部带有 `Contents/Resources/codex` 的 ChatGPT.app。插件会自动检测这两种来源 |

如果找到的可执行文件版本太旧、缺少插件所需接口，插件会明确提示。

插件不会向 PyMOL 的 Python 环境安装额外软件包。

## 快速开始

1. 打开[最新 GitHub Release](https://github.com/wuhuawei1996/codex-for-pymol/releases/latest)，在 **Assets** 中下载 `codex-for-pymol-X.Y.Z.zip`，其中 `X.Y.Z` 是发布版本号。不要下载 GitHub 自动生成的 **Source code** 压缩包，也不要解压插件 zip。
2. 在 PyMOL 中打开：

   ```text
   Plugin → Plugin Manager → Install New Plugin → Choose file…
   ```

3. 选择 zip，然后重启 PyMOL。
4. 主窗口底部应该自动出现 **Codex 助手** 标签，并与 **PyMOL 控制台** 相邻。
5. 输入请求并按 `Enter` 发送。

> 从 0.2.x 或更早版本升级：安装 0.3.0 或更高版本前，请先在 PyMOL 的插件管理器中卸载旧版插件并重启 PyMOL。插件的内部包名已经改变，保留旧版可能导致 PyMOL 同时加载两份插件。

如果面板没有打开，请选择：

```text
Plugin → PyMOL Codex 助手
```

也可以在 PyMOL 命令行输入 `codex_chat`。源码构建和故障排查请参阅 [安装指南](INSTALL.zh-CN.md)。

## 常用控件

| 控件 | 用途 |
| --- | --- |
| **发送** | 发送当前消息 |
| **停止** | 请求 Codex 停止当前处理 |
| **新建对话** | 清空聊天记录并创建新的 Codex 对话 |
| **模型设置…** | 选择当前 Codex 账号实际返回的模型和选项 |
| **启用不受限 Python（高风险）** | 允许经过单独批准的 Python 代码在 PyMOL 内运行 |
| **撤销最新一轮的修改** | 恢复到最近一条修改型用户请求执行之前 |

按 `Enter` 发送；按 `Ctrl+Enter` 或 `Shift+Enter` 插入换行。在主面板中按 `Esc` 不会关闭面板。

面板默认提供四行聊天记录和两行消息输入区。拖动面板上方的分隔线可以调整高度；聊天记录会随面板伸缩，操作控件始终位于底部。嵌入 PyMOL 时，面板会跟随原生控制台的颜色和滚动条样式。

每次启动 PyMOL 都会创建新的对话，不会在后台悄悄恢复上一次的对话上下文。保存的模型选择会保留，但只有当前 Codex 连接确认这些选项仍然可用后才会使用。

## 安全与隐私

普通模式只使用少量受控 PyMOL 工具，不会向 Codex 开放通用命令行或任意文件编辑能力。每次启动时，插件都会读取当前所选 Codex 的真实可选功能列表，并禁用与 PyMOL 无关的命令行、插件、技能和环境访问能力；未来新增的功能在明确确认必要且安全前也会默认禁用。如果无法验证功能列表，插件会停止启动，不会在权限边界不明的情况下继续。每段 PyMOL 对话还会使用不持久保存、只读且不连接 Codex 环境的新线程。插件会进一步核对 Codex 返回的结果，只有确认该对话确实不会写入历史记录才会进入就绪状态；否则会拒绝该对话，并尝试移除尚未使用的空记录。

Codex 准备下载结构或读取本地结构文件时，PyMOL 会先请求你的确认。

**启用不受限 Python（高风险）** 完全不同。批准后的代码会在 PyMOL 进程内以你的操作系统权限运行，可能读取或修改文件、访问网络、启动程序、导致 PyMOL 崩溃，或者进入无法中断的状态。打开开关时需要确认风险，此后每个代码块还要再次批准。切换离开、隐藏或关闭 Codex 面板，以及更换 Codex 后台进程或后台进程意外停止时，开关都会自动关闭。

一条用户请求第一次准备修改 PyMOL 前，插件会保存一个 `.pse` 撤销点。**撤销最新一轮的修改** 可以恢复 PyMOL 会话，但不能撤销普通文件、下载、网络活动、已安装软件包或外部程序造成的影响。

发送给 Codex 的结构摘要和截图会成为模型对话的一部分。除非所在组织允许，否则不要处理未公开或受监管的结构数据。

插件还会在本机保存审计日志、截图和临时撤销点。审计日志可能包含你的消息、工具详情、代码和本地路径。常见凭据格式会尽力脱敏，但不要在提示词或批准执行的代码中放入秘密。插件最多保留：

- 每个不超过 5 MiB 的审计文件，以及三个轮转备份；
- 最近 20 张截图；
- 当前 PyMOL 进程中最近 5 个撤销点。

正常退出时会清理撤销点。更多说明见 [数据与隐私](INSTALL.zh-CN.md#7-数据与隐私)。

## 当前限制

- 已经开始运行的不受限 Python 不一定能够安全停止；
- 撤销功能只能恢复 PyMOL 会话；
- 动态工具仍是实验性 Codex App Server 功能，Codex 协议变化可能要求更新插件；
- GitHub CI 会在 macOS 和 Windows 上测试 Python 代码和打包流程，但发布前仍应在两个系统的目标 PyMOL/Qt 版本中实际检查。

## 开发

本节命令供开发者使用。普通 PyMOL 用户应安装 GitHub Release 中的 `codex-for-pymol-X.Y.Z.zip`，不要安装 wheel、Python 源码包或 GitHub 自动生成的源码压缩包。

运行单元测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

使用 Hatchling 构建 wheel 和源码包：

```bash
python3 -m pip install build==1.2.2.post1
python3 -m build
```

构建可安装的 PyMOL 插件 zip：

```bash
python3 scripts/build_plugin.py
```

Windows 请用 `py` 或可用的 `python` 命令替换 `python3`，并在测试前设置 `$env:PYTHONPATH = "src"`。真实 PyMOL 冒烟测试命令见 [安装指南](INSTALL.zh-CN.md)。维护者发布云端构建和 GitHub Release 时请遵循双语[发布指南](RELEASING.zh-CN.md)。

许可证：[English](../LICENSE) | [简体中文参考译文](LICENSE.zh-CN.md)
