# 2026-11-14 题库接入、验证与全组进展

本轮基于 `main@ca447f0`，提交分支为 `codex/question-bank-validation`。目标是补齐题库读取与完整校验、加入老师提供的 50 题文件，并恢复可验证的正式启动流程。本轮不把“能启动”登记成“完整比赛已完成”。

## 1. 本次交付

- `Codes/server_modules/question_bank.py`：实现 `load_question_bank(path)`；完整校验文件、顶层、测验及全部题目，返回保留顺序和扩展成员的顶层字典。错误包含字段位置。原 `server.main()` 已有调用位置，因此不需要改动网络入口。
- `Codes/questions_50.json`：原样加入老师环境中的题库，共 5 套测验、每套 10 题。保留原 `questions.json` 的 2 套 × 5 题；启动时用 `--questions` 选择。
- `Codes/tests/test_question_bank.py`：新增 21 项测试，包含边界与非法输入、完整文件验证、两份实际题库，以及真实服务器子进程启动与 TCP 连接。
- `Codes/tests/fake_server.py` / `test_connection.py`：补齐原测试夹具缺失的拆包、事件/回复合并、主动断线行为；默认使用空闲端口。断线断言要求 `CONNECTION_LOST`，避免将请求超时误判为主动断线。
- 更新开发 README、模块/测试说明和 E 收件清单，保存本轮测试及启动原始输出。

题库职责原归 B；本轮由 E 按补齐要求实现，后续由 B/C 复核 `bank["quizzes"]` / `quiz["questions"]` 接入方式。没有替其他组员确认协议、签署贡献比例或承诺交付时间。

## 2. 题库规则与边界

按任务书的 Required schema 检查：UTF-8 JSON 顶层对象、整数 `schema_version=1`、1～20 套测验、每套 5～50 题、ID 字符集和全文件唯一性、文本长度、ABCD 精确选项、答案枚举、5～60 秒和 1～1000 分。布尔值与浮点数不按整数接受。文件内最后一题也必须验证成功，才允许监听。

实现解释：文件的“1 MB”上限采用 **1,048,576 字节**；接受 UTF-8 开头 BOM。标题、描述与题目文本要求可打印，必填文本不能全为空白；选项按规范检查类型和长度。除选项对象外保留额外成员，不随机打乱测验或题目。加载器接受合法的单套题库；最终提交数据至少两套，是另一项提交要求。

返回对象包含正确答案，仅供服务端使用。B 构造公开目录时只能挑选 ID、标题、描述和题数；C 发题必须排除答案，关题后才揭晓。模块加载成功不等于这些业务消息已完成。

## 3. 实际环境与文件指纹

| 项目 | 本轮实际值 |
| --- | --- |
| 验证环境 | 按用户提供的课程 Dockerfile 构建的 Linux 容器 |
| 本机镜像标签 | `csi201-cw1:verify-20261112`（本机标签，不是公共下载地址） |
| 镜像 ID | `sha256:1975c4441c8e913e8e0d55480244a7eb16bb65e4b89d80952793d3889c495529` |
| Python | 3.12.16，镜像 ENTRYPOINT 为 `["python"]` |
| Docker | Desktop 4.99.0 (245822)，Engine 29.9.3 |
| 老师 Dockerfile SHA-256 | `e9d3f9b8555901b35ee0a7baee3b1c53ac6617163d89ea5ae42210496ed010b9` |
| 原文件和仓库 questions_50.json SHA-256 | `46f1d17652dc242bbca3a7d47b550f71e571445e869085fa901cc2faa4033bb2`（两者一致） |
| 题库规模 | 19,817 字节；geography、history、natural-science、literature-arts、math-logic 各 10 题 |

本轮未使用仓库自带的开发 Dockerfile。镜像内容及 Python 版本已读取核对，不能将其他机器上同名标签自动视为同一环境。老师文件、镜像和本地缓存不作为本次源码提交的一部分，只有题库数据加入仓库。

## 4. 测试结果与复现

### 全量自动测试

**84 项全部通过，用时 10.569 秒**：网络层 29、D 通信/状态 13、已有 D/E 回归与 CLI 14、C 引擎 7、新题库 21。原始结果见 [完整测试输出](2026-11-14-question-bank-unittest.txt)。

首次检查 84 项中有 2 项因模拟服务器未实现 half_packet/event_and_response 模式而失败；补齐测试夹具后重跑，得到上述结果。保持拆包后的内容、事件分发与状态更新断言；没有通过跳过测试来消除失败。

在自己的老师环境目录构建镜像，然后进入仓库 `Codes` 文件夹。以下 PowerShell 命令使用本轮标签；不同标签自行替换：

```powershell
$codePath = (Get-Location).Path
docker run --rm --network none --env PYTHONPYCACHEPREFIX=/tmp/test-pycache --mount "type=bind,source=$codePath,target=/code,readonly" csi201-cw1:verify-20261112 -X utf8 -B -m unittest discover -s tests -v
```

挂载为只读，缓存和临时无效题库写入容器临时目录；测试只使用容器内回环连接。题库回归测试实测校验失败前不创建 socket，合法题库使用真实入口启动。表中的测试数量按 unittest 方法计数，部分方法包含多个边界子用例。

### 正式入口实际检查

[启动原始输出](2026-11-14-question-bank-startup.txt) 记录：

1. 真实加载 `questions_50.json`，确认 5 套 / 50 题，输出 `SERVER_READY 127.0.0.1 36999`（测试采用系统分配端口）。
2. TCP echo 返回成功、请求编号匹配，验证服务已监听。
3. `hello` 返回 `ok=false / UNKNOWN_COMMAND`，证明身份/大厅路由尚未接入。
4. 对这个测试服务器发送 SIGINT，进程正常退出，退出码 0。
5. 临时把最后一题分值改成 1001，重新启动退出码 1，诊断 `quizzes[4].questions[9].points`，没有输出 SERVER_READY；老师原文件没有修改。

组员可在 `Codes` 目录运行下列命令观察正常启动：

```powershell
$codePath = (Get-Location).Path
docker run --rm -it --name cw1-bank-check --mount "type=bind,source=$codePath,target=/code,readonly" csi201-cw1:verify-20261112 server.py --host 127.0.0.1 --port 5000 --questions questions_50.json
```

另开 PowerShell 执行 `docker exec cw1-bank-check python tests/server_temp_test.py --message "hello"`，检查 echo；它不是正式登录客户端。启动窗口按 Ctrl+C 退出。完整启动/API 说明见 [Codes README](../../Codes/README.md)。

## 5. 当前全组完成情况与下一步

| 角色 | 已有且本轮可核验 | 仍需完成 |
| --- | --- | --- |
| A | TCP、分帧、请求交接、发送/断线处理；失败 response 封装；题库校验后真实启动 | 与 B/C/E 装配业务处理、身份/房间清理、比赛停止及全系统关闭 |
| B | 本分支代补的完整题库加载器及两份有效数据可接入 | `lobby.py` 仍为占位：hello、重复 ID、公开目录、房间、ready/host、离开/断线规则及测试 |
| C | 比赛引擎、计时、判分、拒绝重复/迟到、排名及 7 项模块测试 | 对齐 v3 目标事件与字段，正式接入 B/A/E，验证事件发送失败和比赛线程停止 |
| D | 通信、状态快照、13 项模块测试；display_name/index 与失败 response 修复 | 复核测试夹具修复，完成真实业务字段、超时和断线联调 |
| E | CLI/入口、既有客户端回归；本轮题库补齐、Docker 检查及进度文档 | 把 CLI 提交字段 answer 改成 v3 目标 choice 并同步模拟对端/测试；组织整体装配、验收、报告和视频 |

具体协议差异仍可在代码中看到：C 发 `question_open / question_closed / game_finished`，D/E 接收 `question / question_result / leaderboard`；C 结算答案字段为 `correct`，客户端期待 `answer`；CLI 提交选项仍使用 `answer`，v3 目标为 `choice`。这几项需要按 [分工计划第五、六节](../../CW1_系统流程与五人分工计划.md) 同步修改，全组确认状态仍待登记。

**下一步优先级：** B 交可运行大厅/房间处理器与断线接口；C 和 D/E 按约定对齐字段；A/E 装配正式入口；先跑通两名真实客户端的一局，再做至少十个真实客户端、两个同时比赛房间及异常/关闭验收。各成员继续提交报告、贡献声明和视频素材，E 汇总。

本轮消除了“缺加载器而无法正式启动”的阻塞。尚不能认定整个作业已经符合全部要求：10 条 echo 连接、C 的十名内存玩家及脚本对端流程，均不能替代十个真实客户端的完整系统证据。Development Documentation、视频和最终提交包仍需整合复验。
