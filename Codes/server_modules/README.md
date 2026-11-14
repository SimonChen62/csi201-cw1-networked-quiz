# 服务端模块接口（2026-11-14 整合版）

- question_bank.py：B 的 QuestionBank/Quiz/Question 对象接口；E 在整合时保留有界读取、BOM、严格数值/Unicode/JSON 校验和真实启动回归。bank.public_list() 构造安全目录，bank.get_quiz(id) 返回测验，quiz.question_payloads() 生成仅供比赛引擎的含答案副本。
- lobby.py：B 的身份、房间、ready/host、统一处理器；整合补充开赛预留状态、发送失败隔离、比赛跟踪和 request_shutdown()/shutdown()。
- game_engine.py/scoring.py：C 的独立房间计时、答案、计分和排名；事件统一为 question/question_result/leaderboard，结算字段 answer；内部状态统一大写。
- server.main() 组装 Lobby，并把 handle_request/on_disconnect 传给 Server；题库在任何监听 socket 之前验证。SIGINT 依次停止业务、关闭网络、等待计时器。

create_business_handler(bank) 保留二元组 (request_handler, on_disconnect) 接口供已有测试使用。正式入口持有 Lobby 实例以调用停服方法。

完整字段、错误码、锁顺序和生命周期见 [PROTOCOL.md](../PROTOCOL.md)，启动命令见 [README.md](../README.md)。贡献归属需由组员根据实际提交和评审确认。
