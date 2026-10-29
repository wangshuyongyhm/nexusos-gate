# nexusos-gate

**NEXUS Gate — 声明式门禁引擎（场景 YAML + checks 插件池）**

在多 Agent 体系里，"规则存在 ≠ 规则执行"。nexusos-gate 把「执行关键动作前该检查什么」从自觉变成强制：Agent 在关键动作前调用 `gate_check`，引擎按场景 YAML 定义跑检查插件池，返回 REJECT（硬拦）/ WARN（软警告）分级结果。

## 核心特性

- **声明式场景定义**：每个门禁场景一个 YAML（示例见 examples/gates/），含 required_context 校验 + 检查项列表
- **插件池自动发现**：`etc/gates/_checks/` 下 46 个检查插件按文件名自动装载，覆盖对抗式审查、README 同步、MEM 查询留痕、验证证据等维度
- **分级语义**：REJECT（产出缺失，硬拦截）/ WARN（附属质量，记录后放行）
- **CLI + Python API 双入口**：脚本可 `python3 -m nexusos_gate.gate_engine <scenario> <json>`，代码可 `from nexusos_gate import gate_check`
- **Fail-open 告警写 PG**：psycopg2 为可选依赖，缺失时门禁仍可用，仅失去告警落库能力

## 安装

```bash
# 发布至 PyPI 前：本地路径安装（仓库根目录执行；三包目录并列时同命令安装三件套）
pip install ./nexusos-gate
pip install ./nexusos-gate ./nexusos-mem ./nexusos-xdr   # 三件套一条命令（1597 干净 venv 实证口径）
```

要求 Python >= 3.10。运行时唯一硬依赖是 `pyyaml>=5.4`。

PyPI 发布后可用 `pip install nexusos-gate`（当前包未发布，请勿直接照抄该命令）。

本包**没有** `[full]` extras（extras 是 nexusos-mem 的 BGE 向量能力，见 nexusos-mem README）。

## 快速上手

```python
from nexusos_gate import gate_check

result = gate_check(scenario="minimal", context={
    "report_path": "output/report.md",
})
# result = {"passed": bool, "failures": [...], "hard_fails": [...], "warns": [...]}
if not result["passed"]:
    ...  # 补齐 REJECT 项后重过；WARN 项记录继续
```

安装后导入首验（1597 实证命令）：

```bash
python -c "import nexusos_gate; print('ok')"
```

CLI 方式（shell / pre-commit hook 适用）：

```bash
NEXUS_GATES_DIR=./examples/gates python3 -m nexusos_gate.gate_engine minimal '{"report_path":"output/report.md"}'
```

环境变量（常用）：

| 变量 | 默认值 | 作用 |
|------|--------|------|
| `NEXUS_GATES_DIR` | （无，必需时显式指定） | 场景 YAML 目录（examples/gates 可作模板） |
| `NEXUS_VAULT_ROOT` | env > 包位置哨兵推导 > 空串 | Vault 根目录（vault 类检查插件用，干净环境可缺省） |

## 通用示例场景（examples/）

包内不绑定任何具体业务流程——`examples/gates/` 提供 3 个通用示例（`minimal` / `pre_commit` / `doc_release`），用 `NEXUS_GATES_DIR` 指向即可运行。写你自己的门禁 = 在任意目录加一个场景 YAML（场景名 + required_context + 检查项），可选地往 `_checks/` 放检查插件（引擎自动发现），无需改引擎代码：

```bash
export NEXUS_GATES_DIR=/path/to/your/gates   # 场景目录（examples/gates 可作模板）
gate_check(scenario="your_scenario", context={...})
```

## 依赖分层

| 层 | 内容 |
|----|------|
| 硬依赖 | `pyyaml>=5.4`（gate_engine 顶部 import，缺失即退出） |
| 可选依赖 | `psycopg2-binary`（仅检查插件告警写 PostgreSQL 用，fail-open） |
| 包结构 | `gate_engine.py` 调度核心 + `_checks/` 通用插件池（场景 YAML 不随包，examples/ 提供模板） |

## 与另两件的关系

nexusos-gate 是三件套中**最独立**的一个：只依赖 pyyaml，可单独 pip 安装使用。nexusos-xdr 在 dispatch/callback 等关键链路上调用本包做门禁校验；nexusos-mem 与本包无直接依赖（仅检查插件可选地查询 MEM 知识库留痕）。

## License

MIT License。详见仓库根目录 [LICENSE](./LICENSE)。
