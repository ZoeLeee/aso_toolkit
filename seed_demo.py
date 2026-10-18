"""
初始化数据库脚本 (seed_demo.py)
已将用户真实应用 id6809107174 (喂药本 - 家庭用药管理, CN, v1.1.0) 配置为默认主应用，
包含关联竞品、核心词库（喂药本、喂药记录、家庭用药管理、吃药提醒、宝宝喂药、家庭药箱等）及版本里程碑。
"""
from datetime import date, timedelta
from pathlib import Path
import shutil
import tempfile

from db import (
    add_keyword,
    add_version_release,
    get_keyword_dashboard_rows,
    init_db,
    save_rank_snapshot,
    upsert_app,
    DB_PATH,
)
from apple_api import compute_keyword_difficulty, parse_app_id
from optimizer import analyze_100_char_workspace


def seed_database(target_db_path: Path = DB_PATH) -> Path:
    target_db_path = Path(target_db_path)
    tmp_db = Path(tempfile.gettempdir()) / "aso_seed_work.db"
    if tmp_db.exists():
        try:
            tmp_db.unlink()
        except OSError:
            pass

    init_db(tmp_db)
    today = date.today()

    # 1. 绑定其他参考演示应用 (先插入，使 created_at 较早)
    upsert_app(
        app_id="6448311069",
        name="极简存钱记账 - 随手收支账本",
        country="CN",
        is_own_app=True,
        subtitle="个人资产预算管理与存钱打卡助手",
        icon_url="https://is1-ssl.mzstatic.com/image/thumb/Purple126/v4/00/00/00/icon.png",
        rating=4.9,
        rating_count=12840,
        version="2.4.0",
        db_path=tmp_db,
    )

    # 2. 绑定用户真实主应用 id6809107174: 喂药本 - 家庭用药管理 (最新插入，默认排第一)
    upsert_app(
        app_id="6809107174",
        name="喂药本 - 家庭用药管理",
        country="CN",
        is_own_app=True,
        subtitle="宝宝儿童喂药记录与吃药定时提醒助手",
        icon_url="https://is1-ssl.mzstatic.com/image/thumb/Purple211/v4/a2/9f/67/a29f67ce-a014-f4bf-4b92-8212500935a1/AppIcon-0-0-1x_U007ephone-0-1-85-220.png/100x100bb.jpg",
        rating=5.0,
        rating_count=18,
        version="1.1.0",
        db_path=tmp_db,
    )

    # 强制将 id6809107174 的 created_at 设为最新，确保侧边栏默认选中
    from db import get_conn
    conn = get_conn(tmp_db)
    conn.execute("UPDATE apps SET created_at = datetime('now', '+10 seconds') WHERE app_id = '6809107174'")
    conn.close()

    # 3. 为 id6809107174 绑定同赛道竞品 (医疗/用药提醒/家庭药箱类)
    med_competitors = [
        ("1459871230", "吃药提醒 - 按时服药打卡助手", 4.8, 3420),
        ("1523498712", "家庭小药箱 - 药品过期管理", 4.7, 1890),
        ("1487652341", "宝宝喂药记录 - 育儿体温用药", 4.8, 2150),
    ]
    for cid, cname, crating, ccount in med_competitors:
        upsert_app(
            app_id=cid,
            name=cname,
            country="CN",
            is_own_app=False,
            parent_app_id="6809107174",
            subtitle="医疗健康管理",
            rating=crating,
            rating_count=ccount,
            version="2.1.0",
            db_path=tmp_db,
        )

    # 4. 为 id6809107174 标记版本发布节点
    add_version_release(
        "6809107174",
        "CN",
        "v1.0.0",
        (today - timedelta(days=16)).isoformat(),
        "首发上架：标题定名『喂药本 - 家庭用药管理』",
        db_path=tmp_db,
    )
    add_version_release(
        "6809107174",
        "CN",
        "v1.1.0",
        (today - timedelta(days=5)).isoformat(),
        "v1.1.0 更新：100字符优化去重，补充『喂药记录,宝宝喂药,家庭药箱,吃药提醒』",
        db_path=tmp_db,
    )

    # 5. 为 id6809107174 录入核心监控关键词与 30 天趋势快照
    med_keywords = [
        ("喂药本", "品牌词", 46, 12.5, [12, 6, 3, 1, 1], ["喂药本 - 家庭用药管理", "宝宝喂药记录", "亲宝宝"], {"1459871230": 18, "1523498712": 25, "1487652341": 2}),
        ("喂药记录", "核心词", 77, 24.8, [45, 29, 16, 8, 4], ["宝宝喂药记录", "喂药本 - 家庭用药管理", "美柚"], {"1459871230": 12, "1523498712": 31, "1487652341": 1}),
        ("家庭用药管理", "核心词", 54, 19.6, [38, 22, 11, 5, 2], ["家庭小药箱", "喂药本 - 家庭用药管理", "丁香医生"], {"1459871230": 9, "1523498712": 1, "1487652341": 15}),
        ("宝宝喂药", "核心词", 65, 28.4, [68, 44, 24, 13, 7], ["宝宝喂药记录", "亲宝宝", "喂药本 - 家庭用药管理"], {"1459871230": 27, "1523498712": 42, "1487652341": 1}),
        ("吃药提醒", "核心词", 83, 52.0, [135, 96, 62, 38, 26], ["吃药提醒", "滴答清单", "用药助手"], {"1459871230": 1, "1523498712": 14, "1487652341": 22}),
        ("家庭药箱", "长尾词", 61, 31.2, [82, 54, 33, 19, 11], ["家庭小药箱", "智能药箱", "喂药本 - 家庭用药管理"], {"1459871230": 16, "1523498712": 1, "1487652341": 29}),
        ("儿童用药记录", "长尾词", 52, 21.0, [52, 34, 18, 9, 5], ["宝宝喂药记录", "喂药本 - 家庭用药管理", "儿科医生"], {"1459871230": 24, "1523498712": 19, "1487652341": 1}),
        ("服药打卡", "长尾词", 58, 29.5, [95, 64, 39, 21, 14], ["吃药提醒", "小日常", "喂药本 - 家庭用药管理"], {"1459871230": 1, "1523498712": 17, "1487652341": 19}),
        ("药品过期提醒", "长尾词", 49, 22.8, [110, 72, 41, 22, 13], ["家庭小药箱", "保质期提醒", "喂药本 - 家庭用药管理"], {"1459871230": 21, "1523498712": 1, "1487652341": 35}),
    ]

    for kw_str, tag, pop, diff, stage_ranks, top3, comp_map in med_keywords:
        kid = add_keyword("6809107174", "CN", kw_str, tag=tag, popularity=pop, difficulty=diff, db_path=tmp_db)
        for day_offset in range(29, -1, -1):
            d_str = (today - timedelta(days=day_offset)).isoformat()
            progress = (29 - day_offset) / 29.0
            segment = min(3, int(progress * 4))
            local_p = (progress * 4) - segment
            interp_rank = int(round(stage_ranks[segment] + (stage_ranks[segment + 1] - stage_ranks[segment]) * local_p))
            if day_offset == 0:
                interp_rank = stage_ranks[-1]
            elif day_offset == 1:
                interp_rank = stage_ranks[-2]

            save_rank_snapshot(
                keyword_id=kid,
                app_id="6809107174",
                rank=interp_rank if interp_rank <= 200 else 201,
                top3_apps=top3,
                rating_count=max(0, 18 - day_offset // 2),
                result_count=200,
                record_date=d_str,
                db_path=tmp_db,
            )
            for cid, c_base_rank in comp_map.items():
                save_rank_snapshot(
                    keyword_id=kid,
                    app_id=cid,
                    rank=c_base_rank,
                    top3_apps=top3,
                    rating_count=2500,
                    result_count=200,
                    record_date=d_str,
                    db_path=tmp_db,
                )

    if target_db_path.parent:
        target_db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tmp_db, target_db_path)
    return target_db_path


if __name__ == "__main__":
    db_file = seed_database()
    tmp_check = Path(tempfile.gettempdir()) / "aso_seed_work.db"
    rows = get_keyword_dashboard_rows("6809107174", "CN", db_path=tmp_check)
    assert len(rows) == 9, f"Expected 9 keywords for 6809107174, got {len(rows)}"
    assert parse_app_id("id6809107174") == "6809107174"
    opt_res = analyze_100_char_workspace(
        "喂药本 - 家庭用药管理",
        "宝宝儿童喂药记录与吃药定时提醒助手",
        "喂药本，喂药记录，家庭用药，吃药提醒，宝宝喂药，家庭药箱，服药打卡，儿童用药，药品过期，退烧药，抗生素，慢病管理，处方记录，看病记录，疫苗本",
        auto_remove_title_dups=True,
    )
    print("SEED_6809107174_PASSED:", len(rows), "OPTIMIZED_100_CHAR:", opt_res["keywords"]["active_str"])
