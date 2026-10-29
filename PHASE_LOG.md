# OpsMate 施工进度与决策记录

> 母文档：`OpsMate-施工提示词.md`。施工严格按 Phase 0 → 7 推进；当前 Phase 未通过全部验收前不得进入下一 Phase。
>
> 记录规则：每次修改代码、配置或施工文档后立即更新本文件，记录修改内容、验收结果、自主决策、理由、当前最终形态和未完成项。

## 2026-10-29 · Phase 0 · 环境与骨架（施工中）

### 接管基线

- 已读取 `AGENTS.md`、母施工文档、现有源码、隐藏目录、Git 状态和运行数据目录。
- 未发现 Trae、Claude 或 Codex 的独立记忆文件；`debug.log` 仅包含搜狗输入法/WebView 运行告警，不含施工记忆。
- Git 仓库已初始化但没有提交；现有文件全部未跟踪。
- `app/commands`、`app/kb`、`app/llm`、`app/codegen`、`app/logs` 目前均为 Phase 1–6 占位文件，不代表对应 Phase 已完成。
- `data/commands/` 与 `data/kb/` 均为空，`PHASE_LOG.md` 原先缺失，因此真实进度判定为 Phase 0 未完成。

决策：保留 Trae 已创建的后续 Phase 占位目录和文件，从 Phase 0 重新按验收标准核定进度，不删除或假定后续功能已完成。（理由：施工文档禁止跳 Phase，文件存在不等于验收通过。）

最终形态：仓库结构保留，施工进度以本文件中的验收结果为唯一依据。

### 已完成修改

- 建立 Python 3.12 虚拟环境并安装 `requirements.txt` 中唯一允许的依赖集合。
- 因 Python 3.12.0 在中文路径下创建的虚拟环境无法加载 `_ssl`，实际虚拟环境放在 `C:\Users\Dell\.virtualenvs\OpsMate`，项目内 `.venv` 为目录联接。
- 依赖下载统一改用用户指定的华为云 PyPI 镜像 `https://repo.huaweicloud.com/repository/pypi/simple`，并同步修改 `AGENTS.md` 与母施工文档。
- `main.py` 新增冻结态中文路径兼容启动：中文发布目录首次启动时，将 `OpsMate.exe` 与 `_internal/` 复制到纯英文用户级缓存并自动重启；开发态与英文发布路径不执行此逻辑。
- `app/config.py` 支持由内部启动器通过 `OPSMATE_DATA_DIR` 指回原始 exe 旁 `data/`，确保英文缓存只承载程序文件，不承载用户密钥、数据库或日志。
- PyInstaller 标准构建静默退出后，按母施工文档追加 `--hidden-import=webview.platforms.winforms`。
- `main.py` 的内嵌 uvicorn 配置关闭默认日志格式器与访问日志，兼容 `--noconsole` 下 `sys.stdout/sys.stderr is None`。

决策：使用项目内 `.venv` 目录联接到纯英文虚拟环境，而不修改项目根目录。（理由：Python 3.12.0 在当前中文路径下的 `ensurepip` 与 `_ssl` DLL 加载均失败；目录联接保留标准激活入口和既有中文项目路径。）

最终形态：用户仍使用 `.venv\Scripts\python.exe`；实际环境位于纯英文用户目录，`.venv/` 继续由 `.gitignore` 忽略。

决策：所有需要镜像的下载改用华为云镜像。（理由：用户于 2026-10-29 明确要求。）

最终形态：当前及后续 pip/资源镜像命令优先使用华为云；README 在 Phase 7 同步该口径。

决策：PyInstaller 构建追加 `--hidden-import=webview.platforms.winforms`。（理由：标准构建的 pywebview Windows 后端未被完整静态识别，且母施工文档明确规定此降级步骤。）

最终形态：Windows onedir 构建命令包含 WinForms hidden import；是否还需 `--collect-all webview` 以实际验收为准。

决策：仅在 frozen + Windows + 非 ASCII 发布路径下启用英文运行缓存。（理由：开发态和英文发布路径均能进入原生 GUI，兼容逻辑应严格限于冻结包中文路径，避免扩大影响面。）

最终形态：运行缓存优先位于 `%LOCALAPPDATA%/OpsMate/runtime/<exe哈希>/`，其次尝试 `%PUBLIC%` 与系统临时目录；候选必须为纯 ASCII 且可写。

决策：运行时副本目录按 `%LOCALAPPDATA%` → `%PUBLIC%` → 系统临时目录顺序选择，并逐项验证 ASCII 与写权限。（理由：Codex 执行环境会把 `tempfile.gettempdir()` 重定向到中文工作区，单独依赖临时目录无法覆盖当前路径；用户级 LOCALAPPDATA 更稳定且默认隔离到当前用户。）

最终形态：不修改系统级 .NET 配置，不要求管理员权限；按 OpsMate.exe SHA-256 隔离不同构建版本的缓存。

决策：Windows 用户级运行目录优先通过 `SHGetFolderPathW(CSIDL_LOCAL_APPDATA)` 获取，环境变量仅作后备；候选失败原因写入异常摘要。（理由：冻结进程内环境变量可能被清理或重定向，Windows 已知目录 API 更稳定，保留失败原因便于后续定位。）

最终形态：已知目录 API → `LOCALAPPDATA` → `PUBLIC` → 临时目录，去重后依次验证。

决策：放弃逐个复制 pythonnet/clr_loader DLL，改为复制 PyInstaller onedir 的完整程序载荷 `OpsMate.exe + _internal/` 后自动重启。（理由：双 DLL 重定向后仍无法解析 `Loader.Initialize`，证明 .NET 加载链还依赖冻结目录中的其他组件；完整载荷迁移比继续追补 DLL 稳定。）

最终形态：缓存只包含程序文件；根目录运行时 `data/` 不复制。子进程通过内部环境变量把所有可写数据固定回原始 exe 旁目录，用户仍从原发布目录双击启动。

决策：中文路径兼容采用“完整 onedir 载荷迁移 + 原目录数据回指”，不把 `data/` 复制进运行缓存。（理由：同一诊断包从真实纯 ASCII 路径可正常创建 WebView2 窗口，故兼容层只需解决程序载荷路径；数据继续放在用户选择的发布目录，避免密钥、数据库和日志出现双份。）

最终形态：中文目录中的父进程校验并启动纯 ASCII 缓存子进程；子进程的 `APP_DIR` 来自缓存 `_internal/app`，`DATA_DIR` 固定回原始发布目录的 `data/`。

决策：内嵌 uvicorn 使用 `log_config=None, access_log=False`，应用自身仅在存在 stdout 时输出必要启动/降级消息。（理由：最终 `--noconsole` 包中 uvicorn 默认 `DefaultFormatter` 会调用 `sys.stdout.isatty()`，而此时 stdout 为 `None`，导致 `Unable to configure formatter 'default'`；桌面应用也不需要控制台访问日志。）

最终形态：开发态仍可看到 OpsMate 自身的简短启动信息；无控制台发布态不初始化 uvicorn 控制台日志格式器，不弹日志配置异常。

### 验收命令与结果

- `python --version` → `Python 3.12.0`，通过。
- `.venv\Scripts\python.exe -m pip check` → `No broken requirements found.`，通过。
- `.venv\Scripts\python.exe -m compileall -q main.py app tools` → 退出码 0，通过。
- FastAPI `TestClient`：`GET /api/health` → HTTP 200，`{"ok": true, "version": "1.0.0"}`，通过。
- FastAPI `TestClient`：`GET /` → HTTP 200，`text/html; charset=utf-8`，通过。
- PyInstaller onedir 构建 → `dist/OpsMate/OpsMate.exe` 生成成功，构建步骤通过。
- 开发态 `python main.py` → 后端启动，pywebview 原生 GUI 进入事件循环；仅有 libpng profile 告警，通过开发态启动检查。
- 冻结诊断包位于中文路径 → `Failed to resolve Python.Runtime.Loader.Initialize`；复制同一诊断包到纯英文临时路径后不再出现该错误，确认问题位于 pythonnet/.NET Framework 的冻结包中文路径兼容层。
- 加入首版中文路径兼容逻辑后，`OpsMateDebug2` 明确报错“系统临时目录包含非 ASCII 字符”；根因是执行环境将临时目录重定向到中文工作区。已改为多候选纯英文用户目录，等待复验。
- `OpsMateDebug3` 仍报“未找到纯 ASCII 且可写的 pythonnet 运行时目录”，说明冻结进程内环境变量候选不可依赖；已增加 Windows 已知目录 API 与逐候选错误摘要，等待复验。
- `OpsMateDebug4` 通过 Windows API 找到 `C:\Users\Dell\AppData\Local`，但 Codex 文件沙箱拒绝冻结子进程写入；这是测试环境权限，不是普通用户态权限。
- 使用临时 `R:` 映射将运行时副本写回已授权工作区后，`Python.Runtime.dll` 已处于纯英文路径但仍无法解析 `Loader.Initialize`；由此确认 `clr_loader` 桥接 DLL 也必须迁移，已实现双 DLL 方案，等待复验。
- `OpsMateDebug5` 将 `Python.Runtime.dll` 与 `ClrLoader.dll` 同时迁移到 `R:` 英文路径后仍无法解析 `Loader.Initialize`；已停止零散 DLL 追补，改为完整冻结载荷英文缓存与自动重启方案。
- `OpsMateDebug6` 从真实纯 ASCII 目录启动 → pywebview 原生窗口成功创建；无障碍树确认窗口标题 `OpsMate`，包含“指令速查 / 配置速查 / 脚本工坊 / 日志中心 / 设置”五个导航入口。
- 原生窗口路由从 `#/settings` 切换至 `#/logs`，主内容同步变为“当前模块：日志中心”，证明 hash 路由切换生效。
- 原生窗口通过 `Alt+F4` 关闭后，对应纯英文目录诊断进程退出；中文目录中先前进入浏览器降级的独立诊断进程不计入该次退出结果并已单独清理。
- Codex 的窗口截图通道连续超时，无法保存像素级截图；已用 WebView2 无障碍树、窗口标题、路由 URL、主内容文本和进程存活/退出状态交叉验收，限制如实保留。
- Codex 沙箱禁止冻结子进程写入真实 `%LOCALAPPDATA%`/`%TEMP%`。为只验证启动链，先由构建工具在已授权的纯 ASCII 临时目录预置与 exe SHA-256 对应的完整缓存，并把 `TEMP/TMP` 指向项目可写日志目录；随后从中文发布目录启动父进程，父进程退出码 0，缓存子进程成功创建标题为 `OpsMate` 的原生窗口。该额外预置仅用于沙箱验收，普通用户环境由程序首次启动自动完成缓存写入。
- 首次最终 `--noconsole` 构建成功，但启动弹出 `Unable to configure formatter 'default'`；堆栈定位到 `uvicorn.logging.DefaultFormatter` 对空 stdout 调用 `isatty()`。关闭 uvicorn 默认日志配置与访问日志后重建，异常不再出现。
- 最终 `--noconsole` onedir 构建 → `dist/OpsMate/OpsMate.exe` 生成成功；exe SHA-256 为 `f66b9db21d2896a1359a00965ab9056e35df3539763807992e11bfbb76e918ce`。
- 最终包从中文发布目录启动 → 父进程转入纯 ASCII 缓存，原生窗口标题为 `OpsMate`；无障碍树确认五个导航入口与默认“当前模块：指令速查”。
- 最终包运行中 `GET /api/health` → HTTP 200，`{"ok": true, "version": "1.0.0"}`，通过。
- 最终包关闭窗口后等待 1 秒，未发现残留 `OpsMate` 进程，退出验收通过。
- 源码复核：`webview.create_window(..., width=1280, height=860)`；暗色主题四个约定变量均精确存在；五个 hash 路由映射完整。
- 重新执行 `compileall`、FastAPI `TestClient` 首页/健康检查和 `pip check` 均通过；TestClient 仅出现依赖自身的弃用提示，不影响当前允许依赖集合与运行结果。
- 提交前删除本轮早期 DLL 迁移试验生成的 `OpsMateRuntime/`；`dist/`、`build/`、`.spec` 与 `data/logs/` 均保持忽略，不纳入版本库。

### 当前未完成项

- 无。Phase 1 必须等待用户明确确认后再开始。

### Phase 状态

**验收通过；随 `chore(build): 完成 Phase 0 环境与骨架` 提交封账。停工汇报，未经用户确认不进入 Phase 1。**

## 2026-10-29 · Phase 1 · 指令速查（施工中）

### 步骤 1：读取契约与接管基线

- 已按用户确认进入 Phase 1，重新读取母施工文档 §4.1、§4.2、§6、§7 与 §8 Phase 1，未进入 Phase 2。
- 当前 `app/commands/service.py`、`app/commands/routes.py`、`tools/import_commands.py` 仅有占位说明；`data/commands/` 为空。
- Phase 1 固定施工顺序：命令数据导入脚本 → 全量数据导入 → 后端索引与 API → 前端列表/详情/复制 → 自动化与原生窗口验收 → 打包冒烟 → Git 提交。
- 现有未跟踪目录 `.trae-html-share-packages/` 保持不动，不纳入本 Phase。

决策：每完成上述一个实际步骤立即更新本节，不等 Phase 结束集中补记。（理由：用户明确要求“每走一步就要落盘日志”。）

最终形态（当前）：Phase 1 已开始，尚无功能代码完成；禁止提前进入 Phase 2。

### 步骤 2：实现命令数据导入工具

- 已完成 `tools/import_commands.py`：支持 `--force`、git sparse clone、GitHub Contents API、手工 ZIP 提示和 20 条内置命令兜底。
- sparse clone 固定使用 `--depth 1 --filter=blob:none --sparse`，只检出上游 `command/`，不会整库拉取约 4GB 的截图资源。
- API 路径先检查剩余限额，额度不足 600+ 文件时立即降级，不浪费逐文件请求；可选读取 `GITHUB_TOKEN`，但不会输出令牌。
- 所有候选来源先写入临时暂存目录，数量达到 600 后才替换 `data/commands/*.md`；自动来源失败时写入 20 条内置中文文档并打印手工 ZIP 指引。

决策：完整来源只有达到 600 个文档才允许覆盖目标目录。（理由：避免网络中断或 API 限流把一套可用数据替换成残缺数据。）

决策：不把 GitHub 当作“镜像”替换为其他站点；项目原始数据仍按契约直接取自 GitHub，涉及 PyPI 等镜像下载时继续只用华为云。（理由：母施工文档指定数据源和 sparse clone URL，用户要求的是镜像选择统一为华为镜像，不能擅改上游契约。）

最终形态（当前）：导入脚本代码完成，尚未执行全量导入与数量验收。

### 步骤 3：执行命令数据导入

- 首次运行 `.venv\Scripts\python.exe tools\import_commands.py --force`：沙箱内 sparse clone 返回退出码 128；GitHub API 剩余 50 次，不足 621 个逐文件请求。
- 脚本按契约自动降级并写入 20 条内置命令，输出“导入 20 个命令文档”；兜底路径验证通过，但不满足本 Phase 的全量目标。

决策：首次失败判定为执行沙箱的网络限制，立即用同一 sparse clone 命令申请网络权限重试，不把 20 条兜底数据当作最终交付。（理由：本机网络事实已确认 github.com 可直连，且 Phase 1 验收优先要求 md ≥600。）

最终形态（当前）：`data/commands/` 暂有 20 条兜底数据，等待网络权限下的全量重导覆盖。

#### 步骤 3 复验结果

- 在获准的网络环境中重新运行同一 `--force` 命令，sparse clone 成功，脚本输出“数据来源：sparse-clone”“导入 621 个命令文档”。
- 文件复核：`data/commands/*.md` 共 621 个，总计 1,782,624 字节；`ls.md`、`df.md`、`du.md` 均存在，`ls.md` UTF-8 正文可正常读取。

最终形态：`data/commands/` 已由 20 条兜底数据完整替换为上游 621 条中文命令文档；该目录继续按契约由 `.gitignore` 忽略，可通过导入脚本再生。

### 步骤 4：实现命令索引与后端 API

- `app/commands/service.py` 已实现 `CommandIndex`：启动时扫描 621 个 md，提取命令名、120 字简介和文件路径，内存中按名称排序。
- 搜索优先级固定为名称前缀、名称包含、简介包含；关键词大小写不敏感，空关键词返回字母序结果。
- 详情读取仅接受索引中存在的命令名，不直接拼接用户路径；正文通过正则剥离 `<!--rehype:...-->` 注释。
- `app/commands/routes.py` 已实现 `GET /api/commands` 与 `GET /api/commands/{name}`；limit 范围为 1–2000，缺失详情返回 404。
- `app/server.py` 已在静态文件挂载前注册 commands 路由。

决策：简介提取采用 `===` 下方第一行非空、非标题文本，而不是机械读取第三行。（理由：上游真实 `ls.md` 在 `===` 后有空行，机械第三行会得到空简介；该方式兼容契约描述与真实数据。）

决策：详情通过内存索引定位文件，不用 `{name}` 直接构造磁盘路径。（理由：同时保证 API 契约和路径穿越安全。）

最终形态（当前）：后端索引与路由代码完成，等待 API 验收后进入前端施工。

#### 步骤 4 验收结果

- `GET /api/commands?limit=5` → HTTP 200，total=621，前五项按字母序为 `7z / ab / accept / ack / ag`。
- 搜索 `磁盘` → total=16，结果包含 `df`、`du`；搜索 `disk` → total=3，结果包含 `fdisk`。
- `GET /api/commands/ls` → HTTP 200，markdown 长度 12,951 字符且不存在 `<!--rehype:`；不存在的命令返回 404；limit=2001 返回 422。
- PowerShell 控制台显示中文简介时出现代码页乱码，但 UTF-8 文件读取、Unicode 转义查询和断言均正常；遵循母文档约定未用 GBK 重写文件。

最终形态：命令索引和 API 契约验收通过，可以开始前端 `#/commands` 页面。

### 步骤 5：实现 `#/commands` 前端

- `app/web/app.js` 已将 commands 占位页替换为完整页面：搜索框、结果计数、左侧列表、右侧详情、加载态、空态与复制按钮。
- 输入搜索采用 300ms 防抖；请求 limit=2000，因此空关键词按字母序显示全部 621 条，而不是只显示默认 20 条。
- 列表请求和详情请求均使用递增 request id，较慢的旧请求不会覆盖新查询结果。
- markdown 在渲染前再次剥离 rehype 注释，再交给 vendored marked；复制优先使用 Clipboard API，失败时降级到隐藏 textarea。
- `app/web/style.css` 已加入两列浏览布局、选中态、详情排版和代码块样式；代码块仅等宽、底色、横向滚动，不做语法高亮。

决策：空关键词一次加载全部 621 条到左侧滚动列表。（理由：前端规范明确要求空关键词显示全部字母序，621 条纯文本索引在桌面应用内开销可控，且 API limit 上限为 2000。）

决策：服务端和前端各剥离一次 rehype 注释。（理由：服务端满足 API 契约，前端再做防御性处理，确保任何未来数据来源都不会把网站样式注释交给 marked。）

最终形态（当前）：Phase 1 前后端功能代码已齐，等待自动化与原生窗口交互验收。

### 步骤 6：开发态质量与原生窗口验收

- 原生 pywebview 窗口成功启动；无障碍树确认页面显示“621 条中文 Linux 命令文档”“共 621 条”、搜索输入框、621 个列表条目、详情区和“复制 md”按钮。
- 实际点击列表条目后，右侧从默认 `7z` 切换为 `alias`；概要、主要用途、选项、代码示例、引用和外部链接均由 marked 正常渲染。
- 自动化准备输入“磁盘”时检测到用户正在操作并最小化窗口；为避免抢占用户焦点，停止继续注入输入。搜索结果已由步骤 4 API 断言覆盖，复制按钮留到最终包复验。
- 全量索引质量扫描：total=621、重复名称=0、rehype 简介=0、空简介=0、超过 120 字简介=0。
- `compileall main.py app tools` 与 `pip check` 均通过。

决策：检测到真实用户输入后不强行接管窗口，保留已取得的界面证据，并把剩余复制交互移到最终打包冒烟复验。（理由：避免干扰用户当前操作，同时不降低最终验收标准。）

最终形态（当前）：开发态列表与详情渲染通过；还需复核复制按钮、执行 Phase 1 打包冒烟并确认最终 exe。

### 步骤 7：Phase 1 打包冒烟

- 已结束开发态测试进程并执行 PyInstaller `--noconsole` onedir 构建，包含 `webview.platforms.winforms` hidden import 与 app/commands/kb 数据；构建成功生成 `dist/OpsMate/OpsMate.exe`。
- 构建识别 693 个数据条目；`pycparser.lextab`、`pycparser.yacctab`、`tzdata` 仍为已知非阻断警告，上一 Phase 的实际窗口验证已证明不影响 Windows 主路径。
- 为本 Phase 的功能冒烟，在被忽略的 `dist/OpsMate/data/commands/` 中复制 621 条命令文档。

决策：本 Phase 仅在 `dist/` 构建产物中准备运行数据，不提前实现 Phase 7 的“首启动自动落地知识数据”源码。（理由：施工必须按 Phase 顺序，当前只需完成每 Phase 的打包冒烟；正式自动落地属于 Phase 7 明确任务。）

最终形态（当前）：最终 onedir 已生成并具备 621 条测试数据，等待启动、搜索、复制与退出冒烟。

#### 步骤 7 复验结果（打包冒烟）

- 沙箱限制确认：从中文路径直接启动最终包时，父进程的三个缓存候选在本执行沙箱内全部不可用——`LOCALAPPDATA`/`PUBLIC` 写入被拒（WinError 5），且沙箱在进程创建层把子进程临时目录重定向为中文工作区（显式覆盖 `TMPDIR`/`TEMP`/`TMP` 无效）→ 英文缓存准备失败、降级浏览器。普通用户双击不受此限（Phase 0 已在真实链路验证中继）。
- 沿用既有决策采用预置 ASCII 缓存对策：将 dist 的 `OpsMate.exe + _internal`（781 文件）与 `.ready`（SHA-256 `e262fcc5ff967df1…`）预置到 `Temp\OpsMate\runtime\e262…`，以 `OPSMATE_DATA_DIR` 回指 dist 数据后直接启动缓存子进程。

决策：打包冒烟在预置 ASCII 缓存子进程上执行，而不是强行让父进程在沙箱内完成中继。（理由：沙箱重定向无法绕过，父进程中继在沙箱内必然降级浏览器；中继机制本身已在 Phase 0 验收通过，本 Phase 只需复验冻结包功能。）

- 缓存子进程启动成功：无降级日志，原生窗口标题 `OpsMate`，后端监听 127.0.0.1:15252。
- API 冒烟：`/api/health` → `{"ok": true, "version": "1.0.0"}`；`/api/commands?limit=5` → total=621（7z/ab/accept/ack/ag）；`q=磁盘` → total=16（含 df、du、fdisk）；`/api/commands/ls` → markdown 18851 字符且无 rehype 残留；不存在命令 → 404。
- 浏览器复验（与原生窗口同源前端）：5 个导航齐全、"共 621 条"、搜索"磁盘"→16 条、点击 `du` 详情 markdown 正常渲染、清空后恢复 621 条。
- 复制按钮：自动化标签页无焦点导致 Clipboard API 被拒，toast 机制本身正常（红/绿分支均可触发）；真实窗口内的绿色"已复制"提示留待用户目视复验。
- `WM_CLOSE` 优雅退出：窗口关闭、复查无残留 OpsMate 进程；主进程退出码未能捕获——沙箱拦截 WebView2 子进程 teardown 期的字体/颜色配置文件读取导致其 0xC0000005 崩溃，属测试环境限制，Phase 0 已在无此限制条件下验证过干净退出。
- 冒烟后清理：删除 `Temp\OpsMate` 缓存与冒烟日志；`build/`、7 个 `*.spec`、`debug.log`、`__pycache__/` 为构建可再生残留一并删除；`.gitignore` 追加 `.trae-html-share-packages/` 与 `.screenshots/`（IDE 会重建这两个目录，入库忽略即可）。

最终形态：Phase 1 全部验收项通过；仓库工作区仅保留源码、两份协作文档、venv 联接与 dist 构建产物。

### Phase 状态

**验收通过；随 `feat(commands): 完成 Phase 1 指令速查` 提交封账。停工汇报，未经用户确认不进入 Phase 2。**
