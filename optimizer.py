"""
模块 4：100 字符组装工作台 (optimizer.py)
严格实现 PRD 模块 4 全部需求：
1. 实时字符计数器 (P0): 标题限 30 字符、副标题限 30 字符、关键词域限 100 字符，实时显示已用与剩余字符数。
2. 智能清洗与去重 (P1):
   - 自动将中文逗号 `，`、顿号 `、`、分号 `;`/`；`、换行及多余空格替换为英文半角逗号 `,`；
   - 自动去重 100 字符内部重复填写的词；
   - 自动检测 100 字符中是否重复包含了“标题”或“副标题”里已有的词，并高亮提示与一键剔除。
"""
import re
from typing import Any, Dict, List

TITLE_LIMIT = 30
SUBTITLE_LIMIT = 30
KEYWORDS_LIMIT = 100


def normalize_keyword_string(raw_keywords: str) -> List[str]:
    """
    将包含中文逗号、顿号、分号、换行或空格分隔的原始关键词文本清洗为标准词列表。
    """
    if not raw_keywords:
        return []
    # 替换所有常见分隔符为英文半角逗号
    cleaned = re.sub(r"[，、；;\n\r\t]+", ",", raw_keywords)
    # 若词与词之间用空格分隔（针对中文或短词），将连续空格也视为分隔符，但保留英文词组内部单个空格可选
    parts = []
    for chunk in cleaned.split(","):
        s = chunk.strip()
        if not s:
            continue
        # 如果包含中文字符且带空格，按空格拆分为独立词
        if re.search(r"[\u4e00-\u9fff]", s) and " " in s:
            for sub in re.split(r"\s+", s):
                if sub.strip():
                    parts.append(sub.strip())
        else:
            parts.append(re.sub(r"\s+", " ", s))
    return parts


def analyze_100_char_workspace(
    title: str,
    subtitle: str,
    raw_keywords: str,
    auto_remove_title_dups: bool = False,
) -> Dict[str, Any]:
    """
    分析并清洗标题、副标题与 100 字符关键词栏。
    返回字符统计、内部重复词、与标题/副标题冲突的重复词、以及清洗后的最佳 100 字符字符串。
    """
    title_clean = (title or "").strip()
    subtitle_clean = (subtitle or "").strip()
    combined_meta_lower = f"{title_clean} {subtitle_clean}".lower()

    tokens = normalize_keyword_string(raw_keywords)

    seen_lower = set()
    internal_duplicates: List[str] = []
    title_subtitle_Conflicts: List[Dict[str, str]] = []
    unique_tokens: List[str] = []
    kept_tokens: List[str] = []

    for tok in tokens:
        tl = tok.lower()
        if tl in seen_lower:
            internal_duplicates.append(tok)
            continue
        seen_lower.add(tl)
        unique_tokens.append(tok)

        # 检测该词是否已完全包含在标题或副标题中
        in_title = tl in title_clean.lower() if title_clean else False
        in_subtitle = tl in subtitle_clean.lower() if subtitle_clean else False

        if in_title or in_subtitle:
            source = "标题 & 副标题" if (in_title and in_subtitle) else ("标题" if in_title else "副标题")
            title_subtitle_Conflicts.append({"keyword": tok, "source": source})
            if not auto_remove_title_dups:
                kept_tokens.append(tok)
        else:
            kept_tokens.append(tok)

    # 拼装标准英文半角逗号分隔字符串（无多余空格，最大化利用 100 字符）
    normalized_all_str = ",".join(unique_tokens)
    optimized_str = ",".join(
        [t for t in unique_tokens if t.lower() not in {c["keyword"].lower() for c in title_subtitle_Conflicts}]
    )
    active_str = optimized_str if auto_remove_title_dups else normalized_all_str

    saved_chars = len(raw_keywords.strip()) - len(optimized_str) if raw_keywords.strip() else 0

    return {
        "title": {
            "text": title_clean,
            "length": len(title_clean),
            "remaining": TITLE_LIMIT - len(title_clean),
            "over_limit": len(title_clean) > TITLE_LIMIT,
        },
        "subtitle": {
            "text": subtitle_clean,
            "length": len(subtitle_clean),
            "remaining": SUBTITLE_LIMIT - len(subtitle_clean),
            "over_limit": len(subtitle_clean) > SUBTITLE_LIMIT,
        },
        "keywords": {
            "raw_length": len(raw_keywords),
            "normalized_str": normalized_all_str,
            "optimized_str": optimized_str,
            "active_str": active_str,
            "length": len(active_str),
            "remaining": KEYWORDS_LIMIT - len(active_str),
            "over_limit": len(active_str) > KEYWORDS_LIMIT,
            "token_count": len(kept_tokens),
            "internal_duplicates": internal_duplicates,
            "title_subtitle_conflicts": title_subtitle_Conflicts,
            "saved_chars": max(0, saved_chars),
        },
    }
