# 来源核查与发行边界

核查日期：2026-09-29。README 列出了功能层面的直接复用与设计参考，此处记录核查依据和源码发行时的取舍。依据包括当前导入语句、已安装发行包的许可证及显式来源声明、公开上游文档；未做全网代码相似性鉴定。

## 执行时直接调用的 DSH 组件

- `probe.mjs` 从用户所选 DSH 的 `resources/app.asar/dsh` 下导入 `@deepseek-ai/dsh-app-boot`，调用官方 profile 加载、版本判定、入口合成等接口。
- `market_install.mjs` 调用 `@deepseek-ai/dsh-plugin-manager/lib/types/operations.js` 中的 `runPluginCommand`，通过随附 pnpm 进行固定版本安装。依据：[官方包管理文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/boot/plugin-manager/README.md)。
- `toggle-patch.mjs` 通过目标 DSH 的模块解析路径调用 `yaml`、`js-yaml`、`@deepseek-ai/cordis-plugin-include` 和加载器，修改入口 disabled 标志。这些解析器不是本项目自研。
- DSH 主仓库采用 [MIT](https://github.com/deepseek-ai/deepseek-harness/blob/master/LICENSE)。DSH 的其他依赖分别保留其原有许可；本仓库不分发 DSH 及随附依赖。

这里依赖的是已安装版本的实际内部接口，不承诺它们是长期稳定的公共 API。官方兼容判断、项目补充的依赖提示、历史启动日志证据与真正的插件功能验证是不同层次。

## 直接使用的市场数据

`market.py` 从 [plugins.json](https://awesome-dsh-plugin.com/plugins.json) 读取目录，不执行目录里的命令字符串。目录中的 `source` 指向 [awesome-dsh-plugin/awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin)，其 [LICENSE](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/blob/main/LICENSE) 为 CC0-1.0。

直接使用字段包括插件名称、作者、描述、分类、仓库、npm 身份和版本、Star 数。Stars 是目录快照值；项目不声称实时查询 GitHub，也不把缺失数值写成零。目录的许可不覆盖所列插件的源码和资源；本仓库不附带目录快照或插件包。

## Python 依赖及其附带内容

依赖通过 `requirements.txt` 安装，`vendor/` 不进入 Git 或源码归档：

| 组件 | 版本 | 核验到的许可 |
| --- | --- | --- |
| [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) | 5.2.2 | 随包 [LICENSE](https://github.com/TomSchimansky/CustomTkinter/blob/v5.2.2/LICENSE) 为 MIT，Copyright 2023 Tom Schimansky。METADATA 的许可字段与此不一致，以随包许可文本披露 |
| [darkdetect](https://github.com/albertosottile/darkdetect) | 0.8.0 | [BSD-3-Clause](https://github.com/albertosottile/darkdetect/blob/v0.8.0/LICENSE)，Copyright 2019 Alberto Sottile |
| [packaging](https://github.com/pypa/packaging) | 26.3 | [Apache-2.0 OR BSD-2-Clause](https://github.com/pypa/packaging/blob/26.3/LICENSE)，部分实现另附 MIT 来源声明 |

如果以后打包 EXE 或连同 vendor 分发，还需要保留包内全部子组件和资源声明，不能只附本项目的 MIT：

- CustomTkinter 所附 Roboto 字体的嵌入信息标明 Google 版权、Apache-2.0。需随字体提供适用的版权和许可文本。
- `packaging/licenses/__init__.py` 明确说明适配自 [pypa/hatch](https://github.com/pypa/hatch)，并内嵌 Ofek Lev 的 MIT 声明，应完整保留。
- CustomTkinter 的 `windows_load_font` 注明取自 [Stack Overflow 回答 30631309](https://stackoverflow.com/questions/11993290/truly-custom-font-in-tkinter/30631309#30631309)。其来源声明和适用许可不应被省略。

这次发布的是源码，不包含上述第三方包、字体或解释器。通过 pip 安装仍会取得上游的代码和资源，本项目不会把这些组件描述为原创。

## 设计参考

| 参考项目 | 参考的文档/思路 | 采用边界 |
| --- | --- | --- |
| [dsh-backup](https://github.com/xiaoyuyu6420/dsh-backup) | 独立救援、备份校验、恢复失败回滚 | 当前只有配置快照；未导入其救援网页或完整备份实现 |
| [Deepseek-Harness-Window](https://github.com/kxSenlin/Deepseek-Harness-Window) | 外置插件管理、来源清单、profile 和运行状态处理 | 未导入 WPF/WebView2 应用；本项目使用 Python/Tk 界面 |
| [dsh-plus-plus](https://github.com/limlnx523/dsh-plus-plus) | 插件诊断、升级回归验证的边界 | 未使用其 CLI、工作流测试引擎或凭据管理；不把通用文件读写测试说成 UI 插件正常 |
| [dsh-config-manager](https://github.com/xiajiajun516/dsh-config-manager) | 导入预览、冲突保留、回滚 | 未导入其路径迁移、跨机器同步或完整配置管理实现 |
| [Taste Skill](https://github.com/Leonxlnx/taste-skill) 的 `design-taste-frontend` | 界面层级、间距、一致性审查 | 开发时使用的设计指引，不是运行依赖；没有附带 Skill 全文或模板 |
| 用户提供的 DSH 市场截图 | 卡片布局和信息层次 | 本仓库不附带用户截图或原 UI 资源 |

前四项是文档与思路参考，未安装或实测这些参考项目。本次检查未发现把它们作为依赖或应用源码打包；这一结论不等于全网代码相似性或完整历史溯源保证。

## 验证措辞

开发期在临时 desktop profile 中进行过真实包安装，并验证声明明显不兼容的测试包在安装前被拒绝。这只证明对应版本/案例的安装链路；没有向日常 profile 安装测试插件，也不证明所有目录条目或 UI 插件正常。

源码测试、真实加载器测试、桌面启动验收分别记录；配置快照不等于包目录完整回滚。“检查可用”不意味着“所有功能都已验收”。
