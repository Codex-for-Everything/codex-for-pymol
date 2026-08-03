# Releasing PyMOL Codex

[简体中文](RELEASING.zh-CN.md)

Releases are built and published by GitHub Actions. Maintainers do not need to
build or upload packages from their own computer.

## Before releasing

1. Test the current commit in the intended PyMOL/Qt versions on macOS and
   Windows. Cloud tests do not replace these real GUI checks.
2. Update the version in both `pyproject.toml` and
   `src/pymol_codex/version.py`.
3. Run the unit tests and build the plugin locally when possible:

   ```bash
   PYTHONPATH=src python3 -m unittest discover -s tests -v
   python3 scripts/build_plugin.py
   ```

4. Commit and push the changes to `main`, then wait for the **CI** workflow to
   pass.

## Publish a release

Create an annotated tag that exactly matches the code version, including the
leading `v`, and push it:

```bash
git tag -a v0.2.34 -m "PyMOL Codex v0.2.34"
git push origin v0.2.34
```

The **Release** workflow then:

1. runs the complete macOS and Windows CI matrix;
2. rejects a tag outside `main` or one that does not match the source versions;
3. builds the Python distributions and installable PyMOL plugin in the cloud;
4. verifies that the plugin ZIP can be imported;
5. generates a SHA-256 checksum; and
6. publishes a GitHub Release with generated release notes.

The public release contains `pymol_codex_plugin.zip` and `SHA256SUMS.txt`.
GitHub supplies source ZIP and tar archives automatically. The wheel and Python
source distribution are built as packaging checks but are not release assets,
because ordinary PyMOL users should install the plugin ZIP.

No personal access token, Codex credential, or API key is required. The final
job uses GitHub's short-lived repository token with only `contents: write`
permission.

## If publication fails

- A version error means that the tag, `pyproject.toml`, and
  `src/pymol_codex/version.py` do not agree. Do not move a published version
  tag; fix the version and publish a new tag.
- An HTTP 403 during the final job means repository or organization policy may
  be preventing write access. Check **Settings → Actions → General → Workflow
  permissions**.
- A failed test or build does not create a Release. Fix the problem, commit it,
  and publish a new version tag.
