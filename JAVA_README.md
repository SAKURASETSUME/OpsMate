# OpsMate Java 迁移与试用

Java版使用JDK21、Spring Boot MVC、Spring JDBC/SQLite、JavaFX WebView，复用原零构建Vue界面。便携包内含运行时，用户电脑无需安装Java、Python或数据库。

## 当前状态

这是迁移候选版。接口、存储、模型模拟、MCP和切换回退已有自动验收；用户指定火山API的真实脚本/诊断链路已通过，智谱原接口仍受额度限制。最终原生交互仍待授权补验，不能把候选版描述为最终已验收exe。

## 启动与本机资料

解压整个便携目录，双击`OpsMate.exe`。请放在可写目录。首次启动将621个命令、15个软件知识和6项内置技能落地到exe旁`data`。已有同名资料不覆盖，技能删除后重启保持删除。

在设置页填写模型配置并显式启用。密钥只存本机，分享项目或程序时不要带上`data`。关闭主窗口退出全部后端；嵌入内核失败会改用默认浏览器，小控制窗提供退出按钮。

运行参数由桌面入口传递到后端：`--opsmate.data=绝对目录`覆盖本机数据目录，`--opsmate.knowledge=绝对目录`用于独立知识夹具。默认开发数据在`java-app/target/local-data`。`--headless`仅启动接口，`--browser`强制浏览器降级。HTTP服务始终绑定127.0.0.1的随机端口。

## 从Python版试用迁移

先退出旧程序。使用开发环境执行下面的工具，目标目录必须全新；工具不会覆盖或删除源目录。

```powershell
.venv\Scripts\python.exe tools/migrate_java_data.py --source "原Python程序的数据目录" --destination "独立的Java试用数据目录"
```

工具使用SQLite备份、完整性检查和附件散列核验，复制本机模型档案、授权与MCP配置并修正附件路径。目标为私有本机副本，严禁拿来打包或分享。若放仓库内，只允许已忽略的`local-java-data`或`local-java-backups`目录（测试临时目录另行隔离），避免误提交模型档案。失败目录带`.migration-failed`，先排查，不启动该副本。

Java试用指向该副本。若回退，先关闭Java，将其数据再复制到一个新的独立备份目录保留增量，再重新打开未改动的Python版。不要用旧库覆盖Java新增会话，也不要在同一目录同时运行两版。

## 构建及验收

在`java-app`目录使用JDK21和Maven，镜像只走华为：

```powershell
mvn -B -ntp -gs settings-huawei.xml -s settings-huawei.xml clean verify
```

构建运行单元/模块测试，并在当轮新jar完成后回放离线、日志、设置、生成诊断、助手MCP和切换回退。开发测试需要项目现有`.venv`，发布应用运行无需Python。不要使用跳过测试的构建作为验收产物。

通过后从项目根执行`tools/package_java.py`生成带散列清单的干净候选包，再执行`tools/verify_java_candidate.py`在解压副本无界面验收。打包输入只取验收jar；知识为正向清单，模型档案、数据库、授权、MCP、日志、附件一律排除。候选包不在源码Git中提交。

完整证据见`migration/j0`至`migration/j6`及`PHASE_LOG.md`。真实平台和桌面补验完成前不改为正式交付状态。
