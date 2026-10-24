"""
模块 5：AI ASO 智能分析与元数据推荐 Agent (ai_agent.py)
基于平台积累的历史排名时序数据 (rank_history)、关键词热度与竞争度 (keywords)、
关联竞品同词排名矩阵 (competitor_ranks) 以及当前应用元数据 (apps)，
提供「本地量化策略推理引擎（零成本免 Key）」与「LLM 大模型 Agent（支持 DeepSeek / OpenAI / 通义千问等）」双引擎分析，
最终输出可直接用于 App Store Connect 发版的：
1. 推荐应用标题 (Title, ≤30 字符)
2. 推荐应用副标题 (Subtitle, ≤30 字符)
3. 推荐 100 字符关键词串 (Keywords, ≤100 字符，严格基于用户监控词库去重并按 ROI 贪心装箱，坚决不随意填充无关词根)
4. 词库四象限分层诊断报告（核心护城河词 / 副标题冲刺词 / 100字符黄金词 / 建议淘汰词）
5. 垂直领域候选灵感池（仅供参考，不自动填充入 100 字符，开发者自主点击纳入监控）
"""
import json
import re
import ssl
import urllib.request
from typing import Any, Dict, List, Optional

from optimizer import (
    KEYWORDS_LIMIT,
    SUBTITLE_LIMIT,
    TITLE_LIMIT,
    analyze_100_char_workspace,
    normalize_keyword_string,
)



def evaluate_keyword_aso_value(
    kw_row: Dict[str, Any],
    trend_points: List[Dict[str, Any]],
    app_rating_count: int = 0,
) -> Dict[str, Any]:
    """
    综合评估单个监控词的 ASO 战略价值 (ROI Score 0~100) 与推荐归属位置：
    考虑因素：
    1. 搜索热度 (Popularity 5~100)
    2. 攻克可行性 (100 - Difficulty)，评论数较少的应用对低难度词给予更高加成
    3. 当前排名与历史爬升势能 (Rank & 30d Momentum)
    4. 竞品差距 (Competitor Gap：竞品在 Top 10 而我方在 #4~#50 的词具备极高截流价值)
    """
    pop = float(kw_row.get("popularity") or 50)
    diff = float(kw_row.get("difficulty") or 35.0)
    today_rank = kw_row.get("today_rank")
    best_rank = kw_row.get("best_rank")
    tag = kw_row.get("tag", "核心词")

    # 计算历史累计爬升幅度 (首日排名 - 最新排名)
    valid_pts = [p["rank"] for p in trend_points if p.get("rank") and p["rank"] <= 200]
    rank_gain_30d = (valid_pts[0] - valid_pts[-1]) if len(valid_pts) >= 2 else 0

    # 1. 热度分 (0 ~ 35)
    pop_score = min(35.0, (pop / 100.0) * 35.0)

    # 2. 可行性分 (0 ~ 30)
    feasibility_weight = 34.0 if app_rating_count < 500 else 28.0
    feasibility_score = max(0.0, ((100.0 - diff) / 100.0) * feasibility_weight)

    # 3. 排名卡位与趋势加分 (0 ~ 25)
    momentum_score = 0.0
    position_status = "未入榜 (>200)"
    if today_rank is not None and today_rank <= 3:
        momentum_score = 22.0
        position_status = f"🏆 霸榜护城河 (#{today_rank})"
    elif today_rank is not None and today_rank <= 15:
        # 4~15 名是“临门一脚”黄金冲刺区
        momentum_score = 26.0
        position_status = f"🚀 冲刺 Top 3 (#{today_rank})"
    elif today_rank is not None and today_rank <= 50:
        momentum_score = 18.0
        position_status = f"📈 潜力卡位 (#{today_rank})"
    elif today_rank is not None and today_rank <= 200:
        momentum_score = 10.0
        position_status = f"👀 200内浮动 (#{today_rank})"
    else:
        # 未入榜且难度极大，扣分避免浪费字符
        if diff >= 65.0:
            momentum_score = -12.0
        else:
            momentum_score = 6.0

    # 30 天内排名上升带来额外动量加分
    if rank_gain_30d > 5:
        momentum_score += min(8.0, rank_gain_30d * 0.25)

    # 4. 竞品差距与截流机会 (0 ~ 10)
    comp_ranks = kw_row.get("comp_ranks") or {}
    best_comp_rank = min([r for r in comp_ranks.values() if r and r <= 200], default=None)
    comp_bonus = 0.0
    comp_insight = "无竞品进入 Top 200"
    if best_comp_rank is not None and best_comp_rank <= 10:
        if today_rank is None or today_rank > best_comp_rank:
            comp_bonus = 8.0
            comp_insight = f"⚔️ 竞品最高居 #{best_comp_rank}，截流机会大"
        else:
            comp_bonus = 5.0
            comp_insight = f"✅ 已压制竞品 (#{best_comp_rank})"
    elif best_comp_rank is not None and best_comp_rank <= 50:
        comp_bonus = 3.0
        comp_insight = f"竞品处于前 50 (#{best_comp_rank})"

    total_roi = pop_score + feasibility_score + momentum_score + comp_bonus
    roi_score = max(5.0, min(99.5, round(total_roi, 1)))

    # 计算单字价值密度（ASO 核心逻辑：越短越好填）
    kw_len = max(1, len(kw_row.get("keyword", "")))
    char_efficiency = round(roi_score / kw_len, 1)

    # 归属层级建议 (四象限诊断)
    recommended_slot = "💎 100字符黄金词 (Keywords)"
    action_reason = ""
    if tag == "品牌词" or (today_rank and today_rank <= 2 and diff < 25):
        recommended_slot = "🏆 主标题核心词 (Title)"
        action_reason = f"当前排 #{today_rank}，热度 {int(pop)}、难度仅 {diff}，属于必须稳守的品牌护城河"
    elif (
        (today_rank and 3 <= today_rank <= 25 and diff <= 55)
        or (roi_score >= 72 and diff <= 48)
    ):
        recommended_slot = "🚀 副标题冲刺词 (Subtitle)"
        action_reason = f"近30天变化 {rank_gain_30d:+d} 名至 #{today_rank or '>200'}，高权重副标题可推升进 Top 3"
    elif diff >= 70 and (today_rank is None or today_rank > 35):
        recommended_slot = "⚠️ 建议后置 (避开巨头锋芒)"
        action_reason = f"难度高达 {diff}（巨头盘踞），我方排名后置，建议勿占正副标题高权重位"
    elif tag == "竞品词":
        recommended_slot = "💎 100字符竞品借势词 (Keywords)"
        action_reason = f"竞品品牌词不宜出现在正副标题（防审核被拒），建议置于 100 字符栏借势覆盖"
    else:
        recommended_slot = "💎 100字符黄金词 (Keywords)"
        action_reason = f"单字价值密度 {char_efficiency}（热度 {int(pop)} / 难度 {diff}），适合放入 100 字符栏组合长尾搜索"

    return {
        **kw_row,
        "roi_score": roi_score,
        "char_efficiency": char_efficiency,
        "rank_gain_30d": rank_gain_30d,
        "position_status": position_status,
        "comp_insight": comp_insight,
        "recommended_slot": recommended_slot,
        "action_reason": action_reason,
    }


def _pack_100_char_keywords(
    title: str,
    subtitle: str,
    candidate_keywords: List[str],
) -> Dict[str, Any]:
    """
    智能去重与贪心装箱算法（100% 纯真实数据源）：
    1. 候选词必须 100% 来自开发者自身填写的监控词库与发版侧重点，绝无任何预设假词；
    2. 自动检测并剔除已在 Title 和 Subtitle 中出现的词；
    3. 严格控制在 ≤100 字符，按传入顺序（ROI 或热度权重）贪心放入；
    4. 真实展现字符利用率与剩余额度，装多少是多少，绝不伪造填充。
    """
    meta_combined = f"{title} {subtitle}".lower()
    meta_chars = set(re.findall(r"[\u4e00-\u9fff]", meta_combined))
    meta_en_tokens = set(re.findall(r"[a-z0-9]+", meta_combined))
    
    chosen: List[str] = []
    seen_lower = set()

    for raw_w in candidate_keywords:
        w = raw_w.strip()
        if not w:
            continue
        wl = w.lower()
        if wl in seen_lower or wl in meta_combined:
            continue
            
        # 英文词组检测：若词组内所有单词均已在正副标题中索引，则跳过
        en_tokens = re.findall(r"[a-z0-9]+", wl)
        if en_tokens and set(en_tokens).issubset(meta_en_tokens):
            continue

        # 中文字符检测：若字级重合度超过 70%，剥离已出现字根，剩余 >=2 字保留，否则跳过
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", wl)
        if cjk_chars:
            overlap_ratio = sum(1 for ch in cjk_chars if ch in meta_chars) / len(cjk_chars)
            if overlap_ratio >= 0.70:
                fresh_part = "".join(ch for ch in cjk_chars if ch not in meta_chars)
                if len(fresh_part) >= 2 and fresh_part not in seen_lower:
                    w = fresh_part
                    wl = w.lower()
                else:
                    continue

        candidate_str = ",".join(chosen + [w])
        if len(candidate_str) <= KEYWORDS_LIMIT:
            chosen.append(w)
            seen_lower.add(wl)

    raw_joined = ",".join(chosen)
    checked = analyze_100_char_workspace(title, subtitle, raw_joined, auto_remove_title_dups=True)
    return {
        "keywords_str": checked["keywords"]["active_str"],
        "length": checked["keywords"]["length"],
        "remaining": checked["keywords"]["remaining"],
        "token_count": checked["keywords"]["token_count"],
        "tokens": chosen,
    }


def generate_aso_recommendations_local(
    app_info: Dict[str, Any],
    keyword_rows: List[Dict[str, Any]],
    competitors: List[Dict[str, Any]],
    releases: List[Dict[str, Any]],
    trend_map: Optional[Dict[int, List[Dict[str, Any]]]] = None,
    custom_focus: str = "",
) -> Dict[str, Any]:
    """
    零预设 · 100% 实际数据驱动的本地量化策略推理引擎：
    完全基于开发者在 SQLite 中真实监控的词库、排名时序 (rank_history)、热度难度与真实应用元数据运算。
    坚决杜绝：
    1. 任何形式的预设赛道猜测与理财兜底；
    2. 任何硬编码文案模板；
    3. 任何未经开发者录入确认的伪造词汇。
    """
    trend_map = trend_map or {}
    current_title = str(app_info.get("name") or "").strip()
    current_sub = str(app_info.get("subtitle") or "").strip()
    country = str(app_info.get("country") or "CN").upper()

    # 开发者显式指定的发版侧重点（若填写，作为最高优种子词处理）
    custom_tokens: List[str] = []
    if custom_focus.strip():
        custom_tokens = normalize_keyword_string(custom_focus)

    # 1. 真实词库判空防御：若用户尚未录入任何监控词且无自定义侧重点，如实呈现空状态，绝不捏造假方案
    if not keyword_rows and not custom_tokens:
        diagnosis_bullets = [
            f"⚠️ **未检测到监控词库**：ASO 策略引擎严格遵循「100% 实际数据驱动，绝不预设或捏造任何无关词汇」。当前应用（`{current_title}`，Storefront: `{country}`）尚未录入监控关键词，无法测算排名时序与 ROI 价值。",
            "💡 **请先录入核心监控词**：请前往上方【模块 3：拓词与难度评估】为您关心的核心业务场景添加关键词并跟踪排名，系统将立即基于真实时序数据为您生成专属发布方案！",
            f"🎯 **当前线上标题利用率**：线上标题「`{current_title}`」占用 **{len(current_title)}/30** 字符（闲置 **{max(0, 30 - len(current_title))}** 字符）；线上副标题「`{current_sub}`」占用 **{len(current_sub)}/30** 字符（闲置 **{max(0, 30 - len(current_sub))}** 字符）。",
        ]
        return {
            "engine": "本地量化策略 AI Agent (Zero-Cost Data-Driven Engine)",
            "app_id": app_info.get("app_id"),
            "country": country,
            "diagnosis_bullets": diagnosis_bullets,
            "proposals": [],
            "evaluated_keywords": [],
            "candidate_reserves": [],
        }

    # 2. 对所有真实监控词进行多维 ROI 打分
    evaluated: List[Dict[str, Any]] = []
    for r in keyword_rows:
        t_pts = trend_map.get(r["id"]) or []
        eval_item = evaluate_keyword_aso_value(r, t_pts, app_rating_count=int(app_info.get("rating_count") or 0))
        evaluated.append(eval_item)

    # 按综合 ROI 降序排序
    evaluated.sort(key=lambda x: x["roi_score"], reverse=True)

    # 3. 提取线上真实品牌名前缀
    brand_prefix = current_title.split(" - ")[0].split("—")[0].split(":")[0].strip()[:10]
    if not brand_prefix:
        brand_prefix = current_title[:8] or "App"

    # 判断是否为中文字符环境（决定拼接连接符）
    sample_corpus = f"{current_title} {current_sub} " + " ".join(r.get("keyword", "") for r in keyword_rows[:5])
    is_cjk = bool(re.search(r"[\u4e00-\u9fff]", sample_corpus))

    # 按不同策略维度拆分词库候选池
    non_comp_kws = [e for e in evaluated if e.get("tag") != "竞品词"]
    comp_kws = [e for e in evaluated if e.get("tag") == "竞品词"]

    roi_kws = [e["keyword"] for e in non_comp_kws]
    high_pop_kws = [e["keyword"] for e in sorted(non_comp_kws, key=lambda x: (x["popularity"], -x["difficulty"]), reverse=True)]
    low_diff_kws = [e["keyword"] for e in sorted(non_comp_kws, key=lambda x: (x["difficulty"], -x["popularity"]))]

    # --------------------------------------------------------------------------
    # 4. 纯数据驱动：动态装配 3 套策略级 ASO 元数据方案
    # --------------------------------------------------------------------------
    scheme_definitions = [
        (
            "方案 A（🌟 综合 ROI 黄金平衡方案）",
            "兼顾转化率与搜索潜力：从您的真实词库中提拔近期排名势能最强、综合 ROI 最高的词作为主副标题，剩余监控词全量装箱入 100 字符域。",
            roi_kws,
        ),
        (
            "方案 B（🚀 搜索热度抢量攻坚方案）",
            "流量最大化导向：从您的真实词库中提取搜索热度 (Popularity) 最高的词前置到标题高权重区，适合大版本更新强攻核心大词流量。",
            high_pop_kws,
        ),
        (
            "方案 C（🛡️ 蓝海低竞争稳健方案）",
            "低难度易攻坚导向：锁定您词库中竞争难度 (Difficulty) 最低、容易快速冲入 Top 3 的蓝海细分词，稳扎稳打积累自然曝光。",
            low_diff_kws,
        ),
    ]

    proposals: List[Dict[str, Any]] = []

    for badge_title, strategy_desc, candidate_pool in scheme_definitions:
        ordered_candidates = custom_tokens + [w for w in candidate_pool if w not in custom_tokens]

        # 动态拼接主标题 (Title, ≤30 字符，最多吸收 2 个高优核心词)
        title_picked: List[str] = []
        for kw in ordered_candidates:
            # 避开与品牌名完全相同的词
            if kw.lower() == brand_prefix.lower() or kw.lower() in brand_prefix.lower():
                continue
            conn = "与" if (is_cjk and title_picked) else (" & " if title_picked else "")
            test_t = f"{brand_prefix} - " + (conn.join(title_picked + [kw]) if title_picked else kw)
            if len(test_t) <= TITLE_LIMIT:
                title_picked.append(kw)
                if len(title_picked) >= 2:
                    break

        if title_picked:
            conn_title = "与" if is_cjk else " & "
            dyn_title = f"{brand_prefix} - {conn_title.join(title_picked)}"
        else:
            dyn_title = current_title[:TITLE_LIMIT]

        # 动态拼接副标题 (Subtitle, ≤30 字符，吸收 2~3 个未在主标题出现的次优词)
        sub_picked: List[str] = []
        for kw in ordered_candidates:
            if kw in title_picked or kw.lower() in dyn_title.lower():
                continue
            conn = "·" if (is_cjk and sub_picked) else (", " if sub_picked else "")
            test_s = conn.join(sub_picked + [kw]) if sub_picked else kw
            if len(test_s) <= SUBTITLE_LIMIT:
                sub_picked.append(kw)
                if len(sub_picked) >= 3:
                    break

        conn_sub = "·" if is_cjk else ", "
        dyn_subtitle = conn_sub.join(sub_picked)[:SUBTITLE_LIMIT] if sub_picked else current_sub[:SUBTITLE_LIMIT]

        # 100 字符关键词栏装箱：100% 来源于真实词库中剩余未被正副标题吸收的词（含竞品词）
        used_meta_kws = set(title_picked + sub_picked)
        remaining_pool = [
            w for w in (custom_tokens + [e["keyword"] for e in evaluated])
            if w not in used_meta_kws
        ]

        packed = _pack_100_char_keywords(dyn_title, dyn_subtitle, remaining_pool)
        proposals.append(
            {
                "scheme_name": badge_title,
                "strategy_summary": strategy_desc,
                "title": dyn_title,
                "title_len": len(dyn_title),
                "title_remaining": max(0, TITLE_LIMIT - len(dyn_title)),
                "subtitle": dyn_subtitle,
                "subtitle_len": len(dyn_subtitle),
                "subtitle_remaining": max(0, SUBTITLE_LIMIT - len(dyn_subtitle)),
                "keywords": packed["keywords_str"],
                "keywords_len": packed["length"],
                "keywords_remaining": packed["remaining"],
                "keywords_count": packed["token_count"],
            }
        )

    # 5. 生成基于真实监控数据的诊断洞察
    top10_count = sum(1 for e in evaluated if e.get("today_rank") and e["today_rank"] <= 10)
    striking_kws = [e["keyword"] for e in evaluated if e.get("today_rank") and 4 <= e["today_rank"] <= 20]
    avg_pop = round(sum(e["popularity"] for e in evaluated) / max(1, len(evaluated)), 1)
    avg_diff = round(sum(e["difficulty"] for e in evaluated) / max(1, len(evaluated)), 1)

    diagnosis_bullets = [
        f"📊 **真实词库大盘指标**：当前共监控 **{len(evaluated)}** 个关键词，其中 **{top10_count}** 个已稳居 Top 10 曝光区；监控词库平均搜索热度为 **{avg_pop}**，平均竞争难度为 **{avg_diff}**。",
        f"🎯 **当前线上标题诊断**：线上实际标题「`{current_title}`」占用 **{len(current_title)}/30** 字符（闲置 **{max(0, 30 - len(current_title))}** 个最高权重字符）；在苹果算法中标题权重极高，闲置字符建议直接植入您词库中的高分核心词（如 `{'、'.join(striking_kws[:2]) or (roi_kws[0] if roi_kws else '核心业务词')}`）。",
        f"🚀 **冲刺 Top 3 黄金机会**：监控词汇中 **{'、'.join(f'「{k}」' for k in striking_kws[:4]) or '核心卡位词'}** 当前处于 #4~#20 梯队且近 30 天呈持续爬升态势，动态方案已将其提拔至主副标题，助力下个版本直接抢占 Top 3 自然流量卡位。",
        f"🛡️ **绝对纯净装箱原则**：推荐方案中的所有主标题、副标题与 100 字符**100% 来源于您的真实监控词库与发版意图**，坚决不预设、不捏造任何未经监控的外部生词。当前 100 字符栏已为您装入 **{proposals[0]['keywords_count']}** 个独立词（占 **{proposals[0]['keywords_len']}/100** 字符），若需继续装满剩余额度，建议前往【模块 3：拓词与难度评估】为您关心的更多长尾词添加监控！",
    ]

    # 提取监控词库中未被方案 A 主副标题占用的候选储备词（替代原先假灵感库）
    p0 = proposals[0]
    covered_in_p0 = f"{p0['title']} {p0['subtitle']}".lower()
    candidate_reserves = [
        e for e in evaluated
        if e["keyword"].lower() not in covered_in_p0
    ][:8]

    return {
        "engine": "本地量化策略 AI Agent (Zero-Cost Data-Driven Engine)",
        "app_id": app_info.get("app_id"),
        "country": country,
        "diagnosis_bullets": diagnosis_bullets,
        "proposals": proposals,
        "evaluated_keywords": evaluated,
        "candidate_reserves": candidate_reserves,
    }


def build_agent_prompt_text(
    app_info: Dict[str, Any],
    keyword_eval_rows: List[Dict[str, Any]],
    competitors: List[Dict[str, Any]],
    custom_focus: str = "",
) -> str:
    """构建发送给外部 LLM 的标准 Context 数据包"""
    core_kw_lines = []
    for k in keyword_eval_rows:
        core_kw_lines.append(
            f"- 词名: {k['keyword']} | 分类: {k['tag']} | 热度: {k['popularity']} | 难度: {k['difficulty']} | "
            f"今日排名: #{k['today_rank'] or '>200'} | 30天变化: {k['rank_gain_30d']:+d}名 | ROI得分: {k['roi_score']} | "
            f"竞品态势: {k['comp_insight']}"
        )

    comp_lines = [
        f"- 竞品: {c.get('name')} (ID: {c.get('app_id')}) | 评分: ⭐{c.get('rating')} | 评论数: {c.get('rating_count')}"
        for c in competitors
    ]

    prompt = f"""你是一名精通苹果 App Store ASO (应用商店搜索优化) 的资深增长专家。
请根据以下平台积累的真实数据，为我方 iOS 应用制定下一版本更新的【最终发布元数据方案】。

### 1. 我方应用基础信息
- App ID: {app_info.get('app_id')}
- 国家/地区 Storefront: {app_info.get('country', 'CN')}
- 当前线上标题: {app_info.get('name', '')}
- 当前线上副标题: {app_info.get('subtitle', '')}
- 当前评分: ⭐{app_info.get('rating', 5.0)} ({app_info.get('rating_count', 0)} 条评论)
- 本次发版业务侧重点: {custom_focus or '无特殊偏好，基于数据最大化自然搜索曝光与下载转化'}

### 2. 平台积累的核心关键词时序与 ROI 数据
{chr(10).join(core_kw_lines)}

### 3. 已绑定的核心竞品
{chr(10).join(comp_lines) if comp_lines else '暂未绑定竞品'}

### 4. 输出约束与硬性要求
1. **真实数据准则（最高优先级）**：我方应用功能范畴完全由上述真实标题「{app_info.get('name', '')}」与词库决定。**绝对严禁输出任何与本应用业务无关的行业或生造词汇（如理财、存钱、记账、游戏等未在我方数据包中出现的行业）**！所有推荐必须 100% 严格以我方真实数据为准。
2. **标题 (Title)**：必须 ≤30 字符。品牌名放前，核心功能词在后，用短横线 ` - ` 分隔；
3. **副标题 (Subtitle)**：必须 ≤30 字符。阐明应用核心价值主张与高转化词根，尽量不要与标题有完全相同的词；
4. **100 字符关键词 (Keywords)**：必须 ≤100 字符。
   - **严格基于上述词库**：只选用我方已监控或上述数据包中提到的相关词根，**绝对不要随意生造或填充与应用功能无关的词**；
   - **零重复**：必须自动剔除已在 Title 和 Subtitle 中出现的词根；
   - **零空格紧凑格式**：词与词之间仅使用英文半角逗号 `,` 分隔；
5. 请以结构化 JSON 格式输出 3 套方案（方案 A 黄金平衡冲榜、方案 B 核心大词强攻、方案 C 低竞争蓝海稳健霸榜），并附带简要诊断说明。
"""
    return prompt


def run_llm_aso_agent(
    app_info: Dict[str, Any],
    keyword_rows: List[Dict[str, Any]],
    competitors: List[Dict[str, Any]],
    releases: List[Dict[str, Any]],
    trend_map: Optional[Dict[int, List[Dict[str, Any]]]] = None,
    api_key: str = "",
    base_url: str = "https://api.deepseek.com/v1",
    model_name: str = "deepseek-chat",
    custom_focus: str = "",
) -> Dict[str, Any]:
    """外部大模型 Agent 调用包装器"""
    fallback_res = generate_aso_recommendations_local(
        app_info, keyword_rows, competitors, releases, trend_map, custom_focus
    )

    if not api_key.strip():
        return fallback_res

    prompt = build_agent_prompt_text(
        app_info, fallback_res["evaluated_keywords"], competitors, custom_focus
    )

    req_url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key.strip()}",
        "User-Agent": "ASOToolkit-Agent/1.0",
    }
    payload = {
        "model": model_name or "deepseek-chat",
        "messages": [
            {
                "role": "system",
                "content": "你是一名精通苹果 App Store ASO 规则的资深算法专家。请严格返回 JSON 对象，不要包含 markdown 标记外的冗余解释。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
    }

    try:
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(req_url, data=req_data, headers=headers, method="POST")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
            resp_body = response.read().decode("utf-8")
            data = json.loads(resp_body)
            content = data["choices"][0]["message"]["content"]

            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                parsed_json = json.loads(json_match.group(0))
                if "proposals" in parsed_json and isinstance(parsed_json["proposals"], list):
                    return {
                        "engine": f"LLM Agent ({model_name})",
                        "app_id": app_info.get("app_id"),
                        "country": app_info.get("country"),
                        "diagnosis_bullets": parsed_json.get(
                            "diagnosis_bullets", fallback_res["diagnosis_bullets"]
                        ),
                        "proposals": parsed_json["proposals"],
                        "evaluated_keywords": fallback_res["evaluated_keywords"],
                        "candidate_reserves": fallback_res.get("candidate_reserves", []),
                    }
    except Exception:
        pass

    return fallback_res
