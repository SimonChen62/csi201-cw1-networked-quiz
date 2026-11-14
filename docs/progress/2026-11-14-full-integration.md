# 2026-11-14 正式系统整合进展

> 后续更新：11 月 15 日合入 B@5dc1ed1 并通过 146 项复测，见 [最新进展](2026-11-15-E-report-and-integration.md)。本页保留 11 月 14 日的 145 项结果。

本轮基于 main@44cb8c0 和 B 分支@85ddeb9，在 codex/full-system-integration 中完成整合。主线的题库对象由 dict 迁移到 B 的 QuestionBank 接口，保留边界验证和真实启动回归。此记录描述实际实现与测试，不代替组员人工评审或最终提交。

## 完成内容

1. server.py 正式入口连接 Lobby.handle_request / on_disconnect，并配套计时器停止和等待。hello、目录、房间、ready/host、比赛、答题、结果和排名已能通过正式客户端完成。
2. C 的事件统一为 question / question_result / leaderboard，结果字段 answer，状态大写；CLI 答案请求使用 choice，显示 display_name。模拟对端及原测试同步更新。
3. 修复开赛登记与引擎启动之间允许新玩家加入/取消准备的窗口；记录并停止已删除房间的计时线程；一个发送失败的会话不阻止其他玩家收到事件。
4. 接受连接的 socket 操作限时 1 秒，空闲接收继续等待，发送失败关闭连接；格式错误及解析异常返回失败 response。
5. 使用 B 的 typed bank，同时保留有界读取、UTF-8 BOM、严格整数/Unicode/JSON、完整文件验证；公开目录排除题目/答案。
6. 更新提交版 README、实际协议、D/E 表和收件清单；报告后续使用组员提供的 v1.3 继续修订，具体交付见 11 月 15 日记录。

## 实际验证

**145 项全部通过，用时 38.408 秒。** 原始输出：[integration-unittest](../evidence/2026-11-14-integration-unittest.txt)。逐进程日志及各场景实际题库位于 [integration 证据目录](../evidence/2026-11-14-integration)。

| 验证场景 | 实际执行和结果 |
| --- | --- |
| 双人完整比赛 | server.py + 两个 client.py；原 questions.json；身份、host/ready、重复答案、正确/错误得分、排名、leave/quit 通过 |
| 老师 50 题 | 原 questions_50.json；真实客户端登录并显示 5 套各 10 题 |
| 十客户端全程两房间 | 十个独立 client.py 进程，5+5 分组；不同测验；全员完成比赛、正常退出；房间 A 全答对、房间 B 全答错，无串题/串分 |
| 十客户端中的意外断线 | 单独再执行一次十客户端场景；主动终止一人，其余九人及另一房间继续完成 |
| 权威计时和异常 | 正式服务器 + 诊断 TCP 对端；5 秒限时实测 5.001 秒；缺答 0 分、旧题拒绝、公开数据不泄漏答案、坏 JSON/NaN/嵌套坏 JSON/未知命令拒绝、超长连接隔离 |
| 活跃比赛停服 | 发送真实 SIGINT，server 返回 0、端口释放；真实 CLI 观察者不需额外输入即退出 |
| 整合边界 | 校验失败不创建 socket、最大题库边界、开赛并发预留、发送失败隔离、已删除房间计时器退出 |

十客户端验收使用真正的正式客户端进程，测试驱动只向其 stdin 输入命令并读取 stdout；客户端代码不读取题库。异常报文另由 WirePeer 注入，不能把它计作正式客户端。并发/计时场景的临时题库仅将原题目的 time_limit 改为规范允许的 5 秒，原数据不变；证据目录保存精确输入。

中途终止场景中 b4 的负退出码是测试主动 kill 的实际结果；全程比赛场景所有客户端和服务器正常退出。日志保持实际顺序，因此可能看到结果/下一题早于上一题普通答题确认；请求编号和题号保护已覆盖此时序。

首次整机试跑暴露了测试驱动的两项错误：把合法深嵌套 JSON 假定为解析错误，以及把无 request_id 的事件误当失败回复。已改为确定非法的嵌套报文，并同时按 type=response 和 request_id 匹配；最终上述结果为修正后真实重跑的输出。

## 环境与复现

用户已明确确认继续使用此前提供的 CSI201_CW1_Docker_Env。其 compose.yaml 使用课程 Dockerfile 构建；本轮使用该配置已有镜像，无第三方包安装。

| 项目 | 值 |
| --- | --- |
| 环境 | Linux 容器，Python 3.12.16 |
| 本机镜像标签 | csi201-cw1:verify-20261112（本机名称，不是下载地址） |
| 镜像 ID | sha256:1975c4441c8e913e8e0d55480244a7eb16bb65e4b89d80952793d3889c495529 |
| Docker | Desktop 4.99.0 (245822)，Engine 29.9.3 |
| 老师 Dockerfile SHA-256 | e9d3f9b8555901b35ee0a7baee3b1c53ac6617163d89ea5ae42210496ed010b9 |
| 老师 compose.yaml SHA-256 | 511305be415aa6f362855942ef68132aab434bb4494b821b1ae7208322d0af8e |
| 老师 questions_50.json SHA-256 | 46f1d17652dc242bbca3a7d47b550f71e571445e869085fa901cc2faa4033bb2 |

按 [Codes/README.md](../../Codes/README.md) 的 Docker 命令运行完整测试。若要重留逐进程日志，将证据目录挂载为 /evidence，增加环境变量 QUIZ_EVIDENCE_DIR=/evidence。代码挂载只读，临时题库写容器临时目录；没有外网依赖。

## 仍需人工完成

- A/B/C/D/E 复核本分支，确认实际协议、规则和各自贡献；自动通过不代表全员确认。
- 收齐组名、学号及全组确认的贡献比例，完善已有报告中的个人设计理由和引用，导出最终 Development_Documentation.pdf。
- 全员在指定环境中录制不超过 10 分钟的 Tasks 1–5 视频；实际截图、图示和个人讲解由成员按课程要求制作。
- 最终 PDF/视频就绪后，组长核对 Learning Mall 的归档名称、期限和视频上传位置，从最终 ZIP 解压复验并提交。

最终包的干净解压复验仍待 PDF 和视频材料齐全后完成。当前没有登录 Learning Mall、上传作业或替成员发送消息。
