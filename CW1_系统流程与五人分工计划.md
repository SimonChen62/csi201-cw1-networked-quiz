# CSI201 CW1 系统流程与五人任务分配

> 2026-11-12 对接修订：本轮修改目标以文末「五、接口与消息字段（v3）」及「六、逐人修改与课程需求对应」为准。第六节逐项规定谁改、改什么、如何验收；此前流程与进度表保留作历史说明。v3 是本轮拟统一的实现目标，全组确认与验收仍待完成。[D/E 接口表](CW1_D与E接口确定表.md) 描述现有客户端，字段冲突处应同步到 v3；具体 API 调用方式仍可查该表。进度见 [E 收件清单](CW1_E向各成员收取的交付清单.md)。

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

---

# 四、剩余任务分配（2026-11-11 修订）

> 本节替代前面各节的任务清单。前面「第一幕～第五幕」保留为流程说明，不再作为任务依据。

## 4.1 现状盘点（据 2026-11-11 仓库与文档实测）

| 项目 | 数字 | 判断 |
| --- | --- | --- |
| 距提交截止 | 28 天（12-10 23:59） | 紧 |
| `Codes/` 下模块 | 15 个 py 文件 | — |
| 已实现的模块 | 2 个（`server.py`、`protocol.py`） | 网络层完成 |
| 空的模块 | 6 个（`question_bank`、`lobby`、`game_engine`、`connection`、`state`、`cli`） | 全部未开始 |
| 自动化测试 | 29 项，官方镜像内通过 | 只覆盖网络层 |
| git commit 归属 | SimonChen62 27 条，GakBu-BUDD 1 条，其余 3 人 0 条 | 5 人中 2 人有提交 |
| 报告进度 | 6,121 词中约 5,400 词由成员 A 完成（88%） | 严重失衡 |
| 报告空白 | 14 处正文 + 5 张图 | 见 4.4 |

**结论：剩下 28 天要交付的是「5 个模块 + 14 处报告 + 5 张图 + 打包」，不是润色工作。**

## 4.2 硬截止与里程碑

| 日期 | 里程碑 | 判据 | 责任 |
| --- | --- | --- | --- |
| 11-14 | 题库合规 + 分帧图 | `questions.json` 通过自写校验；Figure 6-1 完成 | B / A |
| **11-16** | **`load_question_bank` 可用** | `python3 server.py --host 0.0.0.0 --port 5000 --questions questions.json` 打印 `SERVER_READY` | **B（阻塞全组）** |
| 11-20 | 客户端能连上 | 用强制命令启动，输入 ID 后建立连接并收到响应 | D |
| **11-22** | **最小可跑闭环** | 两客户端：连接 → 建房间 → 加入 → ready → 房主开始 | B + D + E |
| 11-28 | 一局能打完 | 题序、计时、判分、结果、排行榜全部工作 | C |
| 11-30 | 延迟/重复答案测试 | 两条用例：迟到判 0 分、重复不重复加分 | C |
| 12-01 | 报告空白补齐 | 14 处 `[To be written]` 全部填完；5 张图插入 | 全员 |
| 12-03 | 报告统稿 + 导出 PDF | 目录、题注、引用统一；`Development_Documentation.pdf` 生成 | E |
| 12-05 | **代码冻结** | 只允许改 bug，不再加功能；29+ 项测试全绿 | 全员 |
| 12-08 | 打包完成 | ZIP 结构、命名、排除项全部核对 | E |
| 12-10 23:59 | 提交 | — | 队长 |

## 4.3 代码任务分配（含完成判据）

### 成员 A：网络层收尾 + 网络接入配合

| 编号 | 任务 | 截止 | 完成判据 |
| --- | --- | --- | --- |
| A-1 | Figure 6-1 分帧示意（自己画） | 11-14 | 两种到达情况，`\n` 画成竖线，虚线标 recv 边界 |
| A-2 | Ctrl+C 终端级验证记录 | 11-14 | 镜像内 `-it` 模式按 Ctrl+C 干净退出，输出存 `docs/evidence/` |
| A-3 | 按全组确认的协议完善网络封装与业务回调接入 | 11-22 | 配合 E 将 B 提供的处理器接入 Server；网络正确传递请求、响应和事件 |
| A-4 | 网络并发与断线验证 | 11-30 | 提供十连接等网络测试结果；配合 E 组织的整机联调，排查网络层问题 |

### 成员 B：题库 + 大厅（最重，优先）

| 编号 | 任务 | 截止 | 完成判据 |
| --- | --- | --- | --- |
| B-1 | `questions.json` 合规终版 | 11-14 | 至少 2 quiz × 5 题；ID 字符集合规；可见字符长度合规 |
| B-2 | `load_question_bank(path)` 完整校验 | **11-16** | 好题库返回对象；7 类坏题库（缺字段/类型错/超范围/ID 重复/选项非 ABCD/答案非法/文件超 1MB）各抛 `ValueError` |
| B-3 | 用户登记与重复 ID 处理 | 11-18 | 同一 ID 第二个连接被拒绝，返回明确错误码 |
| B-4 | 房间创建 / 列表 / 加入 / 查看成员 / 离开 | 11-20 | 两个客户端可完成建房与加入 |
| B-5 | ready 状态与房主开始规则 | 11-22 | 只有房主能开始；未全员 ready 时拒绝并说明原因 |
| B-6 | ZIP 打包与排除项核对 | 12-08 | 不含 `.git`、`output/`、`.workbuddy/`、venv、Dockerfile |

### 成员 C：比赛引擎

| 编号 | 任务 | 截止 | 完成判据 |
| --- | --- | --- | --- |
| C-1 | 房间三态与每房间比赛线程 | 11-22 | 两房间各自独立 RUNNING，互不影响 |
| C-2 | 发题与 `time.monotonic()` 计时 | 11-25 | 每题按 `time_limit` 关闭，关闭后才公布答案 |
| C-3 | 答案接收 / 去重 / 迟到判定 / 计分 | 11-28 | 正确加分、错误 0 分、迟到 0 分、重复被拒 |
| C-4 | 排行榜与结束态 | 11-28 | 按分数降序，同分按 ID 稳定排序 |
| C-5 | 迟到与重复答案测试 | 11-30 | 两条用例，断言分数不重复增加 |
| C-6 | Figure 4-1 房间状态迁移图 | 11-22 | 三态 + 每条迁移的触发条件 |

### 成员 D：客户端传输层

| 编号 | 任务 | 截止 | 完成判据 |
| --- | --- | --- | --- |
| D-1 | `client_modules/connection.py`：连接 + 收帧 + 发帧 | 11-18 | 能连、能发请求、能收响应；复用 `protocol.py` 的编解码 |
| D-2 | `client_modules/state.py`：本地用户/房间/题目状态 | 11-20 | 收到 event 时状态正确更新 |
| D-3 | 客户端能区分 response / event / error | 11-20 | 事件不会让主流程提前结束等待 |
| D-4 | `client.py --server --port --id --name` 参数解析 | 11-20 | 强制命令格式可启动并连接 |
| D-5 | 客户端异常与断线处理 | 11-22 | 服务器关闭时客户端不崩、给提示 |
| D-6 | 10 客户端演示脚本 | 12-01 | 一条命令起 10 个客户端，画面可录 |

### 成员 E：界面 + 全组统筹与集成 + 交付

| 编号 | 任务 | 截止 | 完成判据 |
| --- | --- | --- | --- |
| E-1 | `client_modules/cli.py`：菜单、输入、显示 | 11-20 | 能走完「连接→看 quiz→建房→加入→ready→答题」 |
| E-2 | `client.py` 入口：串起 connection / state / cli | 11-24 | 强制命令可启动，能连上并走完一次问答 |
| E-6 | 全组接口确认、合并协调和整体装配 | 11-22 起持续 | 收集各人接口与提交，维护全组确认的协议；组织服务端与客户端装配，各成员完成自己模块的适配 |
| E-7 | 官方 Docker 整机验收与证据汇总 | 12-05 前 | 组织完整流程、十客户端双房间及异常回归，分派问题给对应模块负责人，汇总命令、版本和结果 |
| E-3 | `Codes/README.md` 提交版 | 12-01 | 精确启动命令、CLI 摘要、假设、已知局限四项齐全 |
| E-4 | 报告统稿 + 导出 PDF | 12-03 | 目录可跳转、题注连续、引用 IEEE；PDF 生成 |
| E-5 | 视频组织与剪辑 | 12-05 | 每人出镜讲自己部分（讲解各人自负），E 负责串场、录制、剪辑，总时长 ≤10 分钟 |

## 4.4 报告章节分配（14 处空白 + 5 张图）

> 原则：按模块归属分配，并让文档完成度高的人少拿，以平衡总工作量。

| 章节 | 内容 | 归属 | 字数目标 | 备注 |
| --- | --- | --- | --- | --- |
| 3.1 | 系统上下文视图 | **B** | 120 | 与他画的 Figure 3-1 配套；核心是"只有服务端读题库" |
| 5.1 | 题库 schema 说明 | **B** | 100 | 表 5-1 已填好，只需写说明段 |
| 5.2 | 内存实体与所有权 | **B** | 120 | 会话 / 房间 / 题库分别归谁 |
| 5.3 | 答案保密 | **B** | 100 | 只服务端持有、关闭后才下发 |
| 4.2 | 房间与 quiz 状态模型 | **C** | 150 | 配 Figure 4-1 |
| 4.4 | 计时模型 | **C** | 150 | 为什么用 monotonic、deadline 权威性 |
| 2.2 | 功能需求表 FR-01~06 | **C** | 120 | 一行一个 Task，可直接照任务书写 |
| 2.3 | 非功能需求表 NFR-01~03 | **C** | 60 | 计时与并发相关条目 |
| 3.3 | 部署视图与信任边界 | **D** | 150 | 单容器、端口来自参数、只有服务端读题库 |
| 2.4 | 验收标准 + 追溯矩阵 | **D** | 100 | 表 2-3 已给 6 行，填设计元素与证据 |
| 2.1 | 利益相关者、假设、约束 | **D** | 150 | 从任务书 6 个 Task 反推 |
| 11.1 | 里程碑表 | **E** | 80 | 照 4.2 的表填 |
| 11.2 | 仓库证据与个人职责 | **E** | 150 | 结合本节分工表写 |
| 11.3 | 与原计划的偏差 | **E** | 100 | 如实写：业务模块滞后、文档由 A 代笔较多 |
| 表 1-1 | 姓名 / 学号 / 贡献比例 | **E 汇总** | — | 合计 100%，按实际贡献填 |

**每人合计**：B 440 词、C 480 词、D 400 词、E 330 词、A 0 词（已完成）。正文与图由同一人负责，避免"图是甲画、文是乙写"的对接成本。

### 图表分配（5 张，一人一张）

| 编号 | 图 | 归属 | 完成判据 | 截止 |
| --- | --- | --- | --- | --- |
| F-01 | Figure 3-1 系统上下文 | **B** | 三个方框 + 双向 TCP + 单向箭头标 `only server reads`；核心表达"只有服务端能读题库"这条约束 | 11-20 |
| F-02 | Figure 3-2 组件与接口 | **D** | 六个模块框；箭头标 `request_handler(session, message) -> dict`、`on_disconnect(session)` | 11-20 |
| F-03 | Figure 4-1 房间状态迁移 | **C** | WAITING→RUNNING→FINISHED + 每条迁移条件 | 11-22 |
| F-04 | Figure 6-1 分帧示意 | **A** | 两种到达情况，换行符画成竖线，虚线标出 recv 边界 | 11-14 |
| F-05 | Figure 6-2 消息时序 | **E** | 请求→响应往返，中间插一条 event，体现三类消息的区分 | 11-24 |

**分配原则：一人一张，谁都不多。** F-01 归 B，因为图上要表达的信任边界（客户端不得读题库）本来就是他模块的约束；F-02 归 D，因为客户端传输层要接的两个接口就在图上。

**红线：所有图必须自己画，不得用生成式 AI 生成图片。** 统一用 PowerPoint 形状画完「另存为图片」导出 PNG，交给 A 插入文档并加题注。



## 4.5 工作量

| 成员 | 代码项 | 报告字数 | 图 | 交付 |
| --- | --- | --- | --- | --- |
| A | 已完成 + 联调 | 0 | F-04 | Ctrl+C 证据 |
| B | 6 | 440 | F-01 | ZIP 打包 |
| C | 6 | 480 | F-03 | — |
| D | 6 | 400 | F-02 | 10 客户端脚本 |
| E | 5 | 330 | F-05 | README / PDF / 视频组织 |

## 4.6 违约处理

| 日期 | 未达成 | 处理 |
| --- | --- | --- |
| 11-16 | B 无 `load_question_bank` | 启动项放弃，T-08 改 Pending |
| 11-22 | 无最小闭环 | 12.1 恢复"房间未实现"，T-10/11 改 Pending |
| 12-01 | 报告章节未交 | A 补写，11.3 如实记录 |
| 12-05 | 代码未冻结 | 只修致命 bug |

## 4.7 覆盖核对表（任务书逐项对照）

> 判据：每一行都有明确负责人和交付物。若本表全部打勾，则提交物齐全。

### 提交包结构

| 任务书要求 | 分配项 | 负责 | 状态 |
| --- | --- | --- | --- |
| `Codes/server.py` | 已完成 | A | ✅ |
| `Codes/client.py` | E-2 | E | 待做 |
| `Codes/questions.json`（≥2 quiz × ≥5 题） | B-1 | B | 待做 |
| `Codes/README.md`（命令 / CLI / 假设 / 局限） | E-3 | E | 待做 |
| `Codes/tests/` | 29 项已交付 + D-6 演示脚本 | A / D | 部分完成 |
| `Codes/` 其他模块 | B-2~B-5、C-1~C-6、D-1~D-5、E-1 | B/C/D/E | 待做 |
| `Documentation/Development_Documentation.pdf` | E-4 | E | 待做 |
| ZIP 命名与排除项 | B-6 | E | 待做 |

### 六个功能任务

| 任务书 Task | 分配项 | 负责 | 状态 |
| --- | --- | --- | --- |
| Task 1 启动与题库校验 | 启动顺序（A 已完成）+ B-2 | A / B | 部分完成 |
| Task 2 身份与连接 | B-3（重复 ID）+ D-1、D-4 | B / D | 待做 |
| Task 3 quiz 与房间 | B-4、B-5 + E-1 | B / E | 待做 |
| Task 4 比赛 | C-1~C-4 | C | 待做 |
| Task 5 并发与隔离 | C-1（两房间）+ A（10 连接）+ D-6 | C / A / D | 部分完成 |
| Task 6 容错与关闭 | A（坏帧/断线/关闭）+ C-3（迟到重复）+ D-5 | A / C / D | 部分完成 |

### 报告 12 章

| 章节 | 归属 | 状态 |
| --- | --- | --- |
| 1 文档控制与执行摘要 | A | ✅ |
| 2 需求分析 | C（2.2）、D（2.1、2.4）、C（2.3） | 待做 |
| 3 系统架构 | A（3.2）、B（3.1）、D（3.3） | 部分完成 |
| 4 详细设计 | A（4.1/4.3/4.5/4.6）、C（4.2/4.4） | 部分完成 |
| 5 数据设计 | B（5.1/5.2/5.3） | 待做 |
| 6 协议设计 | A | ✅ |
| 7 实现记录 | A | ✅ |
| 8 部署与运行 | A | ✅ |
| 9 验证与确认 | A | ✅ |
| 10 可靠性与安全 | A | ✅ |
| 11 项目管理与贡献 | E | 待做 |
| 12 局限与未来工作 | A | ✅ |
| References | A（4 条已核实可获取） | ✅ |
| 5 张图 | B/D/C/A/E 各一张 | 待做 |

### 视频与提交

| 要求 | 分配项 | 负责 |
| --- | --- | --- |
| ≤10 分钟，演示 Task 1–5，每人出镜 | E-5 + 全员 | E 组织 |
| 官方镜像内录制 | E-5 | E |
| Learning Mall 提交 | 队长 | — |

## 4.8 补齐项

| 编号 | 事项 | 负责 | 截止 |
| --- | --- | --- | --- |
| G-1 | 交叉检查记录 | 全员 | 11-30 |
| G-2 | 贡献比例汇总 | 每人 → E | 12-03 |
| G-3 | AI 声明一致性 | E 起草，A 复核 | 12-01 |
| G-4 | 分支与 PR 流程 | 全员 | 立即 |

## 4.9 交叉检查

### 4.9.1 报告互查

| 检查人 | 检查章节 | 审阅字数 |
| --- | --- | --- |
| D | 3.2、6.1–6.6 | 1,433 |
| C | 9.1–9.4、10.1–10.3 | 1,448 |
| B | 4.1、4.3、4.5、4.6、8.1–8.2 | 1,353 |
| E | 1.1–1.4、7.1–7.4、12.1–12.2、References | 1,415 |
| A | 3.1、5.1–5.3、4.2、4.4、2.1–2.4、11.1–11.3、表 1-1 | 1,670 |

### 4.9.2 代码互查*

| 检查人 | 被查 |
| --- | --- |
| B | `server.py`（session 注册与关闭） |
| C | `question_bank.py` |
| D | `game_engine.py` |
| E | `client_modules/connection.py` |
| A | `client_modules/cli.py` |

### 4.9.3 交付

每条检查交三样：

1. 至少 3 条意见，指到小节或行号。
2. 每条标 `修正` / `确认无误` / `存疑待议`。
3. 存 `docs/review/<检查人>-<对象>.md` 并 commit。

### 4.9.4 时间

| 日期 | 事项 |
| --- | --- |
| 11-30 | 代码互查完成 |
| 12-02 | 报告互查完成 |
| 12-03 | E 汇总记录 |
| 12-05 | 按意见修完 |



---

---

---

## 五、接口与消息字段（v3）

本轮保留 D/E 已实现的事件名、start_game、inspect_room 和 data.room；保留 C 已实现的 choice、index、display_name 等字段，按第六节分配修改。此为待全组确认的目标协议，不表示当前代码已全部符合。改字段先更新本节并通知全组。

老师任务书第 3 页允许小组自行设计消息名、字段、request_id、事件和错误模型。这里的具体命名、JSON Lines、64 KiB 上限是本组选择，不是老师强制名称；老师强制行为和对应验收见第六节。题库 schema 则必须严格遵守任务书第 3–5 页。


### 传输

一行一个 UTF-8 JSON 对象，`\n` 结尾。单帧上限 64 KiB。

### 两类消息

```json
{"type":"response","request_id":"1","ok":true,"data":{}}
{"type":"response","request_id":"1","ok":false,"error":{"code":"ROOM_NOT_FOUND","message":"..."}}
{"type":"event","event":"question","data":{}}
```

- 失败也是 `response`，不另设 `type:"error"`
- `request_id` 由客户端生成，字符串（`"1"`、`"2"`…），服务端原样回带，不解析其类型
- 同一连接中每次请求使用不同 request_id；不同客户端都可从 "1" 开始。A 按来源 session 回复，不用全局 request_id 识别玩家；用户身份由 B 的 user_id/session 映射确定
- 帧根本解析不出对象时 `request_id` 为 `null`
- `event` 不带 `request_id`、不带 `ok`

### 命名约定

| 项 | 规则 |
| --- | --- |
| 字段名 | 全小写 snake_case（`room_id`，不是 `roomId`） |
| 所有 id | 字符串（`quiz_id` / `question_id` / `room_id` / `user_id`） |
| 选项 | 单字符大写 `A` `B` `C` `D` |
| 分数、题号、人数 | 整数 |
| 秒数 | 整数（`time_limit`） |
| 布尔 | `true` / `false` |
| 请求字段 | 与 `type`、`request_id` 平级，不套 `data` |

### 对象形状

`PLAYER` = `{"user_id","display_name","ready","score"}`

`ROOM` = `{"room_id","quiz_id","host_user_id","state","players":[PLAYER]}`

`state` 取值：`WAITING` / `RUNNING` / `FINISHED`

### 请求 → 响应

| type | 请求字段 | 响应 data |
| --- | --- | --- |
| `hello` | `user_id`、`name` | `{"user_id","name"}` |
| `list_quizzes` | — | `{"quizzes":[{"quiz_id","title","description","question_count"}]}` |
| `list_rooms` | — | `{"rooms":[{"room_id","quiz_id","host_user_id","state","player_count"}]}` |
| `create_room` | `quiz_id` | `{"room":ROOM}` |
| `join_room` | `room_id` | `{"room":ROOM}` |
| `inspect_room` | `room_id` | `{"room":ROOM}` |
| `ready` | `room_id`、`ready`(bool) | `{"room":ROOM}` |
| `start_game` | `room_id` | `{}` |
| `answer` | `room_id`、`question_id`、`choice` | `{"accepted":true}` |
| `leave_room` | `room_id` | `{}` |
| `echo` | `text` | `{"text":"原样字符串"}` |
| `quit` | — | `{"bye":true}`；客户端收到后主动断开，由 A 的统一断线回调触发 B/C 清理。意外断线不要求先发送 quit |

`echo` 只用于联调，不参与业务流程。

以上 `{"room_id","quiz_id"}` 等是字段集合简写，不是可解析 JSON。建房成功的完整示例：

```json
{"type":"response","request_id":"2","ok":true,"data":{"room":{"room_id":"R1","quiz_id":"network-basics","host_user_id":"u1","state":"WAITING","players":[{"user_id":"u1","display_name":"Alice","ready":false,"score":0}]}}}
```

hello 的 name 是玩家显示名；PLAYER 和排行榜中的同一名称使用 display_name，B 负责转换。B 在用户表的同一临界区中完成重复活动 user_id 检查与登记；请求中的 room_id 只用于查找，是否可操作必须根据来源 session 的登录身份/房间成员关系判断。

### 事件

| event | data |
| --- | --- |
| `room_update` | `ROOM`（含 `room_id`） |
| `question` | `{"room_id","question_id","index","text","options":{"A","B","C","D"},"time_limit","points"}` |
| `question_result` | `{"room_id","question_id","answer","scores":{"user_id":整数}}` |
| `leaderboard` | `{"room_id","leaderboard":[{"rank","user_id","display_name","score"}]}` |
| `server_shutdown` | `{"reason"}` |

`question` **不得**含 `answer`、`correct` 等正确答案字段。答案只在 `question_result` 出现；公开 quiz 列表不得提前泄露题目、选项或答案。

index 从 0 开始。question 建立当前题并进入 RUNNING；question_result 按 room_id/question_id 更新分数并关闭对应题；leaderboard 进入 FINISHED。所有房间事件必须带 room_id。收到迟到的 start_game 回复不得重置已收到的题；旧题结算不得关闭下一题。

B 的业务路由须安排新玩家的 create_room/join_room 成功回复先于需要该房间身份的事件发送，A 提供按序发送所需的网络接口。C 的首题事件可能早于 start_game 普通回复，D/E 必须支持该顺序，由 E 组织集成测试覆盖。

### 失败码

| code | 含义 |
| --- | --- |
| `MALFORMED_MESSAGE` | 非法 UTF-8 / 非法 JSON / 非对象 |
| `UNKNOWN_COMMAND` | `type` 未实现 |
| `INVALID_MESSAGE` | 字段缺失或类型错 |
| `MESSAGE_TOO_LARGE` | 超过 64 KiB（发完即断连） |
| `INTERNAL_ERROR` | 服务端编码响应失败 |
| `QUIZ_NOT_FOUND` | `quiz_id` 不存在 |
| `ROOM_NOT_FOUND` | `room_id` 不存在 |
| `NOT_IN_ROOM` | 用户不在该房间 |
| `NOT_HOST` | 非房主执行 `start_game` |
| `NOT_ALL_READY` | 未全员 ready 就 `start_game` |
| `ALREADY_STARTED` | 房间已开赛 |
| `INVALID_CHOICE` | `choice` 不是 A/B/C/D |
| `LATE_ANSWER` | 题目已关闭 |
| `DUPLICATE_ANSWER` | 本题已作答 |
| `DUPLICATE_USER` | `hello` 的 `user_id` 已被占用 |
| `NOT_AUTHENTICATED` | 未成功 hello 就请求业务操作 |

可恢复的请求拒绝保持连接；MESSAGE_TOO_LARGE 返回失败后关闭该连接。EOF、socket 故障、Ctrl+C 等需要关闭连接；客户端在重复 ID 登录失败后也可以主动退出，不影响原用户。B/C 的预期业务拒绝返回错误字典，不能依赖未捕获异常断线。

### 最小闭环（11-22 验收）

```
hello → list_quizzes → create_room → join_room → ready → start_game
→ question → answer → question_result → leaderboard
```

任一步失败，先查字段名与本节是否一致。

## 六、逐人修改与课程需求对应（2026-11-12）

### 6.1 截图六项差异：明确由谁改

检查基线为 main@7d65143（D/E）和 codex/game-engine@b87bcc4（C，尚未合并），加本地 A 的失败 response 修改。本节是待执行修改清单，不是完成记录。此前截图对比的是 v2 和 D/E；本文件目前已更新为 v3，不能再要求所有人照旧截图的左列修改。

| 截图中的差异 | v3 最终目标 | 谁改、改哪里 | 验收 |
| --- | --- | --- | --- |
| 发题：question_open / question | 事件 question | C：game_engine.py 的 start_match、后续发题事件和对应测试，把 question_open 改为 question。D/E 保留 question 接收/显示分支 | C 的真实题目事件使 D 建立当前题、E 显示题目 |
| 结算：question_closed+correct / question_result+answer | 事件 question_result，正确答案字段 answer | C：_settle_question_locked 生成 question_result，把 correct 改为 answer；D/E 保留现有事件名和答案解析 | 关闭后才显示正确答案及累计分；发题不带答案 |
| 结束：game_finished / leaderboard | 事件 leaderboard | C：最后一题后的事件及测试改为 leaderboard；D/E 保留事件名，姓名字段见 6.2 | 排行榜显示并进入 FINISHED |
| 开始：start / start_game | 请求 start_game，成功 data 为 {} | D/E 已使用 start_game，保留；B 路由并检查 host/ready 后调用 C；E 统筹装配，A 配合网络回调接入。C 内部 start_match 方法可保留，无需改函数名 | CLI start 发 start_game；提前到达的首题不被回复清空 |
| 选项：choice / answer | answer 请求使用 choice | E：cli.py 的 parse_command 将发送字段 answer 改成 choice；D 同步连接测试/样例；B 的业务路由从 message.choice 传给 C.submit_answer | 真实请求携带 room_id/question_id/choice；不接受客户端自报分数 |
| 房间：data / data.room | data.room，host_user_id，inspect_room，room_update | B：按 v3 构造 ROOM 和路由；D/E 已使用该形状，保留。旧 v2 的 host_id、room_members、room_updated 不用于新实现 | 建房/加入/成员/ready/房主转移都能正确更新和显示 |

### 6.2 除截图外必须同步的字段与职责

统筹负责人是 E：接口确认、合并协调、整体装配和整机验收由 E 组织。A/B/C/D 各自完成模块实现、适配、测试及问题修复；A 的网络接入配合不等于负责全组统筹。

| 负责人 | 修改文件/接口 | 明确交付内容 |
| --- | --- | --- |
| A | Codes/server.py、protocol.py；网络与启动测试；报告网络章节 | 完成网络封装：失败统一 type:response、ok:false、error，保留 request_id；提供请求/断线回调和向目标 session 发送或广播的接口。按 E 的整体装配安排，配合接入 B 的处理器与断线回调；处理网络发送等待、慢连接和连接关闭，验证网络层 Ctrl+C 行为。负责网络问题排查及本人修改的测试和说明；不承担全组接口确认、合并协调或整体验收组织。当前本地失败封装修改尚未推送 |
| B | Codes/server_modules/question_bank.py、lobby.py、questions.json、对应测试 | 实现完整题库校验；hello(user_id,name)、用户/session 映射、活动 ID 唯一、目录与所有房间请求、ready/host/开赛条件、离开/断线/房主转移/房间生命周期；返回 v3 ROOM。hello.name 转为 PLAYER.display_name。向 E 主导的集成提供统一业务处理器及断线清理入口，由 A 配合网络接入，向 C 提供已验证题目和房间锁/玩家快照 |
| C | codex/game-engine 的 game_engine.py、scoring.py、test_game_engine.py 及接口说明 | 完成 6.1 三项事件/答案字段修改；不发未约定的 game_started，或另行全组确认后再加。保留 choice、index、display_name；内部 start_match 的 state:running 若仍返回应改 RUNNING。向 B 和 E 说明 create_match/start_match/submit_answer/disconnect_player/stop_match，并向 A 说明所需网络发送接口；处理事件发送失败和停服，避免线程死掉后房间永久 RUNNING |
| D | Codes/client_modules/connection.py、state.py；test_connection.py/test_state.py/test_client_regressions.py | 接收 question.index，映射到内部题号；读取 PLAYER/排行榜的 display_name；_make_error_response 统一失败 response。hello 继续发送 name，保留 data.room/host_user_id 和当前三种业务事件名。保留请求匹配、单 reader、发送锁、超时不自动重发、断线唤醒等待者 |
| E | Codes/client_modules/cli.py、client.py；tests/cli_demo_server.py、fake_server.py、test_cli.py；全组协议表、D/E 接口表及交付文档 | 负责全组统筹：收集并组织确认接口、维护最终协议、收集各人提交、协调合并、组织整体装配与官方 Docker 全流程验收、分派缺陷并汇总记录。组织 loader、业务处理器、断线清理、比赛事件和停服流程的装配，由 B/C 提供业务接口、A 配合网络入口。本人客户端修改：answer 发送 choice；排行榜读取 display_name；脚本对端、样例和测试对齐 v3；CLI 保留 --name，和 D 同步内部快照接口 |

内部变量无需机械改名：例如 D 的 PlayerInfo.name、host_user_id、快照中的 correct_answer 可保留，由网络边界映射，E 按约定快照读取。D/E 协调共有测试文件，D 主责连接/状态/回归，E 主责 CLI 和脚本对端，不能互相覆盖。

C 当前返回 accepted/data/error 是内部调用结果，不是完整网络消息。B 的业务路由负责转换为含 type/request_id/ok 的 response，E 统筹装配，A 按网络接口约定发送；不能直接 session.send(C的返回值)。start_game 成功按本表回复 data:{}，失败按统一 error 字段。业务函数返回前不能先关闭 socket，避免普通回复丢失；quit 最小流程是回复 bye:true 后由客户端断开，再走 A 的清理回调。

### 6.3 对应老师的强制要求与验收

依据 Coursework I Task Sheet.pdf 第 2–5 页功能/协议/题库要求、第 6–7 页文档与测试要求。具体协议名是本组选择；老师评估提交的 client/server 作为一对能否完成工作流。

| 老师要求 | 负责人 | 通过判据（最终在老师 Docker 中执行） |
| --- | --- | --- |
| Task 1：完整题库验证后才监听；成功打印 SERVER_READY；非法输入非零退出且不监听 | B loader，A 启动接线 | 真实 loader 好题库启动；空文件/超 1MB/坏 UTF-8/缺字段/类型范围/重复 ID 等拒绝；允许额外字段，options 恰为 A/B/C/D；提交题库至少 2 quiz × 5 题 |
| Task 2：多客户端身份和活动用户 ID 唯一 | A 接入、B 登记、D hello | 两客户端相同 ID，第二个明确失败，原用户正常；身份登记检查与写入必须原子完成 |
| Task 3：目录、建房、房间列表、加入、成员、ready、离开和按组内规则开始 | B 业务、D/E 客户端、A 接线 | 两个正式客户端完成上述操作；非房主、未 ready、错误房间等得到明确拒绝 |
| Task 4：服务器决定题序/计时、每题最多一答、关闭后揭晓、计分和最终排序 | C 核心、B 业务路由、A 网络发送、D/E 展示，E 统筹集成 | 正确/错误/迟到/重复/缺答路径；使用真实 time_limit/points；发题及目录不泄露答案 |
| Task 5：十客户端保持连接、两个独立房间，题目/事件/计时/分数不互相影响 | E 组织集成验收，A/B/C/D 各负责本模块问题 | 十个真实 TCP 客户端、两个比赛房间验收。echo 十连接或内存十玩家测试不能替代此证据 |
| Task 6：坏消息/非法命令/迟到重复/缺席/意外断线/Ctrl+C 不破坏其他会话或永久阻塞 | A 网络、B/C 业务清理、D/E 断线显示 | 错误后其他玩家/另一房间继续；发送或清理不能永久阻塞服务器；停服关闭连接并停止比赛线程 |
| 原生 TCP、处理拆分合并、区分响应/异步更新/错误，完整记录实际协议 | A/D 传输，E 组织全组确认并维护协议 | 多帧/半帧/混合 response与event、request_id 配对；失败以 ok:false 区分符合要求，老师未强制 type:error |

至少两名玩家、全员 ready、只有房主开赛、同分按 user_id 稳定排序是本组游戏设计规则，需在报告里说明，不能写成老师逐项指定。题库只许服务端读取是课程强制要求。

### 6.4 提交与联调顺序

1. E 收集各成员意见，组织全组确认 v3，维护最终协议表并记录变更；A 提供网络约束说明。未确认前不在报告写“全组协议已冻结”。
2. 各成员向 E 提供分支名、提交号、启动命令、测试结果和剩余问题；C 提交事件修改，D/E 分工提交客户端及脚本测试，B 提交题库/大厅，A 提交网络修改。E 协调合并顺序和接口冲突，各人修改自己的模块。
3. E 统筹将 loader、统一请求处理器、断线清理、C 事件回调与停服流程装配到正式入口；B/C 提供并适配业务接口，A 配合 server.py 的网络入口接入及网络问题排查。定义函数不会自动装配到 Server；整体装配的协调与验收责任属于 E。
4. E 组织两个真实客户端完成整局，再组织十客户端/双房间/错误/掉线/Ctrl+C 验收，将问题分派给对应模块负责人。各人提供本模块测试与说明，E 汇总老师 Docker 的镜像、源码版本、命令、预期与实际输出。
5. E 同步 CW1_D与E接口确定表.md、Codes/README.md、docs/E_client_guide.md 及报告；A 更新网络协议章节。docs/iface.md、docs/iface-doc.md 的旧副本标历史，不作为第二套现行标准。

当前分开的 main 54 项和 C 7 项测试通过，不代表 v3 改完或合并整机已验收。脚本客户端对端不是 B/C 正式实现。本文件只明确修改要求，没有替组员改代码、合并分支或发送群消息。
