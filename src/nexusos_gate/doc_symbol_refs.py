#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_symbol_refs.py — Task448 L3 核心：文档符号引用扫描。

封装 obsidian-cli + ripgrep 正则，提供三类文档符号的反向引用查询：
  - wikilink 引用（[[target_doc]]）
  - 章节锚点引用（§2.6 / §核心禁令）
  - MEM# 编号引用

设计原则：
  - obsidian-cli 主路径，rg fallback（obsidian 不可用或粒度不够时）
  - 全部 fail-open，工具异常不抛
  - 路径参数化（从 __file__ 推导 vault_dir，不硬编码绝对路径）
"""
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# Vault 根（1410 移到包根后重数 6 层上溯）：
# nexusos_gate→src→nexusos-gate→pypi→自动化脚本→05-System→Vault 根
_DEFAULT_VAULT_DIR = str(Path(__file__).resolve().parents[6])


def _run_cmd(cmd: list, cwd: Optional[str] = None, timeout: int = 15) -> tuple:
    """运行命令，返回 (rc, stdout, stderr)。失败返 (-1, '', '')。"""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, check=False, cwd=cwd,
        )
        return r.returncode, r.stdout, r.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return -1, "", ""


def _rg_search(pattern: str, vault_dir: str, file_glob: str = "*.md") -> list:
    """ripgrep 递归搜索，返回 [{"file":, "line":, "text":}, ...]。"""
    if not shutil.which("rg"):
        return []
    rc, out, _ = _run_cmd(
        ["rg", "-n", "--with-filename", "--no-heading", "-t", "markdown", pattern, vault_dir],
        timeout=30,
    )
    if rc != 0:
        return []
    results = []
    for line in out.splitlines():
        # rg -n --with-filename 输出格式：path:line:text
        m = re.match(r"^(.+?):(\d+):(.*)$", line)
        if m:
            results.append({"file": m.group(1), "line": int(m.group(2)), "text": m.group(3)})
    return results


def scan_wikilink_refs(target_doc: str, vault_dir: Optional[str] = None) -> list:
    """查 target_doc 被哪些文件的 wikilink 引用。

    Args:
        target_doc: 文档名（不带 .md，如 "init" 或 "init.md"）
        vault_dir: Vault 根目录
    Returns:
        [{"source_file":..., "link_text":..., "line":...}, ...]
        obsidian-cli 优先，自动用 rg 补 line/link_text；不可用则 rg 全局兜底
    """
    vd = vault_dir or _DEFAULT_VAULT_DIR
    # 规整 target：去掉 .md 后缀（obsidian backlinks file= 用裸名）
    target_bare = target_doc[:-3] if target_doc.endswith(".md") else target_doc

    source_files = []
    obsidian_bin = shutil.which("obsidian")
    if obsidian_bin:
        rc, out, _ = _run_cmd(
            [obsidian_bin, "backlinks", f"file={target_bare}", "format=json"],
            cwd=vd, timeout=15,
        )
        if rc == 0 and out.strip():
            try:
                data = json.loads(out)
                if isinstance(data, list):
                    source_files = [item.get("file", "") for item in data if isinstance(item, dict)]
            except json.JSONDecodeError:
                pass

    # 对每个 source_file 用 rg 补 line + link_text（obsidian backlinks 只给 file）
    results = []
    if source_files:
        # 构造 wikilink 匹配：[[target_bare]] / [[target_bare.md]] / [[target_bare|...]] / [[target_bare#...]]
        # 接受可选 .md 后缀（用户写 [[init.md|init]] 也算引用 init）
        link_pattern = (
            r"\[\[" + re.escape(target_bare) + r"(\.md)?(\|[^\]]*)?(#[^\]]*)?\]\]"
        )
        for sf in source_files:
            if not sf:
                continue
            sf_path = Path(vd) / (sf if sf.endswith(".md") else f"{sf}.md")
            if not sf_path.exists():
                # 可能是路径形式（folder/note）
                sf_path = Path(vd) / sf
            if not sf_path.exists():
                results.append({"source_file": sf, "link_text": f"[[{target_bare}]]", "line": -1})
                continue
            rc, out, _ = _run_cmd(
                ["rg", "-n", "--with-filename", "--no-heading", link_pattern, str(sf_path)],
                timeout=10,
            )
            if rc == 0 and out.strip():
                for line in out.splitlines()[:5]:  # 每文件最多 5 个引用
                    m = re.match(r"^(.+?):(\d+):(.*)$", line)
                    if m:
                        # 提匹配到的 wikilink 文本
                        link_match = re.search(link_pattern, m.group(3))
                        link_text = link_match.group(0) if link_match else f"[[{target_bare}]]"
                        results.append({
                            "source_file": sf,
                            "link_text": link_text,
                            "line": int(m.group(2)),
                        })
            else:
                results.append({"source_file": sf, "link_text": f"[[{target_bare}]]", "line": -1})
        return results

    # Fallback: obsidian 不可用，全局 rg
    link_pattern = (
        r"\[\[" + re.escape(target_bare) + r"(\.md)?(\|[^\]]*)?(#[^\]]*)?\]\]"
    )
    raw = _rg_search(link_pattern, vd)
    for r in raw:
        rel = str(Path(r["file"]).relative_to(vd)) if r["file"].startswith(vd) else r["file"]
        link_match = re.search(link_pattern, r["text"])
        results.append({
            "source_file": rel,
            "link_text": link_match.group(0) if link_match else f"[[{target_bare}]]",
            "line": r["line"],
        })
    return results


def scan_section_refs(section_anchor: str, scope_files: Optional[list] = None, vault_dir: Optional[str] = None) -> list:
    """查 §section_anchor（如 "§2.6" 或 "§核心禁令"）被哪些文件引用。

    Args:
        section_anchor: 含 § 前缀（"§2.6"）或不含（"2.6"），都接受
        scope_files: 限定扫描的文件清单（相对 vault 路径），None=全 vault
        vault_dir: Vault 根目录
    Returns:
        [{"file":, "line":, "text":}, ...]
    """
    vd = vault_dir or _DEFAULT_VAULT_DIR
    anchor = section_anchor.lstrip("§").strip()
    # 匹配 §2.6 / § 2.6 / §核心禁令
    pattern = r"§\s*" + re.escape(anchor)
    results = []
    if scope_files:
        for sf in scope_files:
            sf_path = Path(vd) / sf if not Path(sf).is_absolute() else Path(sf)
            if not sf_path.exists():
                continue
            rc, out, _ = _run_cmd(["rg", "-n", "--no-heading", pattern, str(sf_path)], timeout=10)
            if rc == 0:
                for line in out.splitlines():
                    m = re.match(r"^(.+?):(\d+):(.*)$", line)
                    if m:
                        results.append({"file": sf, "line": int(m.group(2)), "text": m.group(3)})
    else:
        raw = _rg_search(pattern, vd)
        for r in raw:
            rel = str(Path(r["file"]).relative_to(vd)) if r["file"].startswith(vd) else r["file"]
            results.append({"file": rel, "line": r["line"], "text": r["text"]})
    return results


def scan_mem_refs(mem_id: str, vault_dir: Optional[str] = None) -> list:
    """查 MEM#xxxx 编号被哪些文件引用。

    Args:
        mem_id: 数字 ID（"38940"）或 "MEM#38940" 形式
    Returns:
        [{"file":, "line":, "text":, "mem_id":}, ...]
    """
    vd = vault_dir or _DEFAULT_VAULT_DIR
    mid = mem_id.replace("MEM#", "").replace("#", "").strip()
    if not mid.isdigit():
        return []
    pattern = r"MEM#" + mid + r"\b"
    raw = _rg_search(pattern, vd)
    results = []
    for r in raw:
        rel = str(Path(r["file"]).relative_to(vd)) if r["file"].startswith(vd) else r["file"]
        results.append({"file": rel, "line": r["line"], "text": r["text"], "mem_id": int(mid)})
    return results


def scan_unresolved_links(vault_dir: Optional[str] = None, limit: int = 50) -> list:
    """查 Vault 断链（unresolved wikilinks），调 obsidian unresolved。

    Returns:
        [{"link": "..."}, ...]  断链目标清单（前 limit 个）
    """
    vd = vault_dir or _DEFAULT_VAULT_DIR
    obsidian_bin = shutil.which("obsidian")
    if not obsidian_bin:
        return []
    rc, out, _ = _run_cmd(
        [obsidian_bin, "unresolved", "format=json"],
        cwd=vd, timeout=30,
    )
    if rc != 0 or not out.strip():
        return []
    try:
        data = json.loads(out)
        if isinstance(data, list):
            return data[:limit]
    except json.JSONDecodeError:
        pass
    return []


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "init"
    print(f"=== wikilink refs to '{target}' ===")
    for r in scan_wikilink_refs(target)[:10]:
        print(f"  {r['source_file']}:{r['line']}  {r['link_text']}")
