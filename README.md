# 个人轻量级 ASO 监控与优化工具 (V1.0 MVP)

基于产品需求文档 (PRD) 开发的零成本、轻量化个人专属 App Store ASO 监控与优化工具。

## 核心功能模块
1. **模块 1：应用与竞品管理 (`apple_api.py` + `db.py`)**
   - 输入 App Store 链接或 `trackId` 及国家代码（`CN` / `US` / `JP` 等），调用 Apple Lookup 接口自动拉取图标、名称、副标题、评分及评论总数。
   - 支持在主应用下绑定 3~5 个核心竞品 App ID；查询某个关键词排名时，单次请求同时记录我方与前 200 名内所有关联竞品的排名，无需二次请求。
2. **模块 2：关键词排名追踪与趋势看板 (`app.py` + `cron_tracker.py`)**
   - 支持按 `(App ID + 国家)` 批量导入关键词并打标签（品牌词、核心词、竞品词、长尾词）。
   - 携带对应国家 `X-Apple-Store-Front` 请求头模拟 iPhone 真机搜索，展示今日排名、较昨日涨跌 (`↑`/`↓`)、历史最高排名、前 3 名应用及竞品同词对比。
   - 提供 **Y 轴倒序**（第 1 名在最上方）的近 30 天 / 90 天排名折线图，并支持标记 **版本发布日**。
3. **模块 3：关键词挖掘与难度评估器 (`apple_api.py`)**
   - 调用苹果客户端 `MZSearchHints` 接口拉取官方下拉联想词及 `Priority` 权重分数，支持一键加入监控词库。
   - 自研竞争度评分算法（1~100 分）：基于前 10 名 App 的 **标题完全匹配率** 与 **头部统治力（平均评论数 + 平均星级）** 自动测算攻克难度。
4. **模块 4：100 字符组装工作台 (`optimizer.py`)**
   - 模拟 App Store Connect 规则：标题（30 字符）、副标题（30 字符）、关键词域（100 字符）实时计数。
   - 自动将中文逗号 `，`、空格及换行转为英文半角逗号 `,`，自动检测并高亮剔除与标题/副标题重复的词根。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 初始化演示数据库 (可选，已预置开箱即用示例数据 aso_data.db)
python3 seed_demo.py

# 3. 启动 Streamlit 交互式 Web 看板
streamlit run app.py

# 4. 配置每日早上 8:00 定时静默更新 (crontab -e)
# 0 8 * * * /usr/bin/python3 /path/to/cron_tracker.py --sleep 3.5 --webhook "https://open.feishu.cn/..."
```
