# E 客户端验证记录 — 2026-11-12

> 后续更新：用户已确认老师环境包，本轮另用其原始 Dockerfile 新构建并复验。main 54 项、C 分支 7 项分别通过，详情见 [官方环境复验记录](2026-11-12-official-env-validation.md)。以下保留此前 `csi201:latest` 的历史结果，不倒推更改旧镜像来源。

本次针对 `codex/e-cli-integration` 的客户端增量，基线为 `main@b2d6b72b775cfa5d7b8f774e4315696cebcc3558`。最终被验证的源码随本记录一并提交，可由 Git 历史定位。未把未执行项目标为通过。

## 实际执行环境与结果

| 项目 | 实际记录 |
|---|---|
| 宿主 | Windows，Docker Desktop Linux 容器 |
| 本机镜像标签 | `csi201:latest` |
| 镜像 ID | `sha256:4efdb970306c4c56d3bc4cf438b7399bf3a46d6653f3d3c1751ecc297653222e` |
| 镜像创建时间 | `2026-09-10T11:26:28.303882675Z` |
| 容器 Python | `Python 3.12.14` |
| 官方来源 | 待用户/小组确认；仅镜像名和测试通过不能证明它是 examiner image |
| 执行结果 | `Ran 54 tests in 10.493s / OK`，Docker 返回码 0 |
| 原始输出 | [完整测试日志](2026-11-12-e-cli-docker-unittest.txt) |

在仓库根目录的 PowerShell 中可复现（镜像应已存在，路径按当前目录自动取得）：

```powershell
$codesPath = (Resolve-Path './Codes').Path
docker run --rm --network none --entrypoint python3 csi201:latest --version
docker run --rm --network none --mount "type=bind,source=$codesPath,target=/code,readonly" --workdir /code --env PYTHONDONTWRITEBYTECODE=1 --entrypoint python3 csi201:latest -X utf8 -B -m unittest discover -s tests -v
```

源码以只读方式挂入容器，测试客户端与对端在容器内用回环 TCP 通信，无需外部网络或发布端口。日志中的 Broken pipe、模拟业务清理失败、无法编码响应来自故障路径测试，应结合对应测试的 `ok` 和最终结果阅读。

此前在 Windows / Python 3.12.14 上已跑通 53 项；随后增加一项“不完整题目事件”回归并调整答题提示/超时边界，本表中的 54 项 Docker 结果对应最终代码。正式结论以本表及原始输出为准。

## 覆盖范围

| 范围 | 对应检查 | 结果 / 限制 |
|---|---|---|
| A 原有网络层 | 29 项原有测试 | 通过；echo 和假加载器不代表业务完成 |
| D 原有连接与状态 | 11 项原有测试 | 通过 |
| D/E 接入边界 | 11 项新增回归 | error 匹配、pending 清理、超时不重发、迟到确认、房间/题目边界、快照、题号输入通过 |
| CLI 操作流程 | test_cli 的完整脚本流程 | 登录、目录、无效房间、建房、未准备拒绝、准备、开始、旧题拒绝、答题/重复、结果/排名、离开/退出通过 |
| 输入空闲时接收消息 | CLI 等待 stdin 时等待结算，另有断线测试 | 无需再按回车即可显示结果并处理断线 |
| EOF | CLI 子进程关闭 stdin | 正常退出 |

客户端业务测试使用 `tests/cli_demo_server.py`：一个真实客户端连接、一个模拟玩家、一道测试题。它不是完整题库或正式 B/C 模块，不能算作十个真实客户端或双房间比赛。

## 仍待完成的正式验收

- B 的完整题库校验、身份和大厅；C 的计时、计分与比赛生命周期。
- A/B/C 的正式请求路由与断线回调，真实 server/client 完整一局。
- 在确认来源的官方镜像中，用至少 10 个实际客户端验证 2 个独立房间，以及迟到、缺答、异常输入、断线和 Ctrl+C。
- 超时后未知房间状态的恢复规则、真实终端使用记录、最终报告/视频和提交包复验。

本分支的 D 文件修改由 E 接入需要触发，仍请 D 复核；服务端业务字段以 [D/E 接口表](../../CW1_D与E接口确定表.md) 的待确认条目为准。
