# 测试说明（2026-11-15）

在课程容器 Codes 目录执行 python3 -B -m unittest discover -s tests -v。本轮 146 项测试通过，用时 36.990 秒。详细运行命令见 [README.md](../README.md)。

| 范围 | 文件 | 证据性质 |
| --- | --- | --- |
| 网络层 29 项 | test_protocol/server/dispatch/disconnect/startup/network.py | 编解码、分帧、发送、路由、关闭和真实 TCP；部分使用 lab-mode |
| D 通信/状态 13 项 | test_connection.py、test_state.py | 请求、事件、分片、超时、状态隔离 |
| 已有 D/E 14 项 | test_client_regressions.py、test_cli.py | 客户端回归、真实 CLI 连接脚本对端；不是整机验收 |
| B 题库 31 项 | test_question_bank.py | typed 题库、schema、数量/类型/范围、公开目录 |
| B 大厅 39 项 | test_lobby.py | 身份、房间、ready/host、退出；使用 StubEngine |
| C 引擎 7 项 | test_game_engine.py | 计时、计分、拒绝重复/迟到、排名与状态隔离 |
| 整合回归 8 项 | test_integration_regressions.py | 加载边界、校验先于 socket、开赛并发窗口、发送失败和计时器停止 |
| 正式配对系统 5 项 | test_paired_system.py | 真实 server.py/client.py 子进程，详见下方 |

正式配对验收的五个场景：

1. 默认原题库：两位真实 CLI 玩家完整比赛，检查重复登录、host/ready 门槛、重复答案、分数、排名和正常退出。
2. 老师 questions_50.json：正式服务器加载，真实客户端登录并列出 5 套各 10 题。
3. 十个真实 CLI 客户端：两房间完整比赛，题目、结果和成绩隔离，全部客户端正常退出。
4. 另一次十客户端：一人意外终止后，两个房间的其余玩家继续比赛。
5. 正式服务器配合诊断 TCP 对端：格式错误、NaN、嵌套坏 JSON、未知命令、答案保密、5 秒权威截止、缺答/旧题拒绝、超长帧隔离，以及活跃比赛中 SIGINT；真实 CLI 观察者自动退出。

第三/四/五项使用临时合法题库，将原题库的限时改成规范允许的 5 秒；原题库文件不改。第五项的恶意报文由 WirePeer 注入，不计作十客户端证据。process_support.py 只负责测试进程的 stdin/stdout、等待及清理。

设置 QUIZ_EVIDENCE_DIR 可保存每个场景的服务器/客户端原始日志和实际输入题库。清理时记录实际进程退出码；中途被测试主动 kill 的客户端保留非零退出记录，其他客户端和服务器必须正常退出。

人工视频和组员实际多终端操作仍需完成。自动终端输入不能替代每位成员解释自己的实现。
