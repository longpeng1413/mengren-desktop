# 猛人桌面助手 (MengRen Desktop) Maintenance Rules

These rules apply to every future modification in this project.

## Product

- The product is **猛人桌面助手** (formerly 猛人软件 / 猛人截图); GitHub repo `longpeng1413/mengren-desktop`.
  Every release is called **正式版**. There is only one edition and one entry point, `main.py`.
- `app/branding.py` defines `PRODUCT_NAME` and `APP_VERSION`; nothing else hard-codes the name or version.
  Old names stay in `LEGACY_AUTOSTART_NAMES` so existing Windows startup entries are migrated.
- The settings folder keeps its historical name `%APPDATA%\AIShot`; never rename it or users lose settings.
- Recording and horizontal long capture were removed in v18.19 and the old code was deleted from
  GitHub entirely at the user's request; do not re-add it unless the user asks.

## Versioning

- A major user-facing update increments the integer version: `18` to `19`, then `20`.
- A smaller update increments the decimal release: `18.19` to `18.20`, and so on.
- After a major release, its smaller updates use that major number, for example `19.1`.
- `tests/test_release.py` asserts the current version; update it together with `branding.py`.

## Documentation required for every change

- Update `使用说明.txt` whenever user-visible behavior changes; keep its first line as
  `猛人桌面助手v<version>正式版 使用说明`. Describe current behavior only, not version history.
- Prepend a release entry to `版本说明.txt` for every released modification, headed
  `猛人桌面助手v<version>正式版`.
- All text files use UTF-8 without BOM. PowerShell scripts stay ASCII and build Chinese file names
  from `[char]` code points so Windows PowerShell 5.1 reads them correctly.

## Testing and release

- Add or update regression tests for changed behavior.
- `tests/conftest.py` redirects `APPDATA` to a temporary folder for every test so the developer's
  real `%APPDATA%\AIShot` settings are never touched. Keep it that way.
- Run the full suite with `.venv\Scripts\python.exe -m pytest -q`.
- Build with `scripts\build_windows.ps1`; the release is the single folder
  `dist\猛人桌面助手v<version>正式版\` (EXE + docs at the top, runtime in `_internal`).
  The script deletes Qt parts the app never loads; after upgrading PySide6, check no remaining
  binary imports a deleted DLL before trusting the list.
- To publish: build with `-Zip`, commit, tag `v<version>`, push, then
  `gh release create v<version>` with `dist\mengren-desktop-v<version>-windows-x64.zip` and
  `dist\SHA256SUMS.txt`, titled `猛人桌面助手 v<version> 正式版`.
- Do not deliver a release until tests pass, the build finishes without errors and the packaged
  EXE starts. Always launch it with `scripts\smoke_test.ps1`, never by hand: a packaged EXE
  re-points the developer's real Windows startup entry to itself, and the script saves and
  restores every startup entry name this product has used.
