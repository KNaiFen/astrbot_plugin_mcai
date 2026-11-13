# 文档索引

[项目简介与快速使用](../README.md)覆盖首次部署和群内操作。按当前目的继续阅读：

| 目的 | 入口 |
|---|---|
| 配置模型、多个服务端、Java、搜索和下载 | [使用文档](usage/README.md) |
| 理解边界、工具、审核、持久化和集成方案 | [设计文档](design/README.md) |
| 修改代码、运行测试、构建发行包或查组件来源 | [开发文档](development/README.md) |

## 文档约定

- 使用文档描述当前可用行为；设计文档解释已经采用的方案与约束；验证记录说明实际测过什么。
- 初期讨论过的方案和后续修订以[设计决策](design/README.md#设计决策)为准，不能把早期设想当成当前实现。
- 仓库根 `AGENTS.md` 约束开发工作；A 插件数据目录的 `AGENTS.md` 约束运行时排障与审核模型。两者用途不同。
- 详细文档放在 `docs/`。代码目录的 `mcai/agent_rules.md` 是随包安装的运行时模板，第三方许可和测试数据来源随组件保留。

文档描述对应 0.7.1。配置字段以 `_conf_schema.json`、`host.example.json` 和 `instances.example.json` 为入口，工具参数以 `mcai/tool_schemas.py` 为准。
