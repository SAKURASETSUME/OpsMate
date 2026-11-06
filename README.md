# OpsMate 运维提效智能体

Windows 单机桌面应用：本地知识 + 智能体，为管理 Linux 服务器的运维工程师提供指令/配置速查、脚本生成、日志诊断与运维问答。免安装，双击即用。

Java 是当前主版本。Windows 便携包通过 [GitHub Releases](https://github.com/SAKURASETSUME/OpsMate/releases) 分发，构建、数据迁移与回退见 [Java 说明](JAVA_README.md)，验收范围见 [J6 记录](migration/j6/STATUS.md)。

Python 备用版固定在 [backup-python 分支](https://github.com/SAKURASETSUME/OpsMate/tree/backup-python)。回退时使用独立目录和原 Python 数据备份。下方保留 Python 基线的功能与运行说明。

## 功能模块

| 模块 | 说明 |
|---|---|
| 指令速查 | 621 个 Linux 命令中文文档，关键词检索，命令卡片一键复制 |
| 配置速查 | 15 个常用软件（nginx/MySQL/PostgreSQL/Redis/Kafka/RabbitMQ/Elasticsearch/Prometheus/HAProxy/Tomcat/ZooKeeper/keepalived/zabbix/docker/firewalld）的启停命令与配置参数严格分 Tab，危险等级标记，附生产配置模板；「我的配置」工坊支持上传/编辑/格式校验（YAML 行号报错、括号配对）与正则效果预览 |
| 脚本工坊 | 自然语言生成安全 bash 脚本：逐段中文解读、风险提示、生成历史可复用；支持一次生成多个脚本（名称标签切换，单次最多 3 个）；缺关键信息会先追问 |
| 日志中心 | 上传日志（≤50MB）→ 级别/关键词/正则过滤、上下文查看、规律聚类；L2 智能体下钻诊断并生成流式报告 |
| 运维助手 | 对话智能体：本地知识检索（来源可点击跳转）、工作目录读写与命令执行（用户授权）、联网查询、附件（文本+图片多模态）、文件生成提案确认制；「本地工具」开关可切换直连模式（问题直发所配模型）；长会话自动压缩摘要 |
| 版本管理 | 手动记录包版本台账：多条件筛选、语义版本排序 |
| 便签 | 待办事项勾选管理 |

## 首次使用

1. **推荐**：把整个 `OpsMate` 文件夹放到纯英文路径（如 `D:\OpsMate`），双击 `OpsMate.exe` 直接使用。
2. 若程序放在含中文的目录：双击 `OpsMate.exe` 会提示"首次启动需要准备运行环境（约 1-2 分钟，仅此一次）"，确认后等待窗口自动打开；之后每次启动都是秒开。也可以用文件夹里的 `start_OpsMate.bat` 启动（用系统 robocopy 建立英文运行副本，效果相同）。首次启动后 exe 旁自动创建 `data/` 目录并落地全量知识数据。
3. 进入「设置」页，选择模型预设（智谱 `glm-4-flash` 免费 / SiliconFlow / DeepSeek / 自定义 OpenAI 兼容），填入 API key 并保存启用。密钥只保存在本机 `data/config.json`，不会上传或随程序分发。
4. 到「运维助手」或「脚本工坊」开始使用。思考强度默认「高」，追求速度可切「低/中」。

> 提示：Windows 可能对未签名 exe 弹出 SmartScreen 警告，点「更多信息 → 仍要运行」即可。若窗口始终无法启动，查看 `data/opsmate-startup.log` 定位原因。

## 数据目录

所有数据保存在 exe 旁（开发态为项目根）的 `data/`：

- `opsmate.db`：会话/日志/版本/便签等 SQLite 数据
- `config.json` / `model_profiles.json`：模型配置（含密钥，仅本机，勿外传）
- `agent_workspace.json`：授权的智能体工作目录列表
- `commands/ kb/ skills/`：知识数据（可随版本更新重新分发）
- `logs/ assistant_files/ agent_files/`：运行期产物

卸载/清理：删除整个程序目录即可，不写注册表、不留系统残留。

## 常见问题

- **窗口打不开 / 白屏**：需要 Microsoft Edge WebView2 运行时（Win11 自带；Win10 缺失时程序会自动降级用默认浏览器打开，或从微软官网安装 WebView2 Runtime）。
- **端口占用**：不会发生——程序每次启动自动选取本机空闲端口。
- **提示未配置模型密钥**：前往「设置」保存并启用 key；使用付费模型前请确认账户额度。
- **回答慢**：思考强度调低；脚本生成耗时主要在模型撰写脚本本身（约 1 分钟内属正常）。
- **中文路径乱码**：程序全链路 UTF-8，无需处理。

## 开发

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -i https://repo.huaweicloud.com/repository/pypi/simple
python main.py            # 开发运行
python tools\verify_*.py  # 隔离验收（各自独立，不触真实数据）
pyinstaller --noconsole --name OpsMate --add-data "app;app" --add-data "data/commands;data/commands" --add-data "data/kb;data/kb" --add-data "data/skills;data/skills" main.py
```

依赖仅：fastapi、uvicorn[standard]、pywebview、httpx、PyYAML、python-multipart、pyinstaller。前端零构建（Vue3/marked 已内置）。
