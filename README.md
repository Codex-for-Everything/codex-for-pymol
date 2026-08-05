# Codex for PyMOL

[English](README.md) | [简体中文](docs/README.zh-CN.md)

Codex for PyMOL adds a Codex chat panel to PyMOL. You can describe what you
want in ordinary language, and Codex can inspect the current structure,
prepare a view, highlight residues, measure distances, and help with other
PyMOL tasks without making you write PML commands.

This is an independent community project, not an official PyMOL or OpenAI
product.

> **Vibe-coding disclosure:** This project was created entirely through vibe
> coding with Codex. Its implementation, tests, documentation, and release
> automation were developed in collaboration with Codex and reviewed through
> the validation described in this repository.

The interface supports English and Simplified Chinese. On first use it uses
Simplified Chinese for a Chinese system locale and English otherwise; you can
change it at any time under **Settings… → Interface language**.

Detailed guide: [English](docs/INSTALL.md) | [简体中文](docs/INSTALL.zh-CN.md)

> **Windows upgrade notice:** Versions 0.3.2 and earlier contain
> Windows-specific bugs that can make button text nearly invisible and prevent
> the plugin from finding or starting some Codex CLI installations, especially
> npm `.cmd` launchers. Windows users should install version 0.4.0 or later.

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
- A recent, authenticated Codex executable; the accepted source differs by
  platform as shown below

| Platform | Codex requirement for this plugin |
| --- | --- |
| **Windows** | Install the standalone [Codex CLI](https://developers.openai.com/codex/cli/) and make sure `codex --version` works in PowerShell. Installing only the ChatGPT/Codex desktop app is not sufficient. |
| **macOS** | Either install the standalone Codex CLI, or install ChatGPT.app with its bundled `Contents/Resources/codex` executable. The plugin detects both automatically. |

The plugin reports clearly if the selected executable is missing the required
integration interface.

The plugin does not install extra Python packages into PyMOL.

## Quick start

1. Open the [latest GitHub Release](https://github.com/wuhuawei1996/codex-for-pymol/releases/latest) and download `codex-for-pymol-X.Y.Z.zip` from **Assets**, where `X.Y.Z` is the release version. Do not download GitHub's automatically generated **Source code** archives, and do not extract the plugin zip.
2. In PyMOL, open:

   ```text
   Plugin → Plugin Manager → Install New Plugin → Choose file…
   ```

3. Select the zip and restart PyMOL.
4. The **Codex Assistant** (or **Codex 助手**) tab should open automatically
   beside the PyMOL console at the bottom of the main window.
5. Type a request and press `Enter`.

> Upgrading from 0.2.x or earlier: uninstall the old plugin in PyMOL's Plugin
> Manager and restart PyMOL before installing 0.3.0 or newer. The internal
> package name changed, so leaving the old copy installed may load both copies.

If the panel does not open, select:

```text
Plugin → Codex for PyMOL
```

You can also enter `codex_chat` in the PyMOL command line. See the
[installation guide](docs/INSTALL.md) for source builds and troubleshooting.

## Everyday controls

| Control | Purpose |
| --- | --- |
| **Send** | Send the current message |
| **Stop** | Ask Codex to stop the current turn |
| **New conversation** | Clear the transcript and start a fresh Codex conversation |
| **Settings…** | Change the interface language and choose options returned by the current Codex account |
| **Enable unrestricted Python (high risk)** | Allow separately approved Python code to run inside PyMOL |
| **Undo the latest turn's changes** | Restore PyMOL to before the latest user request that changed it |

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
Codex general shell or file-editing access. At startup, the plugin reads the
exact optional-feature list from the selected Codex and disables unrelated
capabilities, including shell, plugin, skill, and environment access. A future
feature is disabled unless the integration has explicitly classified it as
necessary and safe. If the list cannot be verified, startup stops instead of
using an unknown permission boundary. Each PyMOL conversation is also started
as an ephemeral, read-only Codex thread with no Codex environment attached.
The plugin also verifies that Codex confirms the thread will not be saved; if
that guarantee is unavailable, it rejects the thread and attempts to remove
the empty record instead of silently adding it to Codex history.

PyMOL asks before Codex downloads a structure or reads a local structure file.

**Enable unrestricted Python (high risk)** is different. Approved code runs inside the
PyMOL process with your operating-system permissions. It may read or change
files, access the network, start programs, crash PyMOL, or become impossible
to interrupt. Enabling the switch requires a warning confirmation, and every
code block requires another approval. Switching away from, hiding, or closing
the Codex panel—or replacing or losing the Codex background process—disables
the switch automatically.

Before a user request first changes PyMOL, the plugin saves a `.pse` undo
point. **Undo the latest turn's changes** can restore PyMOL session state, but it cannot
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

The commands in this section are for contributors. Ordinary PyMOL users should
install `codex-for-pymol-X.Y.Z.zip` from a GitHub Release, not a wheel, source
distribution, or GitHub source archive.

Run the unit tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Optionally verify the installed Codex App Server's temporary-conversation
contract without sending a model request or reading normal Codex history:

```bash
PYTHONPATH=src python3 scripts/codex_app_server_smoke.py
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
Maintainers should follow the bilingual
[release guide](docs/RELEASING.md) for cloud builds and GitHub Releases.

License: [English](LICENSE) | [简体中文参考译文](docs/LICENSE.zh-CN.md)
