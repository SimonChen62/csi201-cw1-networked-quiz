# 老师 Docker 配置复验记录 — 2026-11-12

用户于本轮明确确认 `CSI201_CW1_Docker_Env` 是老师提供的环境包。本次直接使用其中真正的 `Dockerfile` 构建新镜像，并重新执行测试；`__MACOSX/._*` 文件不是构建配置。旧 `csi201:latest` 的来源不因这次确认而被倒推认定，本记录独立保存新的验证结果。

## 配置来源与镜像

| 项目 | 记录 |
|---|---|
| 原始文件位置 | 用户提供的 `CSI201_CW1_Docker_Env/CSI201_CW1_Docker_Env/Dockerfile` 和 `compose.yaml` |
| Dockerfile SHA-256 | `E9D3F9B8555901B35EE0A7BAEE3B1C53AC6617163D89EA5AE42210496ED010B9` |
| compose.yaml SHA-256 | `511305BE415AA6F362855942EF68132AAB434BB4494B821B1AE7208322D0AF8E` |
| FROM（原样保留） | `docker.m.daocloud.io/library/python:3.12-slim` |
| 构建时解析的基础镜像 digest | `sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b` |
| 本轮独立标签 | `csi201-cw1:verify-20261112` |
| Docker inspect 返回的镜像 ID | `sha256:1975c4441c8e913e8e0d55480244a7eb16bb65e4b89d80952793d3889c495529` |
| 构建时间 | `2026-11-12T12:19:16.827007282Z` |
| 容器版本 | `Python 3.12.16` |
| 入口与目录 | 原配置 `ENTRYPOINT ["python"]`，`WORKDIR /code` |

原文件的环境变量 `PYTHONDONTWRITEBYTECODE=1 / PYTHONUNBUFFERED=1 / PYTHONUTF8=1` 保持不变。compose 中的 `csi201-cw1:latest` 是标签；本次给同一 Dockerfile 的构建产物使用独立验证标签，未修改 Dockerfile。为运行项目，把项目 Codes 挂至 /code，而非 compose 默认挂载的环境包目录。

`3.12-slim` 是浮动基础标签，本轮实际得到 3.12.16，旧本机记录是 3.12.14；因此同时记录源码版本、Dockerfile 哈希和基础镜像 digest。

## 实际结果

| 检查 | 代码版本 | 结果 | 原始证据 |
|---|---|---|---|
| main 全部测试 | `7d65143c6db4e8fc5dc54290da252c4b59106519` | `54 tests in 10.158s / OK`，退出码 0 | [main 输出](2026-11-12-official-main-unittest.txt) |
| C 新增模块测试 | `b87bcc48ab9306fcb45440587d5b6807cca49521`，独立检出 | `7 tests in 0.022s / OK`，退出码 0 | [C 输出](2026-11-12-official-game-engine-unittest.txt) |
| 正式服务器启动 | 同上 main | 退出码 1；无法导入 `load_question_bank`，未监听/未输出 SERVER_READY | [启动输出](2026-11-12-official-formal-startup.txt) |

main 的 54 项包括 A 原有 29、D 原有 11 和 E 接入增量 14；CLI 测试仍用脚本对端。C 的 7 项检查题目保密、正确/错误计分、迟到/重复、断线后的排行、房间隔离、最少人数、计时线程等，十玩家场景是内存中的玩家状态，不是 10 个 TCP 客户端。

两套代码分别测试，没有合并 C 分支来声称 61 项整机测试。正式业务尚缺 B 的模块及 A 的接线，D/E 与 C 还存在 v2 协议差异，见 [全组进度](../progress/2026-11-12-team-progress.md)。

## 复现命令

PowerShell 中将 `$courseEnv` 改成老师环境包中实际包含 Dockerfile 的目录；`$mainCodes` 和 `$gameCodes` 分别指向上表两个提交的 Codes 目录。

```powershell
$courseEnv = 'D:/桌面/CSI201_CW1_Docker_Env/CSI201_CW1_Docker_Env'
$mainCodes = (Resolve-Path './Codes').Path
# 在另一份独立检出 b87bcc4 的目录中取得 Codes 路径后填入：
$gameCodes = '<C 分支的 Codes 绝对路径>'
docker build --file "$courseEnv/Dockerfile" --tag csi201-cw1:verify-20261112 "$courseEnv"
docker run --rm --network none csi201-cw1:verify-20261112 --version
docker run --rm --network none --mount "type=bind,source=$mainCodes,target=/code,readonly" --workdir /code csi201-cw1:verify-20261112 -X utf8 -B -m unittest discover -s tests -v
docker run --rm --network none --mount "type=bind,source=$gameCodes,target=/code,readonly" --workdir /code csi201-cw1:verify-20261112 -X utf8 -B -m unittest discover -s tests -p test_game_engine.py -v
docker run --rm --network none --mount "type=bind,source=$mainCodes,target=/code,readonly" --workdir /code csi201-cw1:verify-20261112 server.py --host 127.0.0.1 --port 5000 --questions questions.json
```

最后一条在当前基线中预期失败，不能把它当成部署成功。容器内回环网络足够运行现有 TCP 测试；本次没有把源码、题库或测试输出上传到镜像仓库。

正式验收仍需：完整题库验证与登录/房间业务、v2 兼容、真实客户端完整一局、10 客户端与 2 独立房间、交互式 Ctrl+C、最终报告/视频及提交包复验。
