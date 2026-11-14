# E 客户端操作说明（2026-11-15 整合版）

正式 server.py 已接入 B/C 业务，客户端可完成登录、房间、准备、答题、结算和排名。当前准确命令、CLI 表、两人示例、规则和已知限制统一见 [Codes/README.md](../Codes/README.md)；该文件可独立放入最终提交包。

协议以 [Codes/PROTOCOL.md](../Codes/PROTOCOL.md) 为准：答题发送 choice，公开玩家名称使用 display_name，事件为 question/question_result/leaderboard。输入仍为 answer <question_id> <A/B/C/D>。

tests/cli_demo_server.py 仅保留为客户端回归测试夹具；正式演示及整机验收使用 server.py --questions questions.json。十客户端证据来自十个真正的 client.py 子进程，见 [进展与日志](progress/2026-11-15-E-report-and-integration.md)。

D 维护收发与状态，E 维护入口/CLI 并组织集成。自动验证已完成；全员人工试用、视频讲解和报告确认仍待完成。
