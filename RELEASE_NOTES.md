# ProQ2-EQ-Agent v1.0.0 发行说明 / Release Notes

发布日期 / Released: 2026-10-12

## 这是什么 / What is this

面向编曲辅助的参数优化 Agent：理解制作人的模糊自然语言指令
（"让这个 lead 更亮一点"），自动在 FL Studio 里搜索
Fruity Parametric EQ 2 的参数，经感知反馈闭环迭代优化，直到音色达标。
An EQ parameter optimization agent for music production: it understands
vague natural-language instructions from a producer (e.g. "make this lead
brighter") and automatically searches Fruity Parametric EQ 2 parameters
inside FL Studio through a perceptual feedback loop until the timbre
meets the target.

技术设计 v4.3；AGH 插件 v5.2.0。
Technical design v4.3; AGH plugin v5.2.0.

## 包含内容 / Contents

- `core/`：纯业务逻辑（LLM 规划 / 贝叶斯优化 / DSP+Critic / MIDI 桥）
  Business logic: LLM planning, Bayesian optimization, DSP+CLAP critics, MIDI bridge
- `config/`：运行配置、提示词、Critic 配置 Schema / Runtime config, prompts, schemas
- `scripts/`：本地运行、参数 dump/标定、演示对比
  Local runs, parameter dump/calibration, demo comparison
- `fl_bridge/`：FL Studio 侧 MIDI 控制器脚本 / FL Studio-side MIDI controller script
- `agh_plugin/`：AGH 后端工具插件 v5.2.0（4 个工具，见其 README）
  AGH backend tool plugin v5.2.0 (4 tools, see its README)
- `agh_adapter/`：Python 侧薄包装 / Thin Python-side adapter
- `skills/proq2-eq-workflow/`：Agent 工作流 Skill / Agent workflow Skill
- `tests/`：单元测试（无需 FL）+ 集成测试（需 FL，手动跑）
  Unit tests (no FL needed) + integration tests (need FL, run manually)
- `docs/SETUP_AND_TRANSFER.md`：从安装到运行的全流程指南（必读）
  Full guide from install to run (must read)
- `Agent-4-technical-design.md`：技术设计文档 / Technical design document

## 系统要求 / Requirements

- Windows 10/11，Python 3.10+
- FL Studio 20.7+（需安装 Fruity Parametric EQ 2，官方自带）
- Agnes API key（填入复制自 `.env.example` 的 `.env`）
- 可选 / Optional: VB-Cable（实时音频捕获）、Node ≥ 24.10（仅 AGH 插件接入需要）

## 快速开始 / Quick start

```powershell
install.bat                    # 一键安装依赖（自动建 .venv）/ one-click setup
test.bat                       # 跑单元测试 / run unit tests
copy .env.example .env         # 填入 AGNES_API_KEY / fill in your key
.venv\Scripts\python.exe scripts\install_midi_bridge.py # 装 FL 侧 MIDI 桥脚本 / install FL-side MIDI bridge script
.venv\Scripts\python.exe scripts\run_agent.py --instruction "让这个lead更亮一点"
```

详见 / Details: `docs/SETUP_AND_TRANSFER.md`

## 已知限制 / Known limitations

1. **参数标定**：`assets/eq2_params.json` 是模板；换一台电脑/FL 版本后
   建议重跑 `scripts/calibrate_param_mapping.py` 做一次标定。
   The bundled `eq2_params.json` is a template; recalibrate with
   `scripts/calibrate_param_mapping.py` on a new machine/FL version.
2. **CLAP 默认关闭**：CLAP 慢循环诊断默认关闭（权重约 1GB，
   见 `install_clap.bat`）；DSP 快循环已可独立驱动优化。
   CLAP slow-loop diagnostics are OFF by default (~1GB weights,
   see `install_clap.bat`); the DSP fast loop drives optimization alone.
3. **AGH 插件**：AGH 为 pre-alpha，需从源码自行构建；插件为薄封装，
   调用的是本地 Python 流水线。
   AGH is pre-alpha and must be built from source; the plugin is a thin
   wrapper over the local Python pipeline.

## 许可证 / License

MIT（见 `LICENSE`；版权人可按需替换为你的名字/团队名）。
MIT (see `LICENSE`; replace the copyright holder with your name/team as needed).
