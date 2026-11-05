# J0 基线状态

2026-11-05。Python 行为基线 03b275e。迁移分支 codex/java-migration。

| 验收项 | 结果 | 证据 |
|---|---|---|
| 六套隔离 verify | 6/6 通过，退出码 0 | workbench/logs/analysis/codegen/assistant/tools |
| OpenAPI 和阶段归属 | 60 接口均已分配 | openapi.json、API_MATRIX.md |
| 临时库 DDL | 包含按需创建的脚本历史与 FTS | schema.sql |
| 随机端口真实 HTTP | 十类入口 200，缺 key 日志 SSE 错误事件通过 | http-baseline.json |
| 历史用户故障登记 | 17 项，已分配阶段 | HISTORICAL_BUGS.md |
| 跨进程业务夹具 | 三轮独立目录 CRUD/校验/边界/重启、真实 provider 模拟成功流通过 | tools/verify_java_baseline.py |
| 后端新进程启动／空闲工作集／50 MiB 导入 | 三轮已测，实际服务 PID，正常退出通过 | process-baseline.json |
| 原生页面启动／模拟模型首个成功流事件 | 已取得源码启动及成功流样本 | desktop-baseline.json、process-baseline.json |
| 历史 UI／原生窗口故障实测 | 待对应阶段执行 | 不以当前后端通过替代 |

复现契约导出时从项目根设置 PYTHONPATH，再执行 .venv/Scripts/python.exe tools/freeze_java_baseline.py。所有建表和接口写入使用新建临时目录。内置知识从项目只读加载，未复制私有数据。

成功模型流已通过真实 HTTP provider→助手直连链路，三组样本见 process-baseline.json。原生窗口源码进程入口至 Vue 挂载约 4.17 秒，自动关窗和服务退出通过，见 desktop-baseline.json。该计时排除解释器启动，不作为最终 exe 性能结论。

J0 基线冻结验收通过。六套既有隔离回归、跨进程代表业务、模型成功流和原生页面基线已具备，J1 开始。历史 UI 故障实测按矩阵在 J1/J4/J5/J6 执行，最终包性能另在 J6 验收。
