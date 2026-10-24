"""
个人轻量级 ASO 监控与优化工具 — Streamlit 交互式 Web 看板 (app.py)
启动方式: streamlit run app.py
已针对 id6809107174 (喂药本 - 家庭用药管理) 完成投产预置与体验升级：
- 新增应用后自动切换侧边栏焦点到新应用
- 在「模块 3：拓词挖掘」点击 ➕ 监控 或「模块 2」批量加词时，支持自动立即抓取首日真实排名与难度分
- 支持单独刷新某个关键词、删除单个关键词、或一键清理演示应用数据
"""
import os
from datetime import date
import pandas as pd
import streamlit as st

from apple_api import (
    DEFAULT_RATE_LIMIT_SECONDS,
    STOREFRONT_LABELS,
    STOREFRONT_MAP,
    batch_fetch_app_metadata,
    batch_update_keywords_with_rate_limit,
    extract_app_info_from_input,
    fetch_app_Metadata,
    fetch_search_hints,
    parse_app_id,
    search_keyword_ranks,
)
from db import (
    add_keyword,
    add_version_release,
    delete_app,
    delete_competitor,
    delete_keyword,
    get_keyword_dashboard_rows,
    get_keyword_trend,
    init_db,
    list_competitors,
    list_own_apps,
    list_own_apps_grouped,
    list_own_apps_with_stats,
    list_version_releases,
    save_rank_snapshot,
    upsert_app,
)
from optimizer import analyze_100_char_workspace
from ai_agent import (
    build_agent_prompt_text,
    generate_aso_recommendations_local,
    run_llm_aso_agent,
)
from db import (
    list_ai_recommendations,
    save_ai_recommendation,
)

st.set_page_config(
    page_title="个人轻量级 ASO 监控与优化工作台",
    page_icon="📈",
    layout="wide",
)

init_db()

# ==============================================================================
# 侧边栏：我方主应用与监控区域两级联动
# ==============================================================================
st.sidebar.title("📈 ASO 监控工作台")
st.sidebar.caption("V1.0 正式版 · 多地区集中监控")

grouped_apps = list_own_apps_grouped()
app_map = {a["app_id"]: a for a in grouped_apps}
app_ids = list(app_map.keys())

selected_app = None
active_grouped_app = None

if app_ids:
    if "active_app_id" not in st.session_state or st.session_state["active_app_id"] not in app_map:
        st.session_state["active_app_id"] = app_ids[0]

    current_app_idx = app_ids.index(st.session_state["active_app_id"])

    def format_app_sidebar_label(aid: str) -> str:
        item = app_map[aid]
        c_count = len(item["countries"])
        return f"{item['name']} (id{aid}) · {c_count} 区域"

    chosen_app_id = st.sidebar.selectbox(
        "📱 当前监控主应用 (App)",
        app_ids,
        index=current_app_idx,
        format_func=format_app_sidebar_label,
        key="sidebar_app_select",
    )
    st.session_state["active_app_id"] = chosen_app_id
    active_grouped_app = app_map[chosen_app_id]

    available_countries = active_grouped_app["countries"]
    if "active_country" not in st.session_state or st.session_state["active_country"] not in available_countries:
        st.session_state["active_country"] = "CN" if "CN" in available_countries else available_countries[0]

    st.sidebar.markdown("**🌐 监控区域 (Storefront):**")

    pills_key = f"pills_country_{chosen_app_id}"
    if pills_key not in st.session_state or st.session_state[pills_key] not in available_countries:
        st.session_state[pills_key] = st.session_state["active_country"]
    elif st.session_state[pills_key] != st.session_state["active_country"]:
        st.session_state[pills_key] = st.session_state["active_country"]

    def on_sidebar_country_change():
        val = st.session_state.get(pills_key)
        if val and val in available_countries:
            st.session_state["active_country"] = val

    # 胶囊药丸标签选择当前地区
    st.sidebar.pills(
        "选择当前监控区域",
        options=available_countries,
        format_func=lambda c: STOREFRONT_LABELS.get(c, c),
        label_visibility="collapsed",
        key=pills_key,
        on_change=on_sidebar_country_change,
    )


    current_country = st.session_state["active_country"]
    selected_app = active_grouped_app["regions"].get(current_country)
    if not selected_app and available_countries:
        selected_app = active_grouped_app["regions"][available_countries[0]]
        st.session_state["active_country"] = selected_app["country"]

    # 快捷拓展监控地区弹窗 (无需重新粘贴 App ID)
    unmonitored_countries = [c for c in STOREFRONT_MAP.keys() if c not in available_countries]
    if unmonitored_countries:
        with st.sidebar.popover("➕ 为此 App 拓展新地区", use_container_width=True):
            st.markdown(f"##### ➕ 拓展监控地区")
            st.caption(f"当前主应用：**{active_grouped_app['name']}** (`id{chosen_app_id}`)")
            add_c_choice = st.selectbox(
                "选择要开启监控的区域",
                unmonitored_countries,
                format_func=lambda c: STOREFRONT_LABELS.get(c, c),
                key="sidebar_expand_country_select",
            )
            if st.button("🚀 立即拉取并开通", type="primary", use_container_width=True, key="sidebar_expand_country_btn"):
                with st.spinner(f"正在从 Apple 拉取「{add_c_choice}」区数据..."):
                    try:
                        n_meta = fetch_app_Metadata(chosen_app_id, add_c_choice)
                        if n_meta:
                            upsert_app(
                                app_id=n_meta["app_id"],
                                name=n_meta["name"],
                                country=add_c_choice,
                                is_own_app=True,
                                subtitle=n_meta["subtitle"],
                                icon_url=n_meta["icon_url"],
                                rating=n_meta["rating"],
                                rating_count=n_meta["rating_count"],
                                version=n_meta.get("version", ""),
                            )
                            st.session_state["active_country"] = add_c_choice
                            st.toast(f"成功为应用开通「{add_c_choice}」监控！")
                            st.rerun()
                        else:
                            st.warning(f"Lookup 未查找到该应用，请检查该 App 在「{add_c_choice}」区是否已正式上架。")
                    except Exception as exc:
                        st.error(f"拓展失败: {exc}")

    if selected_app:
        if selected_app.get("icon_url"):
            st.sidebar.image(selected_app["icon_url"], width=64)
        st.sidebar.markdown(
            f"**当前区域名称:** {selected_app['name']}  \n"
            f"**App ID:** `id{selected_app['app_id']}`  \n"
            f"**Storefront:** `{STOREFRONT_LABELS.get(selected_app['country'], selected_app['country'])}`  \n"
            f"**当前版本:** `{selected_app.get('version') or '-'}`  \n"
            f"**当前评分:** ⭐ {selected_app['rating']} ({selected_app['rating_count']:,} 条评论)  \n"
            f"**数据规模:** 🔑 `{selected_app.get('keyword_count', 0)}` 个词 · ⚔️ `{selected_app.get('competitor_count', 0)}` 款竞品"
        )
        if st.sidebar.button("🔄 刷新当前区域线上状态", use_container_width=True, help="立即调用 Apple Lookup 接口更新该 App 的版本、评分与评论总数"):
            with st.spinner("正在请求 Apple 接口拉取最新元数据..."):
                try:
                    meta = fetch_app_Metadata(selected_app["app_id"], selected_app["country"])
                    if meta:
                        old_ver = (selected_app.get("version") or "").strip()
                        new_ver = (meta.get("version") or "").strip()
                        if old_ver and new_ver and old_ver != new_ver:
                            add_version_release(
                                selected_app["app_id"],
                                selected_app["country"],
                                new_ver,
                                date.today().isoformat(),
                                notes=f"手动刷新检测到新版本发布：v{old_ver} → v{new_ver}",
                            )
                            st.sidebar.info(f"🎉 检测到新版本上线：v{old_ver} → v{new_ver}，已自动记录发版日！")

                        upsert_app(
                            app_id=meta["app_id"],
                            name=meta["name"],
                            country=selected_app["country"],
                            is_own_app=True,
                            subtitle=meta["subtitle"],
                            icon_url=meta["icon_url"],
                            rating=meta["rating"],
                            rating_count=meta["rating_count"],
                            version=new_ver or old_ver,
                        )
                        st.toast(f"已同步最新状态：⭐ {meta['rating']} ({meta['rating_count']:,} 评价) · v{new_ver or '-'}")
                        st.rerun()
                    else:
                        st.sidebar.warning("Apple Lookup 接口未返回应用数据")
                except Exception as exc:
                    st.sidebar.error(f"拉取失败: {exc}")
else:
    st.sidebar.info("💡 暂无监控应用，请点击下方或前往「模块 1」添加您的第一款 App。")

# 侧边栏全局快捷添加应用弹窗 (支持一次性多选国家批量添加)
with st.sidebar.popover("➕ 快捷添加 App (支持多选地区)", use_container_width=True):
    st.markdown("##### ➕ 快捷批量添加监控 App")
    st.caption("输入纯数字 ID 或链接，可直接多选开启多个监控区域")
    quick_input = st.text_input(
        "App ID 或链接",
        key="quick_app_input",
        placeholder="例如 6809107174 或粘贴 App Store 链接",
    )
    quick_info = extract_app_info_from_input(quick_input)
    default_q_selected = ["CN", "US"]
    if quick_info.get("country") and quick_info["country"] in STOREFRONT_MAP:
        if quick_info["country"] not in default_q_selected:
            default_q_selected = [quick_info["country"]] + default_q_selected
        st.caption(f"✨ 检测到链接中的地区：`{quick_info['country']}`")

    quick_countries = st.multiselect(
        "选择要监控的区域 (可多选)",
        options=list(STOREFRONT_MAP.keys()),
        default=default_q_selected,
        format_func=lambda c: STOREFRONT_LABELS.get(c, c),
        key="quick_countries_select",
    )
    if st.button("🚀 批量识别并添加", type="primary", key="quick_add_btn", use_container_width=True):
        if not quick_input.strip() or not quick_countries:
            st.error("请输入有效的 App ID 并至少选择一个国家/地区")
        else:
            with st.spinner(f"正在批量从 Apple 拉取 {len(quick_countries)} 个区域数据..."):
                res = batch_fetch_app_metadata(quick_input, quick_countries)
                success_map = res["success"]
                if success_map:
                    for cc, meta in success_map.items():
                        upsert_app(
                            app_id=meta["app_id"],
                            name=meta["name"],
                            country=cc,
                            is_own_app=True,
                            subtitle=meta["subtitle"],
                            icon_url=meta["icon_url"],
                            rating=meta["rating"],
                            rating_count=meta["rating_count"],
                            version=meta.get("version", ""),
                        )
                    first_aid = list(success_map.values())[0]["app_id"]
                    first_c = list(success_map.keys())[0]
                    st.session_state["active_app_id"] = first_aid
                    st.session_state["active_country"] = first_c
                    st.session_state[f"pills_country_{first_aid}"] = first_c
                    st.toast(f"成功批量开通 {len(success_map)} 个区域监控！")
                    st.rerun()
                else:
                    st.warning("所有勾选区域均未查到结果，请检查 App ID 在所选地区是否已正式上架。")

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "📱 模块 1：应用与竞品管理",
        "📊 模块 2：关键词排名看板",
        "🔍 模块 3：拓词挖掘与难度评估",
        "✂️ 模块 4：100 字符去重工作台",
        "🤖 模块 5：AI 决策推荐 Agent",
    ]
)

# ==============================================================================
# 模块 1：应用与竞品管理
# ==============================================================================
with tab1:
    st.subheader("📱 模块 1：应用与竞品管理 (App Management)")
    st.caption("支持通过 App ID、带 id 前缀或完整 App Store 链接添加应用，集中管理已监控应用、关联竞品及安全删除。")

    sub_tab_add, sub_tab_manage, sub_tab_comp = st.tabs(
        [
            "➕ 添加监控应用 (Add App)",
            f"📋 已监控应用列表与区域管理 ({len(grouped_apps)})",
            "⚔️ 竞品关联管理 (Competitors)",
        ]
    )

    # --------------------------------------------------------------------------
    # 子 Tab 1：添加监控应用 (支持批量多选地区)
    # --------------------------------------------------------------------------
    with sub_tab_add:
        st.markdown("#### ➕ 批量添加我方监控 App (支持多选地区)")
        st.caption("输入纯数字 ID（如 `6809107174`）、带 id 前缀（如 `id6809107174`）或完整 App Store 链接，可直接多选并同时开启多个区域监控。")

        app_input = st.text_input(
            "App Store 链接或 App ID (trackId)",
            value="",
            placeholder="例如 6809107174、id6809107174 或 https://apps.apple.com/cn/app/.../id6809107174",
            key="tab1_app_input",
            help="支持自动从链接中识别国家地区",
        )

        # 智能嗅探链接中的国家代码
        parsed_info = extract_app_info_from_input(app_input)
        inferred_cc = parsed_info.get("country")
        default_selected_ccs = ["CN", "US"]
        if inferred_cc and inferred_cc in STOREFRONT_MAP:
            if inferred_cc not in default_selected_ccs:
                default_selected_ccs = [inferred_cc] + default_selected_ccs
            st.info(f"💡 检测到链接中的国家/地区为 **{STOREFRONT_LABELS.get(inferred_cc, inferred_cc)}**，已为您优先勾选。")

        # 常用地区快速预设选择
        st.markdown("**选择要开通的监控国家/地区 (可多选)：**")
        q_cols = st.columns([1.2, 1.2, 1.2, 1, 2])
        if q_cols[0].button("🇨🇳+🇺🇸 中美常用", key="preset_cn_us"):
            st.session_state["tab1_selected_countries"] = ["CN", "US"]
        if q_cols[1].button("🌏 东亚五区", key="preset_asia"):
            st.session_state["tab1_selected_countries"] = ["CN", "JP", "KR", "TW", "HK"]
        if q_cols[2].button("🌍 欧美四国", key="preset_west"):
            st.session_state["tab1_selected_countries"] = ["US", "GB", "DE", "FR"]
        if q_cols[3].button("🌐 全选", key="preset_all"):
            st.session_state["tab1_selected_countries"] = list(STOREFRONT_MAP.keys())

        curr_def_countries = st.session_state.get("tab1_selected_countries") or default_selected_ccs

        selected_countries = st.multiselect(
            "目标国家/地区 (Storefront)",
            list(STOREFRONT_MAP.keys()),
            default=curr_def_countries,
            format_func=lambda c: STOREFRONT_LABELS.get(c, c),
            key="tab1_multiselect_countries",
        )

        custom_subtitle = st.text_input(
            "副标题备忘 (选填，留空将自动从各地区线上商店标题/副标题提取)",
            placeholder="例如：儿童宝宝吃药提醒与家庭药箱记录",
            key="tab1_custom_sub",
        )

        btn_c1, btn_c2 = st.columns([1, 1])
        with btn_c1:
            do_preview = st.button("🔍 批量识别并预览各地区详情", type="primary", use_container_width=True)
        with btn_c2:
            do_direct_add = st.button("⚡ 一键批量添加并设为当前监控", use_container_width=True)

        if do_preview:
            if not app_input.strip() or not selected_countries:
                st.error("请输入有效的 App ID / 链接并至少勾选一个监控地区")
            else:
                with st.spinner("正在请求 Apple Lookup 接口抓取所选地区应用元数据..."):
                    res = batch_fetch_app_metadata(app_input, selected_countries)
                    st.session_state["tab1_preview_results"] = res

        # 显示批量识别预览卡片
        if "tab1_preview_results" in st.session_state:
            res = st.session_state["tab1_preview_results"]
            succ = res["success"]
            fail = res["failed"]
            st.markdown("---")
            st.markdown("##### 📱 批量应用识别预览结果")
            if succ:
                st.success(f"成功识别 {len(succ)} 个区域数据：{', '.join(succ.keys())}")
                for cc, meta in succ.items():
                    with st.container(border=True):
                        p_c1, p_c2 = st.columns([1, 4])
                        with p_c1:
                            if meta.get("icon_url"):
                                st.image(meta["icon_url"], width=64)
                            else:
                                st.markdown("📱")
                        with p_c2:
                            st.markdown(f"**{STOREFRONT_LABELS.get(cc, cc)}: {meta['name']}**")
                            st.caption(
                                f"**副标题/分类:** `{meta['subtitle']}` · **当前版本:** `v{meta.get('version', '-')}` · "
                                f"**评分:** ⭐ `{meta['rating']}` ({meta['rating_count']:,} 条评价)"
                            )
                if fail:
                    st.warning(f"以下地区未能查找到该应用：{', '.join(fail)}（可能未在这些区域发行）")

                if st.button("✅ 确认批量添加入库并立即聚焦", type="primary", use_container_width=True, key="confirm_batch_preview_add"):
                    for cc, meta in succ.items():
                        upsert_app(
                            app_id=meta["app_id"],
                            name=meta["name"],
                            country=cc,
                            is_own_app=True,
                            subtitle=custom_subtitle.strip() or meta["subtitle"],
                            icon_url=meta["icon_url"],
                            rating=meta["rating"],
                            rating_count=meta["rating_count"],
                            version=meta.get("version", ""),
                        )
                    first_aid = list(succ.values())[0]["app_id"]
                    first_c = list(succ.keys())[0]
                    st.session_state["active_app_id"] = first_aid
                    st.session_state["active_country"] = first_c
                    st.session_state[f"pills_country_{first_aid}"] = first_c
                    st.session_state.pop("tab1_preview_results", None)
                    st.toast(f"成功为应用添加 {len(succ)} 个地区监控！")
                    st.rerun()
            else:
                st.error("所有勾选区域均未能拉取到应用信息，请检查 App ID 是否正确或已上架。")

        if do_direct_add:
            if not app_input.strip() or not selected_countries:
                st.error("请输入有效的 App ID / 链接并至少勾选一个监控地区")
            else:
                with st.spinner("正在请求 Apple 接口并批量入库..."):
                    res = batch_fetch_app_metadata(app_input, selected_countries)
                    succ = res["success"]
                    if succ:
                        for cc, meta in succ.items():
                            upsert_app(
                                app_id=meta["app_id"],
                                name=meta["name"],
                                country=cc,
                                is_own_app=True,
                                subtitle=custom_subtitle.strip() or meta["subtitle"],
                                icon_url=meta["icon_url"],
                                rating=meta["rating"],
                                rating_count=meta["rating_count"],
                                version=meta.get("version", ""),
                            )
                        first_aid = list(succ.values())[0]["app_id"]
                        first_c = list(succ.keys())[0]
                        st.session_state["active_app_id"] = first_aid
                        st.session_state["active_country"] = first_c
                        st.session_state[f"pills_country_{first_aid}"] = first_c
                        fail_msg = f"（未在 {', '.join(res['failed'])} 上架）" if res["failed"] else ""
                        st.toast(f"成功开通 {len(succ)} 个监控区域！{fail_msg}")
                        st.rerun()
                    else:
                        st.warning("所有勾选区域均未查到结果，请检查 App ID 在所选地区是否已正式上架。")

        # 手动录入兜底面板
        with st.expander("🛠️ 接口受限或需录入未上架/内测应用？点击手动添加"):
            st.caption("如因海外商店未公开或测试网络无法访问 Apple Lookup，可手动直接创建应用：")
            m_col1, m_col2 = st.columns(2)
            with m_col1:
                man_id = st.text_input("App ID (纯数字)", placeholder="例如 6809107174", key="man_id")
                man_name = st.text_input("应用全名", placeholder="例如 喂药本 - 家庭用药管理", key="man_name")
            with m_col2:
                man_cc = st.selectbox("地区代码", list(STOREFRONT_MAP.keys()), format_func=lambda c: STOREFRONT_LABELS.get(c, c), key="man_cc")
                man_sub = st.text_input("副标题", placeholder="例如 家庭用药管理", key="man_sub")
            if st.button("手动保存并加入监控", key="man_save_btn"):
                if not man_id.strip() or not man_name.strip():
                    st.error("请至少输入有效的 App ID 与应用全名")
                else:
                    clean_man_id = parse_app_id(man_id.strip())
                    upsert_app(
                        app_id=clean_man_id,
                        name=man_name.strip(),
                        country=man_cc,
                        is_own_app=True,
                        subtitle=man_sub.strip(),
                    )
                    st.session_state["active_app_id"] = clean_man_id
                    st.session_state["active_country"] = man_cc
                    st.toast(f"手动添加成功：{man_name.strip()}")
                    st.rerun()

    # --------------------------------------------------------------------------
    # 子 Tab 2：已监控应用列表与区域管理 (按 App 聚合卡片)
    # --------------------------------------------------------------------------
    with sub_tab_manage:
        total_regions_count = sum(len(a["countries"]) for a in grouped_apps)
        st.markdown(f"#### 📋 已监控应用列表（共监控 **{len(grouped_apps)}** 款主应用，涵盖 **{total_regions_count}** 个监控地区）")
        st.caption("以主应用为卡片集中管理各开通区域，支持随时为已有 App 拓展新国家、单独切换聚焦或安全移除。")

        if not grouped_apps:
            st.info("💡 当前暂无任何监控应用，请在「➕ 添加监控应用」子标签中添加您的第一款 App。")
        else:
            for g_app in grouped_apps:
                aid = g_app["app_id"]
                is_active_app = (st.session_state.get("active_app_id") == aid)
                border_color = "🌟 " if is_active_app else ""

                with st.container(border=True):
                    # 顶部：应用概要
                    t_c1, t_c2, t_c3 = st.columns([1, 4, 2])
                    with t_c1:
                        if g_app.get("icon_url"):
                            st.image(g_app["icon_url"], width=68)
                        else:
                            st.markdown("📱")
                    with t_c2:
                        st.markdown(f"### {border_color}{g_app['name']}")
                        st.caption(
                            f"**App ID:** `id{aid}` ｜ **开通地区数:** `{len(g_app['countries'])} 个` ｜ "
                            f"**全区域总词数:** `{g_app['total_keywords']} 个` ｜ **总竞品数:** `{g_app['total_competitors']} 款`"
                        )
                    with t_c3:
                        # 彻底删除整个 App 的所有地区
                        with st.popover("🗑️ 彻底删除整个 App", use_container_width=True):
                            st.error(f"⚠️ 确认彻底删除「{g_app['name']}」在所有地区的数据？")
                            st.caption(f"此操作将同时永久清空该 App 在 {', '.join(g_app['countries'])} 的全部词库与竞品！")
                            if st.button("🔥 确认永久删除全量数据", type="primary", key=f"del_entire_app_{aid}", use_container_width=True):
                                delete_app(aid)
                                if is_active_app:
                                    st.session_state.pop("active_app_id", None)
                                    st.session_state.pop("active_country", None)
                                st.toast(f"已彻底删除应用「{g_app['name']}」")
                                st.rerun()

                    st.markdown("---")
                    st.markdown("##### 🌐 该 App 已开启的监控区域明细：")

                    for r_code in g_app["countries"]:
                        r_info = g_app["regions"][r_code]
                        is_active_region = (is_active_app and st.session_state.get("active_country") == r_code)

                        rc1, rc2, rc3 = st.columns([2.5, 3, 2])
                        with rc1:
                            active_badge = "🌟 **[当前工作区]** " if is_active_region else ""
                            st.markdown(f"{active_badge}**{STOREFRONT_LABELS.get(r_code, r_code)}**")
                            st.caption(f"区域名称: {r_info['name']}")
                        with rc2:
                            st.markdown(
                                f"🔑 词数: `{r_info.get('keyword_count', 0)}` ｜ ⚔️ 竞品: `{r_info.get('competitor_count', 0)}` ｜ "
                                f"⭐ `{r_info['rating']}` ({r_info['rating_count']:,} 评价) ｜ 版本: `v{r_info.get('version') or '-'}`"
                            )
                        with rc3:
                            act_b1, act_b2 = st.columns(2)
                            with act_b1:
                                if not is_active_region:
                                    if st.button("🎯 聚焦", key=f"focus_{aid}_{r_code}", use_container_width=True):
                                        st.session_state["active_app_id"] = aid
                                        st.session_state["active_country"] = r_code
                                        st.session_state[f"pills_country_{aid}"] = r_code
                                        st.toast(f"已切换工作区为：{g_app['name']} ({r_code})")
                                        st.rerun()
                                else:
                                    st.button("✅ 已聚焦", disabled=True, key=f"focused_{aid}_{r_code}", use_container_width=True)
                            with act_b2:
                                with st.popover("🗑️ 移除", use_container_width=True):
                                    st.caption(f"确认移除该 App 在「{r_code}」区的数据？")
                                    if st.button("确认移除", type="primary", key=f"del_region_{aid}_{r_code}", use_container_width=True):
                                        delete_app(aid, r_code)
                                        if is_active_region:
                                            st.session_state.pop("active_country", None)
                                            st.session_state.pop(f"pills_country_{aid}", None)
                                        st.toast(f"已移除 {r_code} 区域数据")
                                        st.rerun()

                    # 底部：快捷为此 App 扩充新地区
                    un_countries = [c for c in STOREFRONT_MAP.keys() if c not in g_app["countries"]]
                    if un_countries:
                        with st.popover(f"➕ 为「{g_app['name']}」追加新监控地区", use_container_width=True):
                            st.caption("直接选择想要新拓展的国家/地区，免输 App ID：")
                            exp_c = st.selectbox(
                                "选择新增地区",
                                un_countries,
                                format_func=lambda c: STOREFRONT_LABELS.get(c, c),
                                key=f"card_add_c_{aid}",
                            )
                            if st.button("🚀 立即拉取并开通", type="primary", key=f"card_btn_add_{aid}"):
                                with st.spinner(f"正在从 Apple 接口拉取 {exp_c} 区数据..."):
                                    try:
                                        new_m = fetch_app_Metadata(aid, exp_c)
                                        if new_m:
                                            upsert_app(
                                                app_id=new_m["app_id"],
                                                name=new_m["name"],
                                                country=exp_c,
                                                is_own_app=True,
                                                subtitle=new_m["subtitle"],
                                                icon_url=new_m["icon_url"],
                                                rating=new_m["rating"],
                                                rating_count=new_m["rating_count"],
                                                version=new_m.get("version", ""),
                                            )
                                            st.session_state["active_app_id"] = aid
                                            st.session_state["active_country"] = exp_c
                                            st.toast(f"成功为「{g_app['name']}」开启「{exp_c}」监控！")
                                            st.rerun()
                                        else:
                                            st.warning(f"Lookup 未查找到该应用，请检查该 App 在「{exp_c}」区是否已上架。")
                                    except Exception as exc:
                                        st.error(f"拓展失败: {exc}")


    # --------------------------------------------------------------------------
    # 子 Tab 3：竞品关联管理
    # --------------------------------------------------------------------------
    with sub_tab_comp:
        st.markdown("#### ⚔️ 竞品关联绑定 (P1 · 单应用支持绑定 3~5 个竞品)")
        if not selected_app:
            st.info("请先在上方或侧边栏选择一款我方监控 App。")
        else:
            comps = list_competitors(selected_app["app_id"], selected_app["country"])
            st.caption(
                f"当前已为 **{selected_app['name']}** 在 **{STOREFRONT_LABELS.get(selected_app['country'], selected_app['country'])}** 绑定 {len(comps)}/5 款核心竞品（查词时单次请求顺便记录竞品排名）："
            )

            if comps:
                for c in comps:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([1, 4, 1.5])
                        with c1:
                            if c.get("icon_url"):
                                st.image(c["icon_url"], width=48)
                            else:
                                st.markdown("⚔️")
                        with c2:
                            st.markdown(f"**{c['name']}** (`id{c['app_id']}`)")
                            st.caption(
                                f"⭐ {c['rating']} · 评论 {c['rating_count']:,} · 版本 `{c.get('version') or '-'}`"
                            )
                        with c3:
                            with st.popover("🗑️ 移除", use_container_width=True):
                                st.caption(f"确认解除与竞品「{c['name']}」的绑定？")
                                if st.button(
                                    "确认移除",
                                    type="primary",
                                    key=f"del_comp_{c['app_id']}_{selected_app['app_id']}",
                                    use_container_width=True,
                                ):
                                    delete_competitor(selected_app["app_id"], c["app_id"], selected_app["country"])
                                    st.toast(f"已移除竞品：{c['name']}")
                                    st.rerun()
            else:
                st.info("当前尚未绑定竞品应用，您可以在下方添加 3~5 款同类竞品。")

            st.markdown("##### ➕ 添加关联竞品")
            comp_input = st.text_input(
                "输入竞品 App ID 或链接",
                key="comp_in",
                placeholder="例如 id1439876541 或粘贴竞品 App Store 链接",
            )
            if st.button("绑定关联竞品", type="primary"):
                if not comp_input.strip():
                    st.error("请输入有效的竞品 ID 或链接")
                elif len(comps) >= 5:
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
                                version=cmeta.get("version", ""),
                            )
                            st.toast(f"已成功绑定竞品：{cmeta['name']}")
                            st.rerun()
                        else:
                            st.warning(f"未查到该竞品 App ID，请确认国家/地区是否与当前监控应用一致 ({selected_app['country']})。")
                    except Exception as exc:
                        st.error(f"绑定竞品失败: {exc}")


# ==============================================================================
# 模块 2：关键词排名追踪与趋势看板
# ==============================================================================
with tab2:
    st.subheader("模块 2：关键词排名追踪与趋势看板 (Rank Tracker)")
    if not selected_app:
        st.info("请先在「模块 1」添加或选择一款监控 App。")
    else:
        app_id = selected_app["app_id"]
        country = selected_app["country"]
        competitors = list_competitors(app_id, country)
        comp_ids = [c["app_id"] for c in competitors]

        # 顶部工作区上下文与原地切区操作
        if active_grouped_app:
            t2_c1, t2_c2 = st.columns([3, 2])
            with t2_c1:
                st.markdown(
                    f"📱 **当前应用：** `{active_grouped_app['name']}` (`id{app_id}`) ｜ **区域：** `{STOREFRONT_LABELS.get(country, country)}`"
                )
            with t2_c2:
                if len(active_grouped_app["countries"]) > 1:
                    b_cols = st.columns(len(active_grouped_app["countries"]))
                    for idx, c_code in enumerate(active_grouped_app["countries"]):
                        if c_code == country:
                            b_cols[idx].button(
                                f"📍 {c_code}",
                                disabled=True,
                                key=f"t2_act_{app_id}_{c_code}",
                                use_container_width=True,
                            )
                        else:
                            if b_cols[idx].button(
                                f"切至 {c_code}",
                                key=f"t2_sw_{app_id}_{c_code}",
                                use_container_width=True,
                            ):
                                st.session_state["active_country"] = c_code
                                st.session_state[f"pills_country_{app_id}"] = c_code
                                st.rerun()


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
with tab3:
    st.subheader("模块 3：关键词挖掘与难度评估器 (Keyword Explorer)")
    if selected_app:
        st.caption(
            f"📱 当前联动监控应用：**{active_grouped_app['name']}** ｜ 默认搜索区域已自动对齐为 **{STOREFRONT_LABELS.get(selected_app['country'], selected_app['country'])}**"
        )
    seed_col, country_col = st.columns([3, 1.5])
    with seed_col:
        seed_kw = st.text_input("输入种子词（如：喂药、用药提醒、家庭药箱、记账）", value="喂药")
    with country_col:
        curr_c = selected_app["country"] if selected_app else "CN"
        all_storefronts = list(STOREFRONT_MAP.keys())
        default_cc_idx = all_storefronts.index(curr_c) if curr_c in all_storefronts else 0
        exp_country = st.selectbox(
            "目标国家 (已自动对齐)",
            all_storefronts,
            index=default_cc_idx,
            format_func=lambda c: STOREFRONT_LABELS.get(c, c),
            key=f"exp_c_{curr_c}",
        )


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
with tab4:
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

    synced_title = st.session_state.get("ai_synced_title") or (selected_app["name"] if selected_app else default_title)
    synced_sub = st.session_state.get("ai_synced_sub") or default_sub
    synced_kws = st.session_state.get("ai_synced_kws") or "喂药本，喂药记录，家庭用药，吃药提醒，宝宝喂药，家庭药箱，服药打卡，儿童用药，药品过期，退烧药，抗生素，慢病管理，处方记录，看病记录，疫苗本，身高体重，体温计，儿科，健康档案"

    in_title = st.text_input("应用标题 (App Store Connect 限制 30 字符)", value=synced_title)
    in_sub = st.text_input("应用副标题 (App Store Connect 限制 30 字符)", value=synced_sub)
    in_kws = st.text_area(
        "100 字符关键词栏（支持粘贴中文逗号 `，`、空格或换行，自动清洗并检测与标题/副标题重复词）",
        value=synced_kws,
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


# ==============================================================================
# 模块 5：AI ASO 智能分析与最终元数据推荐 Agent
# ==============================================================================
with tab5:
    st.subheader("🤖 模块 5：AI ASO 智能决策与推荐中心 (AI Recommendation Agent)")
    st.caption(
        "综合平台积累的关键词搜索热度、竞争难度、近 30 天排名爬升斜率、竞品同词差距及标题覆盖率，为您输出下一版本可直接提审的【最终推荐标题 + 副标题 + 100 字符关键词】。"
    )

    if not selected_app:
        st.info("请先在「模块 1」或左侧边栏选择一款监控 App。")
    else:
        ai_app_id = selected_app["app_id"]
        ai_country = selected_app["country"]
        ai_kw_rows = get_keyword_dashboard_rows(ai_app_id, ai_country)
        ai_comps = list_competitors(ai_app_id, ai_country)
        ai_releases = list_version_releases(ai_app_id, ai_country)
        ai_trend_map = {
            r["id"]: get_keyword_trend(r["id"], ai_app_id, days=30) for r in ai_kw_rows
        }

        with st.container(border=True):
            cfg_c1, cfg_c2 = st.columns([2, 2])
            with cfg_c1:
                engine_choice = st.radio(
                    "选择 AI 推理引擎模式",
                    [
                        "⚡ 内置量化策略 AI Agent (零成本 · 免 Key 毫秒级生成)",
                        "🧠 外部大模型 LLM Agent (OpenAI / DeepSeek / 通义千问兼容 API)",
                    ],
                    horizontal=False,
                )
                custom_focus_input = st.text_input(
                    "本次发版业务侧重点 / 补充种子词（选填）",
                    placeholder="例如：主攻宝妈人群、儿童发烧喂药场景，新增『退烧药,疫苗本』",
                )
            with cfg_c2:
                if engine_choice.startswith("🧠"):
                    llm_base_url = st.text_input(
                        "API Base URL",
                        value=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
                        placeholder="如 https://api.openai.com/v1 或 https://api.deepseek.com/v1",
                    )
                    llm_model = st.text_input(
                        "模型名称 (Model)",
                        value=os.getenv("LLM_MODEL", "deepseek-chat"),
                    )
                    llm_api_key = st.text_input(
                        "API Key",
                        value=os.getenv("LLM_API_KEY", ""),
                        type="password",
                        placeholder="sk-...",
                    )
                else:
                    llm_base_url, llm_model, llm_api_key = "", "", ""
                    st.info(
                        "💡 **内置量化策略引擎**直接基于 SQLite 中积累的 `rank_history` 趋势斜率、搜索热度、竞争难度与竞品差集计算每个词的 **ASO ROI 得分**，并按单字价值密度自动完成 30/30/100 字符最优装箱。"
                    )

            run_agent_btn = st.button(
                "🚀 基于平台积累数据生成最终 ASO 推荐方案",
                type="primary",
                use_container_width=True,
            )

        state_key = f"ai_report_v2_{ai_app_id}_{ai_country}"
        if run_agent_btn or state_key not in st.session_state:
            with st.spinner("🤖 AI Agent 正在深度分析历史排名趋势、竞品差集与字符权重分布..."):
                if engine_choice.startswith("🧠") and llm_api_key.strip():
                    report = run_llm_aso_agent(
                        app_info=selected_app,
                        keyword_rows=ai_kw_rows,
                        competitors=ai_comps,
                        releases=ai_releases,
                        trend_map=ai_trend_map,
                        api_key=llm_api_key,
                        base_url=llm_base_url,
                        model_name=llm_model,
                        custom_focus=custom_focus_input,
                    )
                else:
                    report = generate_aso_recommendations_local(
                        app_info=selected_app,
                        keyword_rows=ai_kw_rows,
                        competitors=ai_comps,
                        releases=ai_releases,
                        trend_map=ai_trend_map,
                        custom_focus=custom_focus_input,
                    )
                st.session_state[state_key] = report
                if run_agent_btn and report.get("proposals"):
                    best_p = report["proposals"][0]
                    save_ai_recommendation(
                        app_id=ai_app_id,
                        country=ai_country,
                        engine_mode=report["engine"],
                        recommended_title=best_p["title"],
                        recommended_subtitle=best_p["subtitle"],
                        recommended_keywords=best_p["keywords"],
                        summary_report="\n".join(report.get("diagnosis_bullets", [])),
                        full_json=pd.io.json.dumps(report),
                    )
                    st.toast("✅ 已生成最新 ASO 推荐方案并存入历史记录！")

        report = st.session_state[state_key]

        # 1. 核心数据诊断洞察
        st.markdown(f"#### 🔍 一、平台积累数据全局诊断 (`{report['engine']}`)")
        with st.container(border=True):
            for bullet in report.get("diagnosis_bullets", []):
                st.markdown(f"- {bullet}")

        # 2. 三大可直接发布的最终元数据方案
        st.markdown("#### 🏆 二、最终推荐 ASO 元数据方案（可直接复制提审或同步至工作台）")
        proposals = report.get("proposals", [])
        if proposals:
            p_tabs = st.tabs([p["scheme_name"] for p in proposals])
            for idx, (ptab, prop) in enumerate(zip(p_tabs, proposals)):
                with ptab:
                    st.caption(f"💡 **策略逻辑：** {prop['strategy_summary']}")
                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric(
                        "1. 推荐主标题 (限 30 字符)",
                        f"{prop['title_len']} / 30 字符",
                        f"剩余 {prop['title_remaining']} 字符",
                    )
                    mc2.metric(
                        "2. 推荐副标题 (限 30 字符)",
                        f"{prop['subtitle_len']} / 30 字符",
                        f"剩余 {prop['subtitle_remaining']} 字符",
                    )
                    mc3.metric(
                        "3. 推荐 100 字符栏 (零重复)",
                        f"{prop['keywords_len']} / 100 字符",
                        f"共覆盖 {prop['keywords_count']} 个独立高优词",
                    )

                    st.markdown("**📌 推荐应用标题 (Title):**")
                    st.code(prop["title"], language="text")
                    st.markdown("**📌 推荐应用副标题 (Subtitle):**")
                    st.code(prop["subtitle"], language="text")
                    st.markdown("**📌 推荐 100 字符关键词域 (Keywords · 已自动剔除正副标题重复词):**")
                    st.code(prop["keywords"], language="text")

                    if st.button(
                        f"✂️ 一键将「{prop['scheme_name']}」同步至模块 4 工作台微调",
                        key=f"sync_prop_{idx}_{ai_app_id}",
                        type="primary",
                    ):
                        st.session_state["ai_synced_title"] = prop["title"]
                        st.session_state["ai_synced_sub"] = prop["subtitle"]
                        st.session_state["ai_synced_kws"] = prop["keywords"]
                        st.toast("已同步至「模块 4：100 字符去重工作台」，请点击上方模块 4 标签查看！")
        else:
            st.info("💡 当前应用尚未在后台添加监控关键词。系统恪守「100% 真实数据量化」原则，不预设也不捏造任何方案。请前往上方【模块 3：拓词与难度评估】添加监控词，或在上方输入本次发版侧重点后点击生成！")

        # 3. 关键词四象限 ROI 评分与推荐归属位置表
        eval_kws = report.get("evaluated_keywords", [])
        if eval_kws:
            st.markdown("#### 📊 三、监控词库 ROI 评分与元数据位置分配明细")
            df_eval = pd.DataFrame(
                [
                    {
                        "关键词": k["keyword"],
                        "标签": k["tag"],
                        "ROI 综合得分": k["roi_score"],
                        "单字价值密度": k["char_efficiency"],
                        "热度": k["popularity"],
                        "难度分": k["difficulty"],
                        "当前状态": k["position_status"],
                        "近30天爬升": f"{k['rank_gain_30d']:+d} 名" if k["rank_gain_30d"] else "—",
                        "竞品博弈": k["comp_insight"],
                        "AI 推荐归属位置": k["recommended_slot"],
                        "AI 决策依据": k["action_reason"],
                    }
                    for k in eval_kws
                ]
            )
            st.dataframe(df_eval, use_container_width=True, hide_index=True)

        # 4. 高潜同赛道拓词补位建议与 Prompt 导出
        col_exp, col_prompt = st.columns(2)
        with col_exp:
            st.markdown("#### 💡 四、监控词库储备池（未被正副标题占用的高优词）")
            reserves = report.get("candidate_reserves", [])
            if reserves:
                st.caption("以下为您词库中未被占用至主副标题的高 ROI 词汇，已优先纳入 100 字符栏装箱：")
                for item in reserves:
                    st.markdown(f"- **{item['keyword']}** (`ROI: {item['roi_score']}` · 热度 `{item['popularity']}` / 难度 `{item['difficulty']}`) — {item['action_reason']}")
            else:
                st.caption("当前词库中所有监控词均已被高密度装配入推荐方案中；若需更多词根，可在【模块 3】添加新监控。")

        with col_prompt:
            st.markdown("#### 📋 五、导出数据包 Prompt / 历史推荐记录")
            prompt_str = build_agent_prompt_text(selected_app, eval_kws, ai_comps, custom_focus_input)
            with st.expander("查看/复制发往大模型的完整数据 Prompt", expanded=False):
                st.code(prompt_str, language="markdown")

            hist_recs = [
                hr for hr in list_ai_recommendations(ai_app_id, ai_country, limit=10)
                if "存钱" not in hr["recommended_title"] and "记账" not in hr["recommended_title"]
            ][:5]
            if hist_recs:
                st.caption(f"最近生成的有效 AI 推荐快照（共 {len(hist_recs)} 条）：")
                for hr in hist_recs:
                    st.markdown(
                        f"- `{hr['created_at']}` (**{hr['engine_mode']}**) → 标题: `{hr['recommended_title']}` | 100字符长度: `{len(hr['recommended_keywords'])}`"
                    )
