# J5 工具验收矩阵

所有接口回放使用临时目录、本机自造模型和MCP服务；真实活动配置未改动。证据为assistant-wire.json、Maven报告及PublicHttpTest。

| 工具 | 权限、输入与限额 | 已验收证据 | 清理/未验收项 |
|---|---|---|---|
| search_commands/search_kb/search_history | 只读、检索限条数 | J2/J4差分与工具规划 | 无写操作 |
| read_user_config | 仅共享配置≤4000字；当轮@引用单独授权 | 共享关闭下一轮不带原文；显式引用可读 | 不缓存共享正文 |
| write_file | 文件名无路径，内容≤1M字 | 确认前无文件、确认/取消、重复确认/路径穿越拒绝 | 原子替换、临时文件清理 |
| list_dir/read_workspace_file/write_workspace_file | 已授权真实目录；300项/200KB/1M字 | 中文读写、父路径与真实Windows联接越界拒绝 | 原子写；写前再次解析 |
| run_command | 授权cwd、命令≤2000字、5–120秒 | 自造echo成功；输出限4000/2000字 | 超时/取消清理子进程树 |
| web_search/web_fetch | 公网地址，重定向逐跳校验，15秒，2MB/8000字 | 内网/IPv6/凭据URL拒绝；HTTP文本/限额/正文挂起测试 | 搜索引擎公网可用性最终联网补验 |
| configure_api | 用户下令，参数校验、本机保存、25秒小请求 | 模拟401诊断、新旧key不回显、设置档案差分 | 真实平台仍受1310阻塞，最终补验 |
| install_skill | YAML/SKILL.md/GitHub转换、≤64K字，拒绝重定向 | 格式转换、安装注入/重复/删除、超限/重定向/公网策略 | CREATE_NEW防覆盖 |
| install_mcp | 用户下令，stdio参数数组或HTTP地址 | 初始化/通知/列举/调用/失败/超时/回滚 | 实际PID已退出 |
| download_file | 公网HTTP(S)、≤300MB、60秒，只下载；镜像只用华为 | 公网边界与有界HTTP下载组件 | 原子替换与临时清理；不执行安装 |
| system_info/list_processes | 只读、进程最多100项 | 实际系统读取与名称过滤 | 不改系统 |
| manage_workspace | 用户下令，现存绝对目录 | 添加/撤销、会话归未分组、重启保存 | 无递归删除 |
| install_kb | 本机增量、cli/conf两类，唯一name、danger/section/example约束 | 安装即读、重启保留 | 原子写，不改内置资源 |
| stop_process | 用户明确指定PID/精确名称；拒绝自身 | 无效PID拒绝 | 实际结束进程留最终专用目标验收 |
| open_path | 已授权目录/本机下载目录，参数数组 | 不存在/越界拒绝 | 打开资源管理器留最终桌面授权 |
| archive_files | 授权目录、真实路径；解压≤10000项/300MB | 中文zip往返、zip-slip与链接越界拒绝 | 先全包预检；逐文件原子替换 |
| schedule_task | 用户明确下令，固定OpsMate_前缀，daily有效时间 | 无效时间拒绝，未创建任务 | 创建/删除只在最终专用目标验收 |
| mcp__* | 仅启用服务器；协议和响应限额 | stdio/HTTP SSE、Session-ID、挂起/失败/禁用/删除 | 失败关闭进程，退出回收全部会话 |

界面来源点击、拖入、布局、流期间切页及原生对话框集中最终桌面授权验收，当前不声称通过。
