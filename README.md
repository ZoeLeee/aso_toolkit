# 个人轻量级 ASO 监控与优化工具 (V1.0 MVP)

基于产品需求文档 (PRD) 开发的零成本、轻量化个人专属 App Store ASO 监控与优化工具。

> 📖 **完整使用手册**：请参阅仓库中的详细使用文档 **[USER_GUIDE.md](./USER_GUIDE.md)**，内含系统架构、五大模块图文操作指南、以「喂药本 (id6809107174)」为例的实操迭代闭环与常见问题排错 (FAQ)。

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
5. **模块 5：AI ASO 智能决策与推荐 Agent (`ai_agent.py`)**
   - **核心输出：** 基于平台积累的关键词热度 (`popularity`)、竞争难度 (`difficulty`)、30 天历史排名爬升趋势 (`rank_history`) 与竞品同词差距 (`competitor_ranks`)，自动生成下一版本可直接提审的 **最终推荐标题（≤30 字符）、推荐副标题（≤30 字符）与 100 字符黄金关键词串（≤100 字符，零重复自动装箱）**。
   - **双引擎架构：** 内置零成本「本地量化策略 AI Agent」（计算每个词的 ASO ROI 得分与单字价值密度，输出三大发版策略方案及词库四象限诊断），同时支持接入 OpenAI / DeepSeek / 通义千问等外部大模型 API 进行深度推理。
   - **严格装箱白名单原则：** 100 字符推荐严格以开发者词库为基准，绝不随意填充未经授权的无关词，杜绝 App Store 2.3.7 拒审风险。

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

## 自动化生产部署 (Docker & GitHub Actions)

本工程支持通过 GitHub Actions 进行自动化 CI/CD 部署，流水线配置位于 `.github/workflows/deploy-server-production.yml`。

### 1. 部署架构
- **镜像仓库**: GitHub Container Registry (`ghcr.io/zoeleee/aso-toolkit`)
- **运行环境**: Linux Docker + Docker Compose，默认暴露端口 `8501`
- **数据持久化**: 映射主机目录 `~/deployments/aso-toolkit-production/data` 至容器内 `/app/data`，保障 SQLite 数据 `aso_data.db` 在更新版本时持久不丢失

### 2. GitHub Secrets 配置要求
在 GitHub 仓库中，进入 **Settings -> Environments -> production**（或 Repository Secrets），配置以下密钥：

| Secret 字段 | 必须 | 说明 | 示例 / 默认值 |
| :--- | :---: | :--- | :--- |
| `SERVER_HOST` | 是 | 生产服务器 IP 或域名 | `1.2.3.4` |
| `SERVER_USER` | 是 | SSH 登录用户名 | `root` / `ubuntu` |
| `SERVER_SSH_KEY` | 是 | 服务器 SSH 私钥 (免密登录) | `-----BEGIN OPENSSH PRIVATE KEY-----...` |
| `SERVER_PORT` | 否 | SSH 端口 | `22` (默认) |
| `GHCR_PAT` | 是 | 拥有 `read:packages` 权限的 GitHub Personal Access Token | `ghp_...` |
| `APP_SERVER_PORT`| 否 | 服务器宿主机对外映射端口 | `8501` (默认) |
| `LLM_API_KEY` | 否 | 模块 5 大模型 API Key (如 DeepSeek/OpenAI) | `sk-...` |
| `LLM_BASE_URL` | 否 | 大模型 API 基础地址 | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 否 | 大模型模型名称 | `deepseek-chat` |
| `ASO_WEBHOOK_URL`| 否 | 每日监控告警飞书/企微 Webhook 地址 | `https://open.feishu.cn/...` |

### 3. 手动触发部署
进入 GitHub 仓库页面 -> **Actions** -> **Deploy ASO Toolkit - Production** -> **Run workflow**，选择目标分支（默认 `master`）即可自动完成镜像打包、推送与远程服务器部署。

### 4. 生产环境配置每日定时爬虫
容器部署成功后，可在服务器上添加定时任务（如每日早上 8:00）：
```bash
crontab -e
# 添加以下任务 (利用 docker exec 运行容器内爬虫脚本)：
0 8 * * * docker exec aso-toolkit-production python3 cron_tracker.py --sleep 3.5
```

更多高级功能与工作流请查看 **[USER_GUIDE.md](./USER_GUIDE.md)**。
