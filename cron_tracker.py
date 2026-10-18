#!/usr/bin/env python3
"""
阶段三：每日定时静默排名更新与暴跌告警脚本 (cron_tracker.py)
支持通过 macOS crontab / launchd、Windows 任务计划程序或 GitHub Actions 每日定时运行。
用法：
  python3 cron_tracker.py                  # 更新所有已绑定的我方 App 及关联竞品关键词排名
  python3 cron_tracker.py --webhook <URL>  # 当核心词排名暴跌超过阈值时推送飞书/企微/Bark Webhook 通知
"""
import argparse
import json
import sys
import urllib.request
from datetime import date

from apple_api import DEFAULT_RATE_LIMIT_SECONDS, batch_update_keywords_with_rate_limit
from db import (
    get_keyword_dashboard_rows,
    init_db,
    list_competitors,
    list_own_apps,
    save_rank_snapshot,
    add_keyword,
)


def send_webhook_alert(webhook_url: str, title: str, lines: list[str]) -> None:
    payload = {
        "msg_type": "text",
        "content": {"text": f"🚨 {title}\n" + "\n".join(lines)},
    }
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[Webhook] 告警已发送，状态码: {resp.status}")
    except Exception as exc:
        print(f"[Webhook] 告警发送失败: {exc}", file=sys.stderr)


def run_daily_tracking(sleep_sec: float = DEFAULT_RATE_LIMIT_SECONDS, webhook_url: str = "", drop_threshold: int = 10) -> None:
    init_db()
    own_apps = list_own_apps()
    if not own_apps:
        print("[ASO Tracker] 当前数据库暂无监控中的 App，请先在看板中添加 App。")
        return

    today_str = date.today().isoformat()
    alerts: list[str] = []

    for app in own_apps:
        app_id = app["app_id"]
        country = app["country"]
        app_name = app["name"]
        competitors = list_competitors(app_id, country)
        comp_ids = [c["app_id"] for c in competitors]

        kw_rows = get_keyword_dashboard_rows(app_id, country)
        if not kw_rows:
            print(f"[{app_name} ({country})] 暂无监控关键词，跳过。")
            continue

        print(f"=== 开始更新 [{app_name} ({country})] 共 {len(kw_rows)} 个关键词 (限流间隔 {sleep_sec}s) ===")

        def on_progress(idx: int, total: int, kw: str) -> None:
            print(f"  [{idx}/{total}] 正在查询关键词: {kw} ...")

        batch_results = batch_update_keywords_with_rate_limit(
            keywords=kw_rows,
            own_app_id=app_id,
            competitor_app_ids=comp_ids,
            country=country,
            sleep_seconds=sleep_sec,
            progress_callback=on_progress,
        )

        # 保存快照并检测排名暴跌
        prev_map = {r["id"]: r["today_rank"] for r in kw_rows}
        for res in batch_results:
            kid = res["keyword_id"]
            kw_text = res["keyword"]
            diff_score = res["difficulty_metrics"]["difficulty"]
            # 更新关键词最新竞争度分
            add_keyword(app_id, country, kw_text, difficulty=diff_score)

            for target_aid, r_info in res["ranks"].items():
                save_rank_snapshot(
                    keyword_id=kid,
                    app_id=target_aid,
                    rank=r_info["rank"],
                    top3_apps=res["top3_apps"],
                    rating_count=r_info["rating_count"],
                    result_count=res["result_count"],
                    record_date=today_str,
                )

            new_rank = res["ranks"][str(app_id)]["rank"]
            old_rank = prev_map.get(kid)
            if old_rank and old_rank <= 200 and new_rank - old_rank >= drop_threshold:
                alerts.append(
                    f"• [{app_name}-{country}] 关键词「{kw_text}」排名下跌: #{old_rank} → #{'200+' if new_rank > 200 else new_rank}"
                )

    print(f"[ASO Tracker] {today_str} 全部关键词更新完毕！")
    if alerts:
        print("\n⚠️ 检测到以下关键词排名显著下跌：")
        for line in alerts:
            print(" ", line)
        if webhook_url:
            send_webhook_alert(webhook_url, f"ASO 每日监控告警 ({today_str})", alerts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="个人轻量级 ASO 每日定时追踪脚本")
    parser.add_argument("--sleep", type=float, default=DEFAULT_RATE_LIMIT_SECONDS, help="每次请求间隔秒数 (默认 3.5 秒)")
    parser.add_argument("--webhook", type=str, default="", help="飞书/企微/自定义告警 Webhook 地址")
    parser.add_argument("--drop-threshold", type=int, default=10, help="触发告警的排名下跌名次阈值")
    args = parser.parse_args()
    run_daily_tracking(sleep_sec=args.sleep, webhook_url=args.webhook, drop_threshold=args.drop_threshold)
