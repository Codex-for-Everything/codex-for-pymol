# Codex for PyMOL

[English](README.md) | [简体中文](docs/README.zh-CN.md)

Codex for PyMOL adds a Codex chat panel to PyMOL. You can describe what you
want in ordinary language, and Codex can inspect the current structure,
prepare a view, highlight residues, measure distances, and help with other
PyMOL tasks without making you write PML commands.

> The current plugin interface is in Simplified Chinese. This English guide
> shows the exact Chinese button labels so they are easy to find.

Detailed guide: [English](docs/INSTALL.md) | [简体中文](docs/INSTALL.zh-CN.md)

## What it can do

- Inspect loaded objects, chains, residues, ligands, selections, and the view.
- Download a structure or open a local structure file after asking permission.
- Show, hide, color, select, center, orient, label, and measure structures.
- Return PyMOL screenshots to Codex so it can check the visual result.
- Keep one undo point for each recent user request that changed PyMOL.
- Use unrestricted Python only when you explicitly enable and approve it.
- Read the models, reasoning levels, and response speeds available to the
  current Codex account instead of relying on a built-in list.

## Requirements

- PyMOL 2.x or 3.x with the Qt interface
- Python 3.8 or newer inside PyMOL
- An installed and authenticated `codex` CLI
- A recent Codex CLI; the plugin reports clearly if the installed version is
  missing the required integration interface

The plugin does not install extra Python packages into PyMOL.

## Quick start

1. Download `pymol_codex_plugin.zip` from the matching GitHub Release.
2. In PyMOL, open:

   ```text
   Plugin → Plugin Manager → Install New Plugin → Choose file…
   ```

3. Select the zip and restart PyMOL.
4. The **Codex 助手** tab should open automatically beside
   **PyMOL 控制台** at the bottom of the main window.
5. Type a request and press `Enter`.

If the panel does not open, select:

```text
Plugin → PyMOL Codex 助手
```

You can also enter `codex_chat` in the PyMOL command line. See the
[installation guide](docs/INSTALL.md) for source builds and troubleshooting.

## Everyday controls

| Control | Purpose |
| --- | --- |
| **发送** | Send the current message |
| **停止** | Ask Codex to stop the current turn |
| **新建对话** | Clear the transcript and start a fresh Codex conversation |
| **模型设置…** | Choose from the models and options returned by the current Codex account |
| **启用不受限 Python（高风险）** | Allow separately approved Python code to run inside PyMOL |
| **撤销最新一轮的修改** | Restore PyMOL to before the latest user request that changed it |

`Enter` sends. `Ctrl+Enter` or `Shift+Enter` inserts a line break. Pressing
`Esc` in the main panel does not close it.

The panel opens with a four-line transcript and a two-line message editor.
Drag the separator above the panel to change its height. The transcript grows
with the panel; the controls remain at the bottom. When embedded, the panel
follows the PyMOL console colors and scrollbar style.

Every PyMOL launch starts a new conversation. Previous conversation context is
not silently resumed. Saved model choices remain available, but they are used
only after the current Codex connection confirms that those options still
exist.

## Safety and privacy

The normal mode uses a small set of controlled PyMOL tools. It does not give
Codex general shell or file-editing access. The plugin first checks which
security features the selected Codex supports; if that check fails, it stops
instead of starting with an unknown permission boundary.

PyMOL asks before Codex downloads a structure or reads a local structure file.

**启用不受限 Python（高风险）** is different. Approved code runs inside the
PyMOL process with your operating-system permissions. It may read or change
files, access the network, start programs, crash PyMOL, or become impossible
to interrupt. Enabling the switch requires a warning confirmation, and every
code block requires another approval. Switching away from, hiding, or closing
the Codex panel disables the switch automatically.

Before a user request first changes PyMOL, the plugin saves a `.pse` undo
point. **撤销最新一轮的修改** can restore PyMOL session state, but it cannot
undo files, downloads, network activity, installed packages, or external
programs.

Structure summaries and screenshots sent to Codex become part of the model
conversation. Do not use unpublished or regulated structures unless that is
allowed by your organization.

The plugin also stores local audit logs, screenshots, and temporary undo
points. Audit logs may contain your messages, tool details, code, and local
paths. Common credential formats are redacted on a best-effort basis, but you
should never put secrets in prompts or approved code. The plugin keeps:

- audit files up to 5 MiB each, plus three rotated backups;
- the 20 most recent screenshots;
- up to 5 recent undo points in the current PyMOL process.

Undo points are removed during a normal shutdown. See
[Data and privacy](docs/INSTALL.md#7-data-and-privacy) for details.

## Current limitations

- Unrestricted Python that has already started cannot always be stopped safely.
- Undo restores only the PyMOL session.
- Dynamic tools are still an experimental Codex App Server feature, so a Codex
  protocol change may require a plugin update.
- GitHub CI tests the Python code and package builds on macOS and Windows, but
  a release should still be checked inside the intended PyMOL/Qt versions on
  both systems.

## Development

Run the unit tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Build the wheel and source distribution with Hatchling:

```bash
python3 -m pip install build==1.2.2.post1
python3 -m build
```

Build the installable PyMOL plugin zip:

```bash
python3 scripts/build_plugin.py
```

On Windows, use `py` or an available `python` command instead of `python3` and
set `$env:PYTHONPATH = "src"` before running tests. The
[installation guide](docs/INSTALL.md) lists the real PyMOL smoke-test commands.

License: [English](LICENSE) | [简体中文参考译文](docs/LICENSE.zh-CN.md)
