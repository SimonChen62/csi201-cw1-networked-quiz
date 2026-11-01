# 证据记录 2026-11-01：成员 A 网络层在官方镜像中的验证

## 环境

| 项 | 值 |
| --- | --- |
| 镜像 | `csi201-cw1:latest`（examiner-provided） |
| 镜像内 Python | 3.12.15 |
| Docker 引擎 | 29.7.2 |
| 挂载方式 | `--mount type=bind,source=D:/Y3/csi201/cw1/Codes,target=/code` |
| 执行日期 | 2026-11-01 |

所有命令与结果均在上述镜像内产生，未使用本机 Python 解释器。

---

## E-01 单元与集成测试

命令：

```bash
docker run --rm --mount "type=bind,source=D:/Y3/csi201/cw1/Codes,target=/code" \
  csi201-cw1:latest -m unittest discover -s tests -v
```

结果：`Ran 29 tests in 1.528s` / `OK`

完整输出见同目录 `2026-11-01-docker-unittest.txt`。

覆盖范围：

| 测试文件 | 项数 | 验证内容 |
| --- | --- | --- |
| `test_protocol.py` | 4 | UTF-8/JSON 编解码、换行分帧、残留尾部保留、超 64 KiB 拒收、非对象 JSON |
| `test_server.py` | 4 | `ClientSession.send()` 成功/编码失败/已关闭 socket；两线程并发写同一连接时帧完整性 |
| `test_network.py` | 3 | **启动真实服务器子进程并建立真实 TCP 连接**：多请求往返、格式错误帧后连接仍可用、两个及十个客户端各自收到自己的响应 |
| `test_dispatch.py` | 3 | 坏帧后自定义处理器 + 定向事件 + 响应、广播只发给目标会话、临时客户端不把 event 当响应 |
| `test_disconnect.py` | 6 | 重复 close、关闭唤醒阻塞读、编码失败不断连、断线回调只触发一次、shutdown 等待回调结束、stop 后仍关闭连接 |
| `test_startup.py` | 7 | 题库先校验后监听、非法题库阻止启动、`--lab-mode` 与 `--questions` 互斥、缺参报错、绑定后打印 `SERVER_READY` |

因此 E-01 本身已包含真实网络证据（`test_network.py` 会启动真实服务器子进程并建立真实 TCP 连接），不是只有单元级检查。E-03 的额外价值是提供一份独立、可直接用于视频演示的运行记录。

## E-02 正式启动命令（当前失败）

命令：

```bash
docker run --rm --mount "type=bind,source=D:/Y3/csi201/cw1/Codes,target=/code" \
  csi201-cw1:latest server.py --host 0.0.0.0 --port 5000 --questions questions.json
```

输出：

```text
题库加载或校验失败：cannot import name 'load_question_bank'
from 'server_modules.question_bank' (/code/server_modules/question_bank.py)
```

退出码：`1`

符合"校验失败返回非零状态且不监听"的约定，但失败原因不是题库内容，而是**依赖模块尚未实现**。

## E-03 真实 TCP 往返（lab 模式）

命令：

```bash
docker run -d --rm --name cw1-a-lab --mount "type=bind,source=D:/Y3/csi201/cw1/Codes,target=/code" \
  csi201-cw1:latest server.py --host 127.0.0.1 --port 5000 --lab-mode
docker exec cw1-a-lab python tests/server_temp_test.py
```

服务端输出：

```text
LAB_LISTENING 127.0.0.1 5000
```

客户端输出：

```text
发出请求：{'type': 'echo', 'request_id': 1, 'text': 'hello server'}
发出请求：{'type': 'echo', 'request_id': 2, 'text': 'second message'}
收到响应：{"type": "response", "request_id": 1, "ok": true, "data": {"text": "hello server"}}
收到响应：{"type": "response", "request_id": 2, "ok": true, "data": {"text": "second message"}}
```

同一 TCP 连接上两条请求各自收到对应响应，`request_id` 保持配对。

---

## 缺陷记录

| 编号 | 描述 | 影响 | 状态 |
| --- | --- | --- | --- |
| DEF-001 | `server_modules/question_bank.py` 仍是占位文件，未提供 `load_question_bank`；`server.py` 的 `main()` 已引用该函数，导致正式启动命令立即退出 | 评分表「Docker start-up, CLI and question bank」6 分不可得；`SERVER_READY` 无法在正常路径出现 | 未修复。等待 B 实现**完整** schema 校验；在此之前保留明确失败，不以不完整校验换取启动成功 |
| DEF-002 | 启动测试全部通过 `question_loader` 参数注入替换 `load_question_bank`，缺少一层"不替换真实依赖"的启动集成检查 | 启动顺序与失败路径已被充分覆盖，但"真实模块能否被导入并返回已验证题库"这一环没有测试守卫，因此 29 项全绿可与 DEF-001 共存 | 待补：新增一条直接以 `server_modules.question_bank` 启动的集成测试 |

DEF-002 的成因**不是"用了模拟"**。注入 loader 是正确做法：它让启动顺序、非法题库拒绝、参数互斥这些路径可以被独立而快速地验证，不必真的准备十几种坏题库文件。缺的是另一层检查——不替换真实依赖，直接以真实模块启动一次。两层测试职责不同，缺一层就留下盲区。

同样地，DEF-001 的处置**不是**补一个只查顶层字段的简化实现。作业要求"完整题库验证通过后才监听"，只校验 `schema_version` 和 `quizzes` 就启动，会让非法题目通过，届时虽然消除了 `ImportError`，却违反了启动要求。当前明确的失败状态比伪装成合法更准确，也更符合"非法输入必须被拒绝"这一被评估行为。文档"验证与确认"章节应将这两条作为缺陷分析案例，并说明为何不采取临时打桩。
