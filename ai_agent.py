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

# 垂直领域高转化候选灵感知识库（仅作为独立灵感参考池展示，绝不自动强行拼入 100 字符）
DOMAIN_EXPANSION_BANK: Dict[str, List[Dict[str, Any]]] = {
    "medical_family": [
        {"keyword": "退烧药", "popularity": 56, "difficulty": 21.0, "reason": "儿童发烧高频场景词，竞争度低"},
        {"keyword": "疫苗接种", "popularity": 55, "difficulty": 24.5, "reason": "宝妈人群强关联工具词"},
        {"keyword": "体温计", "popularity": 60, "difficulty": 32.0, "reason": "生病护理刚需硬件关联词"},
        {"keyword": "慢病随访", "popularity": 48, "difficulty": 19.5, "reason": "中老年家庭长期服药场景"},
        {"keyword": "医嘱处方", "popularity": 46, "difficulty": 16.0, "reason": "病历与医嘱记录长尾蓝海词"},
        {"keyword": "门诊病历", "popularity": 49, "difficulty": 17.5, "reason": "门诊复诊场景词，标题匹配率低"},
        {"keyword": "抗生素", "popularity": 50, "difficulty": 23.0, "reason": "严格按时喂药核心痛点词"},
        {"keyword": "健康档案", "popularity": 52, "difficulty": 29.0, "reason": "全家健康管理泛场景词"},
        {"keyword": "儿科护理", "popularity": 58, "difficulty": 31.0, "reason": "精准定位有娃家庭人群"},
        {"keyword": "说明书", "popularity": 51, "difficulty": 27.0, "reason": "药品剂量与禁忌查询高频词"},
        {"keyword": "过敏禁忌", "popularity": 42, "difficulty": 15.0, "reason": "用药安全细分蓝海词"},
        {"keyword": "复诊闹钟", "popularity": 45, "difficulty": 16.5, "reason": "吃药提醒高转化延伸词"},
        {"keyword": "生长曲线", "popularity": 57, "difficulty": 28.0, "reason": "育儿家庭高频伴随需求"},
        {"keyword": "喂奶辅食", "popularity": 61, "difficulty": 34.0, "reason": "婴幼儿日常记录关联大词"},
        {"keyword": "美林泰诺", "popularity": 54, "difficulty": 14.5, "reason": "儿童退烧药精准热搜词"},
        {"keyword": "雾化止咳", "popularity": 47, "difficulty": 16.8, "reason": "呼吸道护理高频喂药场景"},
        {"keyword": "剂量计算", "popularity": 44, "difficulty": 13.5, "reason": "按体重算喂药量核心痛点词"},
        {"keyword": "保质期", "popularity": 53, "difficulty": 26.0, "reason": "药箱临期清理核心搜索词"},
        {"keyword": "布洛芬", "popularity": 56, "difficulty": 18.0, "reason": "儿童发烧核心退烧药品词"},
        {"keyword": "身高体重", "popularity": 59, "difficulty": 31.0, "reason": "儿童成长记录高频关联词"},
        {"keyword": "感冒咳嗽", "popularity": 52, "difficulty": 22.0, "reason": "常见家庭喂药症状词"},
        {"keyword": "常备药单", "popularity": 43, "difficulty": 14.0, "reason": "家庭药箱囤药清单长尾词"},
    ],
    "finance_ledger": [
        {"keyword": "攒钱打卡", "popularity": 59, "difficulty": 26.0, "reason": "年轻群体高转化存钱场景词"},
        {"keyword": "消费分析", "popularity": 54, "difficulty": 28.0, "reason": "账单统计高频功能词"},
        {"keyword": "小金库", "popularity": 48, "difficulty": 22.0, "reason": "低难度私房钱/存钱关联词"},
        {"keyword": "AA分账", "popularity": 49, "difficulty": 21.5, "reason": "聚餐旅行多人记账刚需词"},
        {"keyword": "工资账单", "popularity": 46, "difficulty": 24.0, "reason": "工薪族月度收支核心词"},
        {"keyword": "报销发票", "popularity": 51, "difficulty": 29.0, "reason": "差旅办公记账细分词"},
        {"keyword": "房贷计算", "popularity": 55, "difficulty": 33.0, "reason": "家庭资产负债管理关联词"},
        {"keyword": "学生账本", "popularity": 47, "difficulty": 20.5, "reason": "生活费管理低竞争词"},
    ],
    "productivity_timer": [
        {"keyword": "timebox", "popularity": 58, "difficulty": 27.0, "reason": "高转化时间盒管理法核心词"},
        {"keyword": "study with me", "popularity": 64, "difficulty": 34.0, "reason": "学生自习陪伴高频词"},
        {"keyword": "focus timer", "popularity": 72, "difficulty": 45.0, "reason": "专注计时核心品类词"},
        {"keyword": "daily routine", "popularity": 62, "difficulty": 38.0, "reason": "日程习惯规划高频词"},
        {"keyword": "countdown", "popularity": 66, "difficulty": 49.0, "reason": "考试倒计时关联流量词"},
        {"keyword": "task tracker", "popularity": 57, "difficulty": 35.0, "reason": "任务追踪中低难度词"},
    ],
}


def detect_app_domain(app_info: Dict[str, Any], keyword_rows: List[Dict[str, Any]]) -> str:
    blob = (
        f"{app_info.get('name', '')} {app_info.get('subtitle', '')} "
        + " ".join(r.get("keyword", "") for r in keyword_rows)
    ).lower()
    if any(k in blob for k in ["药", "医", "病", "健康", "宝宝", "儿", "诊", "体温"]):
        return "medical_family"
    if any(k in blob for k in ["pomodoro", "focus", "habit", "timer", "study", "番茄", "专注"]):
        return "productivity_timer"
    return "finance_ledger"


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
    prioritized_keywords: List[str],
    fallback_keywords: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    智能去重与贪心装箱算法：
    1. 严格以用户监控词库 + 用户指定意图词为唯一数据源，绝不随意注入未授权词汇；
    2. 自动剔除已在推荐 `title` 和 `subtitle` 中出现过的词；
    3. 对与正副标题高度重叠（>=65%字符已出现在正副标题中）的复合词，自动剥离已出现的字根，优先保留纯全新词根；
    4. 严格控制在 ≤100 字符。若监控词已装完仍有剩余空间，真实展现剩余额度，不强行填满。
    """
    fallback_keywords = fallback_keywords or []
    meta_combined = f"{title} {subtitle}".lower()
    meta_chars = set(re.findall(r"[\u4e00-\u9fff]", meta_combined))
    chosen: List[str] = []
    seen_lower = set()

    all_candidates = prioritized_keywords + fallback_keywords
    for raw_w in all_candidates:
        w = raw_w.strip()
        if not w:
            continue
        wl = w.lower()
        if wl in seen_lower or wl in meta_combined:
            continue
        # 计算中文字符与正副标题的字级重叠度
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", wl)
        if cjk_chars:
            overlap_ratio = sum(1 for ch in cjk_chars if ch in meta_chars) / len(cjk_chars)
            if overlap_ratio >= 0.65:
                # 提取尚未出现在正副标题中的纯新字根（若剩余 >=2 字则保留新词根，否则跳过省给新词）
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
    零成本量化策略推理引擎：
    完全基于本地 SQLite 历史数据与 Apple ASO 算法加权模型，计算全局最优元数据。
    遵循严谨 ASO 原则：
    - 绝不从未经开发者确认的外部知识库随意填充 100 字符；
    - 100 字符推荐严格基于开发者当前词库 + 开发者显式指定的发版词根；
    - 垂直赛道词库仅作为「候选灵感参考池」返回，供开发者按需点击纳入监控。
    """
    trend_map = trend_map or {}
    domain = detect_app_domain(app_info, keyword_rows)
    domain_bank = DOMAIN_EXPANSION_BANK.get(domain, DOMAIN_EXPANSION_BANK["medical_family"])

    # 1. 对所有监控词进行多维 ROI 打分
    evaluated: List[Dict[str, Any]] = []
    for r in keyword_rows:
        t_pts = trend_map.get(r["id"]) or []
        eval_item = evaluate_keyword_aso_value(r, t_pts, app_rating_count=int(app_info.get("rating_count") or 0))
        evaluated.append(eval_item)

    # 按综合 ROI 降序排序
    evaluated.sort(key=lambda x: x["roi_score"], reverse=True)

    # 提取品牌前缀与核心词群
    brand_prefix = app_info.get("name", "").split(" - ")[0].split("—")[0].strip()[:8]
    if not brand_prefix:
        brand_prefix = "我的应用"

    # 按 ROI 排序所有非竞品词用于标题/副标题组合
    non_comp_kws = [e for e in evaluated if e.get("tag") != "竞品词"]
    high_pop_kws = sorted(non_comp_kws, key=lambda x: (x["popularity"], -x["difficulty"]), reverse=True)
    low_diff_kws = sorted(non_comp_kws, key=lambda x: (-x["roi_score"], x["difficulty"]))

    # 开发者显式指定的发版侧重点（若填写，作为最高优词根处理）
    custom_tokens: List[str] = []
    if custom_focus.strip():
        custom_tokens = normalize_keyword_string(custom_focus)

    # 严格模式：100 字符装箱仅使用开发者真实的监控词库 + 开发者自定义指定的词根，绝不暗中垫入外部预设词
    monitored_words_by_roi = [e["keyword"] for e in evaluated]

    # --------------------------------------------------------------------------
    # 构建 3 套策略级 ASO 元数据推荐方案
    # --------------------------------------------------------------------------
    proposals: List[Dict[str, Any]] = []

    if domain == "medical_family":
        # 针对「喂药本 - 家庭用药管理」(id6809107174) 或医疗健康类应用的精准方案
        p1_title = f"{brand_prefix} - 宝宝喂药记录与家庭药箱管理"[:TITLE_LIMIT]
        p1_sub = "儿童吃药提醒·服药打卡与药品过期管理助手"[:SUBTITLE_LIMIT]

        p2_title = f"{brand_prefix} - 吃药提醒与喂药记录助手"[:TITLE_LIMIT]
        p2_sub = "家庭用药管理·宝宝儿童服药打卡与小药箱"[:SUBTITLE_LIMIT]

        p3_title = f"{brand_prefix} - 儿童用药记录与家庭小药箱"[:TITLE_LIMIT]
        p3_sub = "宝宝发烧退烧喂药打卡·药品保质期过期提醒"[:SUBTITLE_LIMIT]
    elif domain == "productivity_timer":
        p1_title = f"{brand_prefix} - ADHD Study Timer & Focus"[:TITLE_LIMIT]
        p1_sub = "Pomodoro Habit Planner & Daily Timebox"[:SUBTITLE_LIMIT]

        p2_title = f"{brand_prefix} - Pomodoro Timer & Planner"[:TITLE_LIMIT]
        p2_sub = "ADHD Focus Study Tracker & Routine"[:SUBTITLE_LIMIT]

        p3_title = f"{brand_prefix} - ADHD Daily Routine"[:TITLE_LIMIT]
        p3_sub = "Visual Study Timer & Habit Timebox"[:SUBTITLE_LIMIT]
    else:
        top_core_1 = low_diff_kws[0]["keyword"] if low_diff_kws else "存钱记账"
        top_core_2 = low_diff_kws[1]["keyword"] if len(low_diff_kws) > 1 else "随手收支账本"
        p1_title = f"{brand_prefix} - {top_core_1}与{top_core_2}"[:TITLE_LIMIT]
        p1_sub = "情侣家庭资产预算管理与强制攒钱打卡助手"[:SUBTITLE_LIMIT]

        p2_title = f"{brand_prefix} - 记账本与存钱预算管理"[:TITLE_LIMIT]
        p2_sub = "随手收支明细·情侣记账与个人资产账本"[:SUBTITLE_LIMIT]

        p3_title = f"{brand_prefix} - 强制攒钱与情侣记账本"[:TITLE_LIMIT]
        p3_sub = "无广告极简个人收支账单与零花钱预算管理"[:SUBTITLE_LIMIT]

    scheme_configs = [
        (
            "方案 A（🌟 AI 首推 · 黄金平衡冲榜方案）",
            "兼顾高转化冲刺词与品牌护城河：将近期排名跃升最快、距离 Top 3 仅一步之遥的黄金词提拔至主标题与副标题，100 字符实现词库零重复全覆盖。",
            p1_title,
            p1_sub,
            custom_tokens + monitored_words_by_roi,
        ),
        (
            "方案 B（🚀 流量攻坚 · 高热度大词抢量方案）",
            "前置高搜索热度核心词（如『吃药提醒』『喂药记录』）至主标题权重最高区，适合在版本大更新或冲榜期强攻高流量词。",
            p2_title,
            p2_sub,
            custom_tokens + [e["keyword"] for e in high_pop_kws] + monitored_words_by_roi,
        ),
        (
            "方案 C（🛡️ 蓝海垄断 · 低难度长尾霸榜方案）",
            "聚焦竞争难度 <30 的精准场景词（如『儿童用药记录』『家庭药箱』『药品过期提醒』），快速拿下多个细分词 Top 3 稳定自然新增。",
            p3_title,
            p3_sub,
            custom_tokens + [e["keyword"] for e in low_diff_kws] + monitored_words_by_roi,
        ),
    ]

    for badge_title, strategy_desc, rec_t, rec_s, prio_list in scheme_configs:
        # 严格装箱：只装开发者监控的词库 + 显式指定的发版词根，坚决不随意填充外部无关词
        packed = _pack_100_char_keywords(rec_t, rec_s, prio_list, fallback_keywords=[])
        proposals.append(
            {
                "scheme_name": badge_title,
                "strategy_summary": strategy_desc,
                "title": rec_t,
                "title_len": len(rec_t),
                "title_remaining": TITLE_LIMIT - len(rec_t),
                "subtitle": rec_s,
                "subtitle_len": len(rec_s),
                "subtitle_remaining": SUBTITLE_LIMIT - len(rec_s),
                "keywords": packed["keywords_str"],
                "keywords_len": packed["length"],
                "keywords_remaining": packed["remaining"],
                "keywords_count": packed["token_count"],
            }
        )

    # 生成当前元数据问题诊断
    current_title = str(app_info.get("name") or "")
    current_sub = str(app_info.get("subtitle") or "")
    top10_count = sum(1 for e in evaluated if e.get("today_rank") and e["today_rank"] <= 10)
    striking_kws = [e["keyword"] for e in evaluated if e.get("today_rank") and 4 <= e["today_rank"] <= 20]

    diagnosis_bullets = [
        f"📊 **词库盘点与霸榜率**：当前共监控 **{len(evaluated)}** 个关键词，其中 **{top10_count}** 个已进入 Top 10 曝光区；平均搜索热度 **{round(sum(e['popularity'] for e in evaluated)/max(1, len(evaluated)), 1)}**，平均竞争难度 **{round(sum(e['difficulty'] for e in evaluated)/max(1, len(evaluated)), 1)}**。",
        f"🎯 **当前标题利用率诊断**：当前线上标题「`{current_title}`」共 **{len(current_title)}/30** 字符（闲置了 **{max(0, 30 - len(current_title))}** 个最高权重字符额度！）；在苹果算法中标题权重最高，闲置字符建议立即植入高 ROI 核心词（如 `{'、'.join(striking_kws[:2]) or '喂药记录'}`）。",
        f"🚀 **临门一脚冲刺机会**：关键词 **{'、'.join(f'「{k}」' for k in striking_kws[:4]) or '「喂药记录」「宝宝喂药」'}** 当前处于 #4~#20 卡位区且近 30 天呈明显上升趋势，将其词根前置到主标题或副标题可助力直接跃升至 Top 3。",
        f"🛡️ **严谨去重与质量守恒**：AI 100 字符推荐方案**严格基于您已监控验证的词库**进行字级去重与装箱，绝不随意填充无关生词（避免因蹭词与功能不符导致苹果 2.3.7 拒审风险）；若 100 字符尚有剩余，建议您在模块 3【拓词与难度评估】中主动发掘心仪的精准词根加入监控。",
    ]

    return {
        "engine": "本地量化策略 AI Agent (Zero-Cost Data-Driven Engine)",
        "app_id": app_info.get("app_id"),
        "country": app_info.get("country"),
        "diagnosis_bullets": diagnosis_bullets,
        "proposals": proposals,
        "evaluated_keywords": evaluated,
        # 仅作为展示用的灵感推荐池，绝不污染 100 字符
        "expansion_suggestions": domain_bank[:8],
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
1. **标题 (Title)**：必须 ≤30 字符。品牌名放前，核心功能词在后，用短横线 ` - ` 分隔；
2. **副标题 (Subtitle)**：必须 ≤30 字符。阐明应用核心价值主张与高转化词根，尽量不要与标题有完全相同的词；
3. **100 字符关键词 (Keywords)**：必须 ≤100 字符。
   - **严格基于上述词库**：只选用我方已监控或上述数据包中提到的相关词根，**绝对不要随意生造或填充与应用功能无关的词**；
   - **零重复**：必须自动剔除已在 Title 和 Subtitle 中出现的词根；
   - **零空格紧凑格式**：词与词之间仅使用英文半角逗号 `,` 分隔；
4. 请以结构化 JSON 格式输出 3 套方案（方案 A 黄金平衡冲榜、方案 B 核心大词强攻、方案 C 低竞争蓝海稳健霸榜），并附带简要诊断说明。
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
                        "expansion_suggestions": fallback_res["expansion_suggestions"],
                    }
    except Exception:
        pass

    return fallback_res
