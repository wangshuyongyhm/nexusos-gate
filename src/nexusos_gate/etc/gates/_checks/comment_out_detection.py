"""检查类型: comment_out_detection — 检测"代码被注释掉假装删除"。
C6 用(WARN 级)。检测模式:diff 中新增的注释行,其去注释后内容像是可执行代码。
启发式,会有误报,所以是 WARN 不 REJECT。
"""
import re

try:
    import _gitcmd
except ImportError:
    from . import _gitcmd

# 注释前缀(按语言)
COMMENT_PREFIXES = ("#", "//", ";", "--", "/*")

# 判断"像代码"的启发式:强信号关键字/函数调用形态
# Task519: 去掉裸 =/(/)/;——含等号括号的中文业务说明注释误中(# Task516: exp_id=1 / # === 验证2 ===)
# 最后一条只匹配"整行末尾是函数调用形态 foo(...)"，而非行内任意位置有括号
CODE_LIKE = re.compile(
    r"(return |def |function |if\s*\(|for\s*\(|while\s*\(|var |let |const |"
    r"import |from |class |print\(|echo |self\.|this\.|\$\w|"
    r"\b[a-zA-Z_]\w*\s*\([^)]*\)\s*$)",
    re.IGNORECASE,
)


def _git_diff_added(cwd: str) -> tuple:
    """Task1552 S2: 收口 _gitcmd（quotePath 统一）。
    Task531 B7 语义保持：--cached（只看 staged，和 commit 内容一致）。"""
    return _gitcmd.run_git(["diff", "--cached"], cwd)


def _strip_comment(line: str):
    """如果是注释行,返回去注释后的内容(可能为空);非注释返回 None。"""
    s = line.lstrip()
    for pfx in COMMENT_PREFIXES:
        if s.startswith(pfx):
            rest = s[len(pfx):].lstrip()
            return rest
    # 块注释单行 <!-- ... --> / /* ... */
    m = re.match(r"^\s*(<!--|/\*)(.*?)(--!>|\*/)\s*$", line)
    if m:
        return m.group(2).strip()
    return None


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      project_root: git 仓库根
    返回: (passed, detail)  — WARN 级,passed=True 表示未发现可疑注释化
    """
    project_root = params.get("project_root") or context.get("project_root") or "."
    if isinstance(project_root, str) and "{" in project_root:
        project_root = context.get("project_root", ".")

    rc, diff, err = _git_diff_added(project_root)
    if rc == 128 and "not a git repository" in (err or "").lower():
        return True, "非 git 仓库,跳过"
    if rc not in (0, 128):
        return True, f"git diff 失败(rc={rc}),跳过"
    if not diff.strip():
        return True, "无 diff 内容"

    suspects = []
    cur_file = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            # Task1552 S1: 原 lstrip("b/") 是字符集语义——引号形态剥不动（b/ 残留+乱码）、
            # b 开头文件名被啃（b-fix.py→-fix.py）。收口 _gitcmd.diff_b_path 精确两步剥除。
            cur_file = _gitcmd.diff_b_path(line[4:])
        elif line.startswith("+") and not line.startswith("+++"):
            content = line[1:]
            stripped = _strip_comment(content)
            if stripped is None:
                continue
            if not stripped:
                continue  # 纯空注释
            if CODE_LIKE.search(stripped):
                # CJK 字符占比高 → 业务说明而非代码（Task519）
                cjk = len(re.findall(r'[\u4e00-\u9fff]', stripped))
                if cjk > 0 and cjk / max(len(stripped), 1) > 0.3:
                    continue
                # 排除明显是文档(以 markdown 标题、链接、列表开头)
                if re.match(r"^\s*(#+ |\* |- |\d+\. |\[)", stripped) and \
                   not CODE_LIKE.search(stripped.split(" ", 1)[-1] if " " in stripped else ""):
                    # Task532 P-g1: 原 pass 缺 continue——pass 后仍落到 suspects.append，
                    # markdown 排除分支从未生效（死代码）
                    continue
                suspects.append((cur_file, content.strip()))

    if suspects:
        sample = "; ".join(f"{f}: {l[:50]}" for f, l in suspects[:3])
        return False, f"发现 {len(suspects)} 处疑似注释化代码(应直接删): {sample}"
    return True, "未发现注释化删除痕迹"
