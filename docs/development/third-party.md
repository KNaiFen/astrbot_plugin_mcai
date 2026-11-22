# 第三方组件与测试数据

[开发索引](README.md) · [存档与联网设计](../design/integrations.md)

## 服内探针

插件与 B 主机代码采用根目录 `LICENSE` 的 MIT 许可。以下组件及素材保留各自许可；根许可证不替代它们。

- **MCAI Probe** 源码采用MPL-2.0，完整许可见 `mods/mcai-probe/LICENSE`，来源说明见同目录NOTICE；每次发行附对应源码。
- 计时位置参考 [Observable](https://github.com/tasgon/observable) 固定提交 `f07aba86fbb075077ac7b8d820b4ff8fc6e69aae` 的 ServerLevelMixin、LevelMixin。实现改用 [MixinExtras WrapOperation](https://github.com/LlamaLad7/MixinExtras/wiki/WrapOperation)，不引入Observable的客户端、上传服务或调用栈采样运行时。
- **MixinExtras** 为MIT；Forge、Fabric目标嵌入0.4.1的loader JAR并保留自身许可。NeoForge目标只编译依赖0.5.3 API，运行时使用NeoForge21.1.247自带组件。Forge／NeoForge／Fabric和Minecraft为外部构建与运行依赖，不随包分发游戏程序。用于共存测试的第三方MOD仅保存在忽略目录。
- **spark报告格式**：按[lucko/spark固定提交2335038](https://github.com/lucko/spark/tree/2335038acccc621275e78b8f16a47f5d47babbdd/spark-common/src/main/proto/spark)的`spark.proto`／`spark_sampler.proto`字段号独立声明所需最小布局，原项目GPL-3.0许可保留在`mcai/vendor/licenses/spark-format-GPL-3.0.txt`。采样由外部已安装spark的命令接口执行，B不包含spark运行时或Java生成类。Python **protobuf >=5,<8**通过依赖安装，保留其BSD-3-Clause许可；本轮固定验证版本见依赖记录。

## 网页、搜索及 MOD 接口

- **trafilatura 2.x**：网页正文提取，Apache-2.0，<https://github.com/adbar/trafilatura>；链接和标题同时使用其依赖 lxml 解析。通过 Python 依赖安装，保留各发行包许可。
- 原生搜索遵循 [OpenAI Responses Web Search](https://developers.openai.com/api/docs/guides/tools-web-search)。独立搜索协议参考 [Codex 553c764 的 SearchRequest](https://github.com/openai/codex/blob/553c764e8b99fa519e9c6eb9b657875ef0f5e1c1/codex-rs/codex-api/src/search.rs) 与 endpoint/search.rs，以本项目 Python 实现请求适配；不引入 Codex 运行依赖。服务商是否实现 alpha/search 需单独测试。
- MOD 元数据和下载使用 [Modrinth 官方 v2 API](https://docs.modrinth.com/api/) 和 [CurseForge 官方 API](https://docs.curseforge.com/rest-api/)。CurseForge CDN 鉴权遵循其 [2026年公告](https://blog.curseforge.com/introducing-api-key-authentication-for-curseforge-file-downloads/)。MOD 由 A 按任务下载，安装方案送审时传给 B 暂存并校验；第三方 MOD 不随本项目发行。

## 审核与重试设计参考

上下文计数复用AstrBot的字符估算，以真实API输入用量校准；不附加分词运行库或词表。当前行为和估算边界见[状态与恢复设计](../design/storage-and-recovery.md#操作与后台任务)。

独立审核的材料组织参考本地Codex固定提交69231e119b：guardian/review_request.rs的真实输入版本与审核失效判断、guardian-reviewer/approval_request_json.rs的原始动作序列化，以及shell-command中使用PowerShell原生AST的解析方式。MCAI以现有Python、持久记录和PowerShell实现对应能力，不引入Codex运行依赖。

参考 DeepSeek Harness 固定提交 `e8f7b93a344964de3dca1ace9e72b6e4d6de87cb` 的 [auto-review](https://github.com/deepseek-ai/deepseek-harness/tree/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/experimental/auto-review)、user-approval 和 llm-retry：工具执行前独立审核、决定绑定单次调用、审核事件不进入主模型对话，以及从持久步骤恢复。实现继续使用 AstrBot 原生 runner，没有引入该 harness 的运行时或复制其权限策略。

## HTTPS

- **cryptography**：B 首次启动生成并保存自签名证书，Apache-2.0 或 BSD-3-Clause，<https://github.com/pyca/cryptography>。通过 B 的 Python 依赖安装，沿用其发行包附带许可。A 使用 aiohttp 的证书指纹接口，证书加载与传输使用 Python 标准库 SSL。

## 存档工具

- **nbtlib 2.0.4**：独立 NBT/SNBT 解析，MIT，<https://github.com/vberlier/nbtlib>。通过 Python 依赖安装，保留原发行包许可。
- **MCA Selector 2.9**：区域容器、扇区处理、gzip/zlib/未压缩/LZ4 和外部 MCC 读写，MIT，<https://github.com/Querz/mcaselector/releases/tag/2.9>。
- 固定发行文件 `mcaselector-2.9.jar`，SHA-256：`8e35eaa6a5119ce711b53530c22aaac531332e8fdffda2357d16eb6f52327267`。构建脚本校验后直接随 B 部署，不从 master 编译或运行时下载。
- 配套 **Querz NBT** 使用上述 JAR 自带版本，不额外混装旧版 NBT JAR：<https://github.com/Querz/NBT>。其 NBT 结构不经过块状态转换，保留未知模组字段。
- JAR 内还包含 Gson、fastutil、lz4-java、Log4j 等依赖。原 JAR 自带许可证/NOTICE，同时在 `mcai/vendor/licenses` 中保留副本；MCA Selector 和 Querz NBT 的 MIT 许可单独放在 vendor 下。

本项目 Java 辅助程序只提供 JSON-lines 适配、原始 Chunk 的目录绑定、查询和单点字段修改。不会启动 MCA Selector GUI，不复用其地图转换流程。所有区域文件写入都在备份后的副本中完成。

## 真实存档测试片段

`tests/fixtures/worlds` 来自 Amulet-Team/Amulet-Minecraft-Worlds，MIT：
<https://github.com/Amulet-Team/Amulet-Minecraft-Worlds/tree/126fc297e3de101e61a90e0efb824a500a11d499>

保留其 `LICENSE`；`sources.json` 逐文件记录固定提交下的原地址与 SHA-256。包括 Java 1.17.1 的实体区域和 Forge 1.16.5 暮色森林维度的 POI 区域。其他压缩、异常数据及版本结构样本由测试生成，不能据此宣称覆盖所有整合包。
