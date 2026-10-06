# CSI201 CW1 系统流程与五人任务分配

## 一、系统流程故事

### 第一幕：服务端苏醒与内存初始化

考官运行：

```bash
python3 server.py --host <server_IP> --port <port> --questions <json_path>
```

服务端依次：

1. 使用 `argparse` 解析 host、port 和题库路径；
2. 使用 `json` 读取 `questions.json`；
3. 检查文件存在、非空且不超过 1 MB；
4. 检查 quiz 数量、题目数量、ID 唯一性；
5. 检查选项严格为 `A/B/C/D`；
6. 检查 `answer`、`time_limit` 和 `points`；
7. 验证通过后，在内存中创建只由服务端使用的 `question_bank`；
8. 使用 `socket` 创建、绑定并监听 TCP 端口；
9. 开始接受连接；
10. 输出 `SERVER_READY`。

如果题库验证失败：

- 打印错误；
- 返回非零退出状态；
- 不监听端口；
- 不接受客户端。

此时服务端内存中主要有：

```text
question_bank
sessions = {}
active_rooms = {}
shutdown_event
listen_socket
```

正确答案保存在服务端的 `question_bank` 中。服务端发送 quiz 列表或题目时，必须主动构造不含答案的数据，不能把完整题目对象直接发给客户端。

### 第二幕：客户端连接与会话建立

张三运行：

```bash
python3 client.py --server <server_IP> --port <port> --id zhangsan123 --name ZhangSan
```

客户端：

1. 使用 `argparse` 解析参数；
2. 使用 `socket.create_connection()` 连接服务器；
3. 发送 `hello`；
4. 启动接收线程；
5. 等待服务器确认。

服务器收到连接后：

1. `accept()` 得到客户端 socket；
2. 创建一个 `ClientSession`；
3. 为该连接创建客户端处理线程；
4. 线程调用 `recv()`；
5. 把字节放入该会话的 `recv_buffer`；
6. 提取完整 JSON 消息；
7. 把消息交给命令处理代码。

一个会话对象大致包含：

```text
ClientSession
├── user_id
├── display_name
├── socket
├── recv_buffer
├── send_lock
├── current_room_id
└── connected
```

如果 `user_id` 已经存在于活动会话中，服务器返回重复 ID 错误并关闭新连接。

TCP 是连续字节流，不保证一次 `recv()` 就是一条消息：

```text
一条 JSON 可能被拆成两次 recv()
两条 JSON 也可能被一次 recv() 一起读到
```

本组使用一行一个 JSON 的方式：

```text
recv()
  -> bytes 加入 recv_buffer
  -> 查找换行符 \n
  -> 提取完整一行
  -> UTF-8 解码
  -> json.loads()
  -> 处理完整指令
  -> 不完整的剩余 bytes 留在 buffer
```

### 第三幕：创建房间与内存隔离

张三请求 quiz 列表。服务器只返回：

```text
quiz_id
title
description
question_count
```

不会提前返回：

```text
question text
options
answer
```

张三选择《网络基础》并创建房间。服务器在 `active_rooms` 中创建：

```text
Room_001
├── quiz_id
├── host_user_id
├── players
├── phase = WAITING
├── question_index = 0
├── deadline = None
├── answers = {}
├── scores
├── room_lock
└── game_thread = None
```

李四创建 `Room_002` 后，服务器创建另一份独立的房间对象。

两个房间互不影响，是因为每个房间都有自己的：

- 玩家列表；
- 分数；
- 当前题目索引；
- 截止时间；
- 答案记录；
- 锁；
- 比赛线程。

### 第四幕：同步与异步交织的答题比赛

房间状态：

```text
WAITING -> RUNNING -> FINISHED
```

本组规则：

- 至少两名玩家才能开始；
- 所有玩家都必须 ready；
- 只有房主可以开始；
- 比赛开始后不能加入新玩家；
- 比赛开始后不能更换 quiz。

房主开始后：

1. 在房间锁内将 `phase` 改为 `RUNNING`；
2. 创建该房间的 `GameThread`；
3. `GameThread` 独立负责这个房间的题目循环。

服务器读取当前题目：

```text
question_id
text
options
answer
time_limit
points
```

但发送给客户端的内容只能是：

```text
question_id
text
options
time_limit
points
```

正确答案继续留在服务端内存中。

服务端使用：

```python
deadline = time.monotonic() + time_limit
```

服务端的 deadline 是判断答案是否迟到的权威标准。客户端的倒计时只能作为提示。

客户端分为两个逻辑部分：

```text
主线程
├── 显示菜单
├── 读取用户输入
└── 发送请求

接收线程
├── recv()
├── 拆分 JSON
├── 处理响应
└── 处理服务器主动事件
```

张三输入 B 后发送答案。服务器在 Room 001 的 `room_lock` 内检查：

1. 玩家是否仍在房间；
2. 房间是否处于 `RUNNING`；
3. `question_id` 是否是当前题；
4. 当前时间是否超过 deadline；
5. 玩家是否已经回答过；
6. 答案是否为 `A/B/C/D`。

判分规则：

```text
正确且未迟到 -> 加上该题 points
错误          -> 0 分
迟到          -> 0 分
重复          -> 拒绝，不重复加分
没有回答      -> 0 分
```

答案线程和计时线程使用同一个 `room_lock`，避免两个线程同时修改同一题的状态。

### 第五幕：题目结束、断线与优雅退出

当 `GameThread` 等待到 deadline：

1. 在房间锁内关闭当前题；
2. 固定所有玩家本题结果；
3. 读取服务端保存的正确答案；
4. 更新分数；
5. 向房间广播答案和最新得分；
6. 增加 `question_index`；
7. 有下一题则进入下一题；
8. 没有下一题则设置 `phase = FINISHED`；
9. 发布最终排行榜。

正确答案只能在题目关闭之后发送，不能出现在 quiz 列表、房间列表或 `question_open` 消息中。

如果客户端突然断开、`recv()` 抛出异常或返回空 bytes：

1. 捕获异常或识别 EOF；
2. 将 session 标记为断开；
3. 从 `sessions` 中移除；
4. 从等待中的房间移除；
5. 如果比赛已经开始，通知房间其他玩家；
6. 关闭该 socket；
7. 清理相关引用；
8. 让其他客户端和其他房间继续运行。

比赛结束后：

- 停止房间的 `GameThread`；
- 清理答案和 deadline；
- 不再需要时移除房间；
- 关闭已经断开的 socket。

`del room` 只是删除一个 Python 引用，不代表立即强制释放全部内存。真正要保证的是没有线程继续使用房间、房间不再被共享字典引用、socket 已关闭，之后 Python 才能回收无引用对象。

考官按下 Ctrl+C 后：

1. `signal` 处理函数设置 `shutdown_event`；
2. 停止接受新连接；
3. 通知客户端服务器即将关闭；
4. 关闭所有客户端 socket；
5. 停止所有 `GameThread`；
6. 关闭监听 socket；
7. 等待必要线程结束；
8. 服务器进程退出。



- 精简版:

第一幕：服务端的苏醒与内存初始化
故事从考官在 Docker 容器中敲下启动命令开始。
服务端程序启动，首先调用 Python 标准库中的 argparse 模块，解析传入的 IP、端口和 questions.json 文件路径。接着，它使用 json 模块读取该文件，并在内存中进行极其严格的结构遍历：检查测验数量、题目数量、选项是否严格为 A/B/C/D、分值是否在有效范围内。一旦验证通过，服务端会在其运行内存中创建一个全局的“题库字典”（Dictionary）来永久存放这些数据，随后在终端打印出 SERVER_READY。
为了实现网络通信，服务端调用 socket 模块创建一个原生 TCP 套接字并绑定端口。这里有一个极其关键的技术决策：为了防止阻塞（Blocking），服务端不能使用最基础的死循环 accept() 或 recv()，因为那会导致当一个客户端网络卡顿时，整个服务端停下来等他，其他玩家瞬间全部卡死。因此，服务端必须使用 selectors 模块（I/O 多路复用机制）或者 threading 模块（多线程机制）来管理并发。通过将套接字设置为非阻塞模式（Non-blocking），服务端主线程就可以像一个极其高效的接线员，只在某个客户端“真正有数据发来时”才去处理，从而轻松支持 10 个以上客户端并发。
第二幕：单用户的访问与会话建立
此时，玩家张三在另一个终端运行 client.py，同样使用 argparse 解析自己的 --id 和 --name 参数，并通过 socket.connect() 连向服务端。
当张三的连接抵达服务端时，服务端的 selectors（或线程池）瞬间察觉到有新连接。服务端调用 accept() 接收该连接，并在内存中立刻创建一个“客户端会话（Session）对象”。这个对象通常是一个字典，键是该用户的底层 socket 对象，值是记录该用户状态的数据，例如：{"user_id": "zhangsan123", "name": "张三", "current_room": None, "buffer": b""}。如果此时服务端发现 user_id 已经存在于活动的会话列表中，它会依据规则拒绝或断开旧连接。
这里必须提到你们团队需要自定义的应用层协议（Application-layer protocol）。因为 TCP 是源源不断的字节流，张三发来的消息可能会被切成两半，或者两条消息粘在一起（TCP 粘包/分片）。因此，服务端会利用上面会话对象里的 buffer（缓冲区）临时存放收到的字节，直到检测到你们约定的边界符（比如换行符 \n，或者解析出完整的 JSON 长度），才将其提取出来变成一条完整的指令交由业务逻辑处理。
第三幕：创建房间与内存隔离
张三成功连接后，发送了获取题库的指令。服务端查阅内存中的题库字典，剔除掉所有的 answer（正确答案）字段后，将题目大纲打包发给张三。
张三决定玩《网络基础》测验，点击创建房间。这一步极其关键：服务端收到请求后，会在内存中创建一个全新的“房间对象（Room）”。它在全局的 active_rooms 字典里新增一条记录，例如："Room_001": {"quiz_id": "network-basics", "players": {"zhangsan123": {"score": 0, "status": "ready"}}, "current_question_index": 0, "timer": None}。
由于每个房间在内存中都有专属的字典空间和状态模型，当李四随后创建了 Room_002 时，服务端对张三房间的任何分数修改或计时操作，都绝对不会越界影响到李四的房间。这就是实现“至少两个独立房间并行且互不影响”的底层技术本质。
第四幕：同步与异步交织的答题锦标赛
房间人满并开始比赛后，服务端化身为无情的发题机器。它提取第一道题（包含题目、A/B/C/D 选项、分值和 time_limit），通过循环遍历该房间内的所有玩家 socket，将题目推派过去。正确答案依然死死锁在服务端的内存深处。
此时，服务端必须启动该题的倒计时。如果使用多线程，它可能会利用 time.monotonic() 记录下发题的绝对时间戳，或者启动一个定时器（Timer）。在客户端那边，client.py 接收到题目后，使用标准的 print() 渲染到终端，并使用 select 模块监听用户的键盘标准输入（stdin），确保既能随时显示屏幕上的倒计时更新，又能随时捕获用户敲击的回车键。
当张三抢先输入了 "B" 并发送时，服务端的 selectors 立刻捕获到这段数据。服务端提取张三所在的 Room_001 对象，检查当前时间戳是否超过了 time_limit，并检查张三是否已经在这道题提交过答案。如果一切合法且答案与内存中的正确答案匹配，服务端就在 Room_001 中张三的 score 字段上加上对应的分值；如果不匹配、超时或是重复提交，则记为 0 分或直接丢弃。这一判题过程极其短暂，绝不会阻塞服务端去接收其他房间发来的数据。
第五幕：生命周期的终结与优雅清理
当该题的倒计时彻底结束，服务端强制关闭该题的提交通道，将正确答案以及该房间内所有玩家的最新得分汇总，广播给房间内的所有人，随后无缝进入下一题的循环。当所有题目耗尽，服务端依据最终 score 排序，发布排行榜。游戏结束后，服务端会使用 del 语句将 Room_001 对象从内存字典中抹除，释放系统资源。
在此期间，系统时刻面对着崩溃的风险。如果某个玩家突然拔掉网线，服务端底层的 recv() 会抛出异常或收到空字节。服务端必须使用 try...except 块精准捕获这个错误，断开该 socket 的连接，从内存会话池和房间列表中剔除该玩家（资源清理），但绝对不能让程序崩溃退出，其他正常连接的玩家甚至不会感觉到卡顿。如果考官在服务端的终端里按下了 Ctrl+C，通过 signal 模块注册的信号处理函数会被触发，服务端会优雅地关闭所有存活的客户端 socket，释放占用的本地端口，然后体面地结束整个进程。

## 二、五人任务分配

分工原则：服务端拆成三块，客户端拆成两块。任何一个人都不负责完整的客户端或完整的服务端。

### 成员 A：服务端网络连接和协议底层

负责：

- `socket()`、`bind()`、`listen()`、`accept()`；
- 每个客户端的连接线程；
- `ClientSession`；
- `recv_buffer`；
- JSON 消息拆分和组装；
- `send_lock`；
- 普通响应和主动事件的发送；
- malformed JSON；
- 客户端 EOF 和 socket 异常；
- Ctrl+C 的 socket 关闭部分。

主要文件：

```text
server.py
protocol.py
server_network.py
```

不负责房间规则、计时、评分和客户端菜单。

### 成员 B：服务端题库、用户和大厅房间

负责：

- `questions.json`；
- 题库完整验证；
- 内存中的 `question_bank`；
- quiz 列表；
- 用户 ID 唯一性；
- 创建、查看、加入和离开房间；
- ready 状态；
- 房主规则；
- `RoomState` 和 `PlayerState`。

主要文件：

```text
question_bank.py
server_state.py
server_lobby.py
questions.json
```

不负责 socket 接收、每题计时、答案判分和客户端界面。

### 成员 C：服务端比赛引擎、计时和评分

负责：

- 启动比赛；
- 每房间的 `GameThread`；
- `question_open`；
- `time.monotonic()` deadline；
- 正确、错误、迟到、重复和缺失答案；
- `question_closed`；
- 分数和排行榜；
- 两个房间并行；
- `room_lock`；
- 比赛线程和房间清理。

主要文件：

```text
game_engine.py
scoring.py
```

不负责 `accept()`、TCP buffer、客户端菜单和题库文件格式验证。

### 成员 D：客户端网络传输和客户端状态

负责：

- `socket.create_connection()`；
- 客户端 hello；
- 客户端 `recv_buffer`；
- 客户端接收线程；
- 普通响应和异步事件的区分；
- `request_id`；
- 当前用户、房间和题目状态；
- 服务端断线；
- `server_shutdown`；
- 向界面层提供收到的事件。

主要文件：

```text
client.py
client_transport.py
client_state.py
```

不负责菜单文字、用户操作流程、服务端计时评分和读取题库。

### 成员 E：客户端命令行界面和整体串联

负责：

- 命令行菜单；
- 输入 user ID 和 display name；
- 查看 quiz；
- 创建、查看、加入和离开房间；
- ready；
- 开始比赛；
- 输入答案；
- 显示题目、结果和排行榜；
- 显示错误信息；
- 正常退出；
- 把 A、B、C、D 的模块串成完整流程；
- 发现接口冲突并通知全组同步。

主要文件：

```text
client_ui.py
README.md
tests/
```

不负责 TCP 拆包底层、服务端房间状态、服务端计时和判分。

### 每个人都必须完成

- 自己负责模块的代码；
- 自己负责模块的基础测试；
- 能解释自己模块的内存状态和并发流程；
- 和至少一名组员一起运行完整流程；
- 接口字段变化时及时通知全组。

