#!/usr/bin/env python3
"""
每日定时静默排名与 App 状态更新脚本 (cron_tracker.py)
功能特性：
1. 自动同步监控应用与竞品的最新元数据（线上版本号、评分、评论总数、副标题）
2. 智能检测应用新版本上线：若检测到线上版本号更新，自动向 version_releases 插入发版里程碑
3. 自动抓取全部关键词今日最新排名快照，并顺带记录竞品同词排名
4. 核心词排名暴跌超过阈值时触发 Webhook（飞书/企微/Bark 等）告警
5. 支持一次性运行或 --daemon 守护进程常驻模式（专为 Docker 容器定制）
"""
import argparse
from datetime import date, datetime
import json
import os
import sys
import time
import urllib.request
from typing import List, Optional

from apple_api import (
    DEFAULT_RATE_LIMIT_SECONDS,
    batch_update_keywords_with_rate_limit,
    fetch_app_Metadata,
)
from db import (
    add_keyword,
    add_version_release,
    get_keyword_dashboard_rows,
    init_db,
    list_competitors,
    list_own_apps,
    save_rank_snapshot,
    upsert_app,
)


def send_webhook_alert(webhook_url: str, title: str, lines: List[str]) -> None:
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


def sync_app_and_competitors_metadata(app: dict, today_str: str, sleep_sec: float = 1.0) -> List[str]:
    """
    拉取应用及竞品的最新线上元数据（评分、评论数、版本号），并检测是否发布了新版本。
    """
    app_id = app["app_id"]
    country = app["country"]
    app_name = app["name"]
    version_alerts: List[str] = []

    print(f"--- 正在同步 [{app_name} ({country})] 线上元数据 ---")
    try:
        meta = fetch_app_Metadata(app_id, country)
        if meta:
            old_version = (app.get("version") or "").strip()
            new_version = (meta.get("version") or "").strip()

            if old_version and new_version and old_version != new_version:
                note = f"自动检测到新版本发布：v{old_version} → v{new_version}"
                add_version_release(app_id, country, new_version, today_str, notes=note)
                alert_text = f"🎉 应用「{app_name}」发布了新版本：v{old_version} → v{new_version}（已自动记录发版日）"
                print(f"  {alert_text}")
                version_alerts.append(alert_text)

            upsert_app(
                app_id=meta["app_id"],
                name=meta["name"],
                country=country,
                is_own_app=True,
                subtitle=meta["subtitle"],
                icon_url=meta["icon_url"],
                rating=meta["rating"],
                rating_count=meta["rating_count"],
                version=new_version or old_version,
            )
            print(f"  [主应用] ⭐ {meta['rating']} ({meta['rating_count']:,} 评价) · 版本: v{new_version or '-'}")
    except Exception as exc:
        print(f"  [主应用元数据同步异常] {app_name}: {exc}", file=sys.stderr)

    time.sleep(sleep_sec)

    # 同步关联竞品的最新评分与版本
    competitors = list_competitors(app_id, country)
    if competitors:
        for comp in competitors:
            cid = comp["app_id"]
            cname = comp["name"]
            try:
                cmeta = fetch_app_Metadata(cid, country)
                if cmeta:
                    upsert_app(
                        app_id=cmeta["app_id"],
                        name=cmeta["name"],
                        country=country,
                        is_own_app=False,
                        parent_app_id=app_id,
                        subtitle=cmeta["subtitle"],
                        icon_url=cmeta["icon_url"],
                        rating=cmeta["rating"],
                        rating_count=cmeta["rating_count"],
                        version=cmeta.get("version", ""),
                    )
                    print(f"  [关联竞品] {cmeta['name']}: ⭐ {cmeta['rating']} ({cmeta['rating_count']:,} 评价) · v{cmeta.get('version') or '-'}")
            except Exception as exc:
                print(f"  [竞品元数据同步异常] {cname}: {exc}", file=sys.stderr)
            time.sleep(sleep_sec)

    return version_alerts


def run_daily_tracking(sleep_sec: float = DEFAULT_RATE_LIMIT_SECONDS, webhook_url: str = "", drop_threshold: int = 10) -> None:
    webhook_url = webhook_url or os.getenv("ASO_WEBHOOK_URL", "")
    init_db()
    own_apps = list_own_apps()
    if not own_apps:
        print("[ASO Tracker] 当前数据库暂无监控中的 App，请先在看板中添加 App。")
        return

    today_str = date.today().isoformat()
    alerts: List[str] = []
    version_notices: List[str] = []

    print(f"\n========================================================")
    print(f"📊 开始执行 ASO 定时更新巡检 ({today_str})")
    print(f"共发现 {len(own_apps)} 款监控应用")
    print(f"========================================================")

    for app in own_apps:
        app_id = app["app_id"]
        country = app["country"]
        app_name = app["name"]

        # 1. 自动同步 App 元数据（评分、评价数、版本）与发版日检测
        v_alerts = sync_app_and_competitors_metadata(app, today_str, sleep_sec=1.0)
        version_notices.extend(v_alerts)

        # 2. 检查待更新的关键词
        competitors = list_competitors(app_id, country)
        comp_ids = [c["app_id"] for c in competitors]
        kw_rows = get_keyword_dashboard_rows(app_id, country)

        if not kw_rows:
            print(f"[{app_name} ({country})] 暂无监控关键词，跳过排名查询。\n")
            continue

        print(f"=== 开始更新 [{app_name} ({country})] 共 {len(kw_rows)} 个关键词排名 (限流间隔 {sleep_sec}s) ===")

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
        print(f"[{app_name}] 关键词更新落盘完毕。\n")

    print(f"✅ [ASO Tracker] {today_str} 全部应用状态与关键词排名更新完毕！")

    # 汇总发送告警通知
    all_notices = []
    if version_notices:
        all_notices.append("【新版本发布提醒】\n" + "\n".join(version_notices))
    if alerts:
        all_notices.append("【关键词排名暴跌告警】\n" + "\n".join(alerts))

    if all_notices and webhook_url:
        send_webhook_alert(webhook_url, f"ASO 每日监控报告 ({today_str})", all_notices)


def run_daemon(
    target_time_str: str = "08:00",
    run_on_startup: bool = True,
    sleep_sec: float = DEFAULT_RATE_LIMIT_SECONDS,
    webhook_url: str = "",
    drop_threshold: int = 10,
) -> None:
    """
    常驻守护进程模式：支持每天固定时间自动触发更新，适合 Docker 容器后台常驻运行。
    """
    print("=" * 60)
    print("🚀 ASO Tracker 守护进程已就绪")
    print(f"⏰ 每日自动调度时间: {target_time_str} (本地/容器时区)")
    print(f"⚡ 启动时首次执行: {'开启' if run_on_startup else '关闭'}")
    print("=" * 60)

    last_run_date: Optional[str] = None
    if run_on_startup:
        print("\n[ASO Daemon] 正在执行启动首次全量状态拉取...")
        try:
            run_daily_tracking(sleep_sec=sleep_sec, webhook_url=webhook_url, drop_threshold=drop_threshold)
            last_run_date = date.today().isoformat()
        except Exception as exc:
            print(f"[ASO Daemon] 启动首次更新异常: {exc}", file=sys.stderr)

    while True:
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        today_iso = now.date().isoformat()

        if current_time == target_time_str and last_run_date != today_iso:
            print(f"\n[ASO Daemon] 到达预设时间 {target_time_str}，开始执行每日例行追踪...")
            try:
                run_daily_tracking(sleep_sec=sleep_sec, webhook_url=webhook_url, drop_threshold=drop_threshold)
                last_run_date = today_iso
            except Exception as exc:
                print(f"[ASO Daemon] 任务执行异常: {exc}", file=sys.stderr)

        time.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="个人轻量级 ASO 每日定时追踪脚本")
    parser.add_argument("--sleep", type=float, default=DEFAULT_RATE_LIMIT_SECONDS, help="每次请求间隔秒数 (默认 3.5 秒)")
    parser.add_argument(
        "--webhook",
        type=str,
        default=os.getenv("ASO_WEBHOOK_URL", ""),
        help="飞书/企微/自定义告警 Webhook 地址 (亦可通过环境变量 ASO_WEBHOOK_URL 配置)",
    )
    parser.add_argument("--drop-threshold", type=int, default=10, help="触发告警的排名下跌名次阈值 (默认 10)")
    parser.add_argument(
        "--daemon",
        action="store_true",
        default=os.getenv("ASO_DAEMON_MODE", "false").lower() in ("1", "true", "yes"),
        help="常驻守护进程模式 (每到指定时间自动触发)",
    )
    parser.add_argument(
        "--daemon-time",
        type=str,
        default=os.getenv("ASO_DAEMON_TIME", "08:00"),
        help="每日定时执行时间 (格式 HH:MM，默认 08:00)",
    )
    parser.add_argument(
        "--no-startup-run",
        action="store_true",
        help="守护模式启动时跳过首次立即更新",
    )
    args = parser.parse_args()

    if args.daemon:
        run_daemon(
            target_time_str=args.daemon_time,
            run_on_startup=not args.no_startup_run,
            sleep_sec=args.sleep,
            webhook_url=args.webhook,
            drop_threshold=args.drop_threshold,
        )
    else:
        run_daily_tracking(sleep_sec=args.sleep, webhook_url=args.webhook, drop_threshold=args.drop_threshold)
