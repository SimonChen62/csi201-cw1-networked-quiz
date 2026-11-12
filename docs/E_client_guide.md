E 客户端接入与操作说明（2026-11-12）

本客户端入口、命令行界面和 D/E 接入回归已合入 main。C 的比赛模块已在独立分支交付，B 的题库验证/大厅仍待实现，正式服务端尚不能完成整场比赛。下面的脚本对端仅用于客户端开发，不能作为完整系统、十客户端或双房间验收证据。

最新官方配置环境中 main 54 项、C 模块 7 项分别通过，见 [验证记录](evidence/2026-11-12-official-env-validation.md)。最新分工计划的 v2 与当前客户端仍有差异，以下命令描述现有 CLI；正式联调前需完成 [协议迁移事项](progress/2026-11-12-team-progress.md)。

**代码入口与职责。** E 维护 `Codes/client.py` 和 `Codes/client_modules/cli.py`；D 维护 `connection.py` 和 `state.py`。本分支对 D 文件补充了界面接入所需的响应分类、清理和状态边界，合并前请 D 复核。实际协议字段见根目录的 D/E 接口表。

**正式客户端命令。** 在 `Codes` 目录或提交包的对应目录执行：

```bash
python3 client.py --server <server_IP> --port <port> --id <user_id> --name <display_name>
```

程序只使用 Python 3.12 标准库、标准输入输出和原生 TCP。客户端不会打开 `questions.json`。网络连接和同步请求由后台请求线程执行；主循环持续处理输入队列、主动事件和请求结果。键盘线程通过文件描述符读取输入，不在等待输入时持有 Python 缓冲输入对象的锁。正常退出、EOF 和断线会清理连接；阻塞输入线程是 daemon，不要求用户再按回车才能退出。

| 用户命令 | 用途 |
|---|---|
| `help` | 命令说明 |
| `quizzes` / `rooms` | 查看测验目录 / 可加入房间 |
| `create <quiz_id>` / `join <room_id>` | 创建 / 加入房间 |
| `players` | 请求当前成员、房主和准备状态 |
| `ready` / `ready off` | 准备 / 取消准备；由服务端确认 |
| `start` | 请求开始；权限和条件由服务端判定 |
| `answer <question_id> <A或B或C或D>` | 给明确题号提交答案，例如 `answer NET001 B` |
| `score` | 显示最近一次服务端确认的分数，不发新增协议请求 |
| `status` | 当前用户、房间和比赛状态 |
| `leave` / `quit` | 离开房间 / 退出客户端 |

答题必须带题号：用户输入期间换题时，旧题输入会被识别，不能被自动贴上新题 ID。客户端不会自己判分；提交接受仅显示确认，正确答案和分数在结算事件到达后显示。客户端显示限时数值；本版不实现每秒刷新的倒计时。

**在开发时运行脚本对端。** 以下是本地开发命令；正式评分证据仍须在老师提供的实际镜像中重跑，并记录镜像来源。脚本不会输出 `SERVER_READY`，而是 `DEMO_LISTENING`。

终端一，在 `Codes` 目录：

```bash
python3 tests/cli_demo_server.py --host 127.0.0.1 --port 5001
```

终端二，在同一目录：

```bash
python3 client.py --server 127.0.0.1 --port 5001 --id u1 --name Alice
```

依次输入：

```text
quizzes
rooms
create demo-quiz
players
ready
start
```

看到 `DEMO-Q1` 后，在五秒内输入：

```text
answer DEMO-Q1 B
```

等待结算和排行榜，然后输入 `leave`、`quit`。脚本房间中的 `demo_guest` 是模拟玩家；题目固定，只有一个客户端连接，不能用来证明 B/C 的实现或真实并发房间完成。每次重新演练需重新启动脚本服务端。

如果 Windows 上 Python 命令为 `python`，本地开发时可替换上述 `python3`。评分环境仍须支持任务书要求的 `python3 client.py ...`。

**运行测试。**

```bash
# 从仓库根目录
python3 -m unittest discover -s Codes/tests -v

# 从 Codes 目录
python3 -m unittest discover -s tests -v
```

`test_cli.py` 启动真实客户端进程和脚本 TCP 对端，检查输入、拒绝反馈、题号绑定、等待输入时结算、正常退出、EOF 与断线退出。`test_client_regressions.py` 检查错误响应、待处理请求清理、超时不重发、跨题确认、房间隔离和快照独立性。它们补充原有测试，没有替代整机验收。

| 需求/风险 | 本分支验证 |
|---|---|
| CLI 能完成规定操作入口 | 命令解析及脚本对端完整操作链 |
| 等待输入不阻塞服务器推送 | 不向 stdin 输入时仍收到结果和排行榜 |
| 业务拒绝不能伪装成网络超时 | `ROOM_NOT_FOUND` 和 `DUPLICATE_ANSWER` 原因显示 |
| 旧题答案不能提交给新题 | 命令必须带题号；晚到确认不能标记下一题已答 |
| 请求完成后释放记录 | 连续请求结束后待处理表为空 |
| UI 快照不能修改内部成绩 | 修改快照内排行榜、测验嵌套数据后内部数据不变 |
| 程序能退出 | 正常 quit、stdin EOF、远端断开均有进程级测试 |

**仍需全组完成的验收。** 正式 server/client 的登录、完整题库、真实房间、完整比赛、十个真实客户端、两个独立房间、真实服务器 Ctrl+C，以及老师镜像中的整机回归。A 的 echo 模式不支持 `hello`，当前直接连接它会返回 `UNKNOWN_COMMAND`，这是业务处理器尚未接入的结果。

**已知限制与跟进。** 改变服务器状态的请求超时后只报告“结果未知”，不自动重发；迟到回复只提示刷新状态。如何恢复权威房间状态、房主离开、运行中离开和结束后生命周期，需要 B/C/D 联调确认。GUI、网页、自动重连、数据库不在本版范围。
