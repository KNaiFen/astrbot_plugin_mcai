# 文档索引

[项目首页](../README.md)提供首次安装、连通性检查和群内操作示例。按用途继续阅读：

| 目的 | 入口 |
|---|---|
| 配置模型、多个服务端、Java、搜索和下载 | [使用文档](usage/README.md) |
| 理解边界、工具、审核、持久化和集成方案 | [设计文档](design/README.md) |
| 修改代码、运行测试、构建发行包或查组件来源 | [开发文档](development/README.md) |

## 文档约定

- `usage/`：当前配置、命令、操作步骤及[版本变化](usage/releases.md)。
- `design/`：实际采用的架构、约束和失败处理。
- `development/`：开发、测试、构建与第三方来源。完整源码的 `docs/development/records/` 另存发行和验证证据；安装包附现行指南。

A、B 和托管窗口当前使用 `mcai-9` 通信协议（Probe 协议 1）；各版本变化见[发布说明](usage/releases.md)。配置以 A 的 `_conf_schema.json`、B 的 `host.example.json` 和 `instances.example.json` 为入口，模型工具契约由源码中的 `mcai/tool_schemas.py` 定义。安装时的三份[运行时规则](usage/configuration.md#运行时规则)和源码根目录的开发规则各有用途。
