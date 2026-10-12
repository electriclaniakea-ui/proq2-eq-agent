# ProQ2-EQ-Agent AGH 插件 / AGH Plugin (v5.2.0)

AGH 后端工具插件：让 Agnes Harness 的 Agent 直接调用 ProQ2-EQ-Agent 的
Python 流水线，在 FL Studio 里做智能 EQ 参数优化。
Backend tool plugin for Agnes Harness: lets the AGH agent call the
ProQ2-EQ-Agent Python pipeline to do intelligent EQ parameter
optimization inside FL Studio.

## 提供的工具 / Tools

| 工具 Tool | 作用 Purpose |
|---|---|
| `eq_analyze` | 分析当前 EQ 状态（只读）/ Analyze current EQ state (read-only) |
| `eq_optimize` | 运行完整优化循环（写 DAW 参数，需审批）/ Run the full optimization loop (writes DAW params, requires approval) |
| `eq_confirm_candidate` | 确认候选参数并应用 / Confirm and apply a candidate |
| `eq_rollback` | 回滚到上一次确认的参数 / Roll back to the last confirmed parameters |

`eq_optimize` / `eq_confirm_candidate` / `eq_rollback` 会写 DAW 参数，
已如实声明 `isDestructive: true`、`requiresApproval: 'always'`。
These three write DAW parameters and are declared `isDestructive: true`,
`requiresApproval: 'always'`.

## 安装 / Installation

1. 在你的电脑上装好 AGH（Agnes Harness，pre-alpha，需从源码构建；
   Node ≥ 24.10）。
   Install AGH (pre-alpha, build from source; Node ≥ 24.10).
2. 先按项目根目录 `docs/SETUP_AND_TRANSFER.md` 跑通本地闭环
   （`install.bat` → `test.bat` → `run_agent.py`）。
   First get the local closed loop working per `docs/SETUP_AND_TRANSFER.md`
   at the project root (`install.bat` → `test.bat` → `run_agent.py`).
3. 设置环境变量（AGH host 进程必须可见）/ Set environment variables
   (visible to the AGH host process):
   - `PROQ2_PROJECT_DIR` = 本项目目录 / the project directory
     （例 / e.g. `D:\hackathon\proq2-eq-agent`）
   - `PROQ2_PYTHON` = 项目 venv 的 Python
     （例 / e.g. `D:\hackathon\proq2-eq-agent\.venv\Scripts\python.exe`）
4. AGH → Settings → Plugin management → 从本地路径安装本目录
   → 检查 → 信任 → 启用。
   Install from this local directory → check → trust → enable.
5. 新开 session，确认四个工具已注册。
   Open a new session and confirm the four tools are registered.

## 备注 / Notes

- `eq_optimize` 单次约 2~3 分钟，插件侧超时设为 10 分钟。
  `eq_optimize` takes ~2–3 min per run; the plugin-side timeout is 10 min.
- 插件只是薄封装，所有逻辑在 Python 侧（`scripts/run_agent.py` /
  `scripts/session_tool.py`）。
  The plugin is a thin wrapper; all logic lives in Python.
- AGH 是 pre-alpha，若你安装时的官方文档与本插件有出入，
  以当时的 `docs/develop/backend.md` 为准。
  AGH is pre-alpha; if the official docs at your install time differ,
  follow `docs/develop/backend.md` at that time.
