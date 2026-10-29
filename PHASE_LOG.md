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
