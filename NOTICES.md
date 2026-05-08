# NOTICES

kdkvm (KVMind Device Bridge) 在运行时依赖以下第三方开源软件。此清单遵循各依赖项原始许可证的归属与通告要求。

## Python 运行时依赖

### aiohttp
- 许可证: Apache License 2.0
- 版权: Copyright aio-libs contributors
- 主页: https://github.com/aio-libs/aiohttp
- 用途: HTTP/WebSocket 服务与客户端

### PyYAML
- 许可证: MIT License
- 版权: Copyright (c) 2017-2021 Ingy döt Net / Copyright (c) 2006-2016 Kirill Simonov
- 主页: https://pyyaml.org/
- 用途: 配置文件解析

### cryptography
- 许可证: Apache License 2.0 OR BSD-3-Clause (dual-licensed)
- 版权: Copyright (c) Individual contributors
- 主页: https://github.com/pyca/cryptography
- 用途: Ed25519 签名验证（MyClaw 签名批次 / OTA 清单）

## 可选运行时依赖

### pysqlcipher3
- 许可证: Zlib License
- 主页: https://github.com/rigglemania/pysqlcipher3
- 用途: 加密 SQLite 持久化（设备端 base_store）。若未安装则回退明文 SQLite。

## 系统工具依赖（非 Python）

设备端脚本调用以下系统工具（各自遵守所在 OS 发行版的许可证）：

- `systemd` (LGPL-2.1+)
- `nginx` (BSD-2-Clause) — kvmd 预装
- `cloudflared` (Apache-2.0) — Cloudflare Tunnel 客户端，可选
- `wpa_supplicant` (BSD) — WiFi 管理
- `ustreamer` (GPL-3.0) — kvmd 预装的视频流

## Apache License 2.0 完整通告

以下依赖以 Apache License 2.0 授权，本项目保留其版权与许可证声明：

```
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

应用范围: aiohttp, cryptography (Apache-2.0 路径), cloudflared

## 更新策略

本文件应在 `pyproject.toml` 依赖变更时同步更新。

---

更新于: 2026-04-17 (audit-r4 · Sprint 0 · R4-COMP-03)
