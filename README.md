# ProQ2-EQ-Agent

面向编曲辅助的参数优化 Agent（2026 江苏省黑客松参赛项目，技术设计 v4.3）。

**一句话**：理解制作人的模糊自然语言指令（"让这个 lead 更亮一点"），自动在 FL Studio 里搜索 Fruity Parametric EQ 2 的参数，经感知反馈闭环迭代优化，直到音色达标。

## 架构

- **语义层**（LLM，只做规划）：理解指令 → 划定搜索边界 → 配置 Critic。不直接输出参数值。
- **参数层**（贝叶斯优化）：在给定边界内黑盒搜索 Gain/Freq。
- **Critic**：DSP 快循环每轮打分驱动优化器；CLAP 慢循环后台异步评估，结果进诊断不进优化目标。
- **DAW 控制**：经自研 MIDI 桥（`fl_bridge/device_ProQ2Bridge.py` + `core/fl_bridge.py` 的 `MIDIBridge`）直连 FL 官方 Scripting API 读写参数；音频经 VB-Cable 实时捕获。

## 快速开始

详见 [docs/SETUP_AND_TRANSFER.md](docs/SETUP_AND_TRANSFER.md)（从本机复制到你电脑、安装依赖、运行的全流程）。

> **Windows 调用规范**：所有命令都用虚拟环境的 Python，格式为
> `.venv\Scripts\python.exe scripts\xxx.py`（`.venv\Scripts\` 里的是解释器，
> 我们的脚本在项目 `scripts\` 目录下）。

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env          # 填入 AGNES_API_KEY
.venv\Scripts\python.exe -m pytest tests/ -q   # 单元测试（无需 FL）
.venv\Scripts\python.exe scripts/run_agent.py --instruction "让这个lead更亮一点"
```

## 目录

- `core/`：纯业务逻辑（不依赖 AGH），`agent.py` 为唯一编排入口
- `agh_plugin/`：真正的 AGH 后端工具插件（JS，比赛用，见其 README）
- `agh_adapter/`：Python 侧薄包装（本地/其他运行时用）
- `config/`：运行配置、提示词、Critic 配置 Schema
- `agh_adapter/`：AGH 插件适配（薄包装）
- `scripts/`：本地运行、参数 dump/标定、演示对比
- `tests/`：单元测试（无需 FL）+ 集成测试（需 FL，手动跑）
- `docs/`：技术设计文档、转移安装指南、会话备忘
