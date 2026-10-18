"""
个人轻量级 ASO 监控与优化工具 — Streamlit 交互式 Web 看板 (app.py)
启动方式: streamlit run app.py
已针对 id6809107174 (喂药本 - 家庭用药管理) 完成投产预置与体验升级：
- 新增应用后自动切换侧边栏焦点到新应用
- 在「模块 3：拓词挖掘」点击 ➕ 监控 或「模块 2」批量加词时，支持自动立即抓取首日真实排名与难度分
- 支持单独刷新某个关键词、删除单个关键词、或一键清理演示应用数据
"""
from datetime import date
import pandas as pd
import streamlit as st

from apple_api import (
    DEFAULT_RATE_LIMIT_SECONDS,
    STOREFRONT_MAP,
    batch_update_keywords_with_rate_limit,
    fetch_app_Metadata,
    fetch_search_hints,
    parse_app_id,
    search_keyword_ranks,
)
from db import (
    add_keyword,
    add_version_release,
    delete_app,
    delete_keyword,
    get_keyword_dashboard_rows,
    get_keyword_trend,
    init_db,
    list_competitors,
    list_own_apps,
    list_version_releases,
    save_rank_snapshot,
    upsert_app,
)
from optimizer import analyze_100_char_workspace

st.set_page_config(
    page_title="个人轻量级 ASO 监控与优化工作台",
    page_icon="📈",
    layout="wide",
)

init_db()

# 侧边栏：我方应用与国家/地区切换
st.sidebar.title("📈 ASO 监控工作台")
st.sidebar.caption("V1.0 正式版 · 零成本个人独立开发版")

own_apps = list_own_apps()
app_options = {f"{a['name']} ({a['country']}) - {a['app_id']}": a for a in own_apps}
option_labels = list(app_options.keys())

selected_app = None
if option_labels:
    default_idx = 0
    if "active_app_id" in st.session_state:
        for i, lbl in enumerate(option_labels):
            if app_options[lbl]["app_id"] == st.session_state["active_app_id"]:
                default_idx = i
                break

    selected_label = st.sidebar.selectbox(
        "当前监控应用 (App + 国家)",
        option_labels,
        index=default_idx,
    )
    selected_app = app_options[selected_label]
    st.session_state["active_app_id"] = selected_app["app_id"]

    if selected_app.get("icon_url"):
        st.sidebar.image(selected_app["icon_url"], width=64)
    st.sidebar.markdown(
        f"**应用名称:** {selected_app['name']}  \n"
        f"**App ID:** `id{selected_app['app_id']}`  \n"
        f"**Storefront:** `{selected_app['country']}` (`{STOREFRONT_MAP.get(selected_app['country'], '')}`)  \n"
        f"**当前版本:** `{selected_app.get('version') or '-'}`  \n"
        f"**当前评分:** ⭐ {selected_app['rating']} ({selected_app['rating_count']:,} 条评论)"
    )
else:
    st.sidebar.info("请先在「模块 1：应用与竞品管理」中添加您的第一款 App。")

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📊 模块 2：关键词排名看板",
        "🔍 模块 3：拓词挖掘与难度评估",
        "✂️ 模块 4：100 字符去重工作台",
        "📱 模块 1：应用与竞品管理",
    ]
)

# ==============================================================================
# 模块 1：应用与竞品管理
# ==============================================================================
with tab4:
    st.subheader("模块 1：应用与竞品管理 (App Management)")
    col_add, col_comp = st.columns(2)

    with col_add:
        st.markdown("#### ➕ 添加我方监控 App (P0)")
        app_input = st.text_input(
            "App Store 链接或 App ID (trackId)",
            value="id6809107174",
            placeholder="如 id6809107174 或 https://apps.apple.com/cn/app/id6809107174",
        )
        country_code = st.selectbox("国家/地区 (Storefront)", list(STOREFRONT_MAP.keys()), index=0)
        custom_subtitle = st.text_input(
            "副标题备忘 (选填，若留空自动从标题拆分，用于 100 字符去重)",
            placeholder="如：儿童宝宝吃药提醒与家庭药箱记录",
        )

        if st.button("调用 Lookup 接口拉取并设为当前监控应用", type="primary"):
            if not app_input.strip():
                st.error("请输入有效的 App ID 或链接")
            else:
                try:
                    meta = fetch_app_Metadata(app_input, country_code)
                    if meta:
                        upsert_app(
                            app_id=meta["app_id"],
                            name=meta["name"],
                            country=country_code,
                            is_own_app=True,
                            subtitle=custom_subtitle.strip() or meta["subtitle"],
                            icon_url=meta["icon_url"],
                            rating=meta["rating"],
                            rating_count=meta["rating_count"],
                            version=meta["version"],
                        )
                        st.session_state["active_app_id"] = meta["app_id"]
                        st.success(
                            f"成功绑定并切换至：{meta['name']} (id{meta['app_id']}, {country_code}) · 版本 v{meta['version']}"
                        )
                        st.rerun()
                    else:
                        st.warning("Lookup 接口未返回结果，请检查 App ID 在所选国家/地区是否已上架。")
                except Exception as exc:
                    st.error(f"拉取失败: {exc}")

        if selected_app:
            st.divider()
            st.markdown("#### 🗑️ 管理已绑定应用")
            if st.button(f"删除当前应用「{selected_app['name']} ({selected_app['country']})」及其词库"):
                delete_app(selected_app["app_id"], selected_app["country"])
                st.session_state.pop("active_app_id", None)
                st.success("已删除该应用及其关联数据。")
                st.rerun()

    with col_comp:
        st.markdown("#### ⚔️ 竞品关联绑定 (P1 · 单应用支持绑定 3~5 个竞品)")
        if not selected_app:
            st.info("请先添加并选择一款我方 App")
        else:
            comps = list_competitors(selected_app["app_id"], selected_app["country"])
            st.caption(
                f"当前已为 **{selected_app['name']} ({selected_app['country']})** 绑定 {len(comps)}/5 款核心竞品（查词时单次请求顺便记录竞品排名）："
            )
            for c in comps:
                st.markdown(f"- **{c['name']}** (`id{c['app_id']}`) · ⭐ {c['rating']} · 评论 {c['rating_count']:,}")

            comp_input = st.text_input("输入竞品 App ID 或链接", key="comp_in", placeholder="如 id1439876541")
            if st.button("绑定关联竞品"):
                if len(comps) >= 5:
                    st.warning("每个应用最多建议绑定 5 个核心竞品。")
                else:
                    try:
                        cmeta = fetch_app_Metadata(comp_input, selected_app["country"])
                        if cmeta:
                            upsert_app(
                                app_id=cmeta["app_id"],
                                name=cmeta["name"],
                                country=selected_app["country"],
                                is_own_app=False,
                                parent_app_id=selected_app["app_id"],
                                subtitle=cmeta["subtitle"],
                                icon_url=cmeta["icon_url"],
                                rating=cmeta["rating"],
                                rating_count=cmeta["rating_count"],
                                version=cmeta["version"],
                            )
                            st.success(f"已绑定竞品：{cmeta['name']}")
                            st.rerun()
                        else:
                            st.warning("未查到该竞品 App ID，请确认国家/地区是否一致。")
                    except Exception as exc:
                        st.error(f"绑定竞品失败: {exc}")

# ==============================================================================
# 模块 2：关键词排名追踪与趋势看板
# ==============================================================================
with tab1:
    st.subheader("模块 2：关键词排名追踪与趋势看板 (Rank Tracker)")
    if not selected_app:
        st.info("请先在「模块 1」添加或选择一款监控 App。")
    else:
        app_id = selected_app["app_id"]
        country = selected_app["country"]
        competitors = list_competitors(app_id, country)
        comp_ids = [c["app_id"] for c in competitors]

        with st.expander("➕ 批量导入/添加关注关键词 & 版本发布日标记", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                batch_kws = st.text_area(
                    "批量输入关键词（逗号或换行分隔）",
                    placeholder="喂药本, 喂药记录, 家庭用药管理, 吃药提醒, 宝宝喂药, 家庭药箱",
                )
                kw_tag = st.selectbox("分组标签", ["核心词", "品牌词", "长尾词", "竞品词"])
                kw_pop = st.slider("初始预估热度 (Popularity 5~100)", 5, 100, 60)
                auto_fetch_now = st.checkbox("导入后立即请求苹果接口查询今日实时排名与难度分", value=True)
                if st.button("批量加入词库", type="primary"):
                    raw_list = [
                        k.strip()
                        for k in batch_kws.replace("，", ",").replace("\n", ",").split(",")
                        if k.strip()
                    ]
                    if not raw_list:
                        st.warning("请输入至少一个关键词")
                    else:
                        prog = st.progress(0, text="正在导入关键词...")
                        all_targets = [str(app_id)] + [str(cid) for cid in comp_ids]
                        for idx, k in enumerate(raw_list, start=1):
                            kid = add_keyword(app_id, country, k, tag=kw_tag, popularity=kw_pop)
                            if auto_fetch_now:
                                prog.progress(idx / len(raw_list), text=f"[{idx}/{len(raw_list)}] 正在实时查询「{k}」排名...")
                                try:
                                    res = search_keyword_ranks(k, country, all_targets)
                                    add_keyword(app_id, country, k, tag=kw_tag, popularity=kw_pop, difficulty=res["difficulty_metrics"]["difficulty"])
                                    for tid, r_info in res["ranks"].items():
                                        save_rank_snapshot(
                                            keyword_id=kid,
                                            app_id=tid,
                                            rank=r_info["rank"],
                                            top3_apps=res["top3_apps"],
                                            rating_count=r_info["rating_count"],
                                            result_count=res["result_count"],
                                        )
                                except Exception as exc:
                                    st.warning(f"查询「{k}」排名失败: {exc}")
                        st.success(f"成功为「{selected_app['name']}」导入 {len(raw_list)} 个关键词！")
                        st.rerun()

            with c2:
                st.markdown("**📌 标记版本发布日 (用于在趋势折线图验证发版效果)**")
                ver_num = st.text_input("版本号", value=f"v{selected_app.get('version') or '1.1.0'}")
                ver_date = st.date_input("发版日期", value=date.today())
                ver_notes = st.text_input("更新元数据说明", placeholder="优化副标题与 100 字符，新增『喂药记录,家庭药箱』")
                if st.button("保存版本发布标记"):
                    if ver_num.strip():
                        add_version_release(app_id, country, ver_num.strip(), ver_date.isoformat(), ver_notes.strip())
                        st.success(f"已记录版本 {ver_num} ({ver_date.isoformat()})")
                        st.rerun()

        rows = get_keyword_dashboard_rows(app_id, country)
        col_btn1, col_btn2, col_btn3 = st.columns([2, 2, 3])
        with col_btn1:
            if st.button("🔄 立即抓取全部最新排名 (3.5s 防封限流)", type="primary", disabled=not rows):
                prog = st.progress(0, text="准备请求 Apple Storefront 接口...")

                def _cb(idx: int, total: int, kw_str: str) -> None:
                    prog.progress(idx / total, text=f"[{idx}/{total}] 正在抓取「{kw_str}」Top 200 排名 (间隔 3.5s)...")

                batch_res = batch_update_keywords_with_rate_limit(
                    keywords=rows,
                    own_app_id=app_id,
                    competitor_app_ids=comp_ids,
                    country=country,
                    sleep_seconds=DEFAULT_RATE_LIMIT_SECONDS,
                    progress_callback=_cb,
                )
                for res in batch_res:
                    add_keyword(app_id, country, res["keyword"], difficulty=res["difficulty_metrics"]["difficulty"])
                    for tid, r_info in res["ranks"].items():
                        save_rank_snapshot(
                            keyword_id=res["keyword_id"],
                            app_id=tid,
                            rank=r_info["rank"],
                            top3_apps=res["top3_apps"],
                            rating_count=r_info["rating_count"],
                            result_count=res["result_count"],
                        )
                st.success("全部关键词及关联竞品排名已更新落盘！")
                st.rerun()

        if rows:
            table_data = []
            for r in rows:
                rank_str = (
                    f"#{r['today_rank']}"
                    if (r["today_rank"] and r["today_rank"] <= 200)
                    else (">200" if r["today_rank"] else "未查")
                )
                if r["delta"] is None or r["delta"] == 0:
                    delta_str = "—"
                elif r["delta"] > 0:
                    delta_str = f"↑ +{r['delta']}"
                else:
                    delta_str = f"↓ {r['delta']}"
                best_str = f"#{r['best_rank']}" if r["best_rank"] else "—"
                comp_summary = " | ".join(
                    [
                        f"{cname}: #{cr}" if (cr and cr <= 200) else f"{cname}: >200"
                        for cname, cr in r["competitor_ranks"].items()
                    ]
                )
                table_data.append(
                    {
                        "ID": r["id"],
                        "关键词": r["keyword"],
                        "标签": r["tag"],
                        "热度": r["popularity"],
                        "难度分": r["difficulty"],
                        "今日排名": rank_str,
                        "较昨日变化": delta_str,
                        "历史最高": best_str,
                        "竞品同词排名": comp_summary or "未绑竞品",
                        "当前 Top 3 应用": " / ".join(r["top3_apps"][:3]),
                        "更新时间": r["updated_date"],
                    }
                )
            st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)

            # 历史趋势折线图 (Y 轴倒序，第 1 名在最上方) + 单词操作
            st.markdown("#### 📈 关键词历史排名趋势图 (Y 轴倒序 · 第 1 名在最上方)")
            kw_map = {f"{r['keyword']} ({r['tag']})": r for r in rows}
            c_sel, c_win, c_del = st.columns([3, 2, 1])
            with c_sel:
                chosen_kw_label = st.selectbox("选择要查看历史趋势或管理的关键词", list(kw_map.keys()))
            with c_win:
                days_window = st.radio("时间范围", [30, 90], horizontal=True, format_func=lambda d: f"近 {d} 天")
            chosen_kw = kw_map[chosen_kw_label]
            with c_del:
                if st.button("🗑️ 删除该词"):
                    delete_keyword(chosen_kw["id"])
                    st.toast(f"已删除关键词「{chosen_kw['keyword']}」")
                    st.rerun()

            trend_pts = get_keyword_trend(chosen_kw["id"], app_id, days=days_window)
            releases = list_version_releases(app_id, country)

            if trend_pts:
                import altair as alt
                df_trend = pd.DataFrame(trend_pts)
                base_line = (
                    alt.Chart(df_trend)
                    .mark_line(point=alt.OverlayMarkDef(size=70), color="#2563eb", strokeWidth=3)
                    .encode(
                        x=alt.X("record_date:T", title="日期"),
                        y=alt.Y(
                            "rank:Q",
                            title="App Store 排名 (越靠上名次越高，201代表>200未入榜)",
                            scale=alt.Scale(reverse=True, domain=[1, 205]),
                        ),
                        tooltip=["record_date:T", "rank:Q", "rating_count:Q"],
                    )
                    .properties(height=340)
                )
                if releases:
                    df_rel = pd.DataFrame(releases)
                    rule = (
                        alt.Chart(df_rel)
                        .mark_rule(color="#ef4444", strokeDash=[6, 4], strokeWidth=2)
                        .encode(
                            x="release_date:T",
                            tooltip=["version:N", "release_date:T", "notes:N"],
                        )
                    )
                    st.altair_chart(base_line + rule, use_container_width=True)
                else:
                    st.altair_chart(base_line, use_container_width=True)
        else:
            st.info("当前应用词库为空，请在上方「批量导入/添加关注关键词」录入监控词。")

# ==============================================================================
# 模块 3：关键词挖掘与难度评估器
# ==============================================================================
with tab2:
    st.subheader("模块 3：关键词挖掘与难度评估器 (Keyword Explorer)")
    seed_col, country_col = st.columns([3, 1])
    with seed_col:
        seed_kw = st.text_input("输入种子词（如：喂药、用药提醒、家庭药箱、记账）", value="喂药")
    with country_col:
        default_cc_idx = list(STOREFRONT_MAP.keys()).index(selected_app["country"]) if selected_app and selected_app["country"] in STOREFRONT_MAP else 0
        exp_country = st.selectbox("目标国家", list(STOREFRONT_MAP.keys()), index=default_cc_idx, key="exp_c")

    c_hint, c_diff = st.columns(2)
    with c_hint:
        st.markdown("#### 💡 苹果官方下拉联想词挖掘 (MZSearchHints)")
        if st.button("拉取 Top 10 官方下拉联想词"):
            try:
                hints = fetch_search_hints(seed_kw, exp_country)
                st.session_state["last_hints"] = hints
                if not hints:
                    st.info("苹果官方对该词暂未返回下拉联想词，您可以尝试缩短词根（如输入 2 个字的核心词）。")
            except Exception as exc:
                st.error(f"联想词请求失败: {exc}")

        for h in st.session_state.get("last_hints", []):
            hc1, hc2, hc3 = st.columns([4, 3, 2])
            hc1.markdown(f"**#{h['rank']} {h['term']}**")
            hc2.caption(f"Priority: `{h['priority']}` · 热度≈`{h['estimated_popularity']}`")
            if selected_app and hc3.button("➕ 监控", key=f"add_h_{h['term']}"):
                kid = add_keyword(
                    selected_app["app_id"],
                    selected_app["country"],
                    h["term"],
                    popularity=h["estimated_popularity"],
                )
                try:
                    comp_ids = [c["app_id"] for c in list_competitors(selected_app["app_id"], selected_app["country"])]
                    res = search_keyword_ranks(h["term"], selected_app["country"], [selected_app["app_id"]] + comp_ids)
                    add_keyword(
                        selected_app["app_id"],
                        selected_app["country"],
                        h["term"],
                        popularity=h["estimated_popularity"],
                        difficulty=res["difficulty_metrics"]["difficulty"],
                    )
                    for tid, r_info in res["ranks"].items():
                        save_rank_snapshot(
                            keyword_id=kid,
                            app_id=tid,
                            rank=r_info["rank"],
                            top3_apps=res["top3_apps"],
                            rating_count=r_info["rating_count"],
                            result_count=res["result_count"],
                        )
                    my_rank = res["ranks"][str(selected_app["app_id"])]["rank"]
                    rank_txt = f"#{my_rank}" if my_rank <= 200 else ">200"
                    st.toast(f"已将「{h['term']}」加入「{selected_app['name']}」监控！当前排名: {rank_txt}")
                except Exception:
                    st.toast(f"已将「{h['term']}」加入「{selected_app['name']}」监控列表！")

    with c_diff:
        st.markdown("#### 🎯 自研竞争度评分器 (Top 10 标题匹配率 + 头部统治力)")
        if st.button("评估该词攻克难度并查看我方排名", type="primary"):
            try:
                target_ids = [selected_app["app_id"]] if selected_app else []
                eval_res = search_keyword_ranks(seed_kw, exp_country, target_ids)
                st.session_state["last_eval"] = eval_res
            except Exception as exc:
                st.error(f"难度评估请求失败: {exc}")

        if "last_eval" in st.session_state:
            ev = st.session_state["last_eval"]
            dm = ev["difficulty_metrics"]
            m1, m2, m3 = st.columns(3)
            m1.metric("攻克难度分 (1~100)", f"{dm['difficulty']} 分", dm["level"])
            m2.metric("前 10 标题匹配率", f"{dm['title_match_rate']}%", f"{dm['title_match_count']}/10 包含该词")
            m3.metric("Top 10 平均评论数", f"{dm['avg_rating_count']:,}", f"平均星级 ⭐ {dm['avg_rating']}")
            if selected_app and str(selected_app["app_id"]) in ev["ranks"]:
                my_r = ev["ranks"][str(selected_app["app_id"])]["rank"]
                st.info(
                    f"📱 **{selected_app['name']}** 在关键词「**{ev['keyword']}**」下的实时排名：**{'#' + str(my_r) if my_r <= 200 else '>200 (未入前200名)'}**"
                )
            st.dataframe(pd.DataFrame(ev["top10_apps"]), use_container_width=True, hide_index=True)

# ==============================================================================
# 模块 4：100 字符组装工作台
# ==============================================================================
with tab3:
    st.subheader("模块 4：100 字符组装工作台 (100-Char Optimizer)")
    if selected_app and " - " in selected_app["name"]:
        default_title, inferred_sub = selected_app["name"].split(" - ", 1)
        default_sub = (
            selected_app["subtitle"]
            if (selected_app.get("subtitle") and selected_app["subtitle"] != "Medical")
            else inferred_sub
        )
    else:
        default_title = selected_app["name"] if selected_app else "喂药本 - 家庭用药管理"
        default_sub = (
            selected_app["subtitle"]
            if (selected_app and selected_app.get("subtitle") and selected_app["subtitle"] != "Medical")
            else "宝宝儿童喂药记录与吃药定时提醒助手"
        )

    in_title = st.text_input("应用标题 (App Store Connect 限制 30 字符)", value=selected_app["name"] if selected_app else default_title)
    in_sub = st.text_input("应用副标题 (App Store Connect 限制 30 字符)", value=default_sub)
    in_kws = st.text_area(
        "100 字符关键词栏（支持粘贴中文逗号 `，`、空格或换行，自动清洗并检测与标题/副标题重复词）",
        value="喂药本，喂药记录，家庭用药，吃药提醒，宝宝喂药，家庭药箱，服药打卡，儿童用药，药品过期，退烧药，抗生素，慢病管理，处方记录，看病记录，疫苗本，身高体重，体温计，儿科，健康档案",
        height=110,
    )
    auto_strip = st.checkbox("自动剔除已在「标题」或「副标题」中出现过的冗余词（省出宝贵字符额度）", value=True)

    analysis = analyze_100_char_workspace(in_title, in_sub, in_kws, auto_remove_title_dups=auto_strip)

    k1, k2, k3 = st.columns(3)
    k1.metric("标题字符数 (限 30)", f"{analysis['title']['length']} / 30", f"剩余 {analysis['title']['remaining']} 字符")
    k2.metric("副标题字符数 (限 30)", f"{analysis['subtitle']['length']} / 30", f"剩余 {analysis['subtitle']['remaining']} 字符")
    k3.metric(
        "100 字符栏 (限 100)",
        f"{analysis['keywords']['length']} / 100",
        f"剩余 {analysis['keywords']['remaining']} 字符 (共省下 {analysis['keywords']['saved_chars']} 字符)",
    )

    if analysis["keywords"]["title_subtitle_conflicts"]:
        conflict_tags = "、".join(
            [f"「{c['keyword']}」(与{c['source']}重复)" for c in analysis["keywords"]["title_subtitle_conflicts"]]
        )
        st.warning(f"🔍 **检测到与标题/副标题重复的词：** {conflict_tags} —— 苹果算法已默认收录标题与副标题词根，建议剔除！")

    if analysis["keywords"]["internal_duplicates"]:
        st.info(f"♻️ **已自动合并内部重复填写的词：** {'、'.join(analysis['keywords']['internal_duplicates'])}")

    st.markdown("#### ✅ 清洗后可直接粘贴至 App Store Connect 的 100 字符结果：")
    st.code(analysis["keywords"]["active_str"], language="text")
