# 接口与消息字段（冻结版 v3）

B/C/D/E 照此实现。改字段先改本节，再通知全组。

## 1. 传输

一行一个 UTF-8 JSON 对象，`\n` 结尾。单帧上限 64 KiB。

## 2. 两类消息

```json
{"type":"response","request_id":"1","ok":true,"data":{}}
{"type":"response","request_id":"1","ok":false,"error":{"code":"ROOM_NOT_FOUND","message":"..."}}
{"type":"event","event":"question","data":{}}
```

- 失败也是 `response`，不另设 `type:"error"`
- `request_id` 由客户端生成，字符串（`"1"`、`"2"`…），服务端原样回带，不解析其类型
- 帧根本解析不出对象时 `request_id` 为 `null`
- `event` 不带 `request_id`、不带 `ok`

## 3. 命名约定

| 项 | 规则 |
| --- | --- |
| 字段名 | 全小写 snake_case（`room_id`，不是 `roomId`） |
| 所有 id | 字符串（`quiz_id` / `question_id` / `room_id` / `user_id`） |
| 选项 | 单字符大写 `A` `B` `C` `D` |
| 分数、题号、人数 | 整数 |
| 秒数 | 整数（`time_limit`） |
| 布尔 | `true` / `false` |
| 请求字段 | 与 `type`、`request_id` 平级，不套 `data` |

## 4. 对象形状

`PLAYER` = `{"user_id","display_name","ready","score"}`

`ROOM` = `{"room_id","quiz_id","host_user_id","state","players":[PLAYER]}`

`state` 取值：`WAITING` / `RUNNING` / `FINISHED`

## 5. 请求 → 响应

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

`echo` 只用于联调，不参与业务流程。

## 6. 事件

| event | data |
| --- | --- |
| `room_update` | `ROOM`（含 `room_id`） |
| `question` | `{"room_id","question_id","index","text","options":{"A","B","C","D"},"time_limit","points"}` |
| `question_result` | `{"room_id","question_id","answer","scores":{"user_id":整数}}` |
| `leaderboard` | `{"room_id","leaderboard":[{"rank","user_id","display_name","score"}]}` |
| `server_shutdown` | `{"reason"}` |

`question` **不得**含 `answer`。答案只在 `question_result` 出现。

## 7. 失败码（放在 response.error.code）

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

除 `MESSAGE_TOO_LARGE` 外，所有失败都**保持连接**。

## 8. 最小闭环（11-22 验收）

```
hello → list_quizzes → create_room → join_room → ready → start_game
→ question → answer → question_result → leaderboard
```

任一步失败，先查字段名与本节是否一致。
