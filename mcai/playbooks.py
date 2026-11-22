"""Workflow guidance loaded only when requested by the main agent."""

MOD_REPAIR_GUIDE = """MOD源码修复：先核对故障、目标和素材。用mc_workspace pull从B取素材，在A核对java、javac、jar或项目构建工具后修改和构建。首次提案就写清这次修复范围：隔离试服先安装、启动和验证；管理员实际试玩通过后，正常关试服，备份并把同一份制品安装到正式服，按原方式启动并验证。
获批后在原plan_id内继续。用stage登记产物，经install_download传到B；试服安装、启动和ready验证可合并在一个测试批次。试服就绪后用mc_say提供入口、测试目标与内部test_operation_id，然后等待。
按上下文理解管理员的自然语言。明确试过当前版本且通过时，用原反馈的id作trial_feedback_id提交正式服发布，不复问，不要求固定措辞。发布批次包含安装、启动和ready验证，程序会先正常停试服。新候选装到试服后重新请试玩，无需重复批准同一范围。
未通过则按现象或发生时间查本次试服证据；缺关键线索时问一个问题然后等待。未完成正式服发布和验证，不结束方案或提示done。不要把端口或启动日志说成玩家通过。提示可用say自然回复，不写示例答案让用户照抄。回复只说用户要决定的事、试玩入口或实际结果，内部编号和审核留本地。"""

PLAYBOOKS = {
    "mod_repair": MOD_REPAIR_GUIDE,
    "file_patch": """局部修改与文件写入：改文本先用 mc_query files stat 拿原文件 sha256，再用 preview-patch 核对唯一匹配与差异，确认后通过 mc_propose 提交 patch_text（保留原编码、BOM 与换行）或 write_text；可选 format 会在替换前预解析 JSON/TOML/YAML。
文件修改、配置写入和脚本都会由 B 自动先停服、按声明范围建初始备份，成功后恢复原运行状态；需要指定启停顺序则在同方案显式写明 start/stop/restart 并接 verify(ready)。通用 script 必须声明全部 backup_paths。
验证按影响选择：语法用 file、目标键值用 text/NBT、启动就绪用本轮 start 后的 cursor/session_id 查 ready（query 默认字面量匹配，逐行正则须加 (?m) 和 regex=true）。验证失败留现场与备份，不默认重跑或自动回滚。""",
    "world_nbt_repair": """存档 NBT 与坏区块处理：修改前必须停服备份。NBT 列表项按 UUID、方块实体坐标或 Slot 选择，先用 mc_query nbt/region-nbt 的 select 或 preview-batch 核对数量与旧值，再提交 nbt_batch/region_batch；每条变更带类型的 expected（仅原先不存在的新字段用 null），不用旧列表下标当稳定身份。
坏区块先用 region-check 排查，恢复源先 region-export 并核对目录、维度、坐标及 usable，可从明确备份导出；整块删除或恢复用最新检查点指纹并注意关联 entities/poi/mcc。
方块读改用 region-blocks 的 read/search，提交 block_set 须给出完整旧状态，替换方块实体类型须明确 remove_block_entity 与旧 SNBT；GTNH 等扩展数字 ID 暂不支持 block_set，勿凭可读取推定可写。""",
    "mod_install": """下载与安装 MOD：先用 mc_inventory 核对当前服务端实际版本、加载器、嵌套 JAR、依赖与清单，不用文件名猜身份。
查来源用 mc_mods，下载经 mc_mods/mc_download 进 B 暂存区，不默认最新版，不直接执行未核实文件；再通过 mc_propose 的 install_download 提交安装，并在方案里写清目标路径及须移除的旧文件。""",
    "schedule": """定时备份与重启：先核实实例与 B 本地时间，再用单独的 mc_propose 提交唯一一个 schedule 步骤，不与修复、试服或 continuation 合并，每步对应独立短码批准。
每天只填 at（HH:MM）；每周另填 weekdays（1 为周一，7 为周日）。备份明确 mode（online/offline）、paths 和 retain；重启可用 announce_minutes 调整提前公告分钟（默认 10 和 1），notify_success 默认关闭。调整旧计划时填 replace 指明旧计划编号重新审核与批准。""",
}
