# Codex for PyMOL: Installation and Use

[English](INSTALL.md) | [简体中文](INSTALL.zh-CN.md)

[Back to the project overview](../README.md)

> The current plugin interface is in Simplified Chinese. This guide includes
> the exact Chinese labels shown in PyMOL.

> **Windows upgrade notice:** Versions 0.3.2 and earlier contain
> Windows-specific bugs that can make button text nearly invisible and prevent
> the plugin from finding or starting some Codex CLI installations, especially
> npm `.cmd` launchers. Install version 0.4.0 or later on Windows.

## 1. Check Codex

You need:

- PyMOL 2.x or 3.x with the Qt interface;
- Python 3.8 or newer inside PyMOL;
- a recent, authenticated Codex executable that provides the integration
  interface required by the plugin.

| Platform | Codex requirement for this plugin |
| --- | --- |
| **Windows** | **The standalone [Codex CLI](https://developers.openai.com/codex/cli/) is required.** Installing only the ChatGPT/Codex desktop app does not satisfy this requirement. |
| **macOS** | Use either the standalone Codex CLI or the Codex executable bundled inside ChatGPT.app at `Contents/Resources/codex`. |

The plugin does not install extra packages into PyMOL's Python environment.

Check Codex before installing the plugin.

macOS Terminal:

```bash
codex --version
```

If that command is unavailable but ChatGPT.app is installed, the plugin also
checks these locations automatically:

```text
/Applications/ChatGPT.app/Contents/Resources/codex
~/Applications/ChatGPT.app/Contents/Resources/codex
```

Windows PowerShell:

```powershell
Get-Command codex
codex --version
```

The ChatGPT.app fallback is macOS-specific. On Windows, install the standalone
CLI: the desktop app's packaged executable is not a stable external CLI
interface for this plugin and may be restricted to the app package. The plugin
checks `PATH`, npm's default user directory, `NPM_CONFIG_PREFIX`, and other
common per-user CLI locations. Native executables and `.cmd` or `.bat`
launchers are supported. One supported installation method is:

```powershell
npm install -g @openai/codex
```

Confirm `codex --version` in a new PowerShell window, then restart PyMOL.

If needed, set the executable explicitly before starting PyMOL:

```text
CODEX_FOR_PYMOL_EXECUTABLE=/absolute/path/to/codex
```

Windows example:

```powershell
$env:CODEX_FOR_PYMOL_EXECUTABLE = "C:\Tools\codex.exe"
```

You can also choose the executable later with **选择 Codex…**.

## 2. Install the plugin

### Install a release

Open the [latest GitHub Release](https://github.com/wuhuawei1996/codex-for-pymol/releases/latest). Under **Assets**, download `codex-for-pymol-X.Y.Z.zip`, where `X.Y.Z` matches the release version. Do not choose GitHub's automatically generated **Source code (zip)** or **Source code (tar.gz)** archives; they are repository snapshots, not installable PyMOL plugins. Do not extract the plugin zip.

In PyMOL, select:

```text
Plugin → Plugin Manager → Install New Plugin → Choose file…
```

Choose the downloaded zip and restart PyMOL.

If you are upgrading from 0.2.x or earlier, first uninstall the old plugin in
PyMOL's Plugin Manager and restart PyMOL. Version 0.3.0 changed the internal
package name; installing it alongside the old copy may load both plugins.

### Build from source

Run the command for your platform in the project root.

macOS:

```bash
python3 scripts/build_plugin.py
```

Windows PowerShell:

```powershell
py scripts/build_plugin.py
```

If `py` is unavailable but `python` is on `PATH`, use `python` instead. Install
the versioned `dist/codex-for-pymol-X.Y.Z.zip` produced by the script in the
same way as a release zip.

## 3. Start your first conversation

After PyMOL restarts, **Codex 助手** should open automatically at the bottom
of the main window beside **PyMOL 控制台**. If it does not, use:

```text
Plugin → PyMOL Codex 助手
```

or enter this PyMOL command:

```text
codex_chat
```

Older PyMOL builds that do not expose a compatible main window may show a
separate Codex window instead of an embedded tab.

Every PyMOL launch starts a new Codex conversation. Use **新建对话** when you
want another clean conversation without restarting PyMOL.

Try a read-only request first:

```text
Inspect the current objects, chains, ligands, and residue counts. Do not change
the scene.
```

Then try a visual task:

```text
Load 1FPU, identify the main organic ligand, show the ligand and protein
residues within 4 Å as sticks, and choose a clear view.
```

PyMOL asks for permission before Codex downloads a structure or opens a local
structure file.

## 4. Panel and keyboard controls

| Control | Purpose |
| --- | --- |
| **发送** | Send the message |
| **停止** | Ask Codex to stop the current turn |
| **新建对话** | Start a clean conversation |
| **模型设置…** | Change model, reasoning effort, or response speed |
| **启用不受限 Python（高风险）** | Allow separately approved Python code |
| **撤销最新一轮的修改** | Restore the latest available PyMOL undo point |

- `Enter`: send;
- `Ctrl+Enter` or `Shift+Enter`: insert a line break;
- `Esc`: keep the main panel open; in a separate dialog, cancel that dialog.

The initial transcript is four lines high and the editor is two lines high.
Long content scrolls inside each area. Drag the separator above the panel to
resize it. The transcript uses extra height while the controls stay at the
bottom. In the embedded panel, colors, fonts, and scrollbars follow the PyMOL
console.

The status line shows whether Codex is connecting, ready, working, retrying,
or waiting for an action. The **停止** and **模型设置…** buttons are enabled
only when they can safely be used.

## 5. Model settings

Open **模型设置…** to choose a model, reasoning effort, and response speed.
The choices come from the current Codex account and selected model; the plugin
does not contain a fixed model list.

Real defaults are marked **（默认）**. Baseline response speed appears as
**标准（默认）**; extra options such as Fast appear only when Codex reports
them. The reasoning and speed selectors are disabled when they contain only
one choice.

Settings take effect on the next message. They are saved locally, but after
every PyMOL launch the plugin first checks them against a fresh list from the
current Codex account. An option that is no longer available is replaced by
the current default. If the list cannot be loaded, conversations can continue
with Codex defaults.

Use **刷新模型列表** to retry loading the list. It is normal for
**模型设置…** to be disabled while Codex is working.

## 6. Unrestricted Python and undo

Normal PyMOL work should use the controlled tools. Enable
**启用不受限 Python（高风险）** only when those tools cannot complete the
task.

Unrestricted Python runs inside PyMOL with your operating-system permissions.
It can read or change files, access the network, start programs, crash PyMOL,
or become impossible to stop. The plugin therefore asks once when you enable
the switch and again for every code block. The complete code and Codex's
reason are shown before approval.

If Codex requests unrestricted Python while the switch is off, the plugin
rejects it and asks Codex to stop. Enable the switch and resend only if you
understand the risk and the controlled tools are insufficient.

The switch turns off automatically when you switch to **PyMOL 控制台**, hide
or close the Codex panel, replace or lose the Codex background process, or
exit PyMOL.

Before a user request first changes PyMOL, the plugin saves one `.pse` undo
point. All controlled changes and approved Python in that request share the
same point. Read-only requests do not create one.

**撤销最新一轮的修改** restores the newest available point. You can continue
undoing older modifying requests while their points remain. At most five are
kept for the current PyMOL process. Undo cannot restore ordinary files,
network activity, packages, or external programs, and its history does not
survive a PyMOL restart.

## 7. Data and privacy

Structure summaries and screenshots sent to Codex become part of the model
conversation. Check your organization's policy before using unpublished or
regulated structures.

Each PyMOL launch starts a new ephemeral Codex conversation rather than
resuming an earlier one. The plugin verifies the `thread/start` response before
it becomes ready. If the selected Codex does not explicitly confirm that the
new conversation is ephemeral, the plugin rejects it, attempts to delete the
unused record, and stops. If deletion also fails, the panel identifies the
record that may need to be removed manually in Codex.

The plugin stores the following data locally under Qt's per-user application
data, cache, or temporary directories:

- audit logs, which may include messages, tool arguments and results, approved
  code, and local paths;
- the 20 most recent screenshots;
- up to 5 recent `.pse` undo points for the current PyMOL process.

Audit files rotate at 5 MiB and keep three backups. Common credential fields,
Bearer tokens, and API-key-shaped text are redacted on a best-effort basis,
but this is not a guarantee. Never put passwords, API keys, or other secrets
in prompts or approved code.

On macOS and other POSIX systems, the plugin attempts to make these directories
and files private to the current user. Windows uses the access controls
inherited from the current user's Qt data directories. Undo points are removed
during a normal shutdown. If audit logging fails, the transcript shows a
warning, but the PyMOL tool result is still returned.

## 8. Troubleshooting

### Codex is not found

On Windows, verify `codex --version` in an independent PowerShell window. If it
fails, install the standalone CLI; do not select an executable from inside the
desktop app package.

On macOS, ChatGPT.app is detected automatically when its bundled Codex exists.
Do not select the `.app` directory itself. For a manual selection, choose its
`Contents/Resources/codex` file or a separately installed Codex CLI.

### Codex is not signed in

For a standalone CLI, run `codex` in Terminal or PowerShell, complete sign-in,
and restart PyMOL. When using the macOS ChatGPT.app fallback, sign in to the
ChatGPT app and restart PyMOL.

### The plugin cannot check Codex features

Before opening a conversation, the plugin runs a short safety check against
the selected Codex. It disables every reported optional feature except a small
reviewed set needed for proxy handling, transport, context maintenance, and
the model's advertised standard/fast service tiers. Newly reported features
therefore start disabled. If the plugin cannot verify the feature list, it
does not start the background service. Run:

```bash
codex features list
```

If the command fails or hangs, update Codex or choose the correct executable.

### The model list or a request times out

First check that `codex` works normally in a terminal. Then check the network,
system proxy, VPN, firewall, and DNS. Restart PyMOL after changing Codex or
plugin versions.

If `codex features list` shows `respect_system_proxy`, this diagnostic may
help:

```bash
codex doctor --summary --enable respect_system_proxy
```

Model-list failure does not prevent normal conversations; the plugin simply
uses Codex defaults until the list becomes available.

### The status says Codex is reconnecting

A temporary response-stream interruption is being retried automatically. If a
normal answer follows, the request succeeded. Only the final failure is added
to the transcript as an error.

### Stop does not unfreeze PyMOL

**停止** can interrupt the Codex turn, but it cannot safely terminate arbitrary
Python or native code already running inside PyMOL. If waiting does not help,
close PyMOL. Unsaved changes may be lost; after restarting, reopen a session
that you saved yourself. The plugin's automatic undo history belongs to the
old PyMOL process and is not available after a restart.

### The panel is separate instead of embedded

The plugin embeds into PyMOL only when it can access a compatible Qt main
window and native console dock. Older or differently packaged PyMOL builds may
use the standalone fallback window.

## Developer checks

Run unit tests without PyMOL:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Run the real-runtime and Qt smoke tests with PyMOL's bundled Python, then load
the dock test through the real GUI launcher:

```bash
PYTHONPATH=src /path/to/pymol/python scripts/pymol_smoke.py
PYTHONPATH=src /path/to/pymol/python scripts/pymol_ui_smoke.py
PYTHONPATH=src /path/to/pymol/launcher -k -r scripts/pymol_dock_smoke.py
```

On Windows PowerShell, set `$env:PYTHONPATH = "src"` first and use the
corresponding executables from the PyMOL installation. The `-k` flag keeps an
older installed plugin from shadowing the workspace version during the dock
test.
