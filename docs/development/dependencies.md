# 固定验证环境与依赖重建

[开发索引](README.md) · [本轮整改](architecture-remediation-0.8.0.md)

`dependencies/windows-py312.lock`记录2026-11-13 Windows x64／Python3.12.14验证环境的精确包版本与SHA-256，包含AstrBot集成和测试依赖。`environment.json`记录平台、可安装存档名、官方AstrBot v4.29.4源码ZIP的哈希，以及523个Python源码文件的比对结果（只归一化CRLF）。完整环境用于重建验证；日常开发仍可使用范围依赖。

2026-11-15随Probe0.3.0新增标准Protobuf依赖，固定验证为protobuf7.36.2；重新记录安装来源与SHA-256，其余包版本与既有清单一致，AstrBot523个源码文件重新核对通过。范围声明仅在B的pyproject.toml中，A插件不导入报告解析模块。

先准备官方AstrBot v4.29.4源码并按environment.json核对ZIP哈希，再在源码仓库创建空环境。安装包和依赖下载使用已配置代理：

```powershell
py -3.12 -m venv runtime/rebuild-env
runtime/rebuild-env/Scripts/python.exe -m pip install --require-hashes -r docs/development/dependencies/build-tools.lock --proxy http://127.0.0.1:7890
runtime/rebuild-env/Scripts/python.exe -m pip install --no-build-isolation --require-hashes -r docs/development/dependencies/windows-py312.lock --proxy http://127.0.0.1:7890
runtime/rebuild-env/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e .
$env:PYTHONPATH = "$PWD/runtime/astrbot-4.29.4"
$env:ASTRBOT_ROOT = "$PWD/runtime/astrbot-test"
runtime/rebuild-env/Scripts/python.exe -m pytest -q --require-astrbot
```

aiocqhttp和jieba使用固定源码包；先安装固定build-tools，再禁用构建隔离，避免临时解析另一套构建依赖。部署B可从解压包构建wheel，并以--no-deps安装到同一固定环境；插件从解压目录验证实际导入路径。包哈希不包含凭据、配置和运行数据。

在已完成验证的环境重新记录清单：

```powershell
.venv/Scripts/python.exe scripts/lock_environment.py --astrbot-archive runtime/astrbot-v4.29.4.zip --astrbot-root runtime/astrbot-4.29.4
```

当前开发源码A/B产品协议为mcai-5，既有公开0.11.1附件仍为mcai-4，响应附带MCAI版本；插件、主机及托管窗口需配套更新。客户端在提交远程工作前读取实例接口核对协议，B在创建操作前校验请求协议。不匹配时给出中文错误，不维护旧接口迁移。
