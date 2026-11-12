# CW1 D/E 接口确定表（与当前客户端实现对应）

更新日期：2026-11-12。对接人：D 卜凡洲、E 楼伊诺；服务端协议由 A 陈子谦、B 马雨辰、C 陆昕怡参与确认。

本表区分“本分支已经实现”与“仍需组员确认”。代码以 `codex/e-cli-integration` 分支为准。客户端可与脚本对端运行；B/C 的正式业务模块在本次基线中仍是占位文件，因此不能将以下业务字段称为全组已确认的最终协议。

旧草案中的 `client_ui.py`、`run_ui(api)`、返回请求编号的异步 API 和独立 `answer_result` 事件均已由下述实际接口替代。操作步骤见 [E 客户端指南](docs/E_client_guide.md)，测试与限制见 [验证记录](docs/evidence/2026-11-12-e-cli-validation.md)。

## 1. 职责与本地调用

| 编号 | 对齐事项 | 当前实现 | 待确认 |
|---|---|---|---|
| DE-01 | 入口 | E 本次补齐 `Codes/client.py`，解析 `--server --port --id --name`，调用 `run_client(host, port, user_id, name)` | D/E 复核入口和后续维护分工 |
| DE-02 | 网络 | D 的 `connection.py` 使用原生 TCP、公共 `protocol.py`，单一接收线程和发送锁 | D 复核本次响应、清理和状态适配修改 |
| DE-03 | 输入与输出 | E 的 `cli.py` 负责输入解析和显示；主循环统一输出，输入线程只投递输入 | 已实现；真实终端体验还需组员试用 |
| DE-04 | 同步调用 | 保留 D 的同步 `connect` / `send_request`；E 的请求线程执行，界面主循环持续处理事件 | 不在 UI 主循环直接等待请求 |
| DE-05 | 本地状态 | D 的 `ClientState` 加锁更新，E 只通过 `get_snapshot()` 读取副本 | 房间/题目字段由 B/C 再确认 |
| DE-06 | 规则权威 | CLI 检查命令格式和显式题号；权限、ready、迟到、重复和计分由服务器判定 | A/B/C 提供正式拒绝路径 |
| DE-07 | 退出 | 空闲时 `quit` 请求等待最多 1 秒；忙碌/登录中退出直接清理，EOF/Ctrl+C 也退出 | 全系统 Ctrl+C 和房间清理由 A/B/C/D 联调 |

| 实际 API | 调用方式与返回值 |
|---|---|
| `state = ClientState()` | 由 E 的 `run_client` 组装 |
| `connection = Connection(state)` | 绑定同一个状态对象 |
| `connect(host, port, user_id, name) -> bool` | 阻塞连接并发送 `hello`；仅登录成功才可操作；错误可查 `last_error` |
| `send_request(req_type, data, timeout=5.0) -> dict` | 返回匹配的成功/错误响应；`request_id` 在内部生成，不把 `type/request_id` 放入 `data` |
| `connection.event_queue.get_nowait()` | 取得主动事件或本地 `client_notice`；空队列抛 `queue.Empty` |
| `state.get_snapshot() -> dict` | 获得当前状态副本，不能通过修改副本改变内部状态 |
| `connection.disconnect()` | 取消连接、关闭 socket、唤醒待处理请求；接收线程最多等待 1 秒 |

连接等待上限 5 秒，普通请求默认等待 5 秒；操作系统域名解析不由 socket 超时保证。UI 退出另等待请求线程最多 1 秒，后台输入/请求线程为 daemon。断线清理、输入 EOF 和等待输入期间的服务器退出已有自动测试；实际交互式 Ctrl+C 待补人工记录。

## 2. 公共封装与请求映射

沿用 A 当前代码的 UTF-8 JSON Lines，每条消息以换行结束。客户端 `request_id` 是字符串，服务器应原样回传。

```json
{"type":"join_room","request_id":"3","room_id":"R1"}
{"type":"response","request_id":"3","ok":true,"data":{"room":{"room_id":"R1","quiz_id":"q1","host_user_id":"u1","state":"WAITING","players":[{"user_id":"u1","name":"Alice","ready":false,"score":0}]}}}
{"type":"error","request_id":"3","error":{"code":"ROOM_NOT_FOUND","message":"Room does not exist"}}
{"type":"event","event":"room_update","data":{"room_id":"R1","host_user_id":"u1","state":"WAITING","players":[{"user_id":"u1","name":"Alice","ready":true,"score":0}]}}
```

`response`、`error` 和 `event` 是三种外层类型；`question`、`room_update` 等放在 `event` 字段。A README 中的 `room_updated/question_open` 是封装示意，当前客户端实际消费的是本表中的名称。

**下面的业务内容是客户端当前期望的结构，尚待 B/C 确认。** 实际代码样例位于 `Codes/tests/cli_demo_server.py`；它只是单客户端脚本对端。

| CLI 命令 | 请求类型与字段（除 type/request_id） | 成功 `data` / 后续动作 | 确认人 |
|---|---|---|---|
| 启动自动登录 | `hello: user_id, name` | 对应成功响应；本地保存所提交身份 | A/B/D |
| `quizzes` | `list_quizzes` | `quizzes: [{quiz_id,title,description,question_count}]`；不含题目/答案 | B |
| `rooms` | `list_rooms` | `rooms: [{room_id,quiz_id,state,...}]`；空列表为 `[]` | B |
| `create <quiz_id>` | `create_room: quiz_id` | `room` 对象，见下表 | B |
| `join <room_id>` | `join_room: room_id` | `room` 对象；拒绝使用错误响应 | B |
| `players` | `inspect_room: room_id` | `room` 对象 | B |
| `ready [on/off]` | `ready: room_id, ready` | `room` 对象，并按需广播 `room_update` | B |
| `start` | `start_game: room_id` | 请求接受响应；随后广播 `question` | B/C |
| `answer <question_id> <A/B/C/D>` | `answer: room_id, question_id, answer` | `accepted:true`；不得提前公开正确答案/得分 | C |
| `leave` | `leave_room: room_id` | 成功即清除当前房间；不同比赛阶段能否离开由 B/C 定义 | B/C |
| `quit` | `quit` | 成功响应后关闭或直接断开；服务器需清理身份/房间 | A/B/C |
| `help/status/score` | 无网络请求 | 本地帮助/快照/最近服务器确认的分数 | D/E |

当前答题成功路径兼容省略 `accepted`（默认视为接受），正式协议建议明确返回布尔值。拒绝应发送 `type:error`；不要新增独立 `answer_result` 而不通知 D/E。请求超时表示“执行结果未知”，不会自动重发。

## 3. 房间、事件和快照字段

| 对象/事件 | 当前客户端消费的字段 | 语义及待确认项 |
|---|---|---|
| `data.room` | `room_id, quiz_id, host_user_id, state, players`；每位玩家 `user_id,name,ready,score` | 建房/入房必须有 room_id、host_user_id、players；B 确认完整房间视图及房主转移 |
| `room_update` | `data` 直接为房间视图，不再嵌套 `room` | 更新成员、房主、阶段；不清除正在显示的题目 |
| `question` | `room_id, question_id, question_index, text, options, time_limit, points` | options 为 A/B/C/D 字典；不得带正确答案；C 确认 question_index 从 0 或 1 起 |
| `question_result` | `room_id, question_id, answer, scores` | answer 为正确选项；scores 为 `{user_id:累计分数}`；只在题目关闭后发送 |
| `leaderboard` | `room_id, leaderboard:[{user_id,name,score,rank}]` | 最终结果，进入 FINISHED；服务器排序，rank 可省略则按列表顺序显示 |
| `server_shutdown` | `reason` | 关闭提示；本地断线也用此事件通知界面 |
| 本地 `client_notice` | `code,message` | 超时后的迟到响应、未匹配响应等提示；不是新增服务器命令 |

`question_result` 当前不展示“本人答案/本题增量/中途排名”；如 C 提供这些字段，需同步扩展 UI 和测试。当前 `score` 展示最近服务器确认的累计分数。不同用户的个人化字段不能被原样广播给所有玩家。

快照包含 `connected,user_id,display_name,available_quizzes,available_rooms,current_room_id,quiz_id,host_user_id,is_host,room_phase,players,current_question,has_answered,last_result,leaderboard`。注意快照中题目 ID 的键是 `current_question.id`，网络消息中是 `question_id`；结果快照中的 `correct_answer` 对应网络消息中的 `answer`。

## 4. 本次已实现的边界与剩余工作

| 编号 | 行为 | 本分支实现 / 验证范围 | 仍需完成 |
|---|---|---|---|
| DE-08 | 服务器拒绝 | `type:error` 按 request_id 返回，不再被当成超时 | D 复核错误接口 |
| DE-09 | 请求资源 | 成功、失败、超时后清理 pending；断线唤醒请求 | 真实长时间运行 |
| DE-10 | 推送与输入 | 等待输入时仍显示题目、结算、断线 | 多个真实终端试用 |
| DE-11 | 跨题输入/确认 | 答题必须写明题号；旧题确认不标记新题已答 | C 用真实比赛验证 |
| DE-12 | 已接受后重复提交 | 重复错误不清除已接受标记 | C 实现重复/迟到判断 |
| DE-13 | 房间隔离 | 有 room_id 的外房事件被忽略；旧结算不关闭新题 | B/C 所有房间事件必须带 room_id；旧测试缺字段兼容不作为正式约定 |
| DE-14 | 快照与顺序 | 状态在消息接收线程先更新；目录与排行榜深拷贝 | D 复核；房间显示使用最新快照，题目/结果用各自事件数据 |
| DE-15 | 超时恢复 | 不自动重发；迟到响应仅提示，不恢复未知业务状态 | 建房/入房超时可能无法用 players 恢复，需 B/D 增加身份/房间查询或定义重连规则 |
| DE-16 | 端到端 | 脚本对端覆盖一轮客户端流程 | 正式服务器、完整题库、10 客户端、2 独立房间仍待联调 |

## 5. 请各人填写确认结论

| 确认人 | 本轮优先确认内容 | 结论 / 变更 / 可联调日期 |
|---|---|---|
| A | error/event 封装、业务路由、断线回调及启动接线 | 待填写 |
| B | hello、目录、data.room、ready、room_update、离开/房主转移 | 待填写 |
| C | question/result/leaderboard、答题接受响应、计时和结算顺序 | 待填写 |
| D | 同步 API、event_queue、状态快照、此次 connection/state 补丁 | 待填写 |
| E | CLI 已有可运行版本；按组员确认结果调整并组织正式联调 | 本分支可开始客户端试用 |

改字段时请同时提交实现、样例和测试，并在本表记录变更。此表描述实际客户端和待确认约定，不把参考协议附录的示例作为额外课程硬性要求。