"""检查类型: field_check — 从 context 取字段,检查长度/非空。
用于 G1(files 非空)/G2(summary≥10)/G3(experiences)。
"""
from typing import Any


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      jsonpath: context 里的字段名(如 "files" / "summary")
      min_len: 最小长度(list 取 len,str 取 len字符)
    返回: (passed, detail)
    """
    jsonpath = params.get("jsonpath", "")
    min_len = params.get("min_len", 1)
    value = context.get(jsonpath)
    if value is None:
        return False, f"字段 '{jsonpath}' 不存在(context 未提供)"
    if isinstance(value, (list, str, dict)):
        actual_len = len(value)
    else:
        actual_len = 1 if value else 0
    passed = actual_len >= min_len
    type_desc = type(value).__name__
    if passed:
        return True, f"'{jsonpath}' 长度 {actual_len} ≥ {min_len}({type_desc})"
    else:
        return False, f"'{jsonpath}' 长度 {actual_len} < {min_len}({type_desc},值={str(value)[:40]})"
