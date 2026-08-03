# 发布 Codex for PyMOL

[English](RELEASING.md)

Release 由 GitHub Actions 在云端构建并发布，维护者不需要从自己的电脑构建或上传安装包。

## 发布前

1. 在 macOS 和 Windows 的目标 PyMOL/Qt 版本中实际测试当前提交。云端测试不能替代真实图形界面检查。
2. 同时更新 `pyproject.toml` 和 `src/codex_for_pymol/version.py` 中的版本号。
3. 如果条件允许，在本地运行单元测试并构建插件：

   ```bash
   PYTHONPATH=src python3 -m unittest discover -s tests -v
   python3 scripts/build_plugin.py
   ```

4. 提交改动并推送到 `main`，等待 **CI** 工作流全部通过。

## 发布 Release

在项目根目录读取源码中的版本号，创建包含开头 `v` 的同版本带说明标签，然后推送。macOS 或 Linux：

```bash
VERSION=$(PYTHONPATH=src python3 -c "from codex_for_pymol.version import __version__; print(__version__)")
git tag -a "v${VERSION}" -m "Codex for PyMOL v${VERSION}"
git push origin "v${VERSION}"
```

Windows PowerShell：

```powershell
$env:PYTHONPATH = "src"
$VERSION = py -c "from codex_for_pymol.version import __version__; print(__version__)"
git tag -a "v$VERSION" -m "Codex for PyMOL v$VERSION"
git push origin "v$VERSION"
```

随后 **Release** 工作流会自动：

1. 运行完整的 macOS 和 Windows CI 测试矩阵；
2. 拒绝不属于 `main` 历史或与源码版本不一致的标签；
3. 在云端构建 Python 包和可安装的 PyMOL 插件；
4. 验证插件 ZIP 可以正常导入；
5. 生成 SHA-256 校验文件；
6. 创建带有自动生成更新说明的 GitHub Release。

公开 Release 中包含 `codex-for-pymol.zip` 和 `SHA256SUMS.txt`。GitHub 会自动提供源码 ZIP 和 tar 压缩包。工作流仍会构建 wheel 和 Python 源码包来检查打包配置，但不会把它们作为 Release 附件，因为普通 PyMOL 用户应当安装插件 ZIP。

推送标签后，请等待 **Release** 工作流成功结束，不要再手动创建 Release 或上传文件。只有工作流发布成功后，[Releases 页面](https://github.com/wuhuawei1996/codex-for-pymol/releases)才会出现可供下载的安装包。

整个过程不需要个人访问令牌、Codex 凭证或 API Key。最终任务只使用 GitHub 为当前工作流临时签发的仓库令牌，并且只申请 `contents: write` 权限。

## 发布失败时

- 版本错误表示标签、`pyproject.toml` 与 `src/codex_for_pymol/version.py` 不一致。不要移动已经公开的版本标签；修正版本后发布一个新标签。
- 最终任务出现 HTTP 403，通常表示仓库或组织策略禁止写入。检查 **Settings → Actions → General → Workflow permissions**。
- 测试或构建失败时不会创建 Release。修复问题并提交，然后发布一个新的版本标签；仅重新运行旧工作流不会把原标签移动到修复后的提交。
