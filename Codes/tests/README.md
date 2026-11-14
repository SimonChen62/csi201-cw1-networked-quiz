# 网络层、题库、比赛引擎与客户端测试

运行步骤、对接 API 和当前限制见 [Codes/README.md](../README.md)。

| 文件 | 检查/用途 |
| --- | --- |
| `server_temp_test.py` | 临时 echo 客户端；分别显示响应、错误、事件，事件不计作请求回复；不是 D/E 的正式客户端 |
| `test_protocol.py` | UTF-8/JSON 编解码、换行分帧、不完整尾部、常见坏消息与超长帧 |
| `test_server.py` | session 发送、编码失败、已关闭连接、响应与事件并发发送保持帧完整 |
| `test_dispatch.py` | 交给自定义请求处理器、事件与回复共存、指定名单广播、失败连接隔离、临时客户端分类 |
| `test_disconnect.py` | 网络失败关闭、编码失败保留连接、断线回调、重复关闭、等待回调完成和其他客户端继续工作 |
| `test_startup.py` | 参数必填/互斥、假加载器先于监听、校验失败不启动、正式启动标志；不验证 B 的真实题库 schema |
| `test_question_bank.py` | 新增 21 项：完整题库 schema、数量/长度/大小边界、UTF-8、ID 唯一性、扩展字段与文件顺序、两份真实题库、错误时不创建 socket、真实子进程加载 50 题并接受 TCP |
| `test_game_engine.py` | C 的 7 项引擎测试：不提前泄漏答案、计时/判分、重复/迟到、断线玩家排名、两房间和十名玩家状态；使用内存对象，非十个客户端进程 |
| `test_network.py` | 子进程和真实 TCP 测试；多请求、格式错误、两个客户端和十条同时建立的连接分别收到自己的回复 |
| `test_connection.py` / `test_state.py` | 当前 13 项通信、分片/合并、响应/事件、超时/断线与状态测试；包括失败 response 和 v3 字段兼容 |
| `test_client_regressions.py` | 已有 11 项 D/E 接入回归：错误匹配、pending 清理、超时、旧题确认、外房事件、快照和输入题号 |
| `test_cli.py` | 已有 3 项真实子进程/TCP 客户端检查：脚本业务流程、输入空闲时的结果/断线、EOF 退出 |
| `fake_server.py` | 测试夹具；本轮补齐拆分回复、事件与回复合并、主动断线模式；测试默认使用系统分配的空闲端口 |
| `cli_demo_server.py` | 单客户端脚本对端，含模拟第二名玩家；仅供开发，不是 B/C 的实现或多人验收证据 |

2026-11-14 全部 **84 项测试通过**（10.569 秒）：网络层 29 项、D 通信/状态 13 项、已有 D/E 接入与 CLI 14 项、C 引擎 7 项、新题库 21 项。环境为按老师提供的 Dockerfile 构建的 `csi201-cw1:verify-20261112` / Python 3.12.16；见 [本轮验证记录](../../docs/evidence/2026-11-14-question-bank-validation.md) 和 [原始输出](../../docs/evidence/2026-11-14-question-bank-unittest.txt)。

本轮首次全量检查有 2 项失败：`fake_server.py` 只回复 normal 模式，拆包/合并模式没有回复，导致登录超时。现已补齐对应行为；断线模式也改为真正关闭连接，并断言 `CONNECTION_LOST`，避免把等待超时当作断线通过。没有放宽原有拆包/事件断言。

题库检查调用真实加载器，启动测试使用真实 `server.py --questions questions_50.json`。A 的部分网络测试仍使用 `--lab-mode`，CLI 使用脚本对端，C 使用内存中的玩家/房间。另有 [实际启动与 SIGINT 记录](../../docs/evidence/2026-11-14-question-bank-startup.txt)。这些证据不证明正式登录、房间、完整比赛、十客户端双房间和所有异常关闭流程已完成。

从项目根目录开发调试：

```powershell
python -m unittest discover -s Codes/tests -v
```

老师 Docker 环境中的命令及挂载路径说明见上级 README。
