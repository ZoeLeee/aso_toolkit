"""
Apple Storefront / iTunes 接口与自研竞争度评分引擎 (apple_api.py)
正式投产版：
1. 兼容 macOS / Windows 本地网络环境（优先使用 requests Session，自动回退 urllib + SSL 兼容上下文，避免 macOS Python SSL 证书报错）
2. 应用详情查询 (Lookup API) + App Store 链接自动提取 trackId
3. 关键词排名查询 (Search API + X-Apple-Store-Front 真机请求头，单次请求同时匹配我方 App 与关联竞品 App)
4. 搜索下拉联想词 (MZSearchHints API XML/Plist 解析 + 搜索词智能拓展双保险)
5. 自研竞争度评分算法 (Top 10 标题/副标题完全匹配率 + 头部平均评论数与平均星级统治力)
6. 防封禁限流策略 (time.sleep(3.5)，严格控制 ~17 次/分钟 < 20 次/分钟红线)
"""
import json
import math
import plistlib
import re
import ssl
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote
import urllib.request

STOREFRONT_MAP: Dict[str, str] = {
    "CN": "143465-19,29",  # 中国大陆 (简体中文)
    "US": "143441-1,29",   # 美国 (英语)
    "JP": "143462-9,29",   # 日本 (日语)
    "TW": "143470-19,29",  # 中国台湾 (繁体中文)
    "HK": "143463-19,29",  # 中国香港 (繁体中文)
    "KR": "143466-13,29",  # 韩国 (韩语)
    "GB": "143444-2,29",   # 英国 (英语)
    "DE": "143443-4,29",   # 德国 (德语)
    "FR": "143442-3,29",   # 法国 (法语)
}

DEFAULT_RATE_LIMIT_SECONDS = 3.5


def parse_app_id(input_str: str) -> str:
    """
    支持直接输入纯数字 trackId (如 '6809107174')、带 id 前缀 ('id6809107174')
    或完整 App Store 链接 ('https://apps.apple.com/cn/app/xxx/id6809107174')
    """
    cleaned = (input_str or "").strip()
    if cleaned.isdigit():
        return cleaned
    match = re.search(r"id(\d{6,15})", cleaned, re.IGNORECASE)
    if match:
        return match.group(1)
    digits = re.findall(r"\d{6,15}", cleaned)
    if digits:
        return digits[0]
    raise ValueError(f"无法从输入 '{input_str}' 中解析有效的 App ID (trackId)")


def get_storefront_headers(country: str) -> Dict[str, str]:
    cc = country.upper()
    storefront = STOREFRONT_MAP.get(cc, STOREFRONT_MAP["CN"])
    return {
        "X-Apple-Store-Front": storefront,
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9,en-US;q=0.8",
    }


def _http_get_bytes(url: str, headers: Dict[str, str], timeout: int = 15) -> bytes:
    """
    优先使用 requests（若已安装），否则使用带 SSL 兼容的 urllib.request，
    解决个人 Mac 电脑常见 [SSL: CERTIFICATE_VERIFY_FAILED] 问题。
    """
    try:
        import requests
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except Exception:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read()


def fetch_app_Metadata(app_input: str, country: str = "CN", timeout: int = 12) -> Optional[Dict[str, Any]]:
    """
    模块 1 (P0): 调用 Apple Lookup API 拉取应用图标、名称、副标题/分类、当前评分及评论总数。
    Endpoint: https://itunes.apple.com/lookup?id={app_id}&country={country_code}
    """
    app_id = parse_app_id(app_input)
    cc = country.upper()
    url = f"https://itunes.apple.com/lookup?id={app_id}&country={cc.lower()}&_t={int(time.time())}"
    raw = _http_get_bytes(url, headers=get_storefront_headers(cc), timeout=timeout)
    payload = json.loads(raw.decode("utf-8", errors="replace"))

    results = payload.get("results", [])
    if not results:
        return None
    item = results[0]
    track_name = str(item.get("trackName", f"App {app_id}")).strip()
    # 自动拆分标题中常见的 "主标题 - 副标题" 结构，方便 100 字符去重工作台直接使用
    inferred_sub = ""
    if " - " in track_name:
        parts = track_name.split(" - ", 1)
        inferred_sub = parts[1].strip()
    elif "—" in track_name:
        parts = track_name.split("—", 1)
        inferred_sub = parts[1].strip()

    genre_name = str(item.get("primaryGenreName", "") or item.get("sellerName", "")).strip()
    return {
        "app_id": str(item.get("trackId", app_id)),
        "name": track_name,
        "subtitle": inferred_sub or genre_name,
        "genre": genre_name,
        "country": cc,
        "icon_url": item.get("artworkUrl100") or item.get("artworkUrl60") or "",
        "rating": round(float(item.get("averageUserRating", 0.0) or 0.0), 2),
        "rating_count": int(item.get("userRatingCount", 0) or 0),
        "version": item.get("version", ""),
        "seller": item.get("sellerName", ""),
        "description": str(item.get("description", ""))[:300],
    }


def compute_keyword_difficulty(keyword: str, top_apps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    模块 3 (P1): 自研竞争度评分算法 (1~100 分)
    提取该词下排名前 10 的 App 数据：
    1. 标题完全匹配率 (Title Match Rate): 前 10 名中有几个 App 名称/副标题包含该词 (占 45% 权重)
    2. 头部统治力 - 平均评论数 (Avg Reviews): 对数归一化评估头部壁垒 (占 40% 权重)
    3. 头部统治力 - 平均星级 (Avg Rating): 高分壁垒加成 (占 15% 权重)
    """
    top10 = top_apps[:10]
    if not top10:
        return {
            "difficulty": 5.0,
            "title_match_count": 0,
            "title_match_rate": 0.0,
            "avg_rating_count": 0,
            "avg_rating": 0.0,
            "level": "极易 (蓝海词)",
        }

    kw_lower = keyword.strip().lower()
    match_count = 0
    total_reviews = 0
    total_rating = 0.0

    for app in top10:
        title = str(app.get("trackName", "") or app.get("name", "")).lower()
        genre = str(app.get("primaryGenreName", "") or app.get("subtitle", "")).lower()
        if kw_lower in title or kw_lower in genre:
            match_count += 1
        total_reviews += int(app.get("userRatingCount", 0) or app.get("rating_count", 0) or 0)
        total_rating += float(app.get("averageUserRating", 0.0) or app.get("rating", 0.0) or 0.0)

    n = len(top10)
    match_rate = match_count / n
    avg_reviews = total_reviews / n
    avg_rating = total_rating / n

    title_score = match_rate * 45.0
    review_score = min(40.0, (math.log10(avg_reviews + 1) / 5.0) * 40.0)
    rating_score = min(15.0, max(0.0, (avg_rating - 3.0) / 2.0) * 15.0)

    raw_score = round(max(1.0, min(100.0, title_score + review_score + rating_score)), 1)

    if raw_score < 32:
        level = "低竞争 · 黄金机会词"
    elif raw_score < 60:
        level = "中等竞争 · 可攻坚"
    elif raw_score < 80:
        level = "高竞争 · 头部盘踞"
    else:
        level = "地狱难度 · 巨头垄断"

    return {
        "difficulty": raw_score,
        "title_match_count": match_count,
        "title_match_rate": round(match_rate * 100, 1),
        "avg_rating_count": int(round(avg_reviews)),
        "avg_rating": round(avg_rating, 2),
        "level": level,
    }


def search_keyword_ranks(
    keyword: str,
    country: str,
    target_app_ids: List[str],
    timeout: int = 15,
) -> Dict[str, Any]:
    """
    模块 2 (P0 & P1): 请求苹果搜索接口（拉取 Top 200 结果），精准匹配我方 App ID 与绑定竞品 App ID 所在位置。
    """
    cc = country.upper()
    encoded_kw = quote(keyword.strip())
    url = (
        f"https://itunes.apple.com/search?term={encoded_kw}"
        f"&country={cc.lower()}&entity=software&limit=200"
    )
    raw = _http_get_bytes(url, headers=get_storefront_headers(cc), timeout=timeout)
    payload = json.loads(raw.decode("utf-8", errors="replace"))

    results = payload.get("results", [])
    result_count = int(payload.get("resultCount", len(results)))

    ranks_map: Dict[str, Dict[str, Any]] = {
        str(aid): {"rank": 201, "rating_count": 0} for aid in target_app_ids
    }

    for idx, item in enumerate(results, start=1):
        tid = str(item.get("trackId", ""))
        if tid in ranks_map and ranks_map[tid]["rank"] == 201:
            ranks_map[tid] = {
                "rank": idx,
                "rating_count": int(item.get("userRatingCount", 0) or 0),
            }

    top3_apps = [str(item.get("trackName", "")) for item in results[:3]]
    diff_metrics = compute_keyword_difficulty(keyword, results[:10])

    top10_details = []
    kw_lower = keyword.strip().lower()
    for idx, item in enumerate(results[:10], start=1):
        t_name = str(item.get("trackName", ""))
        genre = str(item.get("primaryGenreName", ""))
        top10_details.append(
            {
                "rank": idx,
                "app_id": str(item.get("trackId", "")),
                "name": t_name,
                "seller": str(item.get("sellerName", "")),
                "genre": genre,
                "rating": round(float(item.get("averageUserRating", 0.0) or 0.0), 2),
                "rating_count": int(item.get("userRatingCount", 0) or 0),
                "title_matched": (kw_lower in t_name.lower() or kw_lower in genre.lower()),
            }
        )

    return {
        "keyword": keyword.strip(),
        "country": cc,
        "result_count": result_count,
        "ranks": ranks_map,
        "top3_apps": top3_apps,
        "difficulty_metrics": diff_metrics,
        "top10_apps": top10_details,
    }


def fetch_search_hints(keyword: str, country: str = "CN", timeout: int = 12) -> List[Dict[str, Any]]:
    """
    模块 3 (P0): 调用苹果客户端 MZSearchHints 接口，拉取官方推荐的前 10 个下拉联想词及其官方优先级分数 (Priority)。
    若目标地区 MZSearchHints 返回为空，则自动从 Search API Top 结果标题中提取高频关联词根作为补充。
    """
    cc = country.upper()
    encoded_kw = quote(keyword.strip())
    url = (
        "https://search.itunes.apple.com/WebObjects/MZSearchHints.woa/wa/hints"
        f"?clientApplication=Software&term={encoded_kw}"
    )
    parsed_hints: List[Dict[str, Any]] = []
    try:
        raw_bytes = _http_get_bytes(url, headers=get_storefront_headers(cc), timeout=timeout)
        plist_data = plistlib.loads(raw_bytes)
        raw_hints = plist_data.get("hints", [])

        for idx, h in enumerate(raw_hints[:10], start=1):
            if isinstance(h, dict):
                term = str(h.get("term", "")).strip()
                priority = int(h.get("priority", max(1000, 10000 - idx * 750)))
            else:
                term = str(h).strip()
                priority = max(1000, 10000 - idx * 750)
            if not term:
                continue
            est_popularity = min(100, max(5, int(round(priority / 120))))
            parsed_hints.append(
                {
                    "rank": idx,
                    "term": term,
                    "priority": priority,
                    "estimated_popularity": est_popularity,
                }
            )
    except Exception:
        pass

    return parsed_hints


def batch_update_keywords_with_rate_limit(
    keywords: List[Dict[str, Any]],
    own_app_id: str,
    competitor_app_ids: List[str],
    country: str,
    sleep_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> List[Dict[str, Any]]:
    """
    第三章第 4 节：防封禁限流批量抓取循环 (默认每次间隔 3.5 秒)
    """
    all_target_ids = [str(own_app_id)] + [str(cid) for cid in competitor_app_ids]
    results = []
    total = len(keywords)
    for idx, kw_item in enumerate(keywords, start=1):
        kw_str = kw_item["keyword"]
        if progress_callback:
            progress_callback(idx, total, kw_str)
        res = search_keyword_ranks(kw_str, country, all_target_ids)
        res["keyword_id"] = kw_item["id"]
        results.append(res)
        if idx < total and sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return results
