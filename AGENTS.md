# AGENTS.md

OpsMate（运维提效智能体）的仓库级协作文档。**母文档为同目录《OpsMate-施工提示词.md》（下称"施工文档"）**：两者冲突时以施工文档为准；施工文档未覆盖的日常约定以本文件为准。施工必须按施工文档 §8 的 Phase 0→7 顺序推进，每个 Phase 结束跑完验收标准再进入下一个。

## 项目定位与技术栈

- Windows 单机桌面应用，中文界面，五大模块：指令速查 / 配置速查 / 脚本工坊 / 日志中心 / 日志 AI 分析。
- 形态：pywebview 原生窗口（Edge WebView2，缺失时降级默认浏览器）+ FastAPI/uvicorn **内嵌同进程**（127.0.0.1 随机空闲端口），无任何外部中间件；最终交付为 PyInstaller 打包的免安装 exe（双击即用，知识数据打进包）。
- 后端：Python ≥ 3.10（推荐 3.11/3.12）。依赖唯一允许集合（版本为下限）：`fastapi`、`uvicorn[standard]`、`pywebview`、`httpx`、`PyYAML`、`python-multipart`、`pyinstaller`。
- 前端：**零构建**——Vue 3 与 marked 均为 vendored 单文件（`app/web/vendor/`），无 package.json、无 Node。
- 数据：SQLite（标准库 `sqlite3`，WAL 模式，禁用 ORM）+ YAML 知识库（`data/kb/`）+ markdown 命令文档库（`data/commands/`）。

## Project Structure

```
OpsMate/                    # 本目录即项目根（含中文路径，注意 shell 引号）
├── main.py                 # 入口：选空闲端口→uvicorn 线程→pywebview 窗口
├── requirements.txt
├── app/
│   ├── server.py           # create_app()：FastAPI 实例、/api 路由、静态托管 app/web
│   ├── config.py           # 路径常量与 settings 读写；frozen/开发双态 data 目录逻辑
│   ├── commands/           # 指令速查：service.py(内存索引+搜索) + routes.py
│   ├── kb/                 # 配置速查：service.py(YAML 加载) + routes.py
│   ├── llm/                # provider.py(OpenAI 兼容客户端 chat/chat_stream) + routes.py
│   ├── codegen/            # prompts.py(CODEGEN_SYSTEM_PROMPT 全文) + routes.py
│   └── logs/               # store.py(SQLite) + rules.py(L1 规则引擎) + analyze.py(L2 SSE) + routes.py
├── app/web/                # index.html + app.js + style.css + vendor/(vue/marked)
├── data/                   # 运行时数据（.gitignore；打包后随 exe）
│   ├── commands/           # 621 个命令 md
│   ├── kb/                 # nginx.yaml / zabbix.yaml
│   ├── opsmate.db          # SQLite
│   └── config.json         # {provider, base_url, model, api_key}
├── tools/import_commands.py  # 数据导入（三级降级）
├── PHASE_LOG.md            # 施工进度与决策记录（每 Phase 追加一节）
└── README.md               # Phase 7 产出
```

## Coding Style

**Python**

- 公共函数签名必须带类型标注；模块级逻辑写在函数/类内，禁止裸脚本式顶层代码（`main.py` 除外）。
- 所有 `open()` 与文本读写**显式 `encoding="utf-8"`**；源码文件保存 UTF-8（无 BOM）；`main.py` 顶部需 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`。
- 路径一律 `pathlib.Path` 拼接，不拼字符串（路径含中文：`E:\Asia\开发\项目\练习工程\OpsMate`）。
- SQLite：连接串 `check_same_thread=False`，每请求新建连接用完即关；大批量导入用单事务 + `executemany` 每 5000 行一批。
- `subprocess` 调 git 等外部命令：参数列表传参（不经 shell），`encoding="utf-8"`。
- frozen（打包）/开发双态的 data 目录基准切换逻辑**只写在 `app/config.py`**（`getattr(sys, "frozen", False)` 判断，frozen 以 `sys.executable` 父目录为基准），其他模块不得自行判断。

**前端（app/web/，原生 ES module + Vue3 全局构建）**

- hash 路由：`#/commands`、`#/kb`、`#/codegen`、`#/logs`、`#/logs/:id`、`#/settings`；单 `app.js` 内组织，组件用模板字符串/`template` 选项。
- 暗色主题 CSS 变量：背景 `#1e1f24`、卡片 `#26272e`、主色 `#4f8cff`、文字 `#d5d7de`；手写 CSS，交互反馈统一右上角 toast（成功绿/失败红，3s 消失）。
- 所有 fetch 走统一封装（超时、错误 toast、JSON 解析）。
- SSE 一律 `fetch POST` + `ReadableStream` 逐 chunk 按 `data: ` 行解析（**EventSource 不支持 POST，禁用**）。
- markdown 渲染前用正则 `<!--rehype:[^>]*-->` 剥离网站样式注释；代码块只做等宽+底色+横向滚动，**不做语法高亮**。

**数据与契约**

- API 路径、JSON 字段名、SQLite 表结构、目录/文件名 = 契约（施工文档 §6、§4.4），前后端与验收脚本互相咬合，不可擅改。
- kb YAML 字段约束：`name` 唯一；`danger ∈ {false, low, medium, high}`；conf 条目必有 `section`；cli 条目必有 `example`；同一软件内 cli 与 conf 永远是两个 category、UI 分 Tab——**用户核心诉求，永不合并**。
- LLM 结构化输出解析容错顺序：剥 ``` 围栏 → 取首个 `{` 到末个 `}` 子串 → `json.loads`；失败重试请求 1 次；再失败返回 502 与原始输出摘要。

## Build Commands

```powershell
# 环境准备（一次性）
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -i https://repo.huaweicloud.com/repository/pypi/simple

# 开发运行（弹出 1280×860 窗口）
python main.py

# 命令数据导入（三级降级策略见施工文档 §4.2；结尾打印"导入 N 个命令文档"，N≥600 为成功）
python tools/import_commands.py --force

# 打包（onedir 模式；每个 Phase 完成后都应复打一次冒烟）
pyinstaller --noconsole --name OpsMate --add-data "app:app" --add-data "data/commands:data/commands" --add-data "data/kb:data/kb" main.py
# exe 启动失败/报找不到后端时，追加 --hidden-import=webview.platforms.winforms（必要时 --collect-all webview）重打
```

## Never 规则

- **Never 引入清单外依赖**：Node/npm/Vite/webpack 等前端构建链、Docker、LangChain、ORM、Redis、UI 组件库、highlight.js 一律禁止；修改依赖清单属设计变更，必须先记 PHASE_LOG.md 并征求用户同意。
- **Never 擅改契约**：API 路径、JSON 字段名、表结构、目录文件名、Phase 验收标准。
- **Never 泄露密钥**：任何 API 响应/日志/打印不得出现 `api_key` 明文，只回传 `api_key_set: true/false`。
- **Never 把解读写进脚本**：codegen 的 `script` 字段内只有代码与代码注释，解读只存在于 `explanation` 数组——验收标准包含"script 内搜索不到'解读''分析'字样"。
- **Never 整库克隆 linux-command**（仓库含截图约 4GB；只要 `command/*.md`，走 sparse clone / contents API / 手动 zip 三级降级）；Never 在缺数据时不走降级路径直接报失败——用占位数据过验收并在 PHASE_LOG 标注"待补数据"。
- **Never 写死端口**（`socket().bind(("127.0.0.1", 0))` 取空闲端口）。
- **Never 在无 `encoding` 参数时读写文本文件**；Never 用 GBK 重写文件。
- **Never 修改**：`app/web/vendor/` 下 vendored 文件、`dist/` 构建产物、`.venv/`、`data/opsmate.db`（改表走代码里的 DDL）。
- **Never 跳过当前 Phase 的验收标准进入下一 Phase**；Never 在用户未确认时连续施工（用户明确说"一口气做完"除外）。
- Never 硬编码敏感信息（LLM key、内网地址）；所有可配置项进 `data/config.json`。

## 施工协作规范

- `PHASE_LOG.md` 为强制进度账本：每 Phase 一节，含日期、做了什么、验收命令与结果、决策记录（格式 `决策：<内容>（理由：<理由>）`）。
- 每 Phase 完成后停下来向用户汇报验收结果，等确认或"继续"。
- 本机网络事实（已实测，勿重复探测）：`github.com` / `api.github.com` 可直连；`raw.githubusercontent.com` / `cdn.jsdelivr.net` 不可达；gitee 无该仓库镜像；pip 需国内镜像。
- vendored 前端库获取源按序尝试（任一成功即止）：npmmirror registry → bootcdn → unpkg → 请用户手动下载存入 `app/web/vendor/`。
- LLM 预设：智谱 `glm-4-flash`（默认，免费）/ SiliconFlow `Qwen/Qwen3-8B` / DeepSeek / 自定义，均为 OpenAI 兼容协议；base_url 入库前 `rstrip("/")`。

## Commit 规范

- 格式：`type(scope): description`
- 类型：feat / fix / docs / style / refactor / test / chore
- scope 建议取模块名：commands / kb / codegen / logs / llm / web / build / data / docs
- 示例：`feat(codegen): 逐段解读卡片渲染与 need_clarification 对话流`
