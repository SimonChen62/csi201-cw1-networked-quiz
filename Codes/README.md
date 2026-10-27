# 成员 A：从 TCP 基础逐步建立服务器

当前进度：**阶段 6，连接登记、断线清理和可控关闭**。这仍不是最终可提交的服务器。

代码由 Codex 分阶段生成，再逐段讲解；你不用手写。每一阶段都按「目标 → 代码 → 运行结果 → 读懂流程」推进。

## 现在看哪些文件

| 文件 | 用途 | 现在是否要读 |
| --- | --- | --- |
| `server.py` | A 的服务器入口，解析 JSON 请求并返回成功/错误响应 | 是 |
| `tests/server_temp_test.py` | A 自测用的临时 JSON 客户端，不是正式客户端 | 是 |
| `protocol.py` | JSON 编解码、换行分帧和 64 KiB 单消息限制 | 是 |
| `tests/test_protocol.py` | 测协议边界与错误输入 | 看不懂测试时再看 |
| `tests/test_network.py` | 自动启动服务器和临时客户端，验证真实 TCP 交互 | 由 Codex 维护 |
| `server_modules/` | B 的题库、房间模块，以及 C 的比赛模块 | 集成时再看 |
| `client_modules/` | D/E 的正式客户端模块 | 由对应成员负责 |
| `questions.json` | 题库数据 | 保留，后续接入 B 的校验 |

`Codes/Dockerfile` 和 `Codes/docker-compose.yml` 是旧骨架配置，当前教学不使用。老师提供的 `CSI201_CW1_Docker_Env` 文件夹保留原位。下面直接使用已经构建好的 `csi201-cw1:latest` 镜像，并把 Codes 挂载进去，不需要复制代码。

## 分阶段目标

1. **基础已完成：**连接、短文字收发和 socket 创建。
2. **基础已完成：**循环接收，理解发送结束和 TCP 半关闭。
3. **基础已完成：**换行分帧，在同一连接上往返多条文本消息。
4. **当前阶段：**将每行解析为 JSON 对象，编码成功/错误响应；拒绝格式错误与超过 64 KiB 的消息。
5. **基础已完成：**主线程持续 accept 并为每个客户端创建处理线程；各连接缓冲区独立。
6. **当前阶段：**登记活动连接，处理客户端 EOF/网络异常，并通过停止事件和 Ctrl+C 关闭监听与连接。
7. **消息分发：**把请求交给 B 的题库/大厅逻辑或 C 的比赛逻辑；用 A 的发送接口返回响应或传递异步事件/广播。
8. **正式启动与关闭：**支持作业要求的 `--host`、`--port`、`--questions`；让 B 完整校验题库，通过后再监听并打印 `SERVER_READY`；处理 Ctrl+C。
9. **整体验证：**在老师 Docker 环境测试 A 的网络边界；全组验证至少 10 个客户端和 2 个互不影响的房间。

每次只完成当前一个小目标，后续阶段还没有实现。

## 成员 A 的最终交付清单

下面是 A 最终负责的网络功能，不代表当前阶段已经完成。正式服务器启动命令必须是：

```bash
python3 server.py --host <server_IP> --port <port> --questions <json_path>
```

- `server.py`：解析三个启动参数；在创建监听 socket 前调用 B 的完整题库校验；仅校验通过后创建 TCP socket、绑定用户提供的端口并监听；开始监听后打印 `SERVER_READY`；持续接受新连接并为每个客户端启动处理线程。
- `protocol.py`：编码 JSON 消息为 UTF-8 换行帧；从字节流缓冲区提取所有完整消息，保留不完整尾部；兼容一条消息分多次 `recv()`、多条消息一次收到的情况。
- 每连接传输：线程循环接收、解帧、解码并把完整请求交给 B/C；处理错误 JSON、无效命令、EOF 和 socket 异常；用发送接口把响应、异步事件和业务层发起的广播送到正确客户端；用锁防止多个线程同时写乱同一个 socket。
- 网络生命周期：停止接受新连接，关闭连接 socket 和监听 socket，处理 Ctrl+C；断线时通知 B/C 清理各自拥有的用户/房间/比赛状态。A 清理网络资源，不接管 B/C 的业务状态。
- A 的证据：测试协议与 TCP 边界（拆分/合并、错误消息、多连接、断线和清理），参与老师 Docker 镜像中的完整集成测试，并撰写实际协议格式和示例供开发文档使用。

职责边界：B 负责题库文件、完整 schema 校验、用户/大厅/房间业务；C 负责比赛线程、计时、答题和评分；D/E 负责客户端。A 负责连接、消息边界、收发和分发，不重写这些业务逻辑。服务器不得在题目关闭前发送正确答案；全组需验证至少 10 个连接客户端和 2 个独立房间，A 为其提供网络并发支持。

分工依据：以《CW1_系统流程与五人任务分配计划.md》的详细分工及作业 PDF 为准。《CW1_团队公告与分工计划.md》是较早建议，其中成员 C/D/E 的职责与后续详细分工不一致；本学习路线不按那份旧建议分配。

## 第一课：先看结果

在 PowerShell 窗口 1 执行：

```powershell
docker run --rm --name cw1-a-stage1 --mount "type=bind,source=D:\Y3\csi201\cw1\Codes,target=/code" csi201-cw1:latest server.py
```

看到 `LAB_LISTENING 127.0.0.1 5000` 后，窗口停在那里是正常的：服务器在等客户端。

打开 PowerShell 窗口 2，执行：

```powershell
docker exec cw1-a-stage1 python tests/server_temp_test.py
```

这会在同一个容器里启动临时客户端，因此它能用 127.0.0.1 连接服务器，不需要端口映射。预期看到：

```text
发出请求：{'type': 'echo', 'request_id': 1, 'text': 'hello server'}
收到响应：{"type": "response", "request_id": 1, "ok": true, "data": {"text": "hello server"}}
发出请求：{'type': 'echo', 'request_id': 2, 'text': 'second message'}
收到响应：{"type": "response", "request_id": 2, "ok": true, "data": {"text": "second message"}}
```

当前多客户端服务器在客户端退出后继续监听。可以再次执行窗口 2 的命令接入一个新客户端；在窗口 1 按 Ctrl+C 才会关闭服务器，随后 `--rm` 会删除该容器。

## 第一课：代码按什么顺序执行

先只看 `server.py`。文件末尾的 `if __name__ == "__main__": main()` 表示直接运行这个文件时进入 main。main 开头的 argparse 读取运行参数；没有额外参数时，使用地址 127.0.0.1、端口 5000。

核心顺序是：

```text
socket 创建通信端点
  → bind 绑定自己的地址和端口
  → listen 开始监听
  → accept 等待并接入一个客户端
  → connection.recv 接收客户端字节
  → connection.sendall 把这些字节发回去
  → 离开 with，关闭连接和监听 socket
```

第一段先理解这三行：

```python
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.bind((args.host, args.port))
    server.listen(1)
```

- `socket.AF_INET`：使用 IPv4 地址，例如 127.0.0.1。
- `socket.SOCK_STREAM`：这里创建使用 TCP 的流式 socket。
- `as server`：把创建出的 socket 取名叫 server。
- `with`：退出这一层缩进时自动关闭 socket，省去手动 close。
- `bind((args.host, args.port))`：把这个 socket 绑定到指定地址和端口；双括号内层是 `(地址, 端口)` 元组。
- `listen(1)`：开始监听，参数是等待 accept 的连接队列长度提示，不能理解成最多只允许一个用户。本课只有一个用户，是因为只调用了一次 accept。

127.0.0.1 表示当前网络环境自身；本实验里它指同一个 Docker 容器。5000 是这个程序使用的端口，帮助系统把连接交给正确的程序。

下一段再看：

```python
connection, address = server.accept()
```

accept 在没有连接时会等待。连接到达后返回两个值：connection 是与这个客户端通信的新 socket；address 是客户端地址。server 仍是监听 socket，实际收发使用 connection。

最后的 recv 返回 bytes，不是 Python 字符串。临时客户端用 encode 把文字转成字节，服务器原样发送，客户端再用 decode 转回文字。`data!r` 让终端展示字节的表示形式，例如 `b'hello server'`。

## 第一阶段回顾

服务端当时只执行一次 `recv(1024)`，读到多少就回复多少；1024 是本次读取的最大字节数，不是一条消息的长度。即使客户端发送一句很短的话，TCP 也不承诺它一定一次到齐。固定短文字实验只用于观察基本流程。

第一阶段没有题库校验、JSON、登录、房间、比赛、多客户端或完整异常处理。故当前教学程序只打印 LAB_LISTENING，不打印作业要求的 SERVER_READY，也暂不支持最终 --questions 参数。

## 第二课：循环接收一整段字节

现在服务端在每次最多读取 1024 字节后继续读，直到客户端发送方向结束。自动测试发送 2500 个字符，确保内容需要多次 `recv()` 才能全部读完。

服务端新增的核心逻辑：

```python
data = bytearray()
while True:
    chunk = connection.recv(1024)
    if not chunk:
        break
    data.extend(chunk)
connection.sendall(data)
```

- `data` 是逐段累积收到的字节。
- `recv(1024)` 最多返回 1024 字节；网络中有更多数据时，需要下一轮再读。
- 若 `recv()` 返回 `b""`，表示对方已结束发送方向，不会再发新字节。
- 客户端调用 `shutdown(socket.SHUT_WR)` 表示“我发完了”，但仍保留连接来接收服务器回复。
- 收到发送结束信号后，服务器才把完整内容用 `sendall()` 发回。

这是“每个连接只传一段数据，以半关闭表示结束”的实验方法。正式作业中连接要维持并传多条 JSON 消息，不能靠关闭发送方向区分每条消息；后续阶段会学习换行分帧。

## 第三课：在 TCP 字节流中找消息边界

现在客户端不再关闭发送方向来表示一条消息结束。每条消息的末尾放一个换行字节 `\n`，同一连接可以一直打开并传多条消息。当前 payload 仍是普通 UTF-8 文本；下一阶段再把每行内容改成 JSON。

为什么要自己找边界？TCP 只提供有序字节流。例如客户端连续发送两条消息：

```text
first\nsecond\n
```

服务器可能分两次收到：

```text
recv 1: b"fir"
recv 2: b"st\nsecond\n"
```

也可能一次收到全部：

```text
recv 1: b"first\nsecond\n"
```

这两种情况下，消息都相同。`recv()` 的返回边界是操作系统给出的数据块边界，不是客户端的消息边界。换行符才是本阶段约定的消息边界。

`protocol.extract_messages(buffer)` 分三步工作：

1. 在缓冲区里寻找换行字节的位置。
2. 找到时，把换行前面的字节取成一条完整消息，并把这一行（包括换行）从缓冲区删除；循环查找，因此一次能取出多条。
3. 找不到换行时停止；残留的不完整字节留在缓冲区，等下一次 `recv()` 后再试。

例如第一次收到 `b"first\nsec"`：提取出 `b"first"`，保留 `b"sec"`。下次收到 `b"ond\n"` 后拼起来，提取出 `b"second"`，缓冲区归空。这个“保留尾巴”是防止把半条消息误当成完整消息的关键。

服务器针对每条连接创建自己的 `buffer`。每次收到 `chunk` 就追加到 buffer，然后把 `extract_messages(buffer)` 返回的完整消息逐条回复，并给回复重新加上 `\n`。服务器持续 `recv()`，直到客户端关闭连接。这样一次收到两条消息时不会丢掉第二条，同一条消息拆开发来也不会提前回复半条。

客户端把 `first` 与 `second` 都编码成 UTF-8，分别在末尾加换行，再用一次 `sendall()` 发出；随后持续读取回复，用同一个提取函数还原回复行。客户端没有调用 `shutdown()`，所以它在收到两次回复之前一直保持连接。这正是与上一阶段半关闭实验的区别。

自动测试验证两种边界：`test_protocol.py` 手动把数据分两次交给缓冲区，检查完整行与残留尾部；`test_network.py` 用真实 TCP 连接连续发送两条消息并确认两条回复都在连接关闭前到达。

**本阶段刻意简化：**服务器仍只接受一个客户端；消息内容是文本，还没有 JSON；没有消息长度上限、错误消息格式或请求/响应类型。这些会在 JSON 协议和并发阶段逐步补上。

## 第四课：每条消息放一个 JSON 请求

第三阶段能分出一行的边界，但行里的文字仍没有结构。现在约定每条消息是一行 JSON 对象，例如：

```json
{"type":"echo","request_id":1,"text":"你好"}
```

服务器成功时回复：

```json
{"type":"response","request_id":1,"ok":true,"data":{"text":"你好"}}
```

若 JSON 不合法、命令未知或字段错误，返回一致的错误外壳，例如：

```json
{"type":"error","request_id":null,"error":{"code":"MALFORMED_MESSAGE","message":"..."}}
```

`request_id` 是客户端给请求的编号；响应带回相同编号，客户端将来可以把响应和对应请求配对。现在测试客户端一次等待几个响应，所以编号先用于展示，之后会真正用于并发请求管理。

### 协议模块：先把字节规则集中起来

`protocol.py` 有三类职责。

```python
MAX_MESSAGE_BYTES = 64 * 1024
```

单条消息最大 64 KiB，即 65,536 字节。这个限制是团队的网络安全/资源选择，不是 TCP 自带限制。解析前就检查大小，避免某个客户端不断发送没有换行的超长内容，让缓冲区无限增长。这个阶段限制单帧长度；以后还要注意一批帧合计占用的 buffer 上限。

```python
class ProtocolError(ValueError): ...
class MessageTooLarge(ProtocolError): ...
```

这两个异常表达不同故障：一般协议错误代表内容不能按 JSON 协议解释；MessageTooLarge 表示帧长度超过限制。它们都能由服务器捕获并转换成网络错误响应。

```python
def extract_messages(buffer):
    # 在 buffer 中循环找 b"\\n"
    # 找到时取出一整行，并从 buffer 删除
    # 没找到时检查长度，留下不足一行的尾部
```

它只处理“哪里是一行”的问题，返回 bytes。它不解释 JSON、不做命令分发，因此职责很窄。

```python
def encode_message(message):
    # JSON 对象 -> UTF-8 字节 -> 末尾添加 b"\\n"

def decode_message(payload):
    # 不带换行的帧 -> UTF-8 字符串 -> JSON 对象
    # 检查解出来的值必须是 dict
```

`ensure_ascii=False` 让中文以 UTF-8 发送，而不是转写成 `\\u` 序列；`separators=(",", ":")` 去掉 JSON 里的无用空格；编码后才检查大小，因为限制单位是线上传输的字节，不是 Python 字符数。

### 服务器：接收、解释、回复

服务器循环仍沿用上一阶段的结构。每次接收字节后先追加到连接的 buffer，再让 `extract_messages` 找完整帧。对于每个帧：

1. `decode_message` 把 UTF-8 JSON 变成 Python 字典；解码失败则回 `MALFORMED_MESSAGE`。
2. 读取 `type`；不是 `echo` 时回 `UNKNOWN_COMMAND`。
3. 要求 `text` 是字符串；否则回 `INVALID_MESSAGE`。
4. 合法请求把 `text` 放进成功响应的 `data` 中，并原样带回 `request_id`。
5. `encode_message` 把响应转回 JSON 行，再由 `sendall` 发给同一个连接。

注意职责顺序：protocol 解出对象，server 根据 `type` 决定动作，protocol 再编码回复。这就是后面接 B/C 的接缝：届时把第 2 步之后的临时 echo 判断交给业务分发函数，而 TCP 收发和帧处理保持在 A。

### 临时客户端：和服务器遵守同一规则

`server_temp_test.py` 生成 `echo` 请求，使用 `encode_message` 附上换行后发送。它保持连接打开，然后循环 `recv`、提取完整回复行、`decode_message` 并以 JSON 格式打印。测试客户端和服务器共用 protocol 函数，保证线上格式相同；底层实际 TCP 流仍由真实 socket 测试覆盖。

它还能追加发送一条损坏的 `{bad json}`。服务器应回复 `MALFORMED_MESSAGE`，并继续保持连接处理前面的请求；坏帧不应该把服务器进程弄崩。

### 这一步测了什么

- `test_protocol.py` 检查中文 JSON 编码结果、JSON 往返、帧拆分/合并、错误 JSON、非对象 JSON 和超长帧。
- `test_network.py` 通过真实 TCP 连接发送两个 JSON echo 请求和一个错误帧，检查成功响应保留 `request_id`、错误帧得到结构化错误、连接正常结束。
- 全部测试在老师的 Docker 镜像里运行；当前结果 5 项通过。这仍只是 A 网络模块的小实验，距离最终服务器还有并发、业务分发、完整启动验证和关闭等阶段。

## 第五课：主线程接连接，客户端线程处理消息

上一阶段的服务器只调用一次 `accept()`，所以只能接入一个客户端。现在将工作拆成两个函数。

服务器主线程的代码：

```python
while True:
    connection, address = server.accept()
    threading.Thread(
        target=handle_client,
        args=(connection, address),
        daemon=True,
    ).start()
```

主线程只做两件事：等待新连接，以及为新连接启动处理线程。`accept()` 每成功一次，就得到一对新的 `connection` 和 `address`；监听用的 `server` socket 继续留着，等待下一个客户端。

`threading.Thread(...)` 创建一个线程对象。`target=handle_client` 表示线程启动后要调用哪个函数；`args=(connection, address)` 是传给这个函数的参数。这里必须写成带逗号的元组形式，单个元素的元组也需要逗号。最后的 `.start()` 才真正启动线程；如果只创建不 start，函数不会运行。

`daemon=True` 表示主程序结束时不等待这些教学线程完成。正式服务器还要在 Ctrl+C 时主动通知并关闭连接，不能只依赖 daemon；这一点留到关闭阶段处理。

每个线程执行同一个 `handle_client()`，但参数里的 `connection` 不同：

```python
def handle_client(connection, address):
    with connection:
        buffer = bytearray()
        while True:
            chunk = connection.recv(1024)
            if not chunk:
                break
            buffer.extend(chunk)
            # 提取、解码、生成响应、发送
```

这里的 `buffer` 是函数内部变量。每次调用 `handle_client()` 都会创建一个新的 `bytearray`，所以客户端一的半条 JSON 不会和客户端二的数据混在一起。`connection` 也是对应客户端自己的 socket；线程不会拿错回复对象。

例如两个客户端同时连接时，结构是：

```text
主线程 accept()
  ├── connection A -> handle_client(A) -> A 的 buffer
  └── connection B -> handle_client(B) -> B 的 buffer
```

客户端 A 卡在 `recv()` 时，主线程仍可以继续 `accept()` 客户端 B，B 的线程也可以独立收发。此时已经具备“多个连接同时存在”的网络基础，但还没有房间或用户业务。

### `send_response()` 为什么单独存在

所有响应先通过这个函数：

```python
def send_response(connection, response):
    try:
        payload = encode_message(response)
    except ProtocolError as exc:
        print(f"无法编码响应：{exc}", flush=True)
        return False

    try:
        connection.sendall(payload)
    except OSError as exc:
        print(f"发送响应失败：{exc}", flush=True)
        return False
    return True
```

第一段 `try` 专门接 `encode_message()` 的错误：响应字典如果包含无法转换为 JSON 的对象，或者编码后的响应太大，`encode_message()` 就会 `raise`；这里接住后返回 `False`。第二段 `try` 专门接 socket 发送错误，例如客户端已经断开导致的 `BrokenPipeError`。这两个错误来源不同，所以分成两段。

调用者这样使用返回值：

```python
if not send_response(connection, response):
    return
```

发送成功返回 `True`，线程继续处理；编码或发送失败返回 `False`，`return` 离开 `handle_client()`，随后 `with connection` 自动关闭 socket。这样异常不会无控制地冲出线程函数，也不会继续向已经坏掉的连接发送数据。

### 当前多客户端测试

`test_network.py` 启动一个服务器，再启动两个独立临时客户端；每个客户端发送自己的文字，并检查响应中的 `data.text` 没有串到另一个客户端。当前本机 8 项测试通过；Docker Desktop 当前未运行，所以这一次的证据是本机 Python 3.12，重新启动 Docker 后还要再执行官方镜像测试。

本阶段仍缺少发送锁、服务器停止事件、Ctrl+C、连接表和业务分发。发送锁会在服务器开始主动广播时加入；现在每个线程只向自己的连接发送，暂时没有共享发送对象。

## 第六课：记录活动连接并安全关闭

多客户端已经能运行，但之前主程序的 `while True` 没有停止条件。现在 `Server` 对象拥有服务器生命周期。

```python
class Server:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.listener = None
        self.stop_event = threading.Event()
        self.connections = set()
        self.connections_lock = threading.Lock()
```

- `listener` 保存监听 socket，关闭时需要它。
- `stop_event` 是线程安全的停止开关。没有设置时，服务器继续工作；设置后，主循环和客户端循环都会逐步退出。
- `connections` 保存当前活动客户端 socket。
- 多个客户端线程会同时读写这个集合，所以用 `connections_lock` 保护它。修改共享集合时先拿锁，完成后自动释放。

主循环的关键部分：

```python
while not self.stop_event.is_set():
    try:
        connection, address = listener.accept()
    except socket.timeout:
        continue
    except OSError:
        break
```

监听 socket 设置了 `settimeout(0.5)`。这样 `accept()` 最多等待半秒，超时后重新检查 `stop_event`；否则它可能永远卡在 `accept()`，看不到 Ctrl+C 设置的停止状态。关闭 listener 时，阻塞中的 `accept()` 可能抛出 `OSError`，这里把它视为关闭过程并退出循环。

接入连接后先登记：

```python
with self.connections_lock:
    self.connections.add(connection)
```

登记必须发生在线程启动前，这样如果马上 Ctrl+C，关闭流程也能找到这个 socket。客户端线程结束时，在 `finally` 中执行：

```python
with self.connections_lock:
    self.connections.discard(connection)
```

`discard()` 在元素已被关闭流程提前移除时不会报错；相比 `remove()` 更适合清理代码。

`shutdown()` 的步骤是：

1. 设置 `stop_event`，让主循环不再接受新连接。
2. 关闭 `listener`，唤醒可能正在等待的 `accept()`。
3. 在锁内复制当前连接列表。复制后马上释放锁，避免关闭 socket 时长期占用集合锁。
4. 对每个连接调用 `shutdown(SHUT_RDWR)`，唤醒正在 `recv()` 的客户端线程。
5. 再调用 `close()` 释放文件描述符。

```python
with self.connections_lock:
    connections = list(self.connections)

for connection in connections:
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        connection.close()
    except OSError:
        pass
```

这里的两个 `try` 是正常的：关闭过程中一个 socket 可能已经被客户端线程或操作系统关闭，所以 `shutdown()` 或 `close()` 报 `OSError` 时，目标已经达到，不应让整个服务器崩溃。

程序入口把系统的 Ctrl+C 交给 `server.shutdown`：

```python
server = Server(args.host, args.port)
signal.signal(signal.SIGINT, server.shutdown)
try:
    server.serve_forever()
finally:
    server.shutdown()
```

第一次调用来自 Ctrl+C；如果没有 Ctrl+C，`finally` 在其他退出路径执行。`shutdown()` 开头检查 `stop_event`，所以重复调用是安全的。这种“正常运行时处理信号，离开主循环后再兜底清理”的结构会保留到最终服务器。

当前本机 8 项测试仍通过；Docker Desktop 未运行，官方镜像验证待 Docker 恢复后执行。下一阶段会把 `questions` 启动参数和 B 的题库验证接入，但在此之前还会补发送锁和正式的消息分发接口。

## 自动检查（由 Codex 执行）

```powershell
docker run --rm --mount "type=bind,source=D:\Y3\csi201\cw1\Codes,target=/code" csi201-cw1:latest -m unittest discover -s tests -v
```

自动检查使用老师 Docker 镜像。协议单元测试检查拆分/合并后的消息边界；网络集成测试检查同一条 TCP 连接上两条消息的完整往返。它们不代表完整作业测试。

Python 官方参考：[Socket Programming HOWTO](https://docs.python.org/3.12/howto/sockets.html)、[socket 模块](https://docs.python.org/3.12/library/socket.html)。先理解本课，再按需读英文参考。任何一行不懂都可以直接指出，我们停在那一行解释。
