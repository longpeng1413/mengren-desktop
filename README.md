# 猛人桌面助手

Windows 截图与桌面效率工具（原名“猛人软件”“猛人截图”），当前版本 **v18.22 正式版**。

- F1：普通截图、标注、OCR 与翻译
- F2：纵向长截图（自动分段滚动、稳定检测与拼接）
- F3：桌面工具（文字/图片贴图、闹钟、计时器、倒计时、计算器、睡眠）
- F4：演示教鞭与绘图工具
- 支持多显示器、高 DPI、全局快捷键和系统托盘

**下载**：到 [Releases](https://github.com/longpeng1413/mengren-desktop/releases/latest) 下载 `mengren-desktop-v<版本>-windows-x64.zip`，完整解压后双击文件夹里的 `猛人桌面助手v<版本>.exe`，免安装。

操作方法见 [使用说明.txt](./使用说明.txt)，版本变化见 [版本说明.txt](./版本说明.txt)。

## 开发

需要 Windows 10/11 和 Python 3.12 或更新版本（已在 3.14 上验证）。

```powershell
git clone https://github.com/longpeng1413/mengren-desktop.git
cd mengren-desktop
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

.venv\Scripts\python.exe main.py            # 运行
.venv\Scripts\python.exe -m pytest -q       # 测试
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1   # 打包
```

打包结果在 `dist\猛人桌面助手v<版本>正式版\`，整个文件夹即可直接使用或发给别人。

## 项目结构

```
main.py          程序入口
app/             启动、托盘、快捷键、设置、开机自启动
core/            截图、长截图拼接、OCR、翻译
ui/              截图编辑器、教鞭、桌面工具等界面
resources/       图标
scripts/         打包脚本
tests/           自动测试
```

## 密钥与设置

- 有道翻译密钥：把 `.env.example` 复制为 `.env`（放在 EXE 旁边或源码根目录）后填写；`.env` 不会提交到仓库。其他翻译服务在软件的“翻译 API 设置”中填写。
- 用户设置保存在 `%APPDATA%\AIShot`，升级不会丢失。
- 闹钟默认提示音由程序生成；如有授权，可自行放置 `resources/audio/default_reminder.mp3`。

## 许可证

[GPL-3.0-only](./LICENSE)。可以使用、修改和再发布；对外发布修改版时须按 GPLv3 同时提供完整源代码。本软件按“原样”提供，不附带任何担保。

Copyright (C) 2026 longpeng1413
