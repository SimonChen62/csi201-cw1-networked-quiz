# Networked Quiz Tournament — 运行与提交说明

2026-11-14 整合版本：基于 main@44cb8c0 和 B 分支@85ddeb9，接通 A 网络层、B 题库/大厅、C 比赛引擎及 D/E 正式客户端。145 项测试通过，含真实客户端双人比赛、十客户端双房间、计时和异常关闭。全组人工复核、报告定稿和视频仍待完成。

## 1. 环境和启动

运行要求：课程提供的 Docker 环境，Python 3.12，仅标准库、原生 TCP socket、纯命令行。无需 pip、数据库或外部服务。只有服务器读取题库，客户端不打开题库文件。以下命令从提交包的 Codes 目录执行。

服务器：

~~~bash
python3 server.py --host 127.0.0.1 --port 5000 --questions questions.json
~~~

客户端（每位玩家开独立终端，使用不同 ID）：

~~~bash
python3 client.py --server 127.0.0.1 --port 5000 --id u1 --name Alice
python3 client.py --server 127.0.0.1 --port 5000 --id u2 --name Bob
~~~

合法题库完整校验且监听成功后输出 SERVER_READY 127.0.0.1 5000。题库无效时输出具体诊断、退出码 1，不监听。端口由参数指定；服务器的端口 0 仅供自动测试分配空闲端口。--lab-mode 是保留的 echo 开发模式，正式运行使用 --questions。

本轮按用户确认的课程环境运行：Docker Desktop 4.99.0 / Engine 29.9.3；Python 3.12.16；本机镜像标签 csi201-cw1:verify-20261112。标签是本机名称，组员使用自己按同一课程环境准备的对应标签。

PowerShell 中先进入 Codes，再启动容器：

~~~powershell
$codePath = (Get-Location).Path
docker run --rm -it --name cw1-run --mount "type=bind,source=$codePath,target=/code,readonly" csi201-cw1:verify-20261112 server.py --host 127.0.0.1 --port 5000 --questions questions.json
~~~

分别在两个新终端运行：

~~~powershell
docker exec -it cw1-run python3 client.py --server 127.0.0.1 --port 5000 --id u1 --name Alice
docker exec -it cw1-run python3 client.py --server 127.0.0.1 --port 5000 --id u2 --name Bob
~~~

客户端和服务器均在同一容器，用回环地址通信，不需要宿主机端口映射。老师镜像以 Python 为 ENTRYPOINT，docker run 的镜像名后不要重复加 python；docker exec 需要写解释器。跨容器部署时应给服务器绑定可达地址并提供相应网络配置，本轮证据仅覆盖同容器多进程。

## 2. CLI 命令摘要

| 命令 | 用途 |
| --- | --- |
| help | 显示帮助 |
| quizzes / rooms | 列出测验 / 可加入的等待房间 |
| create <quiz_id> | 为测验创建房间 |
| join <room_id> | 加入等待房间 |
| players | 刷新房间成员、房主、准备状态和分数 |
| ready / ready off | 准备 / 取消准备 |
| start | 房主请求开赛 |
| answer <question_id> <A/B/C/D> | 提交明确题号的答案 |
| score / status | 显示最近确认的分数 / 本地状态 |
| leave | 离开房间 |
| quit | 确认退出并关闭连接 |

两人演练：Alice 执行 quizzes、create network-basics；Bob 执行 rooms、join R1（以实际房间号为准）；两人执行 ready；Alice 执行 start。每题出现后使用实际题号答题，例如 answer NET001 B。等待结果和排行榜后 leave / quit。

## 3. 游戏规则和假设

- 活动 user_id 唯一；重复登录返回 DUPLICATE_USER，原用户继续工作。ID 不接受首尾空白；ID 和显示名为 1～64 个可打印字符。显示名可重复，身份以 user_id 和来源连接确定。
- 每人至多处于一个房间；CLI 要求先 leave 再进入另一个房间。只有 WAITING 房间接受新玩家。
- 至少两名玩家、所有当前玩家 ready，且请求者是房主，才可开赛。开赛登记与检查受到锁保护。
- 房主离开后转给剩余 user_id 中字典序最小者；最后一人离开时删除房间。FINISHED 房间不能重开，离开后创建新房间。
- 按题库顺序发题；每个房间独立计时、保存答案和分数。服务器以单调时钟为准，到期或所有仍在线玩家已答题时关题。
- 每题只接受每名玩家第一次、当前题号、截止前的合法答案；答对加题目 points，答错或未答为 0；重复、迟到或旧题提交被拒绝，不覆盖先前有效答案。
- 关题前不公布正确答案。最终排名先按分数降序，再按 user_id 升序，名次为顺序编号。断线玩家保留已得分并留在排行榜。
- quit、EOF、客户端 Ctrl+C 都关闭连接；服务器 Ctrl+C 停止监听、关闭连接并停止/等待比赛线程。客户端空闲时无需再按回车即可收到题目、结果或断线通知。

## 4. 题库和服务端接口

questions.json 为最终默认数据（2 套 × 5 题），符合至少两套、每套至少五题的要求；questions_50.json 保留老师提供的 5 套 × 10 题原文件，可通过 --questions questions_50.json 选择。

load_question_bank(path) 返回 B 的 QuestionBank 对象；bank.quizzes 保持文件顺序，bank.get_quiz(id) 查找测验，bank.public_list() 只提供公开目录。quiz.question_payloads() 为比赛生成含答案的副本，只能用于服务端；不要直接发给客户端。

完整校验文件及所有测验/题目：UTF-8（支持初始 BOM）、顶层和必填字段、整数 schema_version=1、数组数量、ID 格式与唯一性、文本/选项长度、ABCD、时间和分值。整数不接受布尔值或浮点数。文件大小上限按 1,048,576 字节解释，读取量有上限；标题/描述/题目按字符数检查，必填文本非空白且不含控制字符；选项按 1～200 字符检查。除 options 的精确键外允许并忽略扩展成员。错误抛 OSError 或 ValueError，在创建监听 socket 前处理。

正式 main 创建 Lobby(bank)，将 handle_request 和 on_disconnect 传给 Server。Lobby 向 GameEngine 提供房间锁、玩家快照和房间事件发送函数；停服先通知计时器停止，再关闭网络及清理会话，最后等待计时线程。

## 5. 协议与模块

实际消息目录、例子、线程关系及错误码见同目录 [PROTOCOL.md](PROTOCOL.md)。请求/事件字段已统一为 v3 实现；这是当前实现记录，仍需全组人工评审，不表示已代替成员确认。

| 文件/目录 | 职责 |
| --- | --- |
| server.py / protocol.py | 原生 TCP、JSON Lines、连接、发送锁、分发与关闭 |
| server_modules/question_bank.py | 加载器、QuestionBank/Quiz/Question、公开目录 |
| server_modules/lobby.py | 身份、房间、ready/host、业务路由和生命周期 |
| server_modules/game_engine.py / scoring.py | 单房间计时、答案、结算和排名 |
| client.py / client_modules/cli.py | 参数、输入/输出、菜单和异步请求工作线程 |
| client_modules/connection.py / state.py | 唯一网络接收线程、请求匹配、事件和线程安全状态 |
| tests/ | 模块、回归、真实多进程验收和测试专用对端 |

## 6. 测试和证据

在课程容器内 Codes 目录运行：

~~~bash
python3 -B -m unittest discover -s tests -v
~~~

从宿主 PowerShell 的 Codes 目录运行同一套测试：

~~~powershell
$codePath = (Get-Location).Path
docker run --rm --network none --env PYTHONPYCACHEPREFIX=/tmp/test-pycache --mount "type=bind,source=$codePath,target=/code,readonly" csi201-cw1:verify-20261112 -X utf8 -B -m unittest discover -s tests -v
~~~

2026-11-14 本轮 145 项全部通过（38.408 秒）。其中 test_paired_system.py 运行正式 server.py / client.py：原题库双人完整比赛、老师 50 题登录/目录、十客户端全程双房间、另一次十客户端中途断线隔离，以及诊断对端的限时/非法报文/关闭检查。5 秒限时实测 5.001 秒。所有控制输入由测试驱动写入真实客户端 stdin，不以假客户端替代十进程验收；异常报文另用诊断 TCP 对端注入。

测试默认写临时目录；设置 QUIZ_EVIDENCE_DIR 可保存实际终端日志和该次题库。并发与超时场景使用基于默认题库生成、每题 5 秒的合法临时数据；双人场景直接使用未改动的 questions.json，50 题场景使用原 questions_50.json。仓库 docs/evidence 保存日志；最终报告应选取必要结果，不把开发目录全部打包。

## 7. 已知限制与提交注意

- 无 GUI、账户密码、TLS、数据库、自动重连或断线恢复；用于课程可信测试网络。题库里的答案在服务器内存中，不发送到活动题目中。
- 请求默认超时 5 秒，超时表示结果未知，不自动重试状态变更操作。可用 players/rooms 刷新；失去连接需重新启动客户端。
- 接收帧上限 64 KiB；每个已接受 socket 的阻塞操作限时 1 秒，空闲接收超时继续等待，发送超时关闭该连接。没有全局连接配额或完整防滥用机制。
- 房间列表只列可加入的 WAITING 房间。并发成员变动时可用 players 刷新最新视图。CLI 显示限时，不逐秒刷新倒计时。
- 自动验收使用 Linux 容器中的回环网络和进程信号；人工多终端体验、全员讲解视频及报告审核仍需完成。
- 最终 ZIP 必须包含 Codes 和 Documentation/Development_Documentation.pdf。不要放入 Dockerfile、docker-compose.yml、镜像、.git、缓存、虚拟环境、IDE 配置、__MACOSX/.DS_Store 或无关文件。README/PROTOCOL 和测试依赖模块应保留。
