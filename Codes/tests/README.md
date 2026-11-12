# 网络层、客户端与 CLI 测试

运行步骤、对接 API 和当前限制见 [Codes/README.md](../README.md)。

| 文件 | 检查/用途 |
| --- | --- |
| `server_temp_test.py` | 临时 echo 客户端；分别显示响应、错误、事件，事件不计作请求回复；不是 D/E 的正式客户端 |
| `test_protocol.py` | UTF-8/JSON 编解码、换行分帧、不完整尾部、常见坏消息与超长帧 |
| `test_server.py` | session 发送、编码失败、已关闭连接、响应与事件并发发送保持帧完整 |
| `test_dispatch.py` | 交给自定义请求处理器、事件与回复共存、指定名单广播、失败连接隔离、临时客户端分类 |
| `test_disconnect.py` | 网络失败关闭、编码失败保留连接、断线回调、重复关闭、等待回调完成和其他客户端继续工作 |
| `test_startup.py` | 参数必填/互斥、假加载器先于监听、校验失败不启动、正式启动标志；不验证 B 的真实题库 schema |
| `test_network.py` | 子进程和真实 TCP 测试；多请求、格式错误、两个客户端和十条同时建立的连接分别收到自己的回复 |
| `test_connection.py` / `test_state.py` | D 原有 11 项通信、分片/合并、响应/事件、超时/断线与状态测试 |
| `test_client_regressions.py` | 本次 11 项 D/E 接入回归：错误匹配、pending 清理、超时、旧题确认、外房事件、快照和输入题号 |
| `test_cli.py` | 本次 3 项真实子进程/TCP 客户端检查：脚本业务流程、输入空闲时的结果/断线、EOF 退出 |
| `cli_demo_server.py` | 单客户端脚本对端，含模拟第二名玩家；仅供开发，不是 B/C 的实现或多人验收证据 |

最新复验中，main **54 项通过**（A 原有 29、D 原有 11、E 增量 14），C 独立分支的 `test_game_engine.py` **7 项通过**。本轮用老师环境包原始 Dockerfile 新构建，Python 3.12.16；见 [官方复验记录](../../docs/evidence/2026-11-12-official-env-validation.md)、[main 输出](../../docs/evidence/2026-11-12-official-main-unittest.txt) 和 [C 输出](../../docs/evidence/2026-11-12-official-game-engine-unittest.txt)。C 测试文件还不在本次 main 基线中，不能把两套测试合称已集成的 61 项。

A 网络测试使用 `--lab-mode`，CLI 使用脚本对端，C 的十玩家场景是内存状态测试。正式启动实测因缺少 B 的加载器失败；真实题库完整校验、v2 联调、完整比赛、真实 SIGINT 和十客户端/双房间仍待验收。

从项目根目录开发调试：

```powershell
python -m unittest discover -s Codes/tests -v
```

老师 Docker 环境中的命令及挂载路径说明见上级 README。
