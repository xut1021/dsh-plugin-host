# DSH 插件托管

**给 DeepSeek Harness 的插件和设置一个固定的家。**

Windows 外置管理面板：更新前后检查插件声明与依赖、保留可用版本、管理插件启停、浏览插件市场，并加密备份配置。DSH 无法启动时，仍可单独打开面板查看原因。

这是一个早期社区工具，与 DeepSeek 官方无隶属关系。它复用已安装 DSH 的官方兼容检查和包管理能力；**检查通过不等于插件实际功能正常**。目前没有实现隔离环境中的全功能试运行、自动晋升或任意更新后的完全无感迁移。

## 能做什么

| 功能 | 当前行为 |
| --- | --- |
| 更新检查 | 使用所选 DSH 版本自己的加载器检查版本声明；结合插件依赖和历史启动日志提示阻断原因 |
| 版本切换 | 在本机配置的新版本、保留版本之间选择，并记住默认选择；检查不通过时优先使用可用版本 |
| 插件开关 | 关闭项排在底部，重新开启恢复原有顺序；运行中更改记为“待重启”，下次托管启动前应用 |
| 来源展示 | 区分本地、npm、GitHub 等安装声明与项目仓库地址；点击可查看来源详情 |
| 插件市场 | 搜索、分类、查看详情和 Star 数；通过 DSH 包管理器安装目录中明确的 npm 固定版本 |
| 配置保留 | 固定 `DSH_HOME`、desktop profile 和 Electron 数据目录，避免更新后误用另一个配置目录 |
| 配置快照 | Windows 当前用户 DPAPI 加密、完整性检查、恢复前检查、写入失败回滚 |

不强制结束正在运行的 DSH。切换版本需要正常退出当前实例；安装插件及恢复配置也需要先退出 DSH。复杂条件控制的插件显示“自动”，不会把原表达式覆盖成简单开关。

## 安装与使用

需要 Windows、Python 3.12（带 Tkinter 和 `pythonw.exe`）、PowerShell 7，以及已经安装并初始化 desktop profile 的 DSH 桌面版。保留版本由你自行准备；本项目不下载或重新分发 DSH。

开发时使用的 DSH 版本为 `0.1.7-rc.2` 和 `0.2.0-rc.1`。这些版本的内部加载器布局是当前适配依据，不保证其他版本接口相同。Node.js 22 仅用于运行源码测试；日常探测和安装使用 DSH 随附运行时。

在 PowerShell 7 中执行：

```powershell
git clone https://github.com/xut1021/dsh-plugin-host.git
cd dsh-plugin-host
python -m pip install --target vendor -r requirements.txt
Copy-Item local.example.json local.json
notepad local.json
```

把示例中的三个路径改成自己的真实路径：

| 配置项 | 应填内容 |
| --- | --- |
| `home` | **已有的** DSH 数据根目录，其下应有 `profiles/desktop/package.json`。不要为了切换版本新建一个空目录 |
| `current_exe` | 当前安装版本的 `DeepSeek Harness.exe` 完整路径 |
| `fallback_exe` | 保留版本的可执行文件完整路径；只有一个版本时，填与 `current_exe` 相同的路径 |
| `launch_env` | 可选的启动环境变量；默认为空对象。不要把含私人代理或凭据的配置提交到仓库 |

路径可使用 JSON 中的正斜杠，例如 `C:/DSH/data`；示例路径只是占位，不会自动创建数据目录。`preferred_exe` 会由面板保存，无须手填。

先检查，再打开面板：

```powershell
python -X utf8 ./host.py check
python -X utf8 ./ui.py
```

“检查版本”下拉框只切换兼容性预览；顶部“切换版本”才设置启动选择。检查有阻断项时查看具体插件，不要通过批量修改声明或豁免假装兼容。

### 可选：接管启动入口

确认 `local.json` 正确后，可运行：

```powershell
pwsh -NoProfile -File ./install.ps1 -Action Install
```

这一步会备份并绑定桌面/开始菜单的 DSH 快捷方式，创建“DSH 插件托管”入口和当前用户的开机检查器，并设置用户级 `DSH_HOME`。**用户级 `DSH_HOME` 也会影响未显式指定数据目录的 DSH CLI。** 后台约每 20 秒查看安装及配置变化，异常证据变化时提醒；不自动下载更新或禁用插件。

请保持项目目录位置稳定。撤销整合会恢复安装前的快捷方式和 `DSH_HOME`，保留项目、快照及 DSH 数据：

```powershell
pwsh -NoProfile -File ./install.ps1 -Action Remove
```

撤销托管不能修复原版本的插件兼容问题。

## 配置到底能记住哪些

已有插件设置通过继续使用原数据目录保留。配置快照覆盖 desktop profile 中的 `package.json`、`cordis.yml`、`cordis.patch.yml`、`pnpm-lock.yaml`、`pnpm-workspace.yaml`、`compatibility.json`（存在时），另保存插件清单指纹。

- 快照不包含 `.credentials.yaml`、会话数据库、附件或整个 `node_modules`；它不是完整数据备份。
- 插件自行存到 home 其他位置的文件会留在原地，但不自动纳入快照。比如 Dream Skin 或提示词增强独立保存的配置。
- 浏览器 localStorage、插件私有配置格式的跨版本迁移仍可能受端口或实现变化影响，未逐项验证。
- DPAPI 快照依赖原 Windows 用户及系统密钥，不作为跨电脑迁移格式。
- 恢复需正常退出 DSH，并要求插件清单和快照一致。配置文件集合或包版本发生变化会拒绝覆盖。

```powershell
python -X utf8 ./host.py snapshot
python -X utf8 ./host.py restore --snapshot-id 具体快照ID
```

安装前快照只保护配置。包管理器失败可能留下包文件变化，当前没有实现整个插件安装目录的事务回滚。

## 直接使用了什么

下表区分“执行时调用”“安装依赖”和“数据来源”。本仓库发布 Python/JavaScript/PowerShell 管理代码，不随仓库打包 DSH、插件包、第三方 `vendor/` 或社区目录快照。

| 上游内容 | 直接使用方式 | 对应代码 / 许可 |
| --- | --- | --- |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 的 `@deepseek-ai/dsh-app-boot` | 从用户已安装的 DSH 动态导入 `loadProfileDirectory`、`evaluatePluginCompatibility`、profile/patch 合成及版本例外读取等接口。官方版本判定并非本项目重写 | [probe.mjs](probe.mjs)、[toggle-patch.mjs](toggle-patch.mjs)；上游 [MIT](https://github.com/deepseek-ai/deepseek-harness/blob/master/LICENSE) |
| [DSH 官方插件管理器](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/boot/plugin-manager/README.md) | 动态调用 `operations.runPluginCommand`，使用 DSH 随附 pnpm 固定版本安装；未将其包管理核心源码复制进本仓库 | [market_install.mjs](market_install.mjs)、[market_install.py](market_install.py) |
| DSH 随附的 `yaml`、`js-yaml` 和 `@deepseek-ai/cordis-plugin-include` | 从 DSH 安装目录解析并调用，用于读取/修改 patch 和处理入口；本仓库不重新分发这些包，版本和许可随目标 DSH 发行包 | [toggle-patch.mjs](toggle-patch.mjs) |
| [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter/tree/v5.2.2) 5.2.2 | 直接使用其窗口、按钮、卡片、开关等控件 | [ui.py](ui.py)、[requirements.txt](requirements.txt)；随包 [MIT](https://github.com/TomSchimansky/CustomTkinter/blob/v5.2.2/LICENSE) |
| [darkdetect](https://github.com/albertosottile/darkdetect) 0.8.0、[packaging](https://github.com/pypa/packaging) 26.3 | CustomTkinter 的间接依赖，固定版本安装 | [requirements.txt](requirements.txt)；BSD-3-Clause、Apache-2.0 OR BSD-2-Clause，另保留包内子组件声明 |
| [awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin) [社区目录](https://awesome-dsh-plugin.com/plugins.json) | 运行时读取名称、作者、说明、仓库、分类、npm 版本及 Stars；不是自建市场，也不是逐项实时查询 GitHub | [market.py](market.py)；目录上游 [CC0-1.0](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/blob/main/LICENSE) |
| Python 标准库、Tkinter、Windows DPAPI 和 Shell | 用于文件操作、原生窗口、加密、快捷方式与进程检查 | [host.py](host.py)、[install.ps1](install.ps1) |

Stars 的日期是社区目录快照日期，缺失值显示“暂无数据”。目录的许可不等于其中各插件代码的许可。依赖的原始许可证由其发行包提供；本项目的 MIT 不替代这些许可。CustomTkinter 5.2.2 的包元数据与随包 LICENSE 存在差异，本项目按核验的随包 MIT 文本标注。

## 参考了哪些设计，具体参考什么

以下四个社区项目用于文档和设计思路参考。本次来源核查未发现将它们作为代码依赖导入或把其应用实现、发布包、资源文件打包到本仓库；没有安装或实测这些参考项目，也未做全网代码相似性鉴定。

| 参考项目 | 借鉴的具体思路 | 本项目对应实现 / 未采用的部分 |
| --- | --- | --- |
| [dsh-backup](https://github.com/xiaoyuyu6420/dsh-backup) | 脱离 DSH 的救援入口、备份校验、恢复失败回滚 | 外置面板与加密配置快照；未采用其救援网页，没有包含会话/附件的完整备份 |
| [Deepseek-Harness-Window](https://github.com/kxSenlin/Deepseek-Harness-Window) | 外置插件清单、来源展示、宿主失败后离线管理 profile | Python 原生面板与启停队列；未复用其 WPF 界面或将 desktop 配置改成 web 配置 |
| [dsh-plus-plus](https://github.com/limlnx523/dsh-plus-plus) | 插件诊断、升级前后检查及回归验证的思路 | 明确区分声明兼容、依赖提示与功能验证；未引入其工作流测试引擎或凭据管理 |
| [dsh-config-manager](https://github.com/xiajiajun516/dsh-config-manager) | 恢复前检查、冲突保留、失败回滚 | 配置及插件指纹检查、安装同名包时拒绝覆盖；未引入其跨机器导入、路径映射或云同步 |
| [Taste Skill](https://github.com/Leonxlnx/taste-skill) / `design-taste-frontend` | 字体层级、间距、颜色克制、一致性等设计约束 | 用于开发过程中的界面审查；不是运行依赖，未将 Skill 内容或网页模板打包到应用 |
| DSH 插件市场界面的用户截图 | 双列卡片、配色与信息层次 | 用 Tk 控件实现；未附带用户截图或 DSH 原界面素材 |

本项目实现的是这些能力之间的本机协调：固定目录、版本选择、状态报告、待重启启停事务、DPAPI 快照、来源整理、市场浏览和控件复用。上游兼容检查、包管理器及 UI 控件等能力按上表直接复用，不宣称全部从零实现。更详细的来源与资源许可边界见 [REFERENCE_NOTES.md](REFERENCE_NOTES.md)。

## 开发与验证

在 Windows 上安装依赖后运行：

```powershell
python -X utf8 -m unittest discover -p 'test_*.py' -v
node --test test_plugin_entries.mjs test_source_metadata.mjs
```

测试使用临时 profile 和模拟回调；不安装到日常 DSH，也不为测试修改真实插件开关。覆盖配置加密/恢复、版本选择、启停事务、市场安装边界、来源脱敏、Stars、文字排版及控件复用。隐藏窗口测试能验证控件状态与布局，不能代替每台机器上的视觉和插件功能验收。

默认套件不需要 DSH 安装，会跳过 9 项加载器集成测试。要用自己的已安装 DSH 验证这些测试，可在当前 PowerShell 进程设置以下变量；测试只操作临时构造的 profile，不启动 DSH 桌面：

```powershell
$env:DSH_TEST_RUNTIME = 'C:/DSH/retained/DeepSeek Harness.exe'
python -X utf8 -m unittest test_host.PluginToggles -v
Remove-Item Env:DSH_TEST_RUNTIME
```

提供 [Windows GitHub Actions 模板](examples/windows-tests.yml)。当前源码仓库未启用自动运行；仓库维护者使用具有 workflow 写入权限的 GitHub 授权，将模板复制为 `.github/workflows/tests.yml` 后提交即可启用。模板使用 Windows、Python 3.12、Node 22 和 PowerShell；默认跳过需要本机 DSH 的集成测试。

本机原型曾验证原配置下的保留版本启动，以及临时 desktop profile 的真实包安装和不兼容包拒绝。尚未完成全新 Windows 机器的端到端安装验收，也未实现逐插件功能回归；请按早期版本使用。

## 隐私与许可证

`local.json`、`state/`、`vendor/`、日志、备份和个人环境不随仓库提交。`state/report.html` 及来源详情可能包含本机路径；反馈问题前请自行移除私人信息，不要上传配置或快照。

本项目管理代码采用 [MIT License](LICENSE)。第三方软件、字体、目录数据和安装的插件继续遵守各自许可；本项目不代表任何被参考项目或 DeepSeek 官方。
