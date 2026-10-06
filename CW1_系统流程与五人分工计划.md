# CSI201 CW1 系统流程与五人任务分配

## 一、先确定并发方式

本组采用 `threading`，不采用 `selectors` 作为主要实现方式：

```text
服务器主线程
└── 接受新连接
    ├── ClientThread 1：处理张三
    ├── ClientThread 2：处理李四
    ├── ClientThread 3：处理王五
    └── ...

Room_001 -> GameThread 1
Room_002 -> GameThread 2
```

选择原因：

- 一个客户端卡在 `recv()` 时，只影响自己的线程；
- 两个房间可以有各自的比赛线程；
- 代码比 `selectors` 更容易让初学者理解；
- 线程之间共享房间状态时，用 `threading.Lock` 保护。

`selectors` 是“一个线程同时观察很多 socket”，适合高效事件循环，但需要自己管理非阻塞 socket、接收 buffer、发送队列和所有房间计时。本组暂时不采用它。

如果线程和 `selectors` 都不用，只使用阻塞式 `accept()` 和 `recv()`，一个客户端不发送数据时就可能把整个服务器卡住，无法可靠支持多个客户端和两个并行房间。

## 二、系统流程故事

下面按照时间线说明：系统发生什么、内存中有什么、并发如何处理，以及五个人分别在什么时候参与。

## 第一幕：服务端苏醒与内存初始化

考官运行：

```bash
python3 server.py --host <server_IP> --port <port> --questions <json_path>
```

### 系统发生什么

服务端依次：

1. `argparse` 解析 host、port 和题库路径；
2. `json` 读取 `questions.json`；
3. 检查文件存在、非空且不超过 1 MB；
4. 检查 quiz 数量和每个 quiz 的题目数量；
5. 检查 quiz ID、question ID 不重复；
6. 检查选项严格为 `A/B/C/D`；
7. 检查 `answer`、`time_limit` 和 `points`；
8. 验证通过后，在内存中创建 `question_bank`；
9. 使用 `socket` 创建、绑定并监听 TCP 端口；
10. 输出 `SERVER_READY`。

如果验证失败：

- 打印错误；
- 返回非零退出状态；
- 不监听端口；
- 不接受客户端。

服务端初始内存大致为：

```text
question_bank
sessions = {}
active_rooms = {}
shutdown_event
listen_socket
```

正确答案保留在服务端的 `question_bank` 中。服务端发 quiz 列表或题目时，必须自己构造不含答案的数据，不能直接把完整题目对象发给客户端。

### 五个人在这一幕分别做什么

**成员 A：服务端网络底层**

- 在 `server.py` 中解析启动参数；
- 创建 `listen_socket`；
- 调用 `bind()`、`listen()`；
- 让服务端在成功监听后输出 `SERVER_READY`；
- 设计网络层使用的消息读取和发送方法。

**成员 B：题库和初始内存**

- 编写 `questions.json`；
- 实现完整题库验证；
- 把合法 JSON 转换成 `question_bank`；
- 保证正确答案只保存在服务端；
- 提供给其他成员读取 quiz 和题目的方法。

**成员 C：比赛状态的基础结构**

- 确认 `RoomState`、`PlayerState` 等对象需要哪些字段；
- 先不启动比赛，只定义后面计时、分数和答案需要使用的状态；
- 确认每个房间都有独立的状态空间。

**成员 D：客户端启动部分**

- 实现客户端参数解析；
- 使用 `socket.create_connection()` 连接服务器；
- 准备客户端接收线程和客户端状态；
- 客户端不读取 `questions.json`。

**成员 E：命令行入口和整体协调**

- 设计客户端启动后看到的第一步提示；
- 把 A、B、C、D 的启动接口串起来；
- 确认服务端和客户端使用的启动命令一致；
- 记录当前版本的运行方式。

### 多人情况

这一幕还没有玩家，但多个客户端可能几乎同时启动。服务器主线程只负责接受连接，不能在启动时为任何一个客户端执行长时间任务。题库只读取一次，之后所有客户端共享同一份只读 `question_bank`。

## 第二幕：张三连接与会话建立

张三运行：

```bash
python3 client.py --server <server_IP> --port <port> --id zhangsan123 --name ZhangSan
```

### 张三的连接过程

客户端：

1. 解析 `--server`、`--port`、`--id` 和 `--name`；
2. 调用 `socket.create_connection()`；
3. 发送 `hello`；
4. 启动客户端接收线程；
5. 等待服务器返回连接结果。

服务器：

1. 主线程调用 `accept()`；
2. 创建张三的 `ClientSession`；
3. 为张三启动一个 `ClientThread`；
4. 线程调用张三 socket 的 `recv()`；
5. 把收到的 bytes 放入 `recv_buffer`；
6. 从 buffer 中提取完整 JSON；
7. 检查并处理 `hello`。

会话对象大致为：

```text
ClientSession
├── user_id = "zhangsan123"
├── display_name = "ZhangSan"
├── socket
├── recv_buffer
├── send_lock
├── current_room_id = None
└── connected = True
```

如果 `user_id` 已经存在，服务器返回重复 ID 错误并关闭新连接。

### TCP buffer 在这里做什么

TCP 是连续字节流，不保证一次 `recv()` 就是一条 JSON：

```text
一条消息可能被拆成两次 recv()
两条消息可能被一次 recv() 一起收到
```

本组采用一行一个 JSON：

```text
recv()
  -> bytes 加入 recv_buffer
  -> 查找 \n
  -> 提取完整一行
  -> UTF-8 解码
  -> json.loads()
  -> 交给业务处理
  -> 不完整的剩余 bytes 留在 buffer
```

### 五个人在这一幕分别做什么

**成员 A：处理服务端连接**

- 接收张三的 socket；
- 创建服务端 `ClientThread`；
- 管理 `recv_buffer`；
- 把完整消息交给命令处理器；
- 负责向张三发送成功响应或错误响应。

**成员 B：检查张三身份**

- 检查 `user_id` 是否重复；
- 创建或更新 `sessions["zhangsan123"]`；
- 确认张三当前还没有加入房间；
- 负责活动用户表中的身份状态。

**成员 C：暂时不执行比赛**

- 只确认张三的 session 能被后面的比赛引擎查询；
- 不在这里创建 GameThread；
- 不在这里修改分数或题目索引。

**成员 D：处理客户端网络状态**

- 在客户端启动 reader thread；
- 接收服务器对 `hello` 的响应；
- 判断连接成功还是失败；
- 保存客户端自己的 user、room 和 connection 状态。

**成员 E：显示连接结果**

- 在命令行告诉张三连接成功或失败；
- 如果失败，显示重复 ID 或连接错误；
- 如果成功，显示下一步可执行的菜单。

### 多人情况

假设张三、李四、王五同时连接：

```text
主线程 accept()
  ├── 张三 -> ClientThread A
  ├── 李四 -> ClientThread B
  └── 王五 -> ClientThread C
```

每个连接都有自己的 `ClientSession` 和 `recv_buffer`。张三网络卡顿时，李四和王五的线程仍然可以继续处理。

如果张三和另一个客户端同时使用 `zhangsan123`：

- 第一个成功登记的 session 保留；
- 第二个收到 `DUPLICATE_USER`；
- 第二个 socket 被关闭；
- 其他用户不受影响。

## 第三幕：查看 quiz、创建房间与内存隔离

### 张三查看 quiz

张三发送 `list_quizzes`。服务器从 `question_bank` 生成公开信息，只返回：

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

### 张三创建 Room 001

张三选择《网络基础》并发送创建房间请求。服务器在 `active_rooms` 中创建：

```text
Room_001
├── quiz_id
├── host_user_id = "zhangsan123"
├── players
├── phase = WAITING
├── question_index = 0
├── deadline = None
├── answers = {}
├── scores = {"zhangsan123": 0}
├── room_lock
└── game_thread = None
```

张三的 session 更新为：

```text
current_room_id = "Room_001"
```

### 李四加入 Room 001

李四查看房间列表后发送加入请求。服务器：

1. 找到 `Room_001`；
2. 确认房间仍处于 `WAITING`；
3. 把李四加入 `players`；
4. 初始化李四分数为 0；
5. 更新李四的 `current_room_id`；
6. 向房间玩家发送房间更新。

### 王五创建 Room 002

王五也可以创建另一个 quiz 房间：

```text
Room_002
├── 自己的 players
├── 自己的 scores
├── 自己的 question_index
├── 自己的 deadline
├── 自己的 answers
├── 自己的 room_lock
└── 自己的 game_thread
```

Room 001 的分数、计时和题目进度不会修改 Room 002，因为它们是两个独立的房间对象。

### 五个人在这一幕分别做什么

**成员 A：接收和发送房间请求**

- 接收 `list_quizzes`、`create_room`、`join_room`；
- 把请求交给大厅逻辑；
- 将服务器返回的 room 信息发回客户端；
- 向多个玩家发送房间更新。

**成员 B：真正管理大厅和房间**

- 生成公开 quiz 列表；
- 创建 `Room_001`；
- 把张三设为 host；
- 处理李四加入；
- 处理王五创建 `Room_002`；
- 保证不同房间使用不同的 players、scores 和状态。

**成员 C：准备后续比赛状态**

- 确认每个房间都有比赛需要的字段；
- 不提前启动比赛线程；
- 不使用全局的 `current_question_index` 或全局 `deadline`；
- 确保以后每个房间可以独立启动。

**成员 D：接收服务器返回的数据**

- 收到 quiz 列表并保存客户端可显示的摘要；
- 收到 `Room_001` 信息并更新客户端状态；
- 收到 room update；
- 让客户端知道自己当前在哪个房间。

**成员 E：让用户完成操作**

- 显示 quiz 列表；
- 让张三选择 quiz 和创建房间；
- 让李四查看并加入 Room 001；
- 让王五创建或加入 Room 002；
- 显示房间成员和当前状态。

### 多人情况

10 个客户端可以同时查看 quiz 或创建房间。A 负责分别接收这些请求，B 负责修改对应的 sessions 和 rooms。B 修改共享字典时需要使用合适的锁，避免两个请求同时创建出重复 room ID 或同时加入已经开始的房间。

## 第四幕：准备、发题、答题与两个房间并行

### 4.1 准备和开始

房间状态：

```text
WAITING -> RUNNING -> FINISHED
```

本组规则：

- 至少两名玩家才能开始；
- 所有当前玩家都必须 ready；
- 只有 host 可以开始；
- 比赛开始后不能加入新玩家；
- 比赛开始后不能更换 quiz。

张三、李四都发送 ready 后，房间状态满足开始条件。张三作为 host 点击开始：

1. A 接收 `start_game`；
2. B 检查房间和玩家状态；
3. C 创建 `Room_001` 的 `GameThread`；
4. 房间 `phase` 改为 `RUNNING`；
5. E 通过客户端显示比赛开始。

如果王五的 Room 002 也满足条件，C 会为 Room 002 创建另一个独立的 GameThread。

### 4.2 发题和计时

C 的 GameThread 读取 Room 001 的第一道题：

```text
question_id
text
options
answer
time_limit
points
```

发给客户端时，A 只发送：

```text
question_id
text
options
time_limit
points
```

`answer` 仍然留在服务端。

C 设置：

```python
deadline = time.monotonic() + time_limit
```

服务端的 deadline 是判断迟到答案的权威标准。客户端显示的时间只是提示。

### 4.3 张三提交答案

张三看到题目后输入 `B`：

1. E 从终端读取输入；
2. D 把答案包装成客户端请求并发送；
3. A 的服务端 ClientThread 收到请求；
4. A 找到张三的 session；
5. A 找到张三所在的 Room 001；
6. C 在 Room 001 的 `room_lock` 内检查答案；
7. C 使用服务端题库中的正确答案判分；
8. A 把接受或拒绝结果发回张三；
9. E 在终端显示结果。

C 检查：

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

### 4.4 多人同时答题

如果张三、李四、王五几乎同时提交：

```text
张三 -> ClientThread 1 -> Room_001.lock
李四 -> ClientThread 2 -> Room_001.lock
王五 -> ClientThread 3 -> Room_002.lock
```

- Room 001 内的玩家共享 Room 001 的锁；
- Room 002 使用自己的锁；
- Room 001 的答案处理不会阻塞 Room 002 的答案处理；
- 同一个玩家的重复答案不会重复加分；
- 答案线程和 GameThread 关闭题目时使用同一个锁，避免截止时间竞态。

### 五个人在这一幕分别做什么

**成员 A：消息接收、路由和广播**

- 接收 ready、start_game 和 answer；
- 把请求路由给 B 或 C；
- 将 `question_open` 广播给对应房间；
- 将 answer response 发给对应玩家；
- 不直接计算分数。

**成员 B：准备条件和房间状态**

- 保存每个玩家的 ready 状态；
- 判断房间人数是否足够；
- 判断是否由 host 启动；
- 将房间从 WAITING 改为 RUNNING；
- 把 Room 001 和 Room 002 的状态分开管理；
- 不负责每题计时和判分。

**成员 C：比赛核心**

- 创建每个房间的 GameThread；
- 读取当前题目；
- 设置 deadline；
- 接收答案判定；
- 修改 score；
- 关闭题目并准备下一题；
- 同时管理 Room 001 和 Room 002，但每个房间使用自己的状态和锁。

**成员 D：客户端网络和事件**

- 接收 `question_open`；
- 把题目交给客户端状态；
- 发送张三或其他玩家的 answer；
- 接收 answer response；
- 接收 `question_closed` 和 score update；
- 保证异步事件不会被普通响应吞掉。

**成员 E：客户端操作和显示**

- 显示 ready 和 start 选项；
- 让用户输入 A/B/C/D；
- 在终端显示题目和选项；
- 显示答案是否被接受；
- 显示题目结束、得分和下一题；
- 同时开多个客户端窗口时，每个窗口只显示自己的用户状态和所在房间。

## 第五幕：题目结束、断线与优雅退出

### 5.1 题目关闭

当 Room 001 的 GameThread 等待到 deadline：

1. C 在 Room 001 的锁内关闭当前题；
2. C 固定所有玩家本题结果；
3. C 从服务端题库读取正确答案；
4. C 更新分数；
5. A 向 Room 001 的玩家广播答案和得分；
6. D 接收事件；
7. E 在终端显示结果；
8. C 增加 `question_index`；
9. 有下一题则进入下一题；
10. 没有下一题则设置 `FINISHED` 并发布排行榜。

Room 002 的 GameThread 同时可以处于自己的第一题或第三题，不需要等待 Room 001。

正确答案只能在题目关闭之后发送，不能出现在 quiz 列表、房间列表或 `question_open` 消息中。

### 5.2 玩家突然断线

假设李四突然关闭客户端：

1. A 的李四 ClientThread 发现 `recv()` 异常或返回空 bytes；
2. A 关闭李四的 socket；
3. B 从 `sessions` 和对应房间玩家列表中移除李四；
4. 如果 Room 001 正在比赛，C 更新该房间的活动玩家状态；
5. A 向 Room 001 其他玩家发送 player-left 通知；
6. D 接收通知；
7. E 在张三终端显示李四离开；
8. Room 002 和其他客户端继续运行。

如果断线发生在等待阶段，B 负责从房间移除玩家并处理 host。若断线发生在比赛中，C 负责让当前比赛继续，不因为一个人断线而让房间或服务器崩溃。

### 5.3 比赛结束和内存清理

当 Room 001 所有题目结束：

- C 设置房间为 `FINISHED`；
- C 停止 Room 001 的 GameThread；
- C 清理当前题目的答案和 deadline；
- A 关闭已经断开的连接；
- B 在不再需要时从 `active_rooms` 移除房间；
- D 接收最终排行榜；
- E 显示排行榜并回到结束状态。

`del room` 只是删除一个 Python 引用，并不代表立即强制释放全部内存。真正要保证的是没有线程继续使用房间、房间不再被共享字典引用、socket 已关闭，之后 Python 才能回收无引用对象。

### 5.4 Ctrl+C

考官在服务端按下 Ctrl+C：

1. A 的 `signal` 处理部分设置 `shutdown_event`；
2. A 停止接受新连接；
3. A 向所有客户端发送关闭通知；
4. C 停止或唤醒 Room 001、Room 002 的 GameThread；
5. B 清理 sessions 和 rooms；
6. A 关闭所有客户端 socket 和 listen socket；
7. D 接收服务器关闭事件；
8. E 让客户端正常退出；
9. 服务端进程结束。

## 三、按成员汇总任务

### 成员 A：服务端网络连接和消息传输

负责：

- `socket()`、`bind()`、`listen()`、`accept()`；
- 服务端 ClientThread；
- `recv_buffer`；
- JSON 消息拆分和发送；
- `send_lock`；
- request/response/event 的传输；
- malformed JSON；
- EOF、socket 异常和 Ctrl+C 的网络清理；
- 负责所有服务端广播的实际发送。

对应流程：第一幕建立监听；第二幕接收张三；第三幕转发房间请求；第四幕接收答案并广播题目；第五幕发送结果、断线通知和关闭通知。

### 成员 B：题库、用户、房间和大厅状态

负责：

- `questions.json`；
- 完整题库验证；
- `question_bank`；
- `sessions` 中的用户身份；
- quiz 列表；
- 创建、查看、加入、离开房间；
- ready 状态；
- host 规则；
- `RoomState` 和 `PlayerState`；
- 断线时从 sessions 和房间移除玩家。

对应流程：第一幕创建题库；第二幕登记张三和其他用户；第三幕创建 Room 001、Room 002；第四幕确认谁能开始；第五幕清理断线用户和结束房间。

### 成员 C：比赛引擎、计时、评分和房间并行

负责：

- 每个房间的 GameThread；
- `WAITING -> RUNNING -> FINISHED`；
- `question_open`；
- `time.monotonic()` deadline；
- 正确、错误、迟到、重复和缺失答案；
- 更新分数；
- `question_closed`；
- leaderboard；
- Room 001 和 Room 002 同时比赛；
- `room_lock`；
- 比赛结束清理。

对应流程：第四幕从房主开始后接管比赛；第五幕负责题目关闭、排行榜和比赛线程结束。

### 成员 D：客户端网络传输和客户端状态

负责：

- `socket.create_connection()`；
- 客户端 hello；
- 客户端 reader thread；
- 客户端 `recv_buffer`；
- 普通 response 和异步 event；
- 当前用户、当前房间和当前题目状态；
- 断线和 `server_shutdown`；
- 把收到的事件交给客户端界面。

对应流程：第二幕连接张三；第三幕接收 quiz 和房间信息；第四幕接收题目、发送答案；第五幕接收结果、断线通知和关闭通知。

### 成员 E：客户端命令行界面和整体流程串联

负责：

- 命令行菜单；
- 输入用户信息；
- 查看 quiz；
- 创建、查看、加入和离开房间；
- ready 和 start；
- 输入答案；
- 显示题目、结果、得分和排行榜；
- 显示错误；
- 把 A、B、C、D 的模块连成完整可操作流程；
- 用多个客户端窗口配合演示多人情况；
- 发现接口不一致并提醒全组同步。

对应流程：第二幕让张三连接；第三幕让张三创建、让李四加入；第四幕让多人准备、答题；第五幕显示断线、结果和服务器关闭。

### 每个人都必须完成

- 自己负责部分的代码；
- 自己负责部分的基础测试；
- 能解释自己的代码在五幕中的运行位置；
- 能说明多人同时发生时自己的模块如何处理；
- 至少和一名组员一起完成一次完整流程；
- 接口字段改变时及时通知全组。

