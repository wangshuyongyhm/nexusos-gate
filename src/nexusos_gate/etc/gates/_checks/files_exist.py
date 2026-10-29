"""检查类型: files_exist — 遍历 files[] 数组,验证每个文件在文件系统真实存在。
用于 done gate G1:防小弟报幽灵路径(files:["假路径"])过门禁。
file_exists.py 只支持单 path/glob,不支持数组遍历,故新增此插件。

路径解析三级（Task898 修复——Vault 外独立 git 工程假阳性, MEM#65556）:
  1. 绝对路径 / ~ 开头: 直接存在性判定（文件系统真相为准）
  2. 相对路径: 先补 Vault 根——task/NN/ 产物在 Vault 根（MEM#37571 修正保持:
     曾误补 05-System/ 前缀, 该修复行为不得回退）
  3. Vault 根解析失败 → report 机读块 repo_root 字段解析（Task898 契约: 产出在
     Vault 外独立 git 工程（如量化 bot/中枢仓）的任务, report.md 机读块声明
     `repo_root: /绝对路径`, files 相对路径按该仓库根二次解析, detail 注
     external-repo）。仍不存在 = 真幽灵, REJECT 语义不动（陷阱1: 不降级）。
"""

# Task1597 参数化：vault 根经 env/仓内推导解析，不再硬编码本机路径
try:
    from _vault_root import vault_root
except ImportError:  # 包模式加载（gate_engine 以子包形态 import 时）
    from ._vault_root import vault_root

import os
import re
from pathlib import Path

_VAULT_ROOT = vault_root()

# 机读块 repo_root 行（yaml: `repo_root: /abs/path`——仅认绝对路径, 防相对套相对;
# 支持 yaml 行尾注释 `# ...`, Task898 契约）
_REPO_ROOT_RE = re.compile(r"^\s*repo_root:\s*(/\S+?)\s*(?:#.*)?$", re.M)


def _resolve_path(fpath):
    """补全相对路径为绝对路径（Vault 根策略, 37571 行为保持）。

    绝对路径 / ~ 开头：原样返回（expanduser 处理 ~）。
    相对路径（含 task/NN/）：统一补 Vault 根（task 目录在 Vault 根，不在 05-System/）。
    """
    if os.path.isabs(fpath) or fpath.startswith("~"):
        return Path(fpath).expanduser()
    return Path(_VAULT_ROOT) / fpath


def _repo_roots_from_context(context: dict) -> list:
    """Task898：从 report.md 机读块提取 repo_root 声明（可能多条 fence, 全收）。

    report 路径来源: context["task_path_report"]（xdr bg-gate 组装, handler.py
    Task492/639）。文件缺失/无字段返回 []（外部解析路径不可用, 不报错）。
    """
    report = context.get("task_path_report") or ""
    roots = []
    if report and os.path.isfile(report):
        try:
            text = open(report, encoding="utf-8", errors="ignore").read()
            roots = _REPO_ROOT_RE.findall(text)
        except Exception:
            roots = []
    return roots


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      jsonpath: context 里的字段名(默认 "files"),值为文件路径列表
      min_len: 最小文件数(默认 1,确保非空)
      allow_missing: 允许的缺失数(默认 0,全部必须存在)
    返回: (passed, detail)
    detail 含 missing 列表便于排查; external-repo 命中数注明（Task898）
    """
    jsonpath = params.get("jsonpath", "files")
    min_len = params.get("min_len", 1)
    allow_missing = params.get("allow_missing", 0)
    value = context.get(jsonpath)
    if value is None:
        return False, f"字段 '{jsonpath}' 不存在(context 未提供)"
    if not isinstance(value, list):
        value = [value] if value else []
    # 1. 数量检查(与 field_check 一致,防空数组)
    if len(value) < min_len:
        return False, f"'{jsonpath}' 文件数 {len(value)} < {min_len}"
    # 2. 逐个验证存在性(核心:防幽灵路径; Task898 三级解析)
    repo_roots = None   # 惰性提取（首个外部相对路径触发才读 report）
    missing = []
    external_hits = 0
    for fpath in value:
        if not isinstance(fpath, str):
            missing.append(f"非字符串: {fpath!r}")
            continue
        p = _resolve_path(fpath)
        if p.exists():
            continue
        # Vault 根解析失败（仅相对路径可能走到这——绝对路径不存在就是真幽灵）
        # → Task898: report 机读块 repo_root 二次解析
        if not os.path.isabs(fpath) and not fpath.startswith("~"):
            if repo_roots is None:
                repo_roots = _repo_roots_from_context(context)
            hit = next((r for r in repo_roots
                        if (Path(r) / fpath).exists()), None)
            if hit:
                external_hits += 1
                continue
        missing.append(fpath)
    if len(missing) > allow_missing:
        preview = missing[:5]
        suffix = f" ...等 {len(missing)} 个" if len(missing) > 5 else ""
        return False, f"{len(missing)}/{len(value)} 文件不存在: {preview}{suffix}"
    if missing:
        return True, f"通过({len(missing)} 个缺失在 allow_missing={allow_missing} 内)"
    if external_hits:
        return True, (f"全部 {len(value)} 个文件存在"
                      f"（含 {external_hits} 个 external-repo: report 机读块"
                      f" repo_root 解析, Task898）")
    return True, f"全部 {len(value)} 个文件存在"
