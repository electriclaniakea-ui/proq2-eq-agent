# 安装与转移指南：把项目从 Muse 虚拟机搬到你的电脑

> 写于 2026-10-09，2026-10-12 修订。项目已在 Muse 这边完成全部可写代码 + 64 个测试全过。
> 你需要做的只有：**下载 → 装依赖 → 装两个外部软件（VB-Cable / loopMIDI）→ 装 MIDI 桥 → 标定 → 跑**。

> ### ⚠️ 先看这条：命令怎么写
> 本文档所有 Python 命令都必须用**虚拟环境的 Python**，格式固定为：
> ```powershell
> .venv\Scripts\python.exe scripts\xxx.py
> ```
> - `.venv\Scripts\` 里面是解释器（`python.exe`），**我们的脚本不在里面**，别去那找；
> - 我们的脚本在项目根目录的 `scripts\` 文件夹；
> - 直接敲 `python` 用的是系统 Python，没有装依赖，会报 `ModuleNotFoundError`。
> - 所有命令都在**项目根目录**下执行（`cd` 到 `proq2-eq-agent` 文件夹）。

---

## 0. 你拿到了什么

`proq2-eq-agent/` 完整项目骨架（对应技术设计 v4.3 的文件树）：

| 目录/文件 | 说明 | 在你电脑上能直接跑？ |
|---|---|---|
| `core/`（10 个模块） | 业务逻辑：agent 编排、DSP 特征库、Critic、贝叶斯优化、参数映射、FL 桥接（MIDI 直连默认，MCP 备用）、音频捕获、CLAP、LLM planner、会话管理、可视化 | ✅（除真实 FL 部分） |
| `config/` | 运行配置、planner 提示词、Critic 配置 Schema | ✅ |
| `scripts/run_agent.py --simulate` | **离线全链路仿真**：无 FL、无 MCP、无声卡也能跑完整 30 轮循环 | ✅ 已验证 |
| `tests/`（64 个测试） | 单元测试 + 离线端到端测试 | ✅ 64/64 通过 |
| `scripts/dump_eq2_params.py` | 连上 MIDI 桥后 dump 插件参数表 | 需装好 MIDI 桥后 |
| `scripts/calibrate_param_mapping.py` | wiggle 标定（交互式，约 2 分钟） | 需装好 MIDI 桥后 |
| `agh_adapter/` | AGH 插件薄包装 | 部署 AGH 时用 |

**我这边验证过的**：`pytest tests/` 64 个全过；`run_agent.py --simulate` 完整跑通 30 轮并产出报告 + 轨迹图 + planner 存档。

**我这边验证不了、必须你本地做的**：MIDI 桥真实连接、VB-Cable 音频流、FL 内真实参数读写（标定）。

---

## 1. 把文件弄到你的电脑

**下载 zip 包（全量基线 + 增量包）**
我在 `~/workspace/your_files/` 放了全量基线包 `proq2-eq-agent.zip`，你直接下载、解压到比如 `D:\hackathon\proq2-eq-agent\`。之后我这边有更新时，我会放一个增量包 `change-<N>.zip`（N 是递增的 change 编号），你下载后解压**覆盖到项目根目录**即可，不用每次重下整个项目（别解压到子文件夹里，包内路径已经是相对项目根目录的）。

解压后目录结构应与上面表格一致，且包含 `Agent-4-technical-design.md`（v4.3 设计文档在项目根目录）。

> 还有一个独立的**发布版** `proq2-eq-agent-release-v1.0.zip`：给评委/外人下载用的干净包（无开发备忘、只留最新插件、带 MIT 许可证和发行说明）。你自己开发用基线包就行，交作品时用发布版。

---

## 2. 安装 Python 依赖（Windows，一键）

**双击 `install.bat`** 即可：自动建 `.venv` 虚拟环境并安装全部依赖
（含 pytest；如果 `.venv` 已损坏它会自动删掉重建，可重复双击）。
装完双击 `test.bat` 验证（期望看到 `64 passed`，无失败即可），
再双击 `simulate.bat` 跑离线全链路冒烟测试。

手动方式（PowerShell，等价）：

```powershell
# 1. 装 Python 3.10+（官网 python.org，勾选 Add to PATH）
python --version   # 确认 3.10+

# 2. 进项目目录，建虚拟环境并装依赖
cd D:\hackathon\proq2-eq-agent
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

说明：
- DSP 用 numpy/scipy 实现，**不需要 librosa**（比 librosa 轻一个数量级，行为等价）。
- `sounddevice` 的 Windows wheel 自带 PortAudio，**不用单独装**。
- `mcp` 是连 PostFader 用的客户端 SDK。
- `laion-clap` **默认不装**——比赛分支默认关闭 CLAP（`config/agent_config.yaml` 里 `clap.enabled: false`）。CLAP 代码已完整实现（后台慢循环，只进诊断不进优化器）；只有当赛事规则允许第三方模型、且你决定启用时才装：**双击 `install_clap.bat` 一键安装**（自动装 torch/torchaudio/transformers 等并跑延迟基准，首次运行自动下载约 1GB 权重；中途断了可重跑，它是幂等的）。装完把 `config/agent_config.yaml` 里 `clap.enabled` 改成 `true`。

验证：

```powershell
.venv\Scripts\activate
.venv\Scripts\python.exe -m pytest tests/ -q
# 期望：64 passed，无失败
```
（或直接双击 `test.bat`）

---

## 3. 必装的两个外部软件（按顺序）

### 3.1 VB-Cable（音频路由，免费）

1. 下载安装 VB-Audio 的 VB-Cable（donationware，免费可用）：官网 https://vb-audio.com/Cable/ → Download → 解压 → **右键 `VBCABLE_Setup_x64.exe` → 以管理员身份运行** → Install Driver → **重启电脑**（驱动不重启设备出不来）。
2. **FL Studio 里**：Options → Audio settings → Output 选 `CABLE Input (VB-Audio Virtual Cable)`。
3. **本项目里**：Python 从 `CABLE Output` 录音（`config/agent_config.yaml` → `audio.input_device: "CABLE Output"`，默认已配好）。
4. 验证：FL 播放任意声音，Windows 音量混合器里 CABLE Input 有电平跳动。

> 原理：FL 的声音不再走你的音箱，而是走进虚拟声卡；Python 实时录下来做 DSP 打分。**演示时记得把监听切回音箱**，否则你自己听不见。

### 3.1.5 处理过程中想同时听到声音？（两种方案）

**方案 A：Windows 自带"侦听"（推荐先试，30 秒搞定）**

1. Windows 设置 → 系统 → 声音 → 更多声音设置 → 「录制」选项卡
2. 右键 `CABLE Output` → 属性 → 「侦听」选项卡
3. 勾选「侦听此设备」，下面下拉选你的 **Roland Rubix 44** 输出 → 确定
4. 效果：Python 照常从 CABLE Output 录音（不受影响），Windows 同时把声音送到你的声卡耳机/音箱

注意：FL 的输出设备要切到 CABLE Input（WDM 驱动），这期间 FL 不走 ASIO，
延迟会变大；"侦听"本身也有几十毫秒延迟。但 Agent 每轮 8~9 秒，
只是监听处理过程的话完全够用。

**方案 B：声卡硬件环路（延迟最低，适合演出级监听）**

1. FL 的音频设置**保持 Roland ASIO** 不变，声音照常从 Rubix 44 的主输出出来
2. 拿两根线把 Rubix 44 的输出 1/2 物理接到输入 3/4（后面板的线路输入）
3. Python 改从声卡输入录音：`config/agent_config.yaml` 里
   `audio.input_device` 改成 Rubix 输入设备的全名（用
   `.venv\Scripts\python.exe -c "import sounddevice; print(sounddevice.query_devices())"` 查）
4. ⚠️ **必须关掉 Rubix 上这几个输入的直接监听**（direct monitor），
   否则输出→输入→输出形成环路会啸叫
5. 优点：你听到的是 FL 的 ASIO 直出，零额外延迟；FL 不用切驱动

两个方案 Python 侧都只取左声道做 DSP 打分（VB-Cable 和硬件环路都一样），
不影响优化效果。

### 3.2 loopMIDI（虚拟 MIDI 通道，免费）

Python Agent 与 FL 内部脚本之间靠虚拟 MIDI 端口通信：

1. 安装 loopMIDI（官网 https://www.tobias-erichsen.de/software/loopmidi.html），新建一个**专用**端口，名字记下来（比如 `ProQ2Bridge`，跟 `config/agent_config.yaml` 里 `midi_bridge.port_name` 一致）。**loopMIDI 要一直开着**（可设开机自启），FL 才能连上。
2. 这个端口只给桥接用，不要在你的音乐工程里拿它传别的 MIDI。
3. 注意：Windows 的 MIDI 后端会在端口名后自动加数字后缀（比如系统里显示为 `ProQ2Bridge 3`），这是正常的。config 里写 `ProQ2Bridge` 就行，代码会自动匹配 `ProQ2Bridge <数字>`。

### 3.3 ProQ2Bridge MIDI 桥（FL 桥接，关键）

原理：FL 里跑一个极简 MIDI 脚本（`fl_bridge/device_ProQ2Bridge.py`，~150 行），
监听 loopMIDI 端口上的触发音符，调官方 `plugins` / `transport` / `mixer` API，
结果写回 JSON 文件。Python 侧 `core/fl_bridge.py` 的 `MIDIBridge` 类负责发命令、
收结果。只要求 **FL Studio 20.7+**（MIDI 脚本 API），不需要 FL 2026。

1. 装 Python 依赖（已在 `install.bat` / `requirements.txt` 里）：`mido` + `python-rtmidi`。
2. 装 FL 脚本（一键）：
```powershell
.venv\Scripts\python.exe scripts/install_midi_bridge.py --port ProQ2Bridge
```
它会把脚本拷到你电脑上**每一个** `Documents\Image-Line\FL Studio*\Settings\Hardware\ProQ2Bridge\`
（如果你装了多个 FL 版本，每个版本的数据文件夹都会装一份；不确定 FL 在用哪个数据文件夹时，去 FL 的 Options → File settings 里看）。
3. （重）开 FL Studio → Options → MIDI Settings → **Input** 里找到 `ProQ2Bridge` 端口：
   启用（点亮），Controller type 选 **ProQ2Bridge**。
   ⚠️ **只在 Input 里启用，Output 里千万别点亮**——之前有人在 Output 也启用了，
   桥的 note_off 消息漏进 FL 的通用 MIDI 映射，直接劫持了播放键等 UI 控件，
   FL 界面会卡死。只开 Input 就对了。
4. 验证（FL 开着）：
```powershell
.venv\Scripts\python.exe scripts/dump_eq2_params.py
```
看到 `found N params` 并列出参数名 → 桥通了。它会自动在混音器里找到
Fruity Parametric EQ 2（`find_eq`），EQ 放在哪个混音器轨都行。

> 备选：如果以后想换回 MCP 方案（PostFader），把 `config/agent_config.yaml`
> 里 `bridge:` 改成 `"mcp"` 并按 `mcp:` 一节配置即可。PostFader 要求
> FL Studio 2026 26.1.3+，且 setup 流程较复杂，默认不推荐。

---

## 4. FL 工程准备（每次演示前）

1. 新建工程，放一个 8 拍的 Pattern（比如一段 lead/vocal loop），设为 **Pattern 循环播放模式**。
2. 在该通道的 Mixer 轨上加载 **Fruity Parametric EQ 2**。
3. 只动 **Band 2**（Peak 形态）；Band 2 的 Gain/Freq 就是 Agent 搜索的两个参数。
4. 播放，确认 VB-Cable 有信号（见 3.1 第 4 步）。

---

## 5. 配置

```powershell
# 复制环境变量模板并填入你的 Agnes API Key
copy .env.example .env
# 用记事本打开 .env，填 AGNES_API_KEY=...
```

> **两个"Agnes"别搞混 / Don't confuse the two:**
> - **Agnes API Key**（本节）：LLM 规划用的 key，没有它真机模式会降级用内置
>   启发式 planner（能跑，但规划质量不如 LLM）。想体验完整 LLM 规划就填上。
>   (API key for LLM planning. Without it, real mode falls back to the
>   heuristic planner.)
> - **AGH（Agnes Harness，第 10 节）**：比赛平台，D3–D4 才做，**不阻塞本地闭环**。
>   所以第 7 节（运行）在第 10 节前面是对的。
>   (AGH platform is D3-D4, NOT required for local runs. Step 7 before 10 is intentional.)

检查 `config/agent_config.yaml` 里这三处跟你机器一致：
- `audio.input_device`：你的 VB-Cable 输出端名字（Windows 声音设置里看全名）
- `midi_bridge.port_name`：跟 loopMIDI 里建的端口名一字不差（默认 `ProQ2Bridge`）
- `llm.base_url`：对照 https://agnes-ai.com/docs 确认（Agnes 多为 OpenAI 兼容接口，`{base_url}/chat/completions`）
- （备选 MCP 才看）`mcp.command` / `mcp.args`：PostFader 的启动方式

---

## 6. 标定（只做一次，约 5 分钟）

```powershell
# 6.1 确认 MIDI 桥能读到插件参数
.venv\Scripts\python.exe scripts/dump_eq2_params.py

# 6.2 wiggle 标定：脚本会逐个写入 0 / 0.25 / 0.5 / 0.75 / 1.0，
#     每次停下来问你"FL 界面上显示的值是多少"，你照着 UI 输入即可
#     （比如 Gain 显示 -6.0 dB 就输入 -6；Freq 显示 2.5 kHz 就输入 2.5kHz）
.venv\Scripts\python.exe scripts/calibrate_param_mapping.py
```

标定结果写入 `assets/eq2_params.json`（含 `calibration` 点对）。**不要跳过这步**——Fruity PEQ2 的旋钮可能是非线性的，Agent 的 dB/Hz ↔ 0~1 换算全靠它。

---

## 7. 运行

```powershell
# 7.1 先离线仿真（无 FL 也能跑，验证代码链路）
.venv\Scripts\python.exe scripts/run_agent.py --simulate --instruction "make this lead brighter"

仿真跑通的标志 / What success looks like：报告 JSON 里 `diagnostic.execution_ok: true`
（30 轮跑完没崩）。`target_reached` 在仿真里可能为 false（合成音频频谱简单，
目标区间不一定够得着）——这是正常的，`target_missed` 也是有效输出，说明
"规划→搜索→打分→报告" 整条链路通了。
（`execution_ok: true` means the pipeline works. `target_missed` in simulation
is fine — the synthetic audio is simple; it still proves the full loop works.）

仿真中 `Data point ... is not unique` 是贝叶斯优化库的提示（允许重复采样），
不是错误，可以忽略。
（"Data point ... is not unique" warnings are harmless optimizer notices.)

# 7.2 真实运行：FL 循环播放中执行
.venv\Scripts\python.exe scripts/run_agent.py --instruction "让这个lead更亮一点"
```

真实运行流程：读当前参数 → 录基线 → LLM 规划（存档原始 JSON 到 `docs/planner_logs/`，首次运行时自动创建）→ 30 轮贝叶斯搜索（每轮约 8~9 秒，共约 4~5 分钟）→ 输出报告。

报告里的 `diagnostic` 四个状态要分开看：`execution_ok`（跑完没）、`optimization_stable`（收敛没）、`target_reached`（进目标区间没）、`user_accepted`（**你试听确认后才变 true**）。

试听候选后如果满意，确认它成为 accepted（之后接 AGH 时由 `eq_confirm_candidate` 工具做；本地脚本阶段你手动记下参数即可）。

---

## 8. 故障排查

| 现象 | 查哪里 |
|---|---|
| `pip install` 慢/失败 | 换国内源：`.venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt` |
| `sounddevice` 报错找不到设备 | `.venv\Scripts\python.exe -c "import sounddevice; print(sounddevice.query_devices())"` 看名字，把全名填进 `audio.input_device` |
| 录到的全是静音 | FL 的 Output 是否切到了 CABLE Input；Windows 录音设备里 CABLE Output 是否启用 |
| MIDI 桥连不上（`dump_eq2_params.py` 超时/报错） | 先看 loopMIDI 里端口名跟 `config/agent_config.yaml` 的 `midi_bridge.port_name` 是否一字不差；FL 的 MIDI Settings → Input 里该端口是否点亮、Controller type 是否选了 **ProQ2Bridge**；`%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\ProQ2Bridge\` 下有没有 `device_ProQ2Bridge.py`（没有就重跑 `scripts/install_midi_bridge.py`） |
| 参数写了但声音没变 | 检查标定文件 `assets/eq2_params.json` 是否有 `calibration`；检查是否改对了 Band（只支持 Band 2） |
| `capture_stable_loop` 一直超时 | 检查 FL 是否在播放、是否循环模式；`setSongPos(0)` 是否生效（MIDI 桥侧看响应文件里有没有 error） |
| LLM 返回格式错误 | 去 `docs/planner_logs/<objective_id>.json` 看原始响应；重试（有 3 次重试） |
| PostFader setup 报 "no exact bidirectional MIDI endpoint" | PostFader 不是"扫不到端口"，而是**要你用环境变量告诉它端口的准确名字**：先在 loopMIDI 里建好端口（光开着不够），然后 PowerShell 里跑 `[System.Environment]::SetEnvironmentVariable("FL_BRIDGE_MIDI_PORT", "端口名", "User")`（端口名跟 loopMIDI 里的一字不差），**关掉重开一个 PowerShell** 再跑 `postfader.exe setup --interactive` |
| 30 轮后 `target_missed` | 正常——看报告里最接近的候选和未满足的维度，换指令或放宽 planner 的目标区间 |

---

## 9. 对应技术设计文档的位置

- 完整设计：`Agent-4-technical-design.md`（v4.3，项目根目录）
- 本次会话的所有决策与待办：`docs/SESSION_STATE.md`
- 开发手册 skill（我已给自己装好）：`~/workspace/skills/proq2-eq-agent/`（在我的虚拟机里，你电脑上不需要）

## 10. AGH（Agnes Harness）接入（D3–D4，不阻塞本地闭环）

比赛要求用 Agnes Harness 平台。`agh_plugin/` 是按官方后端插件文档写的
JS 插件骨架（`node --check` 通过，Python↔JS 整条通路已验证）。

### 10.1 AGH 是怎么跑的（2026-10-09 按官方 README 核实）

- **不是托管服务，也不是桌面客户端**：AGH 是 pre-alpha，需要你从源码构建、
  跑在自己电脑上。启动后是一个本地 App Server，打印 loopback 地址
  （127.0.0.1），你在**浏览器**里打开它进入 Web 工作台；同时有个**终端 CLI**，
  两者共享同一个后端 session。
- 构建：`pnpm install --frozen-lockfile` → `pnpm --filter @agnes/cli build:local`
  → `node packages/cli/dist/local/agnes.mjs serve`（仓库根下有
  `start-local-windows.ps1`，Windows 可直接跑它）。
- ⚠️ 官方只在 macOS 上做过记录的本地验证，**Windows 需要自行验收**。

### 10.2 主办方给的 sk- key 填在哪（两处）

1. **AGH 里**：打开 loopback URL 后第一步 "configure a model"，key 填在那里。
   没有它 AGH 的 agent 没有"脑子"。
2. **本项目里**：`run_agent.py` 非 `--simulate` 模式的 LLM planner 读
   `AGNES_API_KEY`（项目根目录 `.env` 里填，见第 5 节）。同一个 key 就行。

### 10.3 接入步骤

1. 在你电脑上装 AGH：
   - 先装 Node.js 24+（官网 nodejs.org，LTS 版就行），装完 PowerShell 里跑
     `corepack enable` 得到 pnpm（AGH 构建要用）；
   - 按 agnes-harness 仓库 README 构建（`pnpm install --frozen-lockfile` →
     `pnpm --filter @agnes/cli build:local`，Windows 可直接跑仓库根下的
     `start-local-windows.ps1`）。
2. 设环境变量（**AGH host 进程必须能看到**，设完重启 AGH）：
   - `PROQ2_PROJECT_DIR=D:\hackathon\proq2-eq-agent`（换成你的实际项目路径）
   - `PROQ2_PYTHON=D:\hackathon\proq2-eq-agent\.venv\Scripts\python.exe`
   - 设完验证：新开一个 PowerShell，`echo $env:PROQ2_PROJECT_DIR` 能打印出路径才算生效。
3. AGH → Settings → Plugin management → **从本地路径安装**（选文件夹
   `agh_plugin/`，不是 zip 包）→ 点**检查** → **信任** → **启用**。
4. 新开 session，确认四个工具已注册：
   `eq_analyze` / `eq_optimize` / `eq_confirm_candidate` / `eq_rollback`。

**如果"检查"这一步报错（AGH 的插件校验）**：
- 先看报错信息：常见的是 ToolMeta 字段缺失。v5.2 插件的 4 个工具已经带齐
  AGH 要求的全部 8 个 meta 字段（之前 v1 版缺过 3 个，AGH 自己还自动补过一次），
  正常应该一次通过。
- **不要手改 `agh_plugin/index.mjs`**——它是 FROZEN 的，Python/JS 整条通路
  已经验证过，改了反而可能破坏签名。真卡住了把报错截图发回来，我这边修。
- 另一个常见坑：环境变量没设对（第 2 步），插件会报 `PROQ2_PROJECT_DIR is not set`。
  这不是校验问题，是 AGH 进程看不到你的环境变量，重启 AGH 再试。

注意：
- `eq_optimize` 单次约 2~3 分钟，插件侧超时设为 10 分钟。
- 写 DAW 的三个工具（`eq_optimize` / `eq_confirm_candidate` / `eq_rollback`）
  已如实声明 `isDestructive: true`、`requiresApproval: 'always'`；
  `eq_analyze` 是只读的。
- AGH 是 pre-alpha，若你安装时的官方文档与插件有出入，以当时的
  `docs/develop/backend.md` 为准（重点核对 `registerTool` 字段名与 meta 枚举）。
- 详细步骤见 `agh_plugin/README.md`。
