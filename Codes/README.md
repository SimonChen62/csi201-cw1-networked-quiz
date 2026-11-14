# 成员 A：完成内容、API 与组员接入说明

本文说明 A 提供的服务端网络层、各角色如何调用，以及当前尚未完成的联调事项。以当前 `server.py`、`protocol.py` 为准；分工依据是项目根目录的《CW1_系统流程与五人分工计划.md》。

**当前是供全组接入的开发版本（2026-11-14）。** A 的网络层、C 的比赛引擎/计分、D 的客户端通信/状态，以及 E 的客户端入口和 CLI 已有实现。本分支在 `main@ca447f0` 上补齐题库加载与完整校验，加入老师提供的 50 题文件。正式入口现可加载题库并输出 `SERVER_READY`；`lobby.py` 仍为空壳，登录/房间/比赛业务尚未装配。客户端试用见 [操作说明](../docs/E_client_guide.md) 和 [D/E 接口表](../CW1_D与E接口确定表.md)。

2026-11-14 在按老师提供的 Dockerfile 构建的镜像（本机标签 `csi201-cw1:verify-20261112`，Python 3.12.16）中，**84 项测试全部通过**，其中新增题库测试 21 项。另已实测真实入口加载 50 题、TCP echo、SIGINT 退出及错误题库拒绝；`hello` 仍返回 `UNKNOWN_COMMAND`。见 [本轮进展和环境证据](../docs/evidence/2026-11-14-question-bank-validation.md)、[测试原始输出](../docs/evidence/2026-11-14-question-bank-unittest.txt) 和 [启动原始输出](../docs/evidence/2026-11-14-question-bank-startup.txt)。这些结果不代表完整比赛或十客户端双房间验收完成。

## 1. A 已实现的内容

| 内容 | 当前实现 |
| --- | --- |
| TCP 接入 | 原生 `socket`，绑定指定地址和端口，持续 `accept()` |
| 多客户端 | 每个连接一个接收线程，分别保存接收缓冲区；已有 10 条同时连接的真实 TCP 测试 |
| 消息边界 | UTF-8 JSON，每条消息以换行结束；支持拆分、合并和不完整尾部保留 |
| 消息大小 | JSON 内容最多 64 KiB，不含末尾换行 |
| 发送 | `ClientSession.send()` 编码并发送；每连接独立发送锁，防止回复和事件交错写入 |
| 请求交接 | 已解码的字典与来源 session 一起传给可替换的 `request_handler` |
| 事件与广播 | 单连接 `send_event()`；`broadcast_event()` 向业务提供的名单逐个发送 |
| 错误路径 | 常见坏 JSON、非对象消息和超长帧处理；发送编码错误与网络错误分开处理 |
| 断线清理 | 关闭 socket、移除活动连接，通过 `on_disconnect` 通知业务层 |
| 停止与线程收尾 | Ctrl+C 设置停止标志，主流程关闭连接并 `join()` 已记录的客户端线程 |
| 启动交接 | `--host`、`--port` 必填；正式模式用 `--questions`，在监听前调用题库加载接口 |

A 不负责题库完整 schema 校验、登录和房间业务、计时判分、排行榜或正式客户端。下面示例中的业务命令、事件名和数据字段，需要由对应成员与客户端协商，不表示这些业务已经实现。

## 2. 各角色从哪里接入

| 角色 | 自己负责 | 与 A 对接的位置 |
| --- | --- | --- |
| B | 题库校验、用户、房间、大厅、ready、host | 提供 `load_question_bank(path)`；业务请求通过 `request_handler(session, message)` 交接；断线时清理身份和房间 |
| C | 比赛线程、发题、计时、答案、分数和排行榜 | 请求处理器把比赛命令交给 C；C 用 `send_event()` / `broadcast_event()` 发布公开数据；断线回调更新比赛状态 |
| D | 正式客户端网络、接收线程、客户端状态 | 复用 `protocol.py`；区分 `response` 和 `event`，用 `request_id` 匹配回复，用 `ok` 判断成功/失败 |
| E | CLI 和整体组装 | 通过 D 的接口收发、显示信息；在服务端入口把 B/C 的处理函数传入 `Server`，保留校验后监听和关闭流程 |

`Server.sessions` 是 **ClientSession 对象的集合**，用于网络管理，不是按用户 ID 索引的身份表。B 应自行维护用户 ID、显示名、所在房间与连接对象的对应关系。当前 `ClientSession` 只有连接、地址、发送锁和关闭状态，没有预置 `user_id`、`name`、`current_room_id` 字段。

## 3. 公共消息格式（D/E 与 B/C 共用）

编码为 UTF-8，每条 JSON 对象后加一个 `\n`。不要假定一次 `recv()` 就等于一条消息。`request_id` 在同一连接的待处理请求中应能唯一匹配；不同连接可以使用相同编号。

建议全组统一使用递增整数或非空字符串作为 `request_id`。当前 A 只通过 `message.get("request_id")` 取值，并不强制编号的类型或必填性；正式命令的字段验证由业务处理器补充，D/E 按约定发送。

| 类别 | 格式示例 | 处理方式 |
| --- | --- | --- |
| 当前可用请求 | `{"type":"echo","request_id":1,"text":"hello"}` | 默认服务器只实现此教学命令 |
| 成功回复 | `{"type":"response","request_id":1,"ok":true,"data":{"text":"hello"}}` | 对应一条请求 |
| 错误回复 | `{"type":"response","request_id":1,"ok":false,"error":{"code":"UNKNOWN_COMMAND","message":"unknown"}}` | 对应失败请求；无法识别请求编号时为 `null` |
| 主动事件 | `{"type":"event","event":"room_updated","data":{"room_id":"R1"}}` | 不带请求编号，不计作某次请求的回复 |

`hello`、`list_quizzes`、`join_room`、`answer`、`question_open` 等是待业务层接入的名称。默认处理器遇到非 `echo` 命令会返回 `UNKNOWN_COMMAND`；上表的 `room_updated` 用于说明事件封装。

`failure_response(request_id, code, message)` 在 `server.py` 中，返回上述错误字典，不发送消息。`code` 和 `message` 建议使用字符串；请求编号无法可靠取得时传 `None`。

当前网络层使用 `MALFORMED_MESSAGE`、`MESSAGE_TOO_LARGE`，默认 echo 处理器使用 `UNKNOWN_COMMAND`、`INVALID_MESSAGE`。回复编码失败会尝试发送编号为 `null` 的 `INTERNAL_ERROR`。业务错误码仍需 B/C 与 D/E 统一；D 对编号为 `null` 的错误应显示或记录，不能随意匹配到某条待处理请求。

## 4. 题库加载接口（本分支已实现，供 B/C 接入）

E 按本轮补齐要求实现 `server_modules/question_bank.py`；B 后续维护题库与大厅接口，C 直接使用已验证的题目列表：

```python
from server_modules.question_bank import load_question_bank

bank = load_question_bank("questions_50.json")
quizzes = bank["quizzes"]  # 保持文件顺序；每项含 quiz_id/title/description/questions
questions = quizzes[0]["questions"]  # 含正确答案，只能保留在服务端
```

| 项目 | 当前行为 |
| --- | --- |
| 输入 `path` | `str` 或 `pathlib.Path`，来自启动参数 `--questions` |
| 成功返回 | 顶层 `dict`：`schema_version`、`quizzes`，保留数组顺序及额外成员；A 保存为 `server.question_bank` |
| 失败 | 文件访问错误抛 `OSError`；编码、JSON、字段问题抛 `ValueError`，指出文件或字段位置 |
| 文件 | 非空 UTF-8 JSON，接受开头的 BOM；上限按 1,048,576 字节解释，读取量有上限 |
| 顶层 | 对象；`schema_version` 为整数 1；`quizzes` 为 1～20 项数组 |
| 每套测验 | ID 为 1～32 个 ASCII 字母、数字、下划线或短横线，测验 ID 唯一；标题 1～100 字符，描述 0～300 字符；5～50 题 |
| 每题 | 题目 ID 在整份文件唯一、格式同测验 ID；文本 1～500 字符；选项键恰好 A/B/C/D，每项 1～200 字符；答案 A/B/C/D |
| 数值 | `time_limit` 为整数 5～60，`points` 为整数 1～1000；布尔值和浮点数不作为整数 |
| 文本与扩展 | 标题、描述、题目使用可打印字符，必填文本不能全为空白；除 `options` 外允许额外成员 |
| 启动顺序 | 完整校验全部测验/题目后才创建 `Server`、绑定监听并打印 `SERVER_READY`；失败退出码 1，不创建 socket |

仓库保留原有 `questions.json`（2 套 × 5 题），新增 `questions_50.json`（5 套 × 10 题），后者与老师提供的文件字节一致；通过 `--questions` 选择。加载器接受规范允许的单套测验；“最终提交至少 2 套”是提交材料要求，不能因此拒绝合法的单套替换题库。

**只有服务器读取题库。** 不把完整 `bank`、`quiz` 或题目对象直接发给客户端。大厅目录仅构造 `quiz_id/title/description/question_count` 等公开字段；发题时排除 `answer`，关题后才能揭晓。加载器不实现这些业务消息，仍需 B/C 按第 5 节接入处理器。

## 5. B/C：请求处理接口

创建服务器时传入统一处理函数：

```python
Server(host, port, request_handler=None, on_disconnect=None, question_bank=None)
```

| 参数 | 类型及含义 |
| --- | --- |
| `host` | `str`，服务端绑定地址 |
| `port` | `int`，服务端绑定端口 |
| `request_handler` | 可调用对象，接收 `(session, message)`；省略时使用内置 echo 处理器 |
| `on_disconnect` | 可调用对象，接收 `(session)`；省略时不执行业务清理 |
| `question_bank` | B 验证后的对象；传入非 `None` 对象时监听成功输出 `SERVER_READY`，否则输出 `LAB_LISTENING` |

`request_handler(session, message)` 的约定：

- `session` 是来源连接的 `ClientSession`，用于关联身份、获取地址或发送主动事件。
- `message` 是解码后的 Python `dict`。A 已处理 TCP 分帧与 JSON 解码，不需要再 `recv()` 或 `json.loads()`。
- 返回一个成功或错误回复字典。A 随后调用 `session.send(response)` 发送；**处理器不要再发送同一条普通回复**，否则客户端会收到两份。
- 当前接口不支持通过返回 `None` 表示“我已自行回复”。每次调用都应返回一个合法回复对象。
- 成功回复至少按第 3 节提供 `type`、`request_id`、`ok`、`data`；错误回复也使用 `type=response`，提供 `request_id`、`ok=false` 和含 `code/message` 的 `error`。A 不会自动补齐或检查业务回复结构，能 JSON 编码也不代表字段正确。
- 函数在该客户端的接收线程中运行；不同客户端会并发调用它。共享用户/房间状态由 B/C 使用自己的锁保护。
- `hello`、大厅命令和比赛命令的路由由这个统一处理函数组织，不是分别给 `Server` 传两个 request handler。
- 业务预期错误应返回 `failure_response(...)`；当前 `process_frame()` 不会统一捕获业务函数抛出的任意异常，异常会使该客户端线程进入清理流程。
- 启动比赛时创建/通知 C 的比赛线程后尽快返回，不要让接收线程等待整场比赛，否则此连接无法继续处理答题请求。

### 可运行的回调接入示例

下面只演示 API 装配，新增 `ping` 处理并保留 echo；没有实现用户、房间或比赛。可保存为 `Codes/integration_demo.py` 再运行，该文件目前未随本文新增。

```python
import signal

from server import Server


def route_request(session, message):
    if message.get("type") == "ping":
        return {
            "type": "response",
            "request_id": message.get("request_id"),
            "ok": True,
            "data": {"message": "pong"},
        }
    return Server.handle_request(session, message)


def player_disconnected(session):
    print(f"业务收到断线通知：{session.address}", flush=True)
    # 接入 B 的身份/房间清理，以及 C 的比赛玩家状态更新。


if __name__ == "__main__":
    server = Server(
        "127.0.0.1",
        5000,
        request_handler=route_request,
        on_disconnect=player_disconnected,
    )
    signal.signal(signal.SIGINT, server.request_shutdown)
    try:
        server.serve_forever()
    finally:
        server.shutdown()
```

此示例未加载题库，因此是网络联调示例，输出 `LAB_LISTENING`。保存后可以用现有临时客户端测试 echo，并在它退出时看到业务回调日志。

**正式接入位置：**当前 `server.py` 的 `main()` 已会调用题库加载器，但仍只用 `Server(args.host, args.port, question_bank=question_bank)` 创建服务器。仅在 B/C 文件中定义函数不会自动接入；E/A 需要在该创建语句中显式传入实际的 `request_handler` 和 `on_disconnect`，同时让业务处理器获得 B 的题库对象。保留原有参数解析、题库失败退出和 `try/finally` 关闭流程，按作业命令启动。

## 6. B/C：发送事件与房间广播

### 单连接发送

| 函数 | 参数 | 返回及用途 |
| --- | --- | --- |
| `session.send(message)` | JSON 可编码的消息字典 | `bool`；发送完整消息，通常由 A 用于普通回复 |
| `session.send_event(event, data)` | `event: str` 为事件名；`data` 建议为可 JSON 编码的字典 | `bool`；自动包装为 `type=event`，用于主动通知 |
| `session.close()` | 无 | 无返回值；重复调用可安全返回，关闭读写及 socket；不要直接修改 A 的连接集合 |
| `server.broadcast_event(targets, event, data)` | `targets` 为稳定的 session 名单；其余同上 | 返回发送失败的 session 列表，全部成功返回 `[]` |

业务代码拿到目标 session 后可发送：

```python
# 片段：session 是业务层保存的目标连接。
sent = session.send_event("room_updated", {"room_id": "R1"})
```

`send()` 和 `send_event()` 都经过每连接发送锁；B/C 不要直接使用 `session.connection.sendall()` 绕过它。成功表示 `sendall()` 完成，不表示客户端业务层已经读取或确认。

### 只给本房间广播

```python
# 片段：room_lock 和 room_sessions 由 B/C 的房间状态持有。
with room_lock:
    targets = list(room_sessions)
    data = {"room_id": room_id}

# 已释放房间锁，才开始网络发送。
failed = server.broadcast_event(targets, "room_updated", data)
```

`room_sessions` 应当保存此房间的 `ClientSession`，不是用户 ID 字符串。不要把全体 `server.sessions` 当作某个房间的名单。`room_lock`、`room_sessions`、`room_id` 都是业务层示意变量，A 没有提供这些房间字段。

C 组装 `question_open` 数据时，只发送公开题目、选项等；正确答案必须等题目关闭后再加入事件。A 的发送函数不会自动过滤答案。传入的数据应当是已构造好的稳定快照，广播期间不要再由其他线程修改；也不要在持有房间锁或 A 的集合锁时发送网络消息。

### 失败名单如何处理

- 编码失败：`send()` 记录错误并返回 `False`，保留连接。这通常是事件数据不能 JSON 编码或超过大小限制，业务层需修正数据。
- 网络发送错误：`send()` 关闭 session 并返回 `False`；接收线程退出后统一移除连接、调用 `on_disconnect`。
- 已关闭的 session：返回 `False`。`session.closed.is_set()` 为 True 表示正在关闭或已关闭。
- 因此 `failed` 是发送失败报告，可能包含编码问题，**不能把名单中的每个人都认定为断线玩家**。无需再逐个关闭或重复清理用户；业务清理统一交给断线回调。
- 当前广播是顺序发送，慢读者仍可能阻塞本次广播。发送锁只保证帧不交错，不保证多个线程之间的业务发送先后顺序。

## 7. B/C：断线回调与生命周期

`on_disconnect(session)` 在 A 关闭 socket、从活动连接集合移除 session 后，由该连接的接收线程调用。A 不持有 `sessions_lock` 执行业务回调；返回值被忽略。

B 根据自己的映射删除用户、房间成员并处理 host；C 按比赛规则更新活动玩家、答案或缺席状态。不要在回调中再次启动整台服务器的 `shutdown()`；回调应尽快完成，尤其不能无限等待比赛线程或客户端输入。

A 对已登记的连接执行一次回调；业务侧仍应容忍玩家已主动离开房间等情况。回调抛出的 `Exception` 会被记录，网络连接已移除，但业务清理失败不会自动重试。

| 生命周期函数 | 调用方及作用 |
| --- | --- |
| `server.serve_forever()` | 服务端主线程；创建监听 socket，接入连接并开启处理线程；阻塞运行 |
| `server.request_shutdown(*_)` | SIGINT 处理函数；只设置 `stop_event`，不执行完整关闭 |
| `server.shutdown()` | 主线程从监听循环退出后的 `finally`；关闭监听和连接，等待已记录的客户端线程 |
| `server.start_client(session)`、`handle_client(session)`、`process_frame(session, frame)` | A 的内部接入/接收路径；B/C 通常不用直接调用 |

当前 `shutdown()` 会等待客户端线程与回调；回调若永久阻塞，关闭也可能一直等待。C 自己创建的 GameThread 不在 A 的 `client_threads` 集合中，仍需 C 提供停止和等待机制。当前也尚未自动发送 `server_shutdown` 事件；D 应处理 EOF/网络异常，正式关闭通知和比赛线程停止需联调补齐。

## 8. D/E：协议函数与客户端使用方法

`protocol.py` 可在客户端进程中导入，不会读取题库或启动服务器。

| 函数/对象 | 输入 | 输出/行为 |
| --- | --- | --- |
| `encode_message(message)` | 消息 `dict` | UTF-8 JSON 的 `bytes`，已包含末尾 `b"\n"`；不要重复加换行 |
| `extract_messages(buffer)` | 此连接自己的 `bytearray` | 返回完整帧 `list[bytes]`，已去掉换行；原地删除已取出内容，保留不完整尾部 |
| `decode_message(payload)` | 单帧 `bytes` | 返回 Python `dict`，非对象 JSON 会被拒绝 |
| `ProtocolError` | 协议异常类，继承 `ValueError` | 编码/解码的预期错误可捕获此类 |
| `MessageTooLarge` | 继承 `ProtocolError` | 单帧内容超过 64 KiB |

客户端发送片段：

```python
# connection 为 D 已建立的 socket。
from protocol import encode_message

connection.sendall(encode_message({
    "type": "echo", "request_id": 1, "text": "hello",
}))
```

客户端接收顺序：`recv()` → 加入本连接 `bytearray` → `extract_messages()` → 对每帧 `decode_message()`。只有一个 reader thread 读取同一 socket；不要在用户发起每次请求时再开一个接收者与它竞争。

如果 D 的多个线程都可能发送请求，也应在客户端为该 socket 提供一把发送锁，保护一次完整的 `sendall(encode_message(request))`。`protocol.py` 只编解码，没有内置发送锁；服务端的 `session.send_lock` 不保护客户端进程的写入。

D 按 `message["type"]` 区分回复与事件：`response` 用 `request_id` 匹配待处理请求，再检查 `ok`；`event` 按 `event` 字段更新状态并通知 E。事件不能算作某条请求的回复。`recv()` 返回空 bytes 时处理服务器关闭。E 通过 D 的客户端接口显示菜单、题目和结果，不能调用服务端进程中的 `session.send_event()`。

`tests/server_temp_test.py` 只发 echo、显示消息、等预期回复数量后退出，不是正式客户端，也没有长期事件循环或完整请求编号匹配表。

## 9. 当前运行与测试

### 本机快速检查（开发调试）

从项目根目录开启两个 PowerShell 窗口。窗口一：

```powershell
python Codes/server.py --host 127.0.0.1 --port 5000 --lab-mode
```

窗口二：

```powershell
python Codes/tests/server_temp_test.py --message "hello" --message "second" --send-malformed
```

预期两条成功回复和一条 `MALFORMED_MESSAGE`；客户端退出后服务器仍监听，可再连一次。在服务端窗口按 Ctrl+C 请求关闭。

### 老师 Docker 环境

本轮使用老师提供的 Dockerfile 构建镜像，本机标签为 `csi201-cw1:verify-20261112`，入口为 Python。组员先在自己的老师环境目录构建镜像，并将以下标签换成自己的实际标签；它不是公共镜像下载地址。来源、文件校验值及镜像 ID 见 [环境记录](../docs/evidence/2026-11-14-question-bank-validation.md)。

先在 PowerShell 进入本仓库的 `Codes` 文件夹。窗口一加载 50 题题库：

```powershell
$codePath = (Get-Location).Path
docker run --rm -it --name cw1-bank-check --mount "type=bind,source=$codePath,target=/code,readonly" csi201-cw1:verify-20261112 server.py --host 127.0.0.1 --port 5000 --questions questions_50.json
```

窗口二：

```powershell
docker exec cw1-bank-check python tests/server_temp_test.py --message "hello" --message "second" --send-malformed
```

这两个进程运行在同一容器，用容器内回环地址通信，不需要端口映射。窗口二只验证 echo 和坏消息，不代表登录/比赛可用；窗口一显示 `SERVER_READY` 后可按 Ctrl+C 退出。镜像以 Python 为 ENTRYPOINT，不要在 `docker run` 的镜像名后重复加 `python`。

自动测试：

```powershell
$codePath = (Get-Location).Path
docker run --rm --network none --env PYTHONPYCACHEPREFIX=/tmp/test-pycache --mount "type=bind,source=$codePath,target=/code,readonly" csi201-cw1:verify-20261112 -X utf8 -B -m unittest discover -s tests -v
```

本机替代检查为 `python -m unittest discover -s Codes/tests -v`。测试内容与文件对应见 [tests/README.md](tests/README.md)。本机测试通过不能替代老师 Docker 中的验收证据；10 条 echo 连接测试也不证明两个真实比赛房间的隔离。

### 已验证的正式启动

在容器的 `/code` 或提交目录中运行：

```bash
python3 server.py --host <server_IP> --port <port> --questions <json_path>
```

例如：`python3 server.py --host 127.0.0.1 --port 5000 --questions questions_50.json`。现在合法题库会通过完整校验并监听；非法题库打印诊断、退出码为 1，不监听。`--lab-mode` 与 `--questions` 互斥。默认处理器仍仅提供 echo，`hello` 返回 `UNKNOWN_COMMAND`；下一步按第 5 节装配 B/C 业务回调并对齐客户端协议。

## 10. 尚待完成的工作

| 工作 | 负责/协作 |
| --- | --- |
| 确认已实现的题库对象接口，构造不泄漏题目/答案的公共目录 | B/C，E 已补齐加载器和验证 |
| 统一请求路由、登录/房间/比赛处理与断线回调 | B/C，A/E 完成装配，D/E 同步消息字段 |
| 慢连接的发送限制、关闭等待边界和停止比赛线程 | A/C，并与业务回调联调 |
| 特殊 JSON 输入和并发关闭的边界加固 | A；当前测试未覆盖所有情况 |
| 将已有客户端与 CLI 接入正式业务，完成关闭流程联调 | D/E，与 A/B/C 联调 |
| 老师 Docker 中真实 Ctrl+C、10 个正式客户端、两个独立比赛房间 | 全组；保留实际输出和证据 |
| 开发文档中的协议、并发、关闭设计与测试记录 | A 提供网络部分，全组统一汇总 |
