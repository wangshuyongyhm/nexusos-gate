"""检查类型: verification_evidence — 代码改动验证证据强制(C8 用, Task387-oc-c8)。

用户核心诉求: "新建的、修改的、重构的,只要动了代码没经验证测试的,都不可信。
必须验证。融入 gate,影响系统稳定性。"

🔴 08040834 处女原则重写：移除人工标记路径（[verified:...] 是形式主义通行证，
违反「单一真源」+「不留残渣」）。验证证据只来自仓库内真实产物。

3 种证据路径(任一满足即 pass):
  1. 非代码豁免: changed_files 无代码扩展名(.py/.sh/.js/...) → pass（含 .gitignore/.sql/.docx 等无代码扩展名文件）
  2. verify 文件: commit 含 verify_*.md / test_*.py / test_*.sh / *_verify.md → pass
  3. 测试覆盖: changed_files 的 .py/.sh 有对应 test_*.{py,sh} 同目录 → pass (C5 会真跑)

都不满足 → REJECT "代码改动(N个)无验证证据。需: test_*.{py,sh}/verify_*.md/纯文档豁免"

为什么去掉 commit_msg 标记路径：
- 标记不携带信息（不记录验证了什么/怎么验证/结果）
- 标记会腐烂（标了但没真验证，gate 无法区分）
- 违反处女原则：验证证据应是代码的一部分（可追溯），不是 commit_msg 里的声明
- bash 脚本等无 test_*.py 的改动 → 写 verify_*.md 记录验证场景（也是真实产物）
"""
import os
from pathlib import Path


# 代码文件后缀（白名单：只有这些扩展名算代码，需验证证据）
# Task508: 从 _DOC_EXTS 正向判定改为 _CODE_EXTS 反向判定——无扩展名文件(.gitignore/Makefile)自动豁免
_CODE_EXTS = {".py", ".sh", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".vue", ".go", ".rs",
              ".c", ".cpp", ".h", ".hpp", ".cc", ".java", ".kt", ".swift", ".rb", ".php",
              ".scala", ".clj", ".lua", ".r", ".dart", ".pl", ".ex", ".exs",
              ".elixir", ".nim", ".zig", ".v", ".sv"}
_VERIFY_MARKERS = ("verify", "test_", "_verify", "verification")


def _coerce_files(value, context: dict) -> list:
    """规整成 list[str]。处理 changed_files 的多种格式(逗号分隔/换行/list)。"""
    if value is None:
        v = context.get("changed_files") or []
    else:
        v = value
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        s = v.strip()
        if not s or "{" in s:
            # 占位符未解析 → 退回 context
            cv = context.get("changed_files") or []
            return [str(x).strip() for x in cv if str(x).strip()] if isinstance(cv, list) else []
        # Task532 P-g2: repr 格式（engine 把 list 占位符转 str 时是 "['a', 'b']" 形态，
        # 原逗号 split 会连引号带切）——对齐 file_size._coerce_files 的 literal_eval 分支
        if s.startswith("[") and s.endswith("]"):
            import ast
            try:
                p = ast.literal_eval(s)
                if isinstance(p, list):
                    return [str(x).strip() for x in p if str(x).strip()]
            except Exception:
                pass  # 解析失败走下方通用分隔
        # 逗号或换行分隔
        items = []
        for chunk in s.replace("\n", ",").split(","):
            chunk = chunk.strip().strip("'\"").strip()
            if chunk:
                items.append(chunk)
        return items
    return [str(v).strip()] if v else []


def _has_no_code(files: list) -> bool:
    """changed_files 无代码扩展名 → True（豁免验证）。

    Task508 语义反转：原 _is_doc_only 用 _DOC_EXTS 正向判定（黑名单永远列不全，
    .gitignore 无扩展名 / .docx 二进制 / .dump 全漏）。改为 _CODE_EXTS 白名单反向：
    只有已知代码扩展名（.py/.sh/.js/...）才算代码，其余全部豁免。
    无扩展名文件（.gitignore / Makefile / Dockerfile）→ splitext 返回空串 → 不在 _CODE_EXTS → 豁免。
    """
    if not files:
        return True
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        if ext in _CODE_EXTS:
            return False
    return True


def _has_verify_file(files: list) -> bool:
    """commit 含 verify 文件 → True"""
    for f in files:
        name_lower = os.path.basename(f).lower()
        if any(marker in name_lower for marker in _VERIFY_MARKERS):
            return True
    return False


def _has_msg_marker(commit_msg: str) -> bool:
    """[已废弃 08040834] 原 commit_msg 标记路径移除（处女原则：标记是形式主义通行证）。
    保留函数签名避免外部引用报错，但始终返回 False（不再作为验证证据）。
    """
    return False


def _has_test_coverage(files: list, project_root: str) -> bool:
    """changed_files 的代码文件有对应 test_*.{py,sh} 同目录/相邻 tests/ → True

    规则（按文件扩展名找对应测试）:
      foo.py  → test_foo.py / foo_test.py / tests/test_foo.py
      foo.sh  → test_foo.sh / foo_test.sh / tests/test_foo.sh

    08040834 重写：原 _has_pytest_coverage 只认 .py，现支持 .sh（bash 脚本也有测试）。
    """
    if not project_root:
        return False
    root = Path(project_root)
    # 代码文件 → 对应测试扩展名映射（Task508: 对齐 _CODE_EXTS，不只 .py/.sh）
    code_exts = {ext: ext for ext in _CODE_EXTS}
    code_exts.setdefault(".py", ".py")
    code_exts.setdefault(".sh", ".sh")
    code_files = [f for f in files if os.path.splitext(f)[1].lower() in code_exts]
    if not code_files:
        return False
    for code in code_files:
        p = Path(code)
        if p.is_absolute():
            p = Path(os.path.relpath(p, root))
        parent = p.parent
        stem = p.stem
        test_ext = code_exts.get(os.path.splitext(code)[1].lower(), ".py")
        # 候选 test 文件路径
        candidates = [
            parent / f"test_{stem}{test_ext}",
            parent / f"{stem}_test{test_ext}",
            parent / "tests" / f"test_{stem}{test_ext}",
            root / "tests" / f"test_{stem}{test_ext}",
            root / "test" / f"test_{stem}{test_ext}",
        ]
        for cand in candidates:
            full = root / cand if not cand.is_absolute() else cand
            if full.exists():
                return True
    return False


VERIFY_SUFFIXES = (
    "reproduce.sh",
    "report.md",
    "negative-results.md",
)


def _is_substantive_verify(fpath: str, project_root: str) -> bool:
    """Task1552 N1（1545 发现）：路径形态不够——文件须存在且有实质内容。

    空文件 / 仅 shebang / 纯空白行的 task/*.sh|md 不算验证产物（防洗白：
    原判据只看路径，任意既有 task 空壳即可豁免全部生产代码的验证证据）。
    """
    p = Path(fpath).expanduser()
    if not p.is_absolute():
        root = project_root or os.environ.get("NEXUS_ROOT", "")
        if not root:
            return False
        p = Path(root) / fpath
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    lines = [l.strip() for l in text.splitlines()]
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]
    return any(l for l in lines if l)


def _has_task_verify(files: list, project_root: str = "") -> bool:
    """commit 含 task/NN-*/ 目录的验证产出（reproduce.sh / report.md / negative-results.md）→ True。

    NEXUS 体系的实际验证模式是五层资产落盘（task/NN-name/ 下 reproduce.sh +
    output/report.md + output/negative-results.md），而非 test_*.py 同目录模式。
    本函数认这个模式作为验证证据。

    Task1552 N1 收紧：路径形态（task/ 前缀 + 验证后缀）之外还须文件存在且
    有实质内容（_is_substantive_verify）——空壳文件不再洗白。
    """
    for f in files:
        if not isinstance(f, str) or not f:
            continue
        # 归一化：去 ./ 前缀
        norm = f.lstrip("./").lstrip("/")
        lower = norm.lower()
        # 末尾必须是验证文件名
        if not lower.endswith(VERIFY_SUFFIXES):
            continue
        # 必须在 task/ 目录下（路径含 /task/ 或以 task/ 开头）
        if norm.startswith("task/") or "/task/" in norm:
            if _is_substantive_verify(f, project_root):
                return True
    return False


def _exempt_split(files: list, exempt_paths: list) -> tuple:
    """按声明式路径豁免拆分 changed_files → (kept, exempted)。

    exempt_paths：仓库相对目录前缀列表（末尾 / 可省）。
    匹配规则：规范化（去 ./ 与前导 /）后前缀匹配，且必须以 / 边界对齐
    （防 `…/foo` 误命中 `…/foobar`）。纯前缀，不支持 glob——需要 glob 时另开参数。

    语义：豁免 = “该路径不需要验证证据”（镜像/字节复制目录），
    **不是**“跳过检查”——剩余文件仍走原来 4 条路径判定。
    """
    kept, exempted = [], []
    if not exempt_paths:
        return list(files), []
    prefixes = [str(p).strip().lstrip("./").lstrip("/").rstrip("/") for p in exempt_paths]
    prefixes = [p for p in prefixes if p]
    for f in files:
        norm = str(f).lstrip("./").lstrip("/")
        if any(norm == p or norm.startswith(p + "/") for p in prefixes):
            exempted.append(f)
        else:
            kept.append(f)
    return kept, exempted


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params: (无, 全从 context 取)
    context:
      changed_files: 改动文件列表(逗号分隔/换行/list)
      commit_msg: 提交信息
      project_root: 项目根(可选, pytest 覆盖检查用)
    返回: (passed, detail)
    """
    files = _coerce_files(params.get("changed_files"), context)
    commit_msg = context.get("commit_msg", "") or ""
    project_root = (params.get("project_root") or context.get("project_root") or "").strip()
    if isinstance(project_root, str) and "{" in project_root:
        project_root = context.get("project_root", "").strip()

    # 无改动文件 → pass(空 commit 不算违规,虽然 C7 会拦)
    if not files:
        return True, "无 changed_files,跳过验证证据检查"

    # 路径0: 声明式豁免（Task1401-d3）——豁免路径内的文件不参与“需验证证据”判定。
    # 语义边界：豁免 = 该路径不需证据（镜像/字节复制目录），不是跳过检查——
    # 剩余文件仍走下面 4 条路径。豁免名单只能在 yaml 声明，本文件不硬编码路径。
    exempt_paths = params.get("exempt_paths") or []
    note = ""
    if exempt_paths:
        files, _exempted = _exempt_split(files, exempt_paths)
        if _exempted:
            note = f" ｜已豁免 {len(_exempted)} 个文件（{', '.join(str(p).rstrip('/') for p in exempt_paths)}）"
        if not files:
            return True, f"改动全在豁免路径内({len(_exempted)} 个)——镜像/字节复制目录非一手代码,C8 不适用{note}"

    # 路径1: 非代码豁免（Task508: _has_no_code 替代 _is_doc_only，白名单反向判定）
    if _has_no_code(files):
        return True, f"非代码改动({len(files)} 个 .md/.yaml/.json/.gitignore/.sql/...),C9 负责一致性验证{note}"

    # 路径2: verify 文件（commit 含 verify_*.md / test_*.py / test_*.sh）
    if _has_verify_file(files):
        verify_files = [f for f in files
                        if any(m in os.path.basename(f).lower() for m in _VERIFY_MARKERS)]
        return True, f"含验证文件: {verify_files[:2]}{note}"

    # 路径3: 测试覆盖（changed_files 的代码文件有对应 test_*.{py,sh}）
    if _has_test_coverage(files, project_root):
        code_count = sum(1 for f in files if os.path.splitext(f)[1].lower() in _CODE_EXTS)
        return True, f"测试覆盖({code_count} 个代码文件有对应 test_*.py/.sh){note}"

    # 路径4: task/ 目录验证产出（Task453，NEXUS 五层资产落盘模式）
    # 认 task/NN-*/reproduce.sh / task/NN-*/output/report.md / negative-results.md
    if _has_task_verify(files, project_root):
        task_verify = [f for f in files if _is_task_verify_file(f)]
        return True, f"task/ 目录验证产出({len(task_verify)} 个 reproduce/report/negative-results){note}"

    # 都不满足 → REJECT
    code_files = [f for f in files if os.path.splitext(f)[1].lower() in _CODE_EXTS]
    code_count = len(code_files)
    sample = code_files[:3]
    return False, (
        f"代码改动({code_count} 个 .py/.sh/.js/...)无验证证据。"
        f"需: test_*.py/test_*.sh 同目录 / 附 verify_*.md 文件 / task/NN-*/reproduce.sh+report.md / 非代码豁免。"
        f"样本: {sample}。详见 VERIFICATION-DISCIPLINE.md{note}"
    )


def _is_task_verify_file(f: str) -> bool:
    """辅助：判断单文件是否是 task/ 目录下的验证产出（供 check 函数构造 detail 用）。"""
    if not isinstance(f, str) or not f:
        return False
    norm = f.lstrip("./").lstrip("/")
    lower = norm.lower()
    if not lower.endswith(("reproduce.sh", "report.md", "negative-results.md")):
        return False
    return norm.startswith("task/") or "/task/" in norm
