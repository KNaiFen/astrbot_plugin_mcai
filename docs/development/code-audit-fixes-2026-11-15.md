# 2026-11-14 代码审查整改

[开发索引](README.md) · [原始审查与证据](code-audit-2026-11-14.md)

本轮基于本地`dev`提交`0979503`核实并处理原审查的11项功能缺陷与1项工具可用性问题。原报告保留审查当时的行为和断言方向；本页记录后续整改，不将旧复现脚本退出0当作修复验收。

## 核实与修改

| 编号 | 当前行为 | 验证入口 |
|---|---|---|
| R01 | 明确将排障提供商限定为AstrBot的OpenAI兼容Chat／Responses；设置保存、能力测试及任务运行拒绝原生Gemini等其他适配器。保留完整工具schema及执行约束 | `test_audit_agent.py`的不支持提供商用例；`test_tool_contracts.py`真实Chat／Responses请求与工具结果续接 |
| R02 | 根据恢复时的实际类型移除目标，再按备份的原类型复制；保留恢复前备份，复制失败保留部分现场并停止后续步骤 | `test_audit_data.py`的双向类型互换、两份备份与复制失败用例；既有`test_repair_edges.py` |
| R03 | 产物页按JSON转义后的字符预算裁页，偏移仍为原文字符位置，避免已分页内容再生成结果job | `test_audit_data.py`经HTTPS拼接反斜杠、引号、换行、中文，比较全部原文、游标与job数量 |
| R04 | 保存与任务启动复用`create_lock`，保存期间新建／续接／归档等待生效；已有worker时拒绝保存，并发保存串行，仅安装已提交快照 | `test_audit_agent.py`的真实AstrBotConfig写盘屏障、新建、暂停续接与并发保存 |
| R05 | 提交记录成功但审计日志失败时，将原操作持久化为`failed/not_executed`，不创建worker；同编号重提、取消和B初始化保持终结事实 | `test_audit_host.py`将审计路径设为目录制造真实文件错误 |
| R06 | 新建、选服和占用展示共用包含`cancel_pending`的判断；中止／验收的后台取消结算前继续占用，失败与重载保留 | `test_audit_agent.py`的暂停中止、运行中止、验收、取消失败及重载 |
| R07 | 复用现有Windows Job封装，为每次辅助worker增加无独立内存限额的嵌套Job；worker结束后清理全部后代，再报告终结，不依赖存活根PID | `test_audit_host.py`的成功、失败和取消；同时核对其他诊断仍running及MC仍运行 |
| R08 | 将审核响应本地记录移出模型重试闭包，写入失败明确暂停；模型请求成功后的任务保存也移出可重试区 | `test_audit_agent.py`使用真实Chat适配器／SDK与SQLite触发器，仅允许一次HTTP请求且不执行操作 |
| R09 | attach分别维护完成行游标、已显示半行偏移和会话；长行沿原接口续读，会话变化从新游标开始 | `test_audit_host.py`的真实ConPTY跨轮询半行，以及真实HTTPS受控长行／会话边界 |
| R10 | Unicode大小写折叠查找结果转换回原文字符位置，非零offset也使用原文坐标 | `test_audit_data.py`的本地HTTP网页、ß前缀、大小写查询与非零offset |
| R11 | Quilt单独按其声明读取字符串／对象依赖、optional、带独立版本及组名的别名、环境和嵌套JAR；组合与unless条件明确`dependency_unverified` | `test_audit_data.py`的HTTPS清单；既有Fabric／Forge／Bukkit回归 |
| U01 | 控制台区分事件页结束与字符尾部完成；`pending_reads`保留本页所有尾部和下一事件页的可执行参数，`next_call`优先长行；高转义页先走通用产物分支 | `test_audit_data.py`按待办逐项读完多个长行及事件页，并通过产物读回高转义控制台页和原行尾部 |

修复前重新运行原始host、storage、artifact复现：3项“应有行为”断言失败，5项“确认缺陷”断言及1项IntArray排除验证通过，见`runtime/audit-fix-before.log`。设置交错两项复现确认旧行为，见`runtime/audit-fix-settings-before.log`；真实Google SDK请求仍将生产工具结构转成NULL，控制台仍先翻事件页，见`runtime/audit-fix-contracts-before.log`。其余路径逐项对照当前源码和原始证据核实。

## 验证记录

固定Windows／Python3.12.14／AstrBot4.29.4。测试使用真实HTTPS、ConPTY、PowerShell、辅助worker及原生runner，模型／审核HTTP响应由测试控制，测试服通常为受控Python交互进程；恢复中途复制失败用`local_execution`注入，未将该用例称为真实辅助进程故障。

完整源码回归452项全部通过、零跳过（1458.30秒），见`runtime/audit-fix-all.log/xml`。最终复核将通用产物识别移到普通控制台分页之前，并增加高转义控制台页用例；该边界调整后19项相关专项全部通过、零跳过（86.52秒），见`runtime/audit-fix-final-boundary.log/xml`。当前收集的453项场景均出现在上述成功结果中，无遗漏；两批重叠项不累加，核对结果见`runtime/audit-fix-20261115/coverage-proof.json`。

从解压B包离线构建wheel，安装到独立site；从空工作目录以解压A插件执行28项整改与工具契约集成，全部通过、零跳过（124.58秒）。导入路径确认B的host、worker、结果转换来自独立site，A的17个私有模块来自解压插件；测试仅为验证复制到解压目录，发行ZIP不含测试。见`runtime/audit-fix-20261115/release-wheel.log`、`release-install.log`、`release-installed-tests.log/xml`及`release-import-proof.json`。轮初隔离源码副本的13项B专项也通过，未与最终28项相加计数。

两端ZIP、五目标Probe及完整源码包构建通过；插件包55项、B包111项、源码包202项，归档完整性、源码对应、必要文档链接及运行数据排除检查通过。安装包不含开发规则与测试，源码包保留两者。12个JAR内部文件内容与构建前逐项一致；Probe仍为0.2.1，未重跑真实MC组合。构建后按最终验证记录刷新归档中的文档，再核对内容一致性。见`runtime/audit-fix-build.log`、保留无法按UTF-8解释字节的`audit-fix-build-utf8.log`及`runtime/audit-fix-20261115/package-proof.json`。

Ruff、Python格式、设置页JS语法、配置JSON和Git空白检查通过。本地Markdown链接检查通过；保留上游audioop及旧工具schema接口弃用警告。以上证据保存在被忽略的runtime目录，仅本地保留，不随安装包分发。

## 范围与消融审查

保留原生runner、38个工具、操作编号、后台任务、SQLite、审核与一次管理员批准机制。未修改上游、生产实例或用户运行时规则；没有新增配置框架、持久化任务状态或审批层级。占用判断只抽取三处共同谓词；设置复用已有锁，进程清理复用已有Job封装。

R01采用明确限定支持范围的修复路径，本轮没有新增原生Gemini转换器。Quilt组合依赖只报告未核实，未实现完整加载器依赖求解器；HTTP／SDK响应由测试控制，未联调计费模型、QQ或生产服。ConPTY长段输出会受终端呈现影响，因此attach的真实半行与受控缓冲长行分页分开验证。

本页所列代码、文档和本地验证属于开发态整改，未发布新版或推送。
