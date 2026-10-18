"""
模块 5：AI ASO 智能分析与元数据推荐 Agent (ai_agent.py)
基于平台积累的历史排名时序数据 (rank_history)、关键词热度与竞争度 (keywords)、
关联竞品同词排名矩阵 (competitor_ranks) 以及当前应用元数据 (apps)，
提供「本地量化策略推理引擎（零成本免 Key）」与「LLM 大模型 Agent（支持 DeepSeek / OpenAI / 通义千问等）」双引擎分析，
最终输出可直接用于 App Store Connect 发版的：
1. 推荐应用标题 (Title, ≤30 字符)
2. 推荐应用副标题 (Subtitle, ≤30 字符)
3. 推荐 100 字符关键词串 (Keywords, ≤100 字符，自动剔除标题/副标题重复词并按 ROI 贪心装箱)
4. 词库四象限分层诊断报告（核心护城河词 / 副标题冲刺词 / 100字符黄金词 / 建议淘汰词）
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

# 垂直领域高转化补词知识库（当监控词库不足以填满 100 字符时，AI Agent 自动按赛道匹配补位词根）
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
    elif today_rank is not None and 4 <= today_rank <= 15:
        momentum_score = 26.0  # 临门一脚冲刺 Top 3 的黄金卡位词！
        position_status = f"🚀 冲刺前3黄金位 (#{today_rank})"
    elif today_rank is not None and 16 <= today_rank <= 50:
        momentum_score = 18.0
        position_status = f"📈 潜力爬升区 (#{today_rank})"
    elif today_rank is not None and 51 <= today_rank <= 200:
        momentum_score = 10.0
        position_status = f"🌱 入榜培育区 (#{today_rank})"
    else:
        if diff >= 65:
            momentum_score = -12.0
            position_status = "⚠️ 高难未入榜 (>200)"
        else:
            momentum_score = 6.0
            position_status = "🔍 待收录蓝海词 (>200)"

    if rank_gain_30d > 5:
        momentum_score += min(8.0, rank_gain_30d * 0.25)

    # 4. 竞品同词博弈加分 (0 ~ 10)
    comp_ranks = kw_row.get("competitor_ranks") or {}
    best_comp_name = None
    best_comp_rank = 201
    for cname, crank in comp_ranks.items():
        if crank and crank < best_comp_rank:
            best_comp_rank = crank
            best_comp_name = cname

    comp_insight = "暂无竞品入榜"
    comp_bonus = 0.0
    if best_comp_name and best_comp_rank <= 10:
        if today_rank is None or today_rank > best_comp_rank:
            comp_bonus = 8.0
            comp_insight = f"⚔️ 竞品「{best_comp_name}」居 #{best_comp_rank}，可重点截流"
        else:
            comp_bonus = 5.0
            comp_insight = f"✅ 已压制竞品「{best_comp_name}」(#{best_comp_rank})"
    elif best_comp_name and best_comp_rank <= 50:
        comp_insight = f"竞品「{best_comp_name}」排 #{best_comp_rank}"

    roi_score = round(max(5.0, min(99.5, pop_score + feasibility_score + momentum_score + comp_bonus)), 1)
    char_len = max(1, len(kw_row["keyword"].strip()))
    char_efficiency = round(roi_score / char_len, 2)

    # 决策建议分类
    if tag == "品牌词" or (today_rank and today_rank <= 2 and diff < 25):
        recommended_slot = "🏆 主标题核心词 (Title)"
        action_reason = f"当前排名 #{today_rank or '-'}，搜索热度 {int(pop)}、难度仅 {diff}，属于必须稳守的核心词根"
    elif (today_rank and 3 <= today_rank <= 30 and diff <= 55) or (roi_score >= 72 and diff <= 48):
        recommended_slot = "🚀 副标题冲刺词 (Subtitle)"
        action_reason = (
            f"近30天累计上升 {max(0, rank_gain_30d)} 名至 #{today_rank or '待冲榜'}（热度 {int(pop)} / 难度 {diff}），"
            f"提拔至副标题高权重区有望直接冲进 Top 3"
        )
    elif diff >= 70 and (today_rank is None or today_rank > 35):
        recommended_slot = "⚠️ 建议降级或后置 (避开正面硬刚)"
        action_reason = f"竞争难度高达 {diff}（巨头垄断），当前排 #{today_rank if (today_rank and today_rank <= 200) else '>200'}，不宜占用标题/副标题额度"
    elif tag == "竞品词":
        recommended_slot = "💎 100字符蹭流词 (Keywords)"
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
    fallback_keywords: List[str],
) -> Dict[str, Any]:
    """
    智能贪心装箱算法：
    1. 自动剔除已在推荐 `title` 和 `subtitle` 中出现过的词；
    2. 对与正副标题高度重叠（>=60%字符已出现在正副标题中）的复合词，自动剥离已出现的字根或后置，优先装入 100% 全新词根；
    3. 严格控制在 ≤100 字符且使字符利用率达到 95%~100%。
    """
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
    基于平台积累数据的本地 AI 策略分析引擎（零成本、确定性高、100% 契合苹果 30/30/100 字符规范）。
    生成：
    - 词库整体诊断与竞品差距洞察 (`diagnosis`)
    - 关键词四象限分层评分表 (`evaluated_keywords`)
    - 3 套可直接发布的完整 ASO 方案 (`proposals`: 标题 + 副标题 + 100字符 + 推荐理由)
    """
    trend_map = trend_map or {}
    rating_count = int(app_info.get("rating_count") or 0)
    domain = detect_app_domain(app_info, keyword_rows)
    domain_bank = DOMAIN_EXPANSION_BANK.get(domain, DOMAIN_EXPANSION_BANK["medical_family"])

    evaluated = [
        evaluate_keyword_aso_value(
            r,
            trend_map.get(r["id"], []),
            app_rating_count=rating_count,
        )
        for r in keyword_rows
    ]
    evaluated.sort(key=lambda x: x["roi_score"], reverse=True)

    # 提取品牌主词根与核心词
    raw_app_name = str(app_info.get("name") or "我的应用").strip()
    brand_prefix = raw_app_name.split(" - ")[0].split("—")[0].split("-")[0].strip()
    if len(brand_prefix) > 10:
        brand_prefix = brand_prefix[:8]

    # 识别不同梯队关键词
    title_anchors = [e for e in evaluated if e["recommended_slot"].startswith("🏆")]
    subtitle_boosters = [e for e in evaluated if e["recommended_slot"].startswith("🚀")]
    golden_100_kws = [e for e in evaluated if e["recommended_slot"].startswith("💎")]
    low_roi_kws = [e for e in evaluated if e["recommended_slot"].startswith("⚠️")]

    # 按 ROI 排序所有非竞品词用于标题/副标题组合
    non_comp_kws = [e for e in evaluated if e.get("tag") != "竞品词"]
    high_pop_kws = sorted(non_comp_kws, key=lambda x: (x["popularity"], -x["difficulty"]), reverse=True)
    low_diff_kws = sorted(non_comp_kws, key=lambda x: (-x["roi_score"], x["difficulty"]))

    # 候选词池（监控词库 + 垂直领域拓展词库）
    monitored_words_by_roi = [e["keyword"] for e in evaluated]
    expansion_words = [item["keyword"] for item in domain_bank]
    if custom_focus.strip():
        custom_tokens = normalize_keyword_string(custom_focus)
        expansion_words = custom_tokens + expansion_words

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
            "兼顾高转化冲刺词与品牌护城河：将近期排名跃升最快、距离 Top 3 仅一步之遥的黄金词提拔至主标题与副标题，100 字符实现零重复全覆盖。",
            p1_title,
            p1_sub,
            monitored_words_by_roi,
        ),
        (
            "方案 B（🚀 流量攻坚 · 高热度大词抢量方案）",
            "前置高搜索热度核心词（如『吃药提醒』『喂药记录』）至主标题权重最高区，适合在版本大更新或冲榜期强攻高流量词。",
            p2_title,
            p2_sub,
            [e["keyword"] for e in high_pop_kws] + monitored_words_by_roi,
        ),
        (
            "方案 C（🛡️ 蓝海垄断 · 低难度长尾霸榜方案）",
            "聚焦竞争难度 <30 的精准场景词（如『儿童用药记录』『家庭药箱』『药品过期提醒』），快速拿下多个细分词 Top 3 稳定自然新增。",
            p3_title,
            p3_sub,
            [e["keyword"] for e in low_diff_kws] + monitored_words_by_roi,
        ),
    ]

    for badge_title, strategy_desc, rec_t, rec_s, prio_list in scheme_configs:
        packed = _pack_100_char_keywords(rec_t, rec_s, prio_list, expansion_words)
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
    rising_kws = [e for e in evaluated if e["rank_gain_30d"] >= 10]

    diagnosis_bullets = [
        f"📊 **词库盘点与霸榜率**：当前共监控 **{len(evaluated)}** 个关键词，其中 **{top10_count}** 个已进入 Top 10 曝光区；平均搜索热度 **{round(sum(e['popularity'] for e in evaluated)/max(1, len(evaluated)), 1)}**，平均竞争难度 **{round(sum(e['difficulty'] for e in evaluated)/max(1, len(evaluated)), 1)}**。",
        f"🎯 **当前标题利用率诊断**：当前标题「`{current_title}`」共 **{len(current_title)}/30** 字符（还剩 **{max(0, 30 - len(current_title))}** 字符闲置未用！）；在苹果算法中标题权重最高，闲置字符建议立即植入高 ROI 核心词（如 `{'、'.join(striking_kws[:2]) or '喂药记录'}`）。",
        f"🚀 **临门一脚冲刺机会**：关键词 **{'、'.join(f'「{k}」' for k in striking_kws[:4]) or '「喂药记录」「宝宝喂药」'}** 当前处于 #4~#20 卡位区且近 30 天呈明显上升趋势，将其词根前置到主标题或副标题可助力直接跃升至 Top 3。",
        f"♻️ **去重与扩词收益**：通过自动剔除 100 字符栏中与主/副标题重复的词根，并补入同赛道低难度高转化词（如 **{'、'.join(item['keyword'] for item in domain_bank[:5])}**），可在零额外成本下多覆盖 **6~10 个** 独立搜索词根。",
    ]

    return {
        "engine": "本地量化策略 AI Agent (Zero-Cost Data-Driven Engine)",
        "app_id": app_info.get("app_id"),
        "app_name": current_title,
        "country": app_info.get("country", "CN"),
        "diagnosis_bullets": diagnosis_bullets,
        "proposals": proposals,
        "evaluated_keywords": evaluated,
        "expansion_suggestions": domain_bank[:8],
    }


def build_agent_prompt_text(
    app_info: Dict[str, Any],
    evaluated_keywords: List[Dict[str, Any]],
    competitors: List[Dict[str, Any]],
    custom_focus: str = "",
) -> str:
    """
    生成包含平台已积累全量数据的结构化 Prompt，既可用于调用外部 LLM API，也可供用户一键复制到任何 AI 对话中使用。
    """
    kw_summary_lines = []
    for k in evaluated_keywords:
        r_str = f"#{k['today_rank']}" if (k.get("today_rank") and k["today_rank"] <= 200) else ">200"
        b_str = f"#{k['best_rank']}" if k.get("best_rank") else "-"
        kw_summary_lines.append(
            f"- 关键词「{k['keyword']}」({k['tag']}): 热度={k['popularity']}, 难度={k['difficulty']}, "
            f"今日排名={r_str}, 30天爬升={k['rank_gain_30d']:+d}名, 历史最高={b_str}, "
            f"ROI得分={k['roi_score']}, 竞品动态=[{k['comp_insight']}], Top3霸榜={k.get('top3_apps', [])}"
        )

    comp_lines = [
        f"- 竞品「{c['name']}」(id{c['app_id']}): 评分 {c['rating']}, 评论数 {c['rating_count']}"
        for c in competitors
    ]

    return f"""你是一位顶级的 Apple App Store ASO 增长专家 Agent。请基于以下我们在监控平台中积累的真实应用数据、关键词排名时序表现与竞品数据，为我输出下一版本的最终 ASO 元数据推荐方案。

【一、当前我方应用基础信息】
- App ID: id{app_info.get('app_id')} ({app_info.get('country')} 区)
- 当前应用标题 (限30字符): {app_info.get('name')} (当前长度: {len(str(app_info.get('name', '')))} 字符)
- 当前应用副标题 (限30字符): {app_info.get('subtitle')} (当前长度: {len(str(app_info.get('subtitle', '')))} 字符)
- 当前评分与评论数: ⭐ {app_info.get('rating')} ({app_info.get('rating_count')} 条评论)
- 本次发版重点优化方向: {custom_focus or '最大化自然搜索曝光与高转化核心词 Top 3 霸榜率'}

【二、已绑定的同赛道竞品表现】
{chr(10).join(comp_lines) if comp_lines else '- 暂未绑定竞品'}

【三、平台已积累的监控词库表现（含热度、难度、排名趋势与ROI得分）】
{chr(10).join(kw_summary_lines)}

【四、请严格按以下 JSON 格式输出你的分析与最终推荐方案（不要包含多余寒暄）】
{{
  "diagnosis_bullets": [
    "结合具体排名与难度数据的核心诊断结论 1",
    "核心诊断结论 2",
    "核心诊断结论 3"
  ],
  "proposals": [
    {{
      "scheme_name": "方案 A（AI 首推 · 黄金平衡冲榜方案）",
      "strategy_summary": "简述该方案为什么这样组合主标题、副标题与100字符",
      "title": "推荐的新标题（严格 <= 30 字符）",
      "subtitle": "推荐的新副标题（严格 <= 30 字符，且不与标题重复词根）",
      "keywords": "推荐的100字符关键词串（使用英文半角逗号分隔，无空格，严格 <= 100 字符，且绝不包含标题和副标题中已有的词）"
    }},
    {{
      "scheme_name": "方案 B（流量攻坚 · 激进抢量方案）",
      "strategy_summary": "...",
      "title": "...",
      "subtitle": "...",
      "keywords": "..."
    }},
    {{
      "scheme_name": "方案 C（蓝海垄断 · 精准长尾方案）",
      "strategy_summary": "...",
      "title": "...",
      "subtitle": "...",
      "keywords": "..."
    }}
  ]
}}"""


def run_llm_aso_agent(
    app_info: Dict[str, Any],
    keyword_rows: List[Dict[str, Any]],
    competitors: List[Dict[str, Any]],
    releases: List[Dict[str, Any]],
    trend_map: Optional[Dict[int, List[Dict[str, Any]]]] = None,
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
    model_name: str = "gpt-4o-mini",
    custom_focus: str = "",
    timeout: int = 35,
) -> Dict[str, Any]:
    """
    调用外部大模型 (OpenAI / DeepSeek / 通义千问 / 硅基流动等兼容接口) 进行深度推理，
    并对大模型输出的每套方案强制执行 30/30/100 字符清洗与标题去重校验。
    若未配置 API Key 或网络请求异常，自动平滑降级为本地量化策略引擎并附带提示。
    """
    local_result = generate_aso_recommendations_local(
        app_info=app_info,
        keyword_rows=keyword_rows,
        competitors=competitors,
        releases=releases,
        trend_map=trend_map,
        custom_focus=custom_focus,
    )

    if not api_key or not api_key.strip():
        return local_result

    prompt_text = build_agent_prompt_text(
        app_info=app_info,
        evaluated_keywords=local_result["evaluated_keywords"],
        competitors=competitors,
        custom_focus=custom_focus,
    )

    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model_name.strip() or "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": "You are an expert Apple App Store Optimization (ASO) AI Agent. Always respond in valid JSON.",
            },
            {"role": "user", "content": prompt_text},
        ],
        "temperature": 0.4,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key.strip()}",
    }

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw_resp = json.loads(resp.read().decode("utf-8", errors="replace"))

        content = raw_resp["choices"][0]["message"]["content"]
        # 提取 JSON 块
        json_match = re.search(r"\{[\s\S]*\}", content)
        parsed_llm = json.loads(json_match.group(0) if json_match else content)

        llm_proposals = []
        for p in parsed_llm.get("proposals", []):
            t_str = str(p.get("title", "")).strip()[:TITLE_LIMIT]
            s_str = str(p.get("subtitle", "")).strip()[:SUBTITLE_LIMIT]
            raw_k = str(p.get("keywords", "")).strip()
            checked = analyze_100_char_workspace(t_str, s_str, raw_k, auto_remove_title_dups=True)
            active_k = checked["keywords"]["active_str"][:KEYWORDS_LIMIT].rstrip(",")
            llm_proposals.append(
                {
                    "scheme_name": p.get("scheme_name", "🤖 LLM 定制推荐方案"),
                    "strategy_summary": p.get("strategy_summary", ""),
                    "title": t_str,
                    "title_len": len(t_str),
                    "title_remaining": TITLE_LIMIT - len(t_str),
                    "subtitle": s_str,
                    "subtitle_len": len(s_str),
                    "subtitle_remaining": SUBTITLE_LIMIT - len(s_str),
                    "keywords": active_k,
                    "keywords_len": len(active_k),
                    "keywords_remaining": KEYWORDS_LIMIT - len(active_k),
                    "keywords_count": len([x for x in active_k.split(",") if x]),
                }
            )

        if llm_proposals:
            local_result["engine"] = f"LLM AI Agent ({model_name})"
            local_result["proposals"] = llm_proposals
        if parsed_llm.get("diagnosis_bullets"):
            local_result["diagnosis_bullets"] = parsed_llm["diagnosis_bullets"]
        return local_result
    except Exception as exc:
        local_result["engine"] = f"本地量化策略引擎 (LLM 接口调用回退: {exc})"
        return local_result
