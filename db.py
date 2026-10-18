"""
SQLite 数据库层 (db.py)
严格遵循 PRD 第四章表结构设计，并扩展竞品绑定 (competitors) 与版本发布记录 (version_releases) 支持 P1 需求。
"""
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent / "aso_data.db"


def get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    if db_path.parent:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=MEMORY;")
    conn.execute("PRAGMA synchronous=OFF;")
    conn.execute("PRAGMA locking_mode=EXCLUSIVE;")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    conn = get_conn(db_path)
    cur = conn.cursor()

    # 1. 监控应用表 (PRD 标准表 + 扩展副标题/评分/评论数/父应用关联)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS apps (
        app_id VARCHAR(32) NOT NULL,
        name VARCHAR(128) NOT NULL,
        country VARCHAR(8) NOT NULL,
        is_own_app BOOLEAN DEFAULT 1,
        parent_app_id VARCHAR(32) DEFAULT NULL,
        subtitle TEXT DEFAULT '',
        icon_url TEXT DEFAULT '',
        rating FLOAT DEFAULT 0.0,
        rating_count INTEGER DEFAULT 0,
        version VARCHAR(32) DEFAULT '',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (app_id, country)
    );
    """)

    # 2. 关注关键词表 (PRD 标准表)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS keywords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id VARCHAR(32) NOT NULL,
        country VARCHAR(8) NOT NULL,
        keyword VARCHAR(64) NOT NULL,
        popularity INTEGER DEFAULT 5,
        difficulty FLOAT DEFAULT 0,
        tag VARCHAR(32) DEFAULT '核心词',
        UNIQUE(app_id, country, keyword)
    );
    """)

    # 3. 每日排名快照表 (PRD 标准核心时序数据表)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS rank_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword_id INTEGER NOT NULL,
        app_id VARCHAR(32) NOT NULL,
        rank INTEGER,
        top3_apps TEXT,
        rating_count INTEGER,
        result_count INTEGER DEFAULT 0,
        record_date DATE NOT NULL,
        UNIQUE(keyword_id, app_id, record_date)
    );
    """)

    # 4. 版本发版标记表 (用于 P1 历史趋势折线图标记“版本发布日”)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS version_releases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id VARCHAR(32) NOT NULL,
        country VARCHAR(8) NOT NULL,
        version VARCHAR(32) NOT NULL,
        release_date DATE NOT NULL,
        notes TEXT DEFAULT '',
        UNIQUE(app_id, country, release_date)
    );
    """)

    conn.commit()
    conn.close()


def upsert_app(
    app_id: str,
    name: str,
    country: str,
    is_own_app: bool = True,
    parent_app_id: Optional[str] = None,
    subtitle: str = "",
    icon_url: str = "",
    rating: float = 0.0,
    rating_count: int = 0,
    version: str = "",
    db_path: Path = DB_PATH,
) -> None:
    conn = get_conn(db_path)
    conn.execute(
        """
        INSERT INTO apps (app_id, name, country, is_own_app, parent_app_id, subtitle, icon_url, rating, rating_count, version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(app_id, country) DO UPDATE SET
            name=excluded.name,
            is_own_app=excluded.is_own_app,
            parent_app_id=COALESCE(excluded.parent_app_id, apps.parent_app_id),
            subtitle=excluded.subtitle,
            icon_url=excluded.icon_url,
            rating=excluded.rating,
            rating_count=excluded.rating_count,
            version=excluded.version
        """,
        (
            str(app_id),
            name,
            country.upper(),
            1 if is_own_app else 0,
            parent_app_id,
            subtitle,
            icon_url,
            rating,
            rating_count,
            version,
        ),
    )
    conn.commit()
    conn.close()


def list_own_apps(db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_conn(db_path)
    rows = conn.execute(
        "SELECT * FROM apps WHERE is_own_app = 1 ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_own_apps_with_stats(db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """获取所有监控的我方应用，并统计关联的关键词数和竞品数"""
    conn = get_conn(db_path)
    rows = conn.execute("""
        SELECT 
            a.*,
            (SELECT COUNT(*) FROM keywords k WHERE k.app_id = a.app_id AND k.country = a.country) as keyword_count,
            (SELECT COUNT(*) FROM apps c WHERE c.parent_app_id = a.app_id AND c.country = a.country) as competitor_count
        FROM apps a
        WHERE a.is_own_app = 1
        ORDER BY a.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_competitors(parent_app_id: str, country: str, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_conn(db_path)
    rows = conn.execute(
        "SELECT * FROM apps WHERE is_own_app = 0 AND parent_app_id = ? AND country = ? ORDER BY created_at ASC",
        (str(parent_app_id), country.upper()),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_keyword(
    app_id: str,
    country: str,
    keyword: str,
    tag: str = "核心词",
    popularity: int = 5,
    difficulty: float = 0.0,
    db_path: Path = DB_PATH,
) -> int:
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO keywords (app_id, country, keyword, popularity, difficulty, tag)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(app_id, country, keyword) DO UPDATE SET
            tag=excluded.tag,
            popularity=CASE WHEN excluded.popularity > 5 THEN excluded.popularity ELSE keywords.popularity END,
            difficulty=CASE WHEN excluded.difficulty > 0 THEN excluded.difficulty ELSE keywords.difficulty END
        """,
        (str(app_id), country.upper(), keyword.strip(), popularity, difficulty, tag),
    )
    conn.commit()
    row = cur.execute(
        "SELECT id FROM keywords WHERE app_id = ? AND country = ? AND keyword = ?",
        (str(app_id), country.upper(), keyword.strip()),
    ).fetchone()
    conn.close()
    return int(row["id"])


def delete_keyword(keyword_id: int, db_path: Path = DB_PATH) -> None:
    conn = get_conn(db_path)
    conn.execute("DELETE FROM rank_history WHERE keyword_id = ?", (keyword_id,))
    conn.execute("DELETE FROM keywords WHERE id = ?", (keyword_id,))
    conn.commit()
    conn.close()


def save_rank_snapshot(
    keyword_id: int,
    app_id: str,
    rank: Optional[int],
    top3_apps: List[str],
    rating_count: int = 0,
    result_count: int = 0,
    record_date: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> None:
    rec_date = record_date or date.today().isoformat()
    stored_rank = rank if (rank is not None and 1 <= rank <= 200) else 201
    conn = get_conn(db_path)
    conn.execute(
        """
        INSERT INTO rank_history (keyword_id, app_id, rank, top3_apps, rating_count, result_count, record_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(keyword_id, app_id, record_date) DO UPDATE SET
            rank=excluded.rank,
            top3_apps=excluded.top3_apps,
            rating_count=excluded.rating_count,
            result_count=excluded.result_count
        """,
        (
            keyword_id,
            str(app_id),
            stored_rank,
            json.dumps(top3_apps, ensure_ascii=False),
            rating_count,
            result_count,
            rec_date,
        ),
    )
    conn.commit()
    conn.close()


def get_keyword_dashboard_rows(app_id: str, country: str, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """
    获取模块 2 关键词排名追踪看板所需全量指标：
    包含今日排名、昨日排名、升降变化、历史最高排名、Top 3 应用、竞品同词排名。
    """
    conn = get_conn(db_path)
    kws = conn.execute(
        "SELECT * FROM keywords WHERE app_id = ? AND country = ? ORDER BY tag, id ASC",
        (str(app_id), country.upper()),
    ).fetchall()
    competitors = list_competitors(app_id, country, db_path)

    result = []
    for kw in kws:
        kid = kw["id"]
        snaps = conn.execute(
            """
            SELECT rank, top3_apps, rating_count, result_count, record_date
            FROM rank_history
            WHERE keyword_id = ? AND app_id = ?
            ORDER BY record_date DESC
            LIMIT 2
            """,
            (kid, str(app_id)),
        ).fetchall()

        best_row = conn.execute(
            """
            SELECT MIN(rank) as best_rank
            FROM rank_history
            WHERE keyword_id = ? AND app_id = ? AND rank <= 200
            """,
            (kid, str(app_id)),
        ).fetchone()

        today_rank = snaps[0]["rank"] if len(snaps) >= 1 else None
        prev_rank = snaps[1]["rank"] if len(snaps) >= 2 else None
        top3 = json.loads(snaps[0]["top3_apps"]) if (len(snaps) >= 1 and snaps[0]["top3_apps"]) else []
        updated_date = snaps[0]["record_date"] if len(snaps) >= 1 else "-"
        result_count = snaps[0]["result_count"] if len(snaps) >= 1 else 0

        # 计算排名升降 (正数代表排名上升，如从 20 名升至 12 名，delta = +8)
        delta = None
        if today_rank is not None and prev_rank is not None:
            if today_rank <= 200 and prev_rank <= 200:
                delta = prev_rank - today_rank
            elif today_rank <= 200 and prev_rank > 200:
                delta = 201 - today_rank  # 新入榜
            elif today_rank > 200 and prev_rank <= 200:
                delta = -(201 - prev_rank)  # 跌出榜

        # 顺便读取竞品同词最新排名
        comp_ranks = {}
        for comp in competitors:
            c_snap = conn.execute(
                """
                SELECT rank FROM rank_history
                WHERE keyword_id = ? AND app_id = ?
                ORDER BY record_date DESC LIMIT 1
                """,
                (kid, comp["app_id"]),
            ).fetchone()
            comp_ranks[comp["name"]] = c_snap["rank"] if c_snap else None

        result.append(
            {
                "id": kid,
                "keyword": kw["keyword"],
                "tag": kw["tag"],
                "popularity": kw["popularity"],
                "difficulty": round(kw["difficulty"], 1),
                "today_rank": today_rank,
                "prev_rank": prev_rank,
                "delta": delta,
                "best_rank": best_row["best_rank"] if best_row else None,
                "top3_apps": top3,
                "result_count": result_count,
                "updated_date": updated_date,
                "competitor_ranks": comp_ranks,
            }
        )
    conn.close()
    return result


def get_keyword_trend(
    keyword_id: int, app_id: str, days: int = 30, db_path: Path = DB_PATH
) -> List[Dict[str, Any]]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = get_conn(db_path)
    rows = conn.execute(
        """
        SELECT record_date, rank, rating_count
        FROM rank_history
        WHERE keyword_id = ? AND app_id = ? AND record_date >= ?
        ORDER BY record_date ASC
        """,
        (keyword_id, str(app_id), cutoff),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_version_release(
    app_id: str, country: str, version: str, release_date: str, notes: str = "", db_path: Path = DB_PATH
) -> None:
    conn = get_conn(db_path)
    conn.execute(
        """
        INSERT INTO version_releases (app_id, country, version, release_date, notes)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(app_id, country, release_date) DO UPDATE SET
            version=excluded.version,
            notes=excluded.notes
        """,
        (str(app_id), country.upper(), version, release_date, notes),
    )
    conn.commit()
    conn.close()


def list_version_releases(app_id: str, country: str, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_conn(db_path)
    rows = conn.execute(
        """
        SELECT version, release_date, notes
        FROM version_releases
        WHERE app_id = ? AND country = ?
        ORDER BY release_date ASC
        """,
        (str(app_id), country.upper()),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_app(app_id: str, country: str, db_path: Path = DB_PATH) -> None:
    """删除指定监控应用及其关联词库、历史快照与绑定竞品"""
    conn = get_conn(db_path)
    cc = country.upper()
    kw_ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM keywords WHERE app_id = ? AND country = ?", (str(app_id), cc)
        ).fetchall()
    ]
    for kid in kw_ids:
        conn.execute("DELETE FROM rank_history WHERE keyword_id = ?", (kid,))
    conn.execute("DELETE FROM rank_history WHERE app_id = ?", (str(app_id),))
    conn.execute("DELETE FROM keywords WHERE app_id = ? AND country = ?", (str(app_id), cc))
    conn.execute("DELETE FROM version_releases WHERE app_id = ? AND country = ?", (str(app_id), cc))
    conn.execute("DELETE FROM apps WHERE parent_app_id = ? AND country = ?", (str(app_id), cc))
    conn.execute("DELETE FROM apps WHERE app_id = ? AND country = ?", (str(app_id), cc))
    conn.commit()
    conn.close()


def delete_competitor(parent_app_id: str, comp_app_id: str, country: str, db_path: Path = DB_PATH) -> None:
    """解除/删除指定的竞品关联应用"""
    conn = get_conn(db_path)
    cc = country.upper()
    conn.execute(
        "DELETE FROM apps WHERE app_id = ? AND parent_app_id = ? AND country = ?",
        (str(comp_app_id), str(parent_app_id), cc),
    )
    conn.execute("DELETE FROM rank_history WHERE app_id = ?", (str(comp_app_id),))
    conn.commit()
    conn.close()


def ensure_ai_recommendations_table(db_path: Path = DB_PATH) -> None:
    conn = get_conn(db_path)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS ai_recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id VARCHAR(32) NOT NULL,
        country VARCHAR(8) NOT NULL,
        engine_mode VARCHAR(64) NOT NULL,
        recommended_title TEXT NOT NULL,
        recommended_subtitle TEXT NOT NULL,
        recommended_keywords TEXT NOT NULL,
        summary_report TEXT DEFAULT '',
        full_json TEXT DEFAULT '',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()


def save_ai_recommendation(
    app_id: str,
    country: str,
    engine_mode: str,
    recommended_title: str,
    recommended_subtitle: str,
    recommended_keywords: str,
    summary_report: str = "",
    full_json: str = "",
    db_path: Path = DB_PATH,
) -> int:
    ensure_ai_recommendations_table(db_path)
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ai_recommendations (
            app_id, country, engine_mode, recommended_title,
            recommended_subtitle, recommended_keywords, summary_report, full_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(app_id),
            country.upper(),
            engine_mode,
            recommended_title,
            recommended_subtitle,
            recommended_keywords,
            summary_report,
            full_json,
        ),
    )
    rec_id = int(cur.lastrowid or 0)
    conn.commit()
    conn.close()
    return rec_id


def list_ai_recommendations(app_id: str, country: str, limit: int = 10, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    ensure_ai_recommendations_table(db_path)
    conn = get_conn(db_path)
    rows = conn.execute(
        """
        SELECT * FROM ai_recommendations
        WHERE app_id = ? AND country = ?
        ORDER BY id DESC LIMIT ?
        """,
        (str(app_id), country.upper(), limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
