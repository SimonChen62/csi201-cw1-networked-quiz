# CW1 D/E 接口确定表（2026-11-15 整合版）

基线：main@44cb8c0、B@5dc1ed1，加 codex/full-system-integration 的整合修改。对接人 D 卜凡洲、E 楼伊诺；服务端由 A 陈子谦、B 马雨辰、C 陆昕怡参与评审。

目前正式 server/client 已通过自动整机验收。下表记录实际代码，不替代全组人工确认；请成员回复同意或指出具体差异。完整协议以 [Codes/PROTOCOL.md](Codes/PROTOCOL.md) 为准。

## 1. 本地 API 和职责

| 事项 | 当前实现 | 后续确认 |
| --- | --- | --- |
| 客户端入口 | client.py 解析 --server/--port/--id/--name；调用 run_client | D/E 复核 |
| 收发 | D 的 Connection，原生 TCP、唯一接收线程、发送锁 | D 复核异常与超时策略 |
| 同步方法 | connect(host,port,id,name) → bool；send_request(type,data,timeout=5) → response | E 在请求工作线程调用，CLI 主循环不阻塞 |
| 事件与状态 | event_queue、get_snapshot() 深拷贝；网络线程先更新状态再交给 CLI | D/E 确认快照字段 |
| CLI | 输入线程仅投递命令，主循环显示题目/结果/错误 | E 维护；全员试用 |
| 权威规则 | 服务端控制身份、房间权限、ready、时间和分数 | A/B/C 复核 |
| 退出 | quit/EOF/Ctrl+C 关闭连接；远端关闭唤醒待处理请求 | 自动测试已覆盖，人工录像待补 |

Connection 内部生成字符串 request_id，调用者不要把 type/request_id 放进 data。普通请求默认 5 秒超时；超时表示执行结果未知，不自动重发。可用 players 刷新当前房间。

## 2. 实际消息约定

成功与失败均为 response，使用 ok 区分；主动消息为 event。失败不再使用 type=error。

~~~json
{"type":"response","request_id":"3","ok":false,"error":{"code":"ROOM_NOT_FOUND","message":"room does not exist"}}
{"type":"answer","request_id":"4","room_id":"R1","question_id":"NET001","choice":"B"}
{"type":"event","event":"question_result","data":{"room_id":"R1","question_id":"NET001","answer":"B","scores":{"u1":100}}}
~~~

| CLI / 操作 | 请求字段 | 成功结果 |
| --- | --- | --- |
| 自动登录 hello | user_id, name | user_id, name |
| quizzes / rooms | 无 | quizzes / rooms 列表 |
| create / join / players | quiz_id 或 room_id | data.room |
| ready [on/off] | room_id, ready 布尔值 | data.room 和 room_update |
| start | room_id；请求类型 start_game | 空 data；question 可能先于回复到达 |
| answer <qid> <A/B/C/D> | room_id, question_id, choice | accepted=true；不提前给正确答案 |
| leave | room_id | 空 data；本地清空房间 |
| quit | 无 | bye=true；客户端随后断开 |
| help/status/score | 无网络请求 | 本地显示 |

PLAYER 为 user_id/display_name/ready/score。ROOM 为 room_id/quiz_id/host_user_id/state/players，state 为 WAITING/RUNNING/FINISHED。D 内部快照仍可使用 name，网络字段使用 display_name。

| 事件 | 字段 |
| --- | --- |
| room_update | data 直接是 ROOM |
| question | room_id, question_id, index, text, options, time_limit, points |
| question_result | room_id, question_id, answer, scores |
| leaderboard | room_id, leaderboard（rank/user_id/display_name/score） |

index 从 0 开始；发题不含 answer/correct。房间事件包含 room_id；旧题回复不能标记新题已作答，外房事件不能更新当前房间。server_shutdown 当前由客户端在 EOF/网络失败时合成，服务器停服不保证另发一条通知。

## 3. 已完成验证和待交付

- 正式双人比赛、50 题目录、十客户端全程两房间、意外断线后的隔离、活跃比赛 SIGINT：已通过自动验收。
- C 的事件名和答案字段、E 的 choice 请求、B 的 typed bank、大厅处理器与正式入口：本分支已接通。
- 全组确认、每人实际操作及解释、视频和贡献声明：仍待完成。
- 记录见 [整合进展](docs/progress/2026-11-15-E-report-and-integration.md)，原始结果见 [测试日志](docs/evidence/2026-11-15-integration-unittest.txt)。

请 D 优先复核 connection/state 与新 test_paired_system.py 的真实收发；B/C 复核生命周期、时序和字段；A 复核网络超时和停服顺序；E 收集回复后再登记“全组确认”。
