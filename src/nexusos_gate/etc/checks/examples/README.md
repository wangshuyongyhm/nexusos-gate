# nexusos.gate.checks · 自定义 check 接入指南（1959 单3，design §5）

nexusos-gate 的 check 注册分三层，按需组合：

| 层 | 位置 | 适用 |
|---|---|---|
| 包内声明（内置） | `etc/gates/_checks/*.py` + 场景 yaml `type:` 引用 | 通用检查（command/file_exists/...） |
| 用户声明式启用 | `$NEXUS_HOME/gate/checks.d/*.yaml` | 把 check（含内置/插件）以自定义参数挂进场景 |
| entry_points 协议 | 包 pyproject `[project.entry-points."nexusos.gate.checks"]` | 外部包注入新 check（sorted(name) 稳定序） |

## 挂一个 check 进场景（checks.d）

```yaml
# $NEXUS_HOME/gate/checks.d/<任意名>.yaml
scenario: code          # 追加到哪个场景（init/dispatch/persist/done/code）
items:
  - id: MY1
    name: 我的检查
    auto: true
    severity: WARN      # WARN / REJECT
    check:
      type: config_key_refs   # 任意已注册 check 类型名
      scope: ["/abs/your/config/dir"]   # 该 check 支持的参数
```

items 结构与场景 yaml 内置项完全同构（追加不改内置）。

## 本目录示例

- `e2e-paths.yaml` — e2e_suite_evidence 的用户配置样本（放 `$NEXUS_HOME/gate/e2e-paths.yaml`，支持 `${NEXUS_VAULT_ROOT}`/`${NEXUS_HOME}` 占位；无配置=该 check WARN skip）
- `config_key_refs.yaml` — 扫描目标声明样本（私配置不随包，示例用占位路径）
- `persist_pool_ledger.yaml` — 取号脚本路径参数化样本（env `NEXUS_POOL_NEXT_ID_SCRIPT` 同效）
- `doc_consistency.yaml` — 文档一致性检查目标样本

## 外部包注入 check（entry_points）

在你的包 pyproject 里：

```toml
[project.entry-points."nexusos.gate.checks"]
my_check = "my_pkg.gate_checks:my_check_fn"   # 模块或 "mod:attr"，须可调用 check(params, context, agent) -> (bool, str)
```

安装后 `nexus gate` 引擎自动发现（与内置五 check 同协议同待遇）。
