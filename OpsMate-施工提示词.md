# OpsMate 运维提效智能体 · 施工提示词文档

> **文档性质**：本文档是一份完整的"施工提示词"。阅读者（AI 或工程师）应严格按本文档从零构建出 OpsMate 桌面应用，无需阅读者了解本文档之外的任何背景。
> **版本**：v1.0 · 预计 8 个施工阶段（Phase 0–7）
> **成品定位**：跑在 Windows 桌面的单机运维提效工具，中文界面，内置免费大模型能力。

---

## 0. 给施工 AI 的元规则（先读完本节再动手）

1. **你是本项目唯一的施工者**，角色 = 资深全栈工程师（Python 后端 + 原生前端）。按 §8 的 Phase 0→7 顺序施工；**每个 Phase 结束必须跑完该 Phase 的"验收标准"再进入下一个**。
2. **进度记录**：项目根目录维护 `PHASE_LOG.md`。每完成一个 Phase 追加一节：日期、Phase 号、做了什么、验收命令与结果、以及"决策记录"（凡本文档未写死而你自行决定的细节，逐条记入，格式：`决策：<内容>（理由：<理由>）`）。
3. **交付节奏**：每完成一个 Phase 停下来向用户汇报验收结果，等待用户确认或直接说"继续"。用户说"一口气做完"则连续施工不停顿。
4. **技术栈纪律**：
   - 只用 §2 列出的依赖，**禁止**引入 Node/npm/Vite/webpack 等任何前端构建链，**禁止** Docker、LangChain、ORM、Redis 等重型依赖。
   - 修改依赖清单属于设计变更，必须先在 PHASE_LOG.md 记录理由并征求用户同意。
5. **环境事实（已在本机实测，直接采信，不要重复探测）**：
   - 工作机 Windows，项目代码**直接建在本文档所在目录**（本文档所在目录即项目根；示例绝对路径 `E:\Asia\开发\项目\练习工程\OpsMate\`，含中文，注意 shell 引号）。
   - 本机网络：`github.com`、`api.github.com` 可直连；`raw.githubusercontent.com`、`cdn.jsdelivr.net` **不可达**；gitee 无该仓库镜像。pip 需配国内镜像。
   - **2026-10-29 施工前环境核查（实测补充）**：Python 3.12.0、git 2.52.0、Edge WebView2 运行时已安装（156.0.4314.50，pywebview 主路径可用，无需降级浏览器）；裸 `pip` 不在 PATH——**一律使用 `python -m pip`**；`registry.npmmirror.com` 可达，vendored 库第 1 优先源实测成功（vue.global.prod.js 146843 字节、marked.min.js 35479 字节）。
6. **编码纪律（Windows）**：所有读写文本文件必须显式 `encoding="utf-8"`；所有源码文件保存为 UTF-8（无 BOM）；PowerShell 输出中文乱码不影响功能时忽略，不要用 GBK 重写文件。
7. **本文档即契约**：API 路径、JSON 字段名、目录结构、文件名与 §8 验收标准不可擅自改动（前后端、验收脚本互相咬合）。确有必要时：先记 PHASE_LOG.md 决策记录，再改，且同步更新本文档对应处。
8. **遇到外部资源不可用**：按文档内给定的降级路径走（每处已写明）；全部降级失败时用内置最小占位数据让功能先过验收，并在 PHASE_LOG.md 标注"待补数据"。
9. **仓库环境管理（项目将发布到 GitHub）**：项目根以 git 管理（`git init` 于 Phase 0）；根目录维护 `.gitignore`，必须忽略：`.venv/`、`__pycache__/`、`build/`、`dist/`、`*.spec`、`.git/`（git 自管）、`data/opsmate.db*`、`data/config.json`（含 API key，**严禁入库**）、`data/logs/`、`data/commands/`（外部仓库导入产物，约 10MB，可由 `tools/import_commands.py` 随时再生，不入库）；`data/kb/*.yaml` 为本项目手写源数据资产，**必须入库**。commit 规范见 AGENTS.md；每个 Phase 验收通过后提交一次（格式如 `feat(模块): 描述`）。

---

## 1. 项目背景与目标

用户是一名运维工程师（Windows 工作机，中文环境，有 Java/Linux 背景）。日常痛点：查 Linux 命令用法要开网页翻文档；nginx/zabbix 的命令与配置参数记不牢、查起来散；手写 shell 脚本费时且怕写错；排障时日志又长又乱，肉眼 grep 效率低。OpsMate 把这五件事装进一个本地桌面应用：

| # | 模块 | 一句话验收 |
|---|------|-----------|
| 1 | **指令速查** | 本地离线检索 600+ 条中文 Linux 命令文档（数据源 = github.com/jaywcjlove/linux-command） |
| 2 | **配置速查** | nginx / zabbix 的"启停命令"与"配置参数"严格分 Tab 展示，支持搜索 |
| 3 | **脚本工坊** | 自然语言 → 带完整中文注释的 bash 脚本 + 右侧逐段解读（解读绝不混入脚本本体） |
| 4 | **日志中心** | 上传/粘贴日志 → level 着色、关键词/正则/level 过滤、统计、导出（对标 mclo.gs 的核心体验，本地化） |
| 5 | **日志 AI 分析** | 规则引擎免费提炼"问题日志"并聚类；再可选调用大模型生成根因分析报告 |

**最终交付形态（硬性要求）**：免安装的 `OpsMate.exe`——双击即弹出应用窗口使用全部功能。目标机器**无需安装 Python、无需启动或连接任何外部中间件、无需手动打开浏览器**：uvicorn/FastAPI 以库的形式嵌在同一进程内，监听随机分配的 127.0.0.1 端口（进程内通信，用户无感知）；SQLite 为单文件库；知识数据随 exe 一起打包。除调用 LLM 的在线 API 外全部离线可用。

**明确非目标**：多用户/鉴权、云部署、日志分享短链（桌面版无场景，用"导出"替代）、macOS/Linux 打包。

---

## 2. 总体架构与技术栈

### 2.1 架构图（文字版）

```
┌─ pywebview 原生窗口（失败则降级为默认浏览器打开）
│    └─ 加载 http://127.0.0.1:<port>/ —— Vue3 前端（无构建，静态文件）
│         ┌─ 指令速查 / 配置速查：纯本地检索，0 token
│         ├─ 脚本工坊：POST → FastAPI → 智谱/自配 LLM（非流式，结构化 JSON）
│         └─ 日志分析：上传→SQLite；筛选=本地；AI 报告=SSE 流式
└─ FastAPI + uvicorn（单进程，127.0.0.1，随机空闲端口）
      ├─ app/commands —— command/*.md 内存索引 + 搜索
      ├─ app/kb       —— knowledge YAML 加载
      ├─ app/codegen  —— LLM 脚本生成
      ├─ app/logs     —— SQLite 存取 + L1 规则引擎 + L2 LLM 分析
      └─ app/llm      —— 统一 OpenAI 兼容客户端（httpx）
数据：data/ 目录（opsmate.db + config.json + commands/ + kb/*.yaml），全部可读可备份
```

### 2.2 技术栈与依赖（唯一允许清单）

- Python ≥ 3.10（推荐 3.11/3.12；`python --version` 检查，缺失时 `winget install -e --id Python.Python.3.12`）
- `requirements.txt`（版本为下限，安装时取最新兼容版）：

```text
fastapi>=0.110
uvicorn[standard]>=0.29
pywebview>=5.1
httpx>=0.27
PyYAML>=6.0
python-multipart>=0.0.9
```

- Phase 0 起追加：`pyinstaller>=6.0`（用于打包冒烟与 Phase 7 正式打包）
- 前端**零构建**：Vue 3 与 marked 均为 vendored 单文件（`app/web/vendor/`），来源与降级见 §4.5。
- 数据库：SQLite（标准库 `sqlite3`，WAL 模式）。日志行数据量大，禁用 ORM。

### 2.3 前端形态

- 单页应用：`app/web/index.html` + `app.js` + `style.css`，hash 路由（`#/commands` 等）。
- 暗色主题为默认（运维工具惯例），CSS 手写，禁止引入 UI 组件库。
- markdown 渲染用 vendored `marked.min.js`；代码块只做等宽+底色+横向滚动，**不做语法高亮**（砍掉 highlight.js 依赖）。

---

## 3. 目录结构（文件级，必须严格一致）

```
OpsMate/                    # 本文档所在目录即项目根
├── main.py                  # 入口：选空闲端口→起 uvicorn 线程→开 pywebview 窗口
├── requirements.txt
├── app/
│   ├── __init__.py          # 空
│   ├── server.py            # create_app()：FastAPI 实例、挂载 /api 路由、静态托管 app/web
│   ├── config.py            # 路径常量(APP_DIR/DATA_DIR/DB_PATH/COMMANDS_DIR/KB_DIR/CONFIG_JSON)、settings 读写
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── service.py       # CommandIndex：扫描 data/commands/*.md → 内存索引；search(name_or_kw)
│   │   └── routes.py        # /api/commands*
│   ├── kb/
│   │   ├── __init__.py
│   │   ├── service.py       # load_kb()：读 data/kb/*.yaml；search 跨软件搜索
│   │   └── routes.py        # /api/kb*
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── provider.py      # LLMClient：OpenAI 兼容 chat/completions；chat() 非流式、chat_stream() SSE
│   │   └── routes.py        # /api/settings、/api/llm/test
│   ├── codegen/
│   │   ├── __init__.py
│   │   ├── prompts.py       # CODEGEN_SYSTEM_PROMPT 常量（§9.1 全文）
│   │   └── routes.py        # /api/codegen/*
│   └── logs/
│       ├── __init__.py
│       ├── store.py         # SQLite：建表、导入日志、分页查询、统计、报告存取
│       ├── rules.py         # L1 规则引擎：classify_level / merge_multiline / cluster
│       ├── analyze.py       # L2：组装分析材料→调 LLM→SSE→落库
│       └── routes.py        # /api/logs*
├── app/web/
│   ├── index.html
│   ├── app.js               # Vue 应用：路由、5 个页面视图、SSE 消费
│   ├── style.css
│   └── vendor/
│       ├── vue.global.prod.js
│       └── marked.min.js
├── data/                    # 运行时数据（.gitignore；打包后跟随 exe）
│   ├── commands/            # 621 个命令 md（由 tools/import_commands.py 落地）
│   ├── kb/
│   │   ├── nginx.yaml
│   │   └── zabbix.yaml
│   ├── opsmate.db           # SQLite
│   ├── config.json          # {provider, base_url, model, api_key}
│   └── logs/                # 上传日志的原始副本 {id}.txt（DELETE 时连带删除；不打包、不入库）
├── tools/
│   └── import_commands.py   # 数据导入（三级降级，见 §4.2）
├── PHASE_LOG.md
└── README.md                # Phase 7 产出
```

`main.py` 关键行为：`socket` 绑定 `127.0.0.1:0` 取空闲端口 → 线程里 `uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")` → `webview.create_window("OpsMate", url, width=1280, height=860)` → `webview.start()`；`webview.start` 抛异常（无 WebView2）则 `webbrowser.open(url)` 并保持进程。注意：**打包(frozen)后** data 目录以 `sys.executable` 的父目录为基准（`getattr(sys, "frozen", False)` 判断），开发态以项目根为基准——此逻辑放 `app/config.py`。两个补充硬性点：① `webview.start()` 返回（用户关窗）后必须显式结束进程（uvicorn 线程不会随窗口自动终止，进程会挂死）；② `--noconsole` 打包态 `sys.stdout` 为 `None`，所有 `print` 与 `sys.stdout.reconfigure` 前必须判空，否则 exe 内直接崩溃。

---

## 4. 数据层规范

### 4.1 指令速查数据（来源与格式）

- 来源：`github.com/jaywcjlove/linux-command`（MIT 协议），默认分支 `master`，正文数据全部在 `command/` 目录，共 **621 个** `*.md` 中文文档（总量约 10MB；**仓库含截图约 4GB，严禁整库克隆**）。
- md 格式（已实测样例 `ls.md`）：首行=命令名，次行=`===`，第三行=一句话中文简介；正文小节有 `##`/`###`（如 `### 语法`、`### 选项`、`### 实例`、`## 扩展阅读`），各命令小节不完全一致——**解析时不要按固定小节名硬解析**；文中偶有 `<!--rehype:style=...-->` HTML 注释（网站样式标记），前端渲染前用正则 `<!--rehype:[^>]*-->` 清除。
- 索引字段（内存即可，不必入库）：`name`（文件名去 .md）、`title`（第三行简介，截断 120 字符）、`path`。搜索逻辑：优先 `name` 前缀/包含命中，其次 `title` 包含；支持中英文关键词（如 "磁盘" 命中 `df`/`du` 需依赖 title 中文描述，标题不含"磁盘"时允许用 `name` 的字母匹配兜底，不做分词）。

### 4.2 数据获取（tools/import_commands.py，三级降级）

1. **首选**：`git clone --depth 1 --filter=blob:none --sparse https://github.com/jaywcjlove/linux-command.git <临时目录>` → `git -C <临时目录> sparse-checkout set command` → 把 `command/*.md` 拷入 `data/commands/`。（执行前检查 `git --version`，无 git 直接跳 2）
2. **备选**：GitHub contents API（本机实测可达）：`GET https://api.github.com/repos/jaywcjlove/linux-command/contents/command` 拿文件清单（每条含 name/size/download_url），再逐个 `download_url` 下载。注意：① `download_url` 域名是 raw.githubusercontent（本机不可达）时改用 `GET https://api.github.com/repos/jaywcjlove/linux-command/contents/command/<name>` 取回 base64 的 JSON（`{"content": "...", "encoding": "base64"}`）解码保存；② API 未认证限流 60 次/小时不够 621 个文件——**逐文件 contents API 仅用于小批量验证，大批量走 1 或 3**。
3. **兜底**：让用户浏览器打开 `https://github.com/jaywcjlove/linux-command/archive/refs/heads/master.zip` 手动下载（浏览器有登录态/代理时通常可达），解压后把 `linux-command-master/command/` 整目录拷到 `data/commands/`。
4. **全失败**：内置 20 个常用命令（ls, cd, cp, mv, rm, mkdir, cat, grep, sed, awk, find, ps, top, df, du, tar, systemctl, journalctl, chmod, chown）的最小 md（按 §4.1 格式自写），验收先过，PHASE_LOG.md 标注"数据待补"。

导入脚本参数：`python tools/import_commands.py --force`（重导覆盖）。脚本结尾打印统计：`导入 N 个命令文档`。数量 ≥ 600 视为成功（621 减个别文件名异常）。

### 4.3 配置知识库（data/kb/*.yaml）

**schema（每个软件一个文件）**：

```yaml
software: nginx              # 小写 id，同时是文件名
label: Nginx
version_ref: "官方文档 1.24/1.26 稳定版（参考）"
generated: "AI 整理"          # UI 显示"AI 整理，使用前请核对官方文档"
sources:
  - https://nginx.org/en/docs/
  - https://wiki.nix.beer/Nginx-zh (如无中文权威源可省)
categories:
  - id: cli                   # 固定两类：cli=启停命令；conf=配置参数
    label: 启停与运行命令
    entries:
      - name: nginx -t
        syntax: nginx -t [-c file] [-q]
        desc: 测试配置文件语法是否正确，不启动服务。改完配置后必须先执行
        example: nginx -t -c /etc/nginx/nginx.conf
        notes: 返回码 0=通过；输出 test is successful
        danger: false
        tags: [验证]
      - name: nginx -s reload
        syntax: nginx -s reload
        desc: 平滑重载配置（不断连接，master 重读配置、新 worker 替换旧 worker）
        example: nginx -s reload
        notes: 执行前先 nginx -t；与 systemctl reload nginx 等价
        danger: medium        # low|medium|high；medium 以上 UI 显示红色提示
        tags: [热加载]
  - id: conf
    label: 配置参数（nginx.conf 及 include 文件）
    entries:
      - name: worker_processes
        section: main         # 参数所属层级：main/events/http/server/location
        syntax: worker_processes number | auto;
        default: auto
        context: "main"
        desc: worker 进程数；auto=按 CPU 核数
        example: "worker_processes auto;"
        notes: 建议保持 auto；CPU 密集型业务才需要手调
        danger: false
        tags: [进程模型]
      # ……（其余条目见 §11 收录清单）
```

条目字段约束：`name` 唯一；`danger ∈ {false, low, medium, high}`；conf 条目必须有 `section`；`example` 必填（cli 类）；`notes` 可选。**同一软件内 cli 与 conf 是两个 category，UI 永远分 Tab 展示——这是用户明确的核心诉求。** zabbix 的 `section` 取值口径：zabbix-server.conf 分组内的 conf 条目统一为 `server`；zabbix_agent2.conf 分组内的统一为 `agent`。

首批收录范围（数据由你按官方文档知识生成，条目清单见 §11）：nginx（cli ≥ 12 条、conf ≥ 55 条）、zabbix（cli ≥ 10 条、conf 拆两文件：`zabbix.yaml` 内 server 与 agent2 各为 category，conf 合计 ≥ 55 条）。

### 4.4 SQLite DDL（app/logs/store.py 启动时建表）

```sql
CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  filename TEXT,
  size_bytes INTEGER NOT NULL,
  line_count INTEGER NOT NULL,
  format_guess TEXT,          -- nginx_access/nginx_error/syslog/java_app/known_service/unknown
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS log_lines (
  log_id INTEGER NOT NULL,
  line_no INTEGER NOT NULL,
  level TEXT NOT NULL DEFAULT '',   -- ERROR/WARN/INFO/DEBUG/'' (空=未识别)
  text TEXT NOT NULL,
  PRIMARY KEY (log_id, line_no)
);
CREATE INDEX IF NOT EXISTS idx_lines_level ON log_lines(log_id, level);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  log_id INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'llm',
  model TEXT, content TEXT NOT NULL,   -- markdown 全文
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS codegen_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  requirement TEXT NOT NULL,
  params TEXT,               -- JSON: {distro, notes}
  script TEXT NOT NULL,
  explanation TEXT,          -- JSON 数组序列化
  warnings TEXT, usage TEXT, model TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
```

约束：单文件 ≤ 50MB（超出拒绝并提示"请先 split/grep 裁剪"）；导入用单事务 + 每 5000 行 `executemany`；`PRAGMA journal_mode=WAL`。格式猜测规则（导入时逐行采样前 200 行）：nginx 访问日志（`^\S+ \S+ \S+ \[.*\] "\w+ .*" \d{3} `）→ nginx_access；含 ` \[error\] | \[warn\] ` → nginx_error；`^\w{3} +\d+ \d{2}:\d{2}:\d{2} \S+ ` → syslog；含 ` \[main\]|java\.|Exception|ERROR` → java_app；`zabbix_server|zabbix_agent` 字样 → known_service；否则 unknown。

### 4.5 设置存储与 vendored 前端库

- `data/config.json`：`{"provider": "zhipu", "base_url": "...", "model": "...", "api_key": "..."}`。**任何 API 不得回传 api_key 明文**（回传 `api_key_set: true/false`）。目录权限即可（单用户桌面工具）。
- `app/web/vendor/vue.global.prod.js`（Vue 3.4.x）与 `marked.min.js`（12.x）获取来源（按序尝试，任一成功即止）：
  1. `https://registry.npmmirror.com/vue/3.4.38/files/dist/vue.global.prod.js`；`https://registry.npmmirror.com/marked/12.0.2/files/marked.min.js`
  2. `https://cdn.bootcdn.net/ajax/libs/vue/3.4.38/vue.global.prod.js`；`https://cdn.bootcdn.net/ajax/libs/marked/12.0.2/marked.min.js`
  3. `https://unpkg.com/vue@3.4.38/dist/vue.global.prod.js`；`https://unpkg.com/marked@12.0.2/marked.min.js`
  4. 全失败：PHASE_LOG.md 记录，请用户手动下载这两个 URL 存入 vendor/（文件大小量级：vue ≈ 130KB+，marked ≈ 40KB+）。

---

## 5. LLM Provider 层规范（app/llm/provider.py）

- 协议：OpenAI 兼容 `POST {base_url}/chat/completions`，headers `Authorization: Bearer <key>`，body `{"model", "messages", "temperature", "stream"}`。base_url **不带尾斜杠**（入库前 `rstrip("/")`）。
- **内置预设**（settings 页下拉可选，选完自动填 base_url 与推荐 model）：

| 预设 id | 显示名 | base_url | 推荐 model | 说明 |
|---|---|---|---|---|
| `zhipu` | 智谱 BigModel（默认） | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash`（备选 `glm-4.5-flash`） | 官方免费档，注册 open.bigmodel.cn 领 key |
| `siliconflow` | 硅基流动 | `https://api.siliconflow.cn/v1` | `Qwen/Qwen3-8B`（`:free` 档） | 有多个免费小模型 |
| `deepseek` | DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` | 无免费档，按量低价 |
| `custom` | 自定义（任意 OpenAI 兼容） | 空 | 空 | 用户自填 |

- `chat(messages, temperature, timeout=120)` → 非流式，返回 `{"content": str, "model": str}`；用于脚本生成。
- `chat_stream(messages, temperature, timeout=300)` → 生成器，逐段 yield 文本 delta；用于日志分析。
- 错误处理：连接失败/超时 → 返回结构化错误 `{ok: false, error: "..."}`（HTTP 状态码 + 响应体前 500 字符），前端 toast 显示"检查网络/密钥/模型名"。429 重试 1 次（退避 2s），其余不重试。
- `/api/llm/test`：发送单条 user 消息 `"回复 pong"`（max_tokens=8）测连通，返回 `{ok, latency_ms, model, error?}`。

---

## 6. 后端 API 契约（全部挂 /api 前缀，JSON 均为 UTF-8）

| 方法 | 路径 | 入参 | 出参（关键形状） |
|---|---|---|---|
| GET | `/api/health` | - | `{"ok": true, "version": "1.0.0"}` |
| GET | `/api/commands` | `q`(可空), `limit=20` | `{"items": [{"name","title"}], "total": N}`；q 空时返回字母序前 limit 个 |
| GET | `/api/commands/{name}` | - | `{"name", "title", "markdown"}`（md 已剥离 rehype 注释） |
| GET | `/api/kb` | - | `{"items": [{"software","label","cli_count","conf_count"}]}` |
| GET | `/api/kb/{software}` | - | 完整 YAML 解析结果（含 categories/entries 原样） |
| GET | `/api/kb/search` | `q`, `software`(可空) | `{"items": [{"software","category","name","desc","danger"}]}` |
| GET | `/api/settings` | - | `{"provider","base_url","model","api_key_set"}` |
| PUT | `/api/settings` | body 同上 + `api_key`(可空，空=不改) | `{"ok": true}` |
| POST | `/api/llm/test` | - | `{"ok","latency_ms","model","error"?}` |
| POST | `/api/codegen/generate` | `{"requirement", "distro"?, "notes"?}` | 二选一：`{"need_clarification":true,"questions":[...]}` 或 `{"need_clarification":false,"script","explanation":[{lines,title,detail}],"warnings":[],"usage"}`；同时写 codegen_history |
| GET | `/api/codegen/history` | `limit=50` | `{"items":[{id,requirement,created_at,model}]}` |
| GET | `/api/codegen/history/{id}` | - | 完整记录 |
| POST | `/api/logs` | multipart `file` **或** json `{"title","content"}` | `{"id","title","line_count","size_bytes","format_guess","level_stats":{"ERROR":n,...}}` |
| GET | `/api/logs` | - | `{"items":[{id,title,filename,size_bytes,line_count,format_guess,created_at,level_stats}]}`（倒序） |
| GET | `/api/logs/{id}` | - | 元数据（同上单条） |
| DELETE | `/api/logs/{id}` | - | `{"ok":true}`（连带删行、报告、`data/logs/{id}.txt`） |
| GET | `/api/logs/{id}/lines` | `level,q,regex,offset,limit=500,order=asc\|desc` | `{"total","lines":[{line_no,level,text}]}`；regex 与 q 并用取交集 |
| GET | `/api/logs/{id}/stats` | - | `{"level_counts":{...},"format_guess":...,"time_range":[first_ts,last_ts]?,"top_clusters":[{pattern,count,first_no,last_no,sample}]}`（top_clusters 见 §8 Phase 6 L1） |
| GET | `/api/logs/{id}/export` | `level,q,regex` | `text/plain` 附件下载（过滤后全文，带原始行号前缀） |
| POST | `/api/logs/{id}/llm-analyze` | `{"focus"?}` | **SSE 流**：`data: {"delta":"..."}` 逐段；结束发 `data: {"done":true,"report_id":N}`；错误发 `data: {"error":"..."}`；完成后报告落 reports 表 |
| GET | `/api/logs/{id}/reports` | - | `{"items":[{id,model,created_at}]}` |
| GET | `/api/logs/{id}/reports/{rid}` | - | `{"content":"markdown"}` |

规则：分页 limit 上限 2000；`q` 大小写不敏感子串；`regex` 无效时返回 400 `{"detail":"正则表达式无效"}`；SSE 的响应头 `Content-Type: text/event-stream`（用 fetch+ReadableStream 消费，**不是 EventSource**，因为需要 POST）。路由注册顺序硬性要求：`/api/kb/search` 必须先于 `/api/kb/{software}` 注册——FastAPI 按注册顺序匹配，否则 `search` 会被当作 `{software}` 参数吞掉。

---

## 7. 前端规范（app/web/）

**布局**：左侧固定 200px 边栏（Logo "OpsMate" + 5 个导航：指令速查/配置速查/脚本工坊/日志中心/设置），右侧内容区。暗色主题（背景 #1e1f24，卡片 #26272e，主色 #4f8cff，文字 #d5d7de）。所有交互反馈走右上角 toast（成功绿/失败红，3s 消失）。

**hash 路由与视图**：

- `#/commands`：顶部搜索框（防抖 300ms）→ 左列结果列表（name 加粗 + title 灰字）→ 点击右栏 marked 渲染 md；右上"复制 md"按钮；空关键词显示全部字母序。
- `#/kb`：软件卡片（nginx/zabbix）→ 进入后 **Tab：`启停与运行命令` | `配置参数`**（用户核心诉求，永不合并）；列表项显示 name/syntax/desc/danger 标记（medium+ 红字 ⚠）；点击展开详情（example/notes）；顶部跨软件搜索框。
- `#/codegen`：表单（需求 textarea 必填、发行版下拉 [不指定/CentOS/Ubuntu/Debian/其他]、补充说明 textarea）→ 生成按钮（loading 态，可 60–120s，按钮显示"生成中…"并禁用）→ 结果区左右布局：左=脚本（`<pre>` 等宽显示 + 复制 + 下载 .sh 按钮），右=逐段解读卡片（lines 徽标 + title + detail）+ warnings 红块 + usage 灰块；底部历史记录列表（点击回看）。若返回 `need_clarification`：把 questions 以对话形式展示，用户回答后自动拼进 requirement 重新生成。
- `#/logs`：上部"新建"区（拖拽/点击上传 + 或粘贴文本框，粘贴时 title 必填）→ 下部日志列表（title/行数/大小/格式/level 统计小徽章/时间），行内"分析"和"删除"按钮。
- `#/logs/:id`：顶部元信息条（标题、行数、格式、level 徽章）；工具栏（level 多选过滤、关键词、正则开关、排序、导出按钮、**AI 分析**按钮、历史报告下拉）；主体行列表（行号灰、level 着色：ERROR 红/WARN 橙/INFO 蓝/DEBUG 灰/未知默认色，长行截断+hover 展开）；分页"加载更多"（每次 +500）；点击 AI 分析 → 右侧抽屉流式渲染 markdown 报告，完成后提示"已存历史"。
- `#/settings`：预设下拉（§5 表）→ base_url/model/api_key（password 型输入，已保存显示 `••••已保存`，留空=不修改）→ 保存 + "测试连通"按钮（显示延迟 ms 或错误）→ 底部灰字说明：key 仅存本机 `data/config.json`；免费推荐：智谱 GLM-4-Flash（open.bigmodel.cn 注册领取）。

**通用**：所有 fetch 统一封装（超时、错误 toast、JSON 解析）；SSE 消费用 `fetch POST` + `ReadableStream` 逐 chunk 按 `data: ` 行切分解析 JSON。

---

## 8. 施工计划（Phase 0–7）

### Phase 0 · 环境与骨架
**做**：检查 Python ≥3.10；`git init` 与根目录 `.gitignore`（规范见 §0 第 9 条）；`python -m venv .venv`；`python -m pip` 配华为云镜像装 requirements；建目录树（§3 全部空文件）；`main.py`+`server.py`+`config.py` 跑通（health 接口 + 静态托管 + 窗口）；`index.html` 空壳（边栏 5 导航 + "OpsMate 已就绪"）；下载 vendor 两文件（§4.5）；建 `PHASE_LOG.md`；下载 `data/kb` 与 `data/commands` 留到 Phase 1/2。
**打包冒烟（风险前置）**：骨架跑通后立即安装 pyinstaller 并按 §8 Phase 7 的命令试打包一次，确认 dist 下 exe 能双击弹窗——尽早暴露 pywebview/WebView2 打包链路问题；此后每个 Phase 完成后都复打一次冒烟。
**验收**：`python main.py` 弹出 1280×860 窗口，左侧 5 个导航可切换空页面；浏览器访问窗口同源地址 `/api/health` 返回 `{"ok":true}`（窗口内 F12 或外部 curl 均可验证）；试打包出的 exe 双击能弹出与开发态一致的窗口。

### Phase 1 · 指令速查
**做**：`tools/import_commands.py`（§4.2 三级降级）；`commands/service.py` 索引与搜索；`commands/routes.py`；前端 `#/commands` 页（列表+详情+复制）。
**验收**：`data/commands/` 下 md ≥ 600 个（兜底模式除外，需在 PHASE_LOG 标注）；搜索 `磁盘` 能看到 df/du 类结果（兜底数据则验证 `ls`）；搜索 `disk` 命中字母名；点击详情正常渲染（rehype 注释不可见）；复制按钮产出 md 原文。

### Phase 2 · 配置速查
**做**：编写 `data/kb/nginx.yaml`、`data/kb/zabbix.yaml`（§4.3 schema + §11 清单，zabbix 一个文件两个 conf category：zabbix-server.conf / zabbix_agent2.conf）；`kb/service.py`+`routes.py`；前端 `#/kb`（软件卡片→Tab 切换→搜索→详情展开）。
**验收**：`/api/kb` 返回 2 个软件且 cli/conf 计数 >0；UI 中 nginx 的"启停命令"Tab **看不到任何配置参数**（worker_processes 等），"配置参数"Tab 看不到 nginx -t 等 cli；搜索 `worker` 命中 worker_processes；danger=medium 的条目有红字标记；zabbix server 与 agent2 的配置在不同分组。

### Phase 3 · LLM 接入与设置
**做**：`llm/provider.py`（chat/chat_stream/错误结构化）；`llm/routes.py`（settings 读写、test）；前端 `#/settings`（预设联动、密钥留空不改、测试按钮显示延迟）。**需要用户提供真实 key**——向用户说明注册 open.bigmodel.cn 领取免费 key（此步可先以假 key 完成错误路径验收，真 key 到位后复验）。
**验收**：保存设置后重启应用，设置仍读取正确（`api_key` 永不出现在任何 GET 响应，抓包/日志验证）；假 key 点"测试连通"→ 明确错误 toast（401/403 字样）；真 key → 显示延迟 ms。无网环境点测试 60s 内返回错误（不挂死）。

### Phase 4 · 脚本工坊
**做**：`codegen/prompts.py`（§9.1 全文照抄）；`codegen/routes.py`（调 LLM→解析 JSON→容错→入库）；前端 `#/codegen`（表单/左右结果布局/解读卡片/warnings/usage/历史）。**JSON 解析容错**：LLM 输出可能被 ```json 包裹或前后有杂文字——先剥 ``` 围栏，再取首个 `{` 到末个 `}` 子串 `json.loads`；仍失败则重试请求 1 次；再失败返回 502 与原始输出摘要。
**验收**：输入"每天凌晨 2 点打包 /var/log/nginx 目录为 tgz，保留最近 7 天"→ 得到带 `#!/usr/bin/env bash` 与 `set -euo pipefail` 的脚本，含中文注释；**script 字段内搜索不到"解读""分析"字样**（解读只在 explanation）；右侧至少 3 张解读卡片；warnings 提及 cron/root/路径等注意事项；生成记录出现在历史列表可回看。再输入一个故意含糊需求（如"清理一下日志"）→ 追问 questions 而非瞎编脚本。

### Phase 5 · 日志中心·基础层
**做**：`logs/store.py`（建表/导入/分页/统计/导出/删除）；`logs/rules.py` 的 `classify_level`（导入时预计算 level 入库）；前端 `#/logs` 与 `#/logs/:id` 的全部非 AI 功能（上传、拖拽、粘贴、过滤、着色、分页、导出）。文件方式导入另存一份原始文件 `data/logs/{id}.txt` 供导出兜底。
**验收**：上传一份含 ERROR/WARN/Java 堆栈的样例日志（自造 200 行）→ 行数/大小/格式猜测正确；level 过滤"仅 ERROR"后 total 与实际 ERROR 行数一致；正则 `Exception` 过滤正常；关键词+level 组合过滤取交集；导出文件每行带原行号；删除后列表消失且 DB 行数下降；50MB 限制生效（造一个超限文件被拒并提示）。

### Phase 6 · 日志 AI 分析
**做**：`logs/rules.py` 补全 L1（多行堆栈合并、变量归一化聚类——规格见下）；`/api/logs/{id}/stats` 输出 top_clusters；`logs/analyze.py`（L2 材料组装→SSE→落库）；前端 AI 分析按钮+右侧抽屉流式渲染+历史报告。
- **多行堆栈归属**：行首为空白、或以 `at `、`Caused by:`、`...\s*\d+ more` 开头的行，聚类时归入其上方最近的非堆栈行（查看器仍显示原始行，不受影响）。
- **归一化聚类**：每行依次替换——IPv4→`<ip>`；连续数字（含小数）→`<num>`；连续十六进制 ≥6 位→`<hex>`；UUID→`<id>`；`'...'`/`"..."` 内容→`<str>`；`/[\w./-]+` 路径（含 ≥1 个 `/`）→`<path>`；然后压缩连续空白。归一化串 sha1 为组键；组输出 `{pattern(截断80), count, first_no, last_no, sample(首条原始行截断300)}`；只保留 count≥1 的 ERROR 组与 count≥2 的 WARN 组，按 count 降序取前 20。
- **L2 材料组装**（喂给 LLM 的唯一输入，总长截断 ~6000 字符）：日志元信息 + level 统计 + 时间范围 + top_clusters 全量 +（可选）用户 focus。**不喂原始日志全文**——省 token 且防超窗。
**验收**：对 Phase 5 样例日志点"AI 分析"→ 右侧抽屉流式出报告（逐字出现）；报告含"结论速览/问题清单/下一步排查"结构；问题条目引用了行号或"聚类×次数"证据；报告出现在历史报告下拉并可重新打开；无 key 时点击给出明确引导去设置页；断网时 SSE 报错且界面不卡死。

### Phase 7 · 打磨与打包
**做**：全局 UI 走查（空态/loading/错误态文案中文）；`pyinstaller --noconsole --name OpsMate --add-data "app;app" --add-data "data/commands;data/commands" --add-data "data/kb;data/kb" main.py`（Windows 下 `--add-data` 分隔符为分号 `;`，以附录 A 第 6 条为准——本文档及 AGENTS.md 早期写法中的冒号一律以分号为准）（**全量知识数据必须打进包**：`data/commands/` 与 `data/kb/` 随 exe 发布，保证双击即有全量数据，不要求用户跑任何导入脚本；`data/config.json`（含用户 API key）与 `opsmate.db` **不打包**，由 `app/config.py` 在 frozen 态首启动时于 exe 旁 `data/` 自动创建，并把包内 commands/kb 拷贝落地一次，运行期始终读写 exe 旁副本）；README.md（功能简介、首次配置模型 key 指引、数据目录说明、常见问题：WebView2 缺失/端口占用/编码）；图标（可选，无素材则跳过并记录）。
**验收**：`dist/OpsMate/OpsMate.exe` 双击启动，功能抽测（搜索一个命令、看一个配置 Tab、生成一个脚本需真 key、上传一份日志并过滤）；exe 旁生成 data/ 且重启数据仍在；首次启动自动落地全量知识数据（commands ≥600、kb 齐全），无需任何手动导入；README 存在且含模型配置章节；PHASE_LOG.md 覆盖全部 Phase。

---

## 9. LLM 提示词全文（一字不改写进 prompts.py）

### 9.1 脚本工坊 CODEGEN_SYSTEM_PROMPT

```text
你是资深 Linux 运维工程师与 bash 脚本专家，帮助运维人员把自然语言需求转换为安全、可靠、可直接使用的 shell 脚本。

【输出格式——最高优先级】
只输出一个 JSON 对象，禁止输出 JSON 之外的任何文字（包括 markdown 代码围栏、解释、寒暄）。结构如下：
{
  "need_clarification": false,
  "questions": [],
  "script": "完整脚本内容",
  "explanation": [{"lines": "1-6", "title": "段落标题", "detail": "…"}],
  "warnings": ["…"],
  "usage": "…"
}

【何时追问】
需求缺少关键信息（目标路径、服务名、阈值、时间、范围等）导致无法安全编写时：need_clarification=true，questions 列出至多 3 个具体问题（每个问题给出你建议的默认选项），其余字段留空。宁可追问，不要猜。

【脚本硬性要求】
1. 首行 #!/usr/bin/env bash。
2. 随后 set -euo pipefail，并加中文注释解释三重防护各自作用。
3. 需要 root 时用 EUID 检查，非 root 给出中文报错并退出。
3. 所有变量展开必须双引号包裹；路径含空格也要安全。
5. 每个逻辑段（不超过 8 行）上方有中文注释，说明"做什么、为什么"。
6. 破坏性或影响业务的操作（rm、kill、systemctl stop/restart、iptables、分区）前必须 echo 中文提示。
7. 尽量幂等：重复执行不产生副作用（如 mkdir -p、判断存在再删）。
8. 失败路径输出明确中文错误到 stderr 并以非 0 码退出；不使用未定义命令；不假设未提供的参数。
9. 脚本顶部注释块：用途、用法、参数说明、依赖命令、生成方式（AI 生成，使用前请 review）、适用发行版。
10. 禁止 curl|bash 式管道执行远程脚本；禁止 rm -rf 变量展开未加保护的写法。

【解读要求】
explanation 数组按脚本逻辑分段（通常 3-8 段），每段：lines=行号范围、title=四到十字标题、detail=面向"看得懂基础命令但不熟 shell 陷阱的运维"，必须讲清这段做什么、为什么这样写、有什么坑（如为什么要 -o pipefail、为什么双引号、为什么先判断再删）。解读只存在于 explanation 字段，script 字段内只有代码与代码自身注释，绝不出现"解读""说明"性质段落。

【warnings 要求】
列出 2-6 条真实风险提示：涉及定时任务、root 权限、磁盘空间、误删风险、服务中断、生产环境需先在测试机验证等。

【usage 要求】
一行保存+执行示例（chmod +x 与调用方式）+ 参数说明（如有参数）。
```

user 模板：`需求：{requirement}\n发行版：{distro 或 未指定}\n补充：{notes 或 无}`，temperature=0.2。

> 注（2026-10-29 评审补充）：上文【脚本硬性要求】中编号重复（"EUID 检查"与"变量双引号"均为 3.）为原始提示词固有笔误——按"一字不改"契约**照抄保留**进 `prompts.py`，不做修正，不影响 LLM 理解。

### 9.2 日志分析 LOG_ANALYZE_SYSTEM_PROMPT

```text
你是资深运维排障专家。用户会提供一段日志的预处理结果（元信息、级别统计、错误/告警聚类样本）。你只依据这些证据分析，输出一份 markdown 排障报告。

【报告结构——严格遵守】
## 结论速览
（3 行以内：这段日志整体健康度、最可能的主线问题、影响面）

## 问题清单
（逐个问题输出，每个必须包含以下小节）
### 问题 N：<一句话标题>
- 现象：<观察到的表现>
- 证据：<引用聚类编号与次数、或"行号 123"级别的原始行摘录，必须是材料里出现过的内容>
- 根因推断：<按可能性排序的 1-3 个原因，每个标注置信度：高/中/低>
- 建议动作：<可执行的排查或修复步骤，给出具体命令>

## 下一步排查建议
（3 条以内，按优先级排序，附具体命令）

【纪律】
1. 禁止编造材料中不存在的日志行、时间、数值；不确定就明确写"不确定"，并说明缺什么证据。
2. 证据必须可回溯：引用聚类（如"聚类 3，出现 47 次"）或行号；不要泛泛说"日志中有错误"。
3. 聚类样本已被截断时，不得对截断部分的内容做推断。
4. 全文中文，直接输出 markdown 正文，不要输出多余的开场白和结尾客套。
```

user 模板：日志材料组装（§8 Phase 6）+ 可选 `重点关注：{focus}`，temperature=0.3。

---

## 10. 附录 A · Windows 环境坑清单（施工时逐条对照）

1. **编码**：Python 任何 `open()` 必带 `encoding="utf-8"`；`print` 中文到 GBK 控制台可能报 UnicodeEncodeError——`main.py` 顶部 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`。
2. **中文路径**：`E:\Asia\开发\项目\练习工程\OpsMate` 含中文——所有路径用 `pathlib.Path` 拼接，不拼字符串；PowerShell 命令行引用路径时整体加引号。
3. **pip 国内镜像**：`-i https://repo.huaweicloud.com/repository/pypi/simple`（写入 README 与 requirements 安装说明）。
4. **端口**：`socket().bind(("127.0.0.1", 0))` 取空闲端口，杜绝冲突；勿写死端口。
5. **WebView2**：pywebview 依赖 Edge WebView2 运行时，缺失时 `webview.start()` 抛异常——捕获后 `webbrowser.open(url)` 降级并在控制台提示安装 WebView2。
6. **PyInstaller 数据文件**：`--add-data "src;dst"`（Windows 用分号）；代码内用 `sys._MEIPASS`（只读资源）与 `sys.executable` 旁目录（可写数据）区分——`app/config.py` 必须实现该双态逻辑。双态常量口径：`APP_DIR`（开发态=项目根 `app/`；frozen 态=`sys._MEIPASS` 下 `app/`，用于定位静态资源 `app/web` 与包内知识数据只读源）与 `DATA_DIR`（开发态=项目根 `data/`；frozen 态=`sys.executable` 父目录下 `data/`，可写），其余模块一律引用 config 常量、不得自行判断 frozen。
7. **subprocess 调 git**：参数列表传参（不经 shell），`encoding="utf-8"`，避免 GBK 解码 git 输出报错。
8. **SSE**：uvicorn 的 `StreamingResponse` 需要 `media_type="text/event-stream"`；前端用 fetch 流读取（EventSource 不支持 POST）。
9. **SQLite 并发**：全部连接串 `check_same_thread=False` + 每请求新建连接用完即关（或线程局部连接）；WAL 已开。
10. **pywebview 打包坑**：exe 启动失败或报找不到后端时，追加 `--hidden-import=webview.platforms.winforms`（必要时 `--collect-all webview`）重打；发布用 onedir 模式（`dist/OpsMate/` 整目录分发），比 onefile 启动快、杀软误报率低；如仍被 Defender 误报，README 指引用户加排除项而不是改名规避。

## 11. 附录 B · 首批知识库收录清单（条目名，内容你按官方文档补全）

**nginx · cli（≥12）**：`nginx`（启动）、`nginx -t`、`nginx -s reload`、`nginx -s stop`、`nginx -s quit`、`nginx -s reopen`、`nginx -v / -V`、`nginx -c <file>`、`nginx -g <directive>`、`nginx -T`、`systemctl start|stop|restart|reload|status nginx`、`nginx -p <prefix>`。
**nginx · conf（≥55，覆盖 main/events/http/server/location 五层）**：worker_processes、worker_cpu_affinity、worker_rlimit_nofile、events{worker_connections}、use epoll、http{default_type}、log_format、access_log、error_log、sendfile、tcp_nopush、tcp_nodelay、keepalive_timeout、keepalive_requests、send_timeout、client_max_body_size、client_body_buffer_size、client_header_buffer_size、large_client_header_buffers、server_tokens、types_hash_max_size、server_names_hash_bucket_size、server{listen}、server_name、root、alias、index、location 匹配（= ^~ ~ ~* /）、try_files、rewrite、return、error_page、autoindex、internal、limit_except、limit_conn/limit_conn_zone、limit_req/limit_req_zone、gzip on/off、gzip_types、gzip_min_length、gzip_comp_level、proxy_pass、proxy_set_header（Host/X-Real-IP/X-Forwarded-For）、proxy_connect_timeout、proxy_read_timeout、proxy_send_timeout、proxy_buffering、proxy_cache 及 cache_valid、upstream{server weight/max_fails/fail_timeout}、ip_hash、least_conn、fastcgi_pass、ssl_certificate、ssl_certificate_key、ssl_protocols、ssl_ciphers、ssl_session_cache、listen 的 backlog/so_keepalive、resolver、charset、add_header、expires、stub_status、auth_basic、allow/deny、access_by_lua（标注需 lua 模块）。
**zabbix · cli（≥10）**：`systemctl start|stop|restart|status zabbix-server`、`systemctl start|stop|restart|status zabbix-agent2`、`zabbix_server --version`、`zabbix_server -c <file>`、`zabbix_agentd` 二进制用法（-c/-t/-p）、`zabbix_agent2 -t <key>`、`zabbix_get -s <ip> -k <key>`、`zabbix_sender -s/z/k/o`、`zabbix_server -R config_cache_reload`、数据库初始化提示（zcat schema.sql）。
**zabbix · conf（server ≥35）**：ListenPort、ListenIP、SourceIP、LogFile、LogFileSize、DebugLevel、PidFile、SocketDir、DBHost、DBName、DBSchema、DBUser、DBPassword、DBSocket、DBPort、StartPollers、StartIPMIPollers、StartPollersUnreachable、StartTrappers、StartPingers、StartDiscoverers、StartHTTPPollers、StartTimers、StartEscalators、StartAlerters、JavaGateway、JavaGatewayPort、StartJavaPollers、StartVMwareCollectors、VMwareFrequency、VMwareCacheSize、HousekeepingFrequency、MaxHousekeeperDelete、CacheSize、CacheUpdateFrequency、StartDBSyncers、HistoryCacheSize、HistoryIndexCacheSize、TrendCacheSize、ValueCacheSize、Timeout、TrapperTimeout、UnavailableDelay、UnreachableDelay、UnreachablePeriod、ExternalScripts、AlertScriptPath、FpingLocation、Fping6Location、LogSlowQueries、ProxyConfigFrequency、ProxyDataFrequency、StartProxyPollers、Include、TLSConnect/TLSAccept（server 侧）。
**zabbix · conf（agent2 ≥25）**：PidFile、LogFile、LogFileSize、DebugLevel、Server、ServerActive、ListenPort、ListenIP、Hostname、HostnameItem、HostMetadata、HostMetadataItem、HostInterface、HostInterfaceItem、RefreshActiveChecks、BufferSend、BufferSize、MaxLinesPerSecond、Timeout、Include、UnsafeUserParameters、UserParameter（含示例与命令黑名单提醒）、Alias、ListenBacklog、TLSConnect、TLSAccept、TLSCAFile、TLSCertFile、TLSKeyFile、TLSPSKIdentity、TLSPSKFile、LoadModule、Plugins（UserParameter/Mock 等插件子配置概述）。

每条必须有：name、syntax、default（conf 类必填，cli 类可省）、section（nginx conf 标 main/events/http/server/location；zabbix conf 标 server/agent）、desc（1-3 句中文）、example（真实可抄）、notes（改动生效方式：reload/restart/无）、danger、tags。**版本口径**：nginx 1.24/1.26、Zabbix 6.0 LTS（notes 标注"7.0 起有变化"的条目单独注明）。

---

## 尾注：验收总表（全部完成后逐项复验）

- [ ] 桌面窗口打开，五模块导航可用，暗色主题
- [ ] 指令速查：600+ 命令离线可搜可看
- [ ] 配置速查：nginx/zabbix 启停与配置严格分 Tab，可搜索，危险项有标记
- [ ] 脚本工坊：含糊需求会追问；成稿脚本注释全、无解读混入；右侧解读/风险/用法齐全；历史可回看
- [ ] 日志中心：上传/粘贴、level 着色、组合过滤、导出带行号
- [ ] AI 分析：L1 聚类免费可用；L2 报告流式生成、证据带行号、可回看
- [ ] 设置：key 不回传；测试连通有延迟/错误反馈；免费模型预设就绪
- [ ] 打包 exe 可独立运行：双击即用、无需 Python/中间件，首启动自动落地全量知识数据，README 完整
