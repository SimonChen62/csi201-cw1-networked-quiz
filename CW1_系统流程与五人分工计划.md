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

