# HeroFlow Desktop

HeroFlow Desktop 是一个面向 Windows 的本地英雄自动化与实时监控控制台。它使用 React + TypeScript 构建界面，以 Tauri 管理桌面窗口和进程生命周期，并由模块化 Python sidecar 执行图像识别、键鼠输入、英雄轮换、功耗监控与覆盖层显示。

> 本项目为独立的社区工具，与 Blizzard Entertainment 或《守望先锋》官方无隶属、授权或背书关系。请遵守游戏服务条款并自行承担自动化工具的使用风险。

## 功能

- 英雄分类、搜索、多选和比例轮换
- 完整自动化流程与独立 Loop2 模式
- 立即运行、预约启动、有限时长和无限模式
- 暂停、恢复、停止以及全局 F8 紧急停止
- 识别覆盖层、当前/下一流程步骤和分级日志
- 实时功率、累计能耗、五分钟曲线与费用估算
- 本地电价定位、缓存、档位和自定义价格
- Interception 驱动检查、UAC 安装和运行环境自检
- 程序打开期间保持系统唤醒，同时允许显示器按 Windows 设置自动熄灭
- 配置迁移、原子保存和危险关机操作二次确认

## 架构

```text
React UI
   │ Tauri command / event
Rust desktop shell
   │ newline-delimited JSON
Python backend
   ├─ automation core
   ├─ capture and input drivers
   ├─ scheduler and configuration
   ├─ power and tariff monitoring
   └─ overlay / F8 system services
```

`backend/` 是新桌面端的 Python 服务入口。根目录中的旧模块和 `gui.py` 暂时保留，用于功能回归和兼容验证。

## 开发

环境要求：

- Windows 10/11
- Node.js 20+
- Rust stable，目标 `x86_64-pc-windows-msvc`
- Python 3.10+ 与 `requirements.txt` 中的构建依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
cd frontend
npm install
npm run build
```

字体从根目录 `fonts/HarmonyOS Sans` 自动同步，桌面和安装包图标使用 `icon/icon.ico`。

构建 Python sidecar：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_sidecar.ps1
```

启动桌面开发环境：

```powershell
cd frontend
npm run desktop:dev
```

生成 NSIS 安装包：

```powershell
cd frontend
npm run desktop:build
```

## 数据与安全

- 用户配置保存在 Tauri 应用数据目录，而不是安装目录。
- Python 运行依赖随 sidecar 打包，成品应用不会执行在线 `pip install`。
- 电价定位和用户主动触发的驱动下载之外，核心流程不依赖网络。
- “关闭游戏”或“关闭电脑”必须在启动任务前再次确认；倒计时期间可通过界面或 F8 取消。

## 熄屏运行

HeroFlow 启动后会向 Windows 申请保持系统运行，避免电脑因空闲自动睡眠；该请求不会保持显示器常亮，因此显示器仍可按系统电源设置自动熄灭。退出 HeroFlow 后，请求会自动释放并恢复原有电源策略。

- 手动选择睡眠、按电源键或笔记本合盖仍会让系统进入睡眠，HeroFlow 不会阻止这些用户操作。
- Win+L 会切换到安全桌面，现有截图和键鼠自动化无法保证继续工作。
- Modern Standby 笔记本使用电池时可能限制保持唤醒请求，长时间任务建议接通电源。
- 部分显卡或显示器在熄屏后会停止提供新的 DXGI 帧，是否能持续识别应以实际硬件测试为准。

## License

项目代码采用 [MIT License](LICENSE)。HarmonyOS Sans 字体遵循 `fonts/HarmonyOS Sans/LICENSE-update.txt` 中的独立许可。
