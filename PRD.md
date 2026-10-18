# **个人轻量级 ASO 监控与优化工具 — 产品需求文档 (PRD)**

| 文档版本 | V1.0 (MVP 个人独立开发版) | 适用对象 | 个人开发者 / 独立工作室 |
| :---- | :---- | :---- | :---- |
| **核心目标** | 零成本实现关键词排名每日追踪、拓词挖掘与 100 字符去重组装 | **预算成本** | **0 元**（本地运行 / 免费云服务 \+ 官方免费接口） |
| **建议形态** | 本地 Web 看板（Python \+ Streamlit）或 桌面端小工具 | **数据范围** | 支持多国家/地区（Storefront），单日监控 50\~500 个词 |

## **一、 产品背景与核心痛点**

市面上商业 ASO 工具（如 SensorTower、七麦、AppRadar、Astro 等）动辄每年数千元的订阅费，对于个人开发者成本过高；而手动在手机上搜索查排名不仅耗时，还无法记录历史趋势。  
本项目旨在构建一套**零成本、自动化、轻量化**的个人专属 ASO 工具，解决以下三个核心问题：

> 1. **监控难：** 每天自动记录自己的 App 在核心词下的排名涨跌，验证发版更新后的 ASO 效果。  
> 2. **拓词难：** 快速批量拉取苹果搜索框的下拉联想词（Hints），并评估该词的攻克难度。  
> 3. **组词繁琐：** 辅助编写 App Store Connect 后台的“100 字符关键词栏”，自动去重并统计剩余字符。

## **二、 核心业务流程与功能模块**

### **模块 1：应用与竞品管理 (App Management)**

用于绑定自己的 App 和重点关注的竞品 App，支持按国家/地区隔离数据。

| 功能点 | 优先级 | 详细需求描述 |
| :---- | :---- | :---- |
| **添加监控 App** | **P0** | 输入 App Store 链接或 App ID (trackId) 及国家代码（如 CN、US、JP），自动调用 Lookup 接口拉取应用图标、名称、副标题、当前评分及评论总数。 |
| **竞品关联绑定** | **P1** | 在我方 App 下可绑定 3\~5 个核心竞品 App ID。查询某个关键词排名时，顺便把同处于前 200 名内的竞品排名一并记录下来，无需二次发起网络请求。 |

### **模块 2：关键词排名追踪与趋势看板 (Rank Tracker)**

工具最核心的日常监控模块，支持手动刷新与每日定时静默更新。

| 功能点 | 优先级 | 详细需求描述 |
| :---- | :---- | :---- |
| **关键词词库管理** | **P0** | 支持按 (App ID \+ 国家) 批量导入/添加关注的关键词（支持标签分类，如“品牌词”、“核心词”、“竞品词”）。 |
| **实时排名抓取** | **P0** | 请求苹果搜索接口（拉取 Top 200 结果），精准匹配我方 App ID 所在位置： • 若在前 200 名内，记录具体名次（1\~200）； • 若未出现，记为 \>200（未入榜）； • 同时记录该词返回的结果总数及排名前 3 的应用名称。 |
| **排名升降对比** | **P0** | 列表展示：关键词、今日排名、较昨日变化 (↑/↓)、历史最高排名、更新时间。 |
| **历史趋势折线图** | **P1** | 点击任意关键词，弹出近 30 天/90 天的排名变化折线图（Y 轴倒序，第 1 名在最上方）。支持在时间轴上标记“版本发布日”，直观看出更新元数据后的排名变化。 |

### **模块 3：关键词挖掘与难度评估器 (Keyword Explorer)**

在准备发版更新标题、副标题和 100 字符时，用于寻找“高流量、低竞争”的黄金词。

| 功能点 | 优先级 | 详细需求描述 |
| :---- | :---- | :---- |
| **下拉联想词挖掘** | **P0** | 输入一个种子词（如“记账”），调用苹果客户端 MZSearchHints 接口，一键列出苹果官方推荐的前 10 个下拉联想词及其官方优先级分数（Priority）。支持一键将好词加入监控列表。 |
| **关键词热度接入** | **P1** | *(可选接入)* 通过 Apple Ads API 获取关键词的官方流行度（Search Popularity，5\~100 分）。若初期不接 API，支持手动录入或以联想词 Priority 替代参考。 |
| **自研竞争度评分** | **P1** | 自动提取该词下排名前 10 的 App 数据，计算**攻克难度分 (1\~100)**： • **标题完全匹配率：** 前 10 名中有几个 App 标题/副标题包含该词； • **头部统治力：** 前 10 名 App 的平均评论数与平均星级。 *(评论越少、标题未匹配越多，说明该词越容易排进前十)* |

### **模块 4：100 字符组装工作台 (100-Char Optimizer)**

发版前的实操辅助工具，避免字符浪费与重复。

| 功能点 | 优先级 | 详细需求描述 |
| :---- | :---- | :---- |
| **实时字符计数器** | **P0** | 模拟苹果后台规则：输入标题（限 30 字符）、副标题（限 30 字符）、关键词域（限 100 字符），实时显示剩余可用字符数。 |
| **智能清洗与去重** | **P1** | 1\. 自动将中文逗号 ， 及空格替换为英文半角逗号 ,； 2\. 自动检测 100 字符中是否重复包含了“标题”或“副标题”里已有的词，并高亮提示剔除（苹果算法默认收录标题词，重复填写浪费额度）。 |

## **三、 数据源与接口技术规范**

个人使用无需购买任何商业代理，直接通过本地网络 \+ 请求限速（Rate Limiting）即可稳定运行：

> 1. **应用详情查询 (Lookup API)**  
   * **Endpoint:** \[https\://itunes.apple.com/lookup?id=\](https\://itunes.apple.com/lookup?id=){app\_id}\&country={country\_code}  
   * **用途：** 获取 App 图标、当前版本、评分、评论总数。  
> 2. **关键词排名查询 (Search API / Storefront API)**  
   * **公开版 (快速开发):** \[https\://itunes.apple.com/search?term=\](https\://itunes.apple.com/search?term=){keyword}\&country={country\_code}\&entity=software\&limit=200  
   * **高精版 (模拟真机):** 请求客户端接口并携带 Header X-Apple-Store-Front: {storefront\_id}（例如中国区为 143465-19,29，美国区为 143441-1,29），结果与 iPhone 真机搜索 100% 一致。  
> 3. **搜索下拉联想词 (Hints API)**  
   * **Endpoint:** \[https\://search.itunes.apple.com/WebObjects/MZSearchHints.woa/wa/hints?clientApplication=Software\&term=\](https\://search.itunes.apple.com/WebObjects/MZSearchHints.woa/wa/hints?clientApplication=Software\&term=){keyword}  
   * **Header:** 需携带对应国家的 X-Apple-Store-Front，返回 XML/Plist 格式的联想词列表及权重。  
> 4. **防封禁限流策略 (关键)**  
   * 苹果对单 IP 的公开请求限制约为 **20 次/分钟**。  
   * **策略：** 在后台抓取循环中强制加入 time.sleep(3.5)（每次请求间隔 3.5 秒）。以监控 100 个关键词为例，每天只需耗时约 6 分钟即可全部更新完毕，完全不会触发 IP 封禁。

## **四、 数据库表结构设计 (SQLite)**

个人使用推荐直接采用单文件数据库 **SQLite**，无需额外部署数据库服务，备份只需复制一个 .db 文件。

SQL  
\-- 1\. 监控应用表  
CREATE TABLE apps (  
    app\_id VARCHAR(32) PRIMARY KEY,      \-- 苹果 trackId，如 '123456789'  
    name VARCHAR(128) NOT NULL,          \-- 应用名称  
    country VARCHAR(8) NOT NULL,         \-- 国家代码，如 'CN', 'US'  
    is\_own\_app BOOLEAN DEFAULT 1,        \-- 1: 自己的App, 0: 竞品App  
    icon\_url TEXT,  
    created\_at DATETIME DEFAULT CURRENT\_TIMESTAMP  
);

\-- 2\. 关注关键词表  
CREATE TABLE keywords (  
    id INTEGER PRIMARY KEY AUTOINCREMENT,  
    app\_id VARCHAR(32) NOT NULL,  
    country VARCHAR(8) NOT NULL,  
    keyword VARCHAR(64) NOT NULL,  
    popularity INTEGER DEFAULT 5,        \-- 搜索热度 (5-100)  
    difficulty FLOAT DEFAULT 0,          \-- 估算竞争难度 (0-100)  
    tag VARCHAR(32),                     \-- 分组标签，如 '核心词'  
    UNIQUE(app\_id, country, keyword)  
);

\-- 3\. 每日排名快照表 (核心时序数据)  
CREATE TABLE rank\_history (  
    id INTEGER PRIMARY KEY AUTOINCREMENT,  
    keyword\_id INTEGER NOT NULL,  
    app\_id VARCHAR(32) NOT NULL,  
    rank INTEGER,                        \-- 1\~200，未入榜存 NULL 或 201  
    top3\_apps TEXT,                      \-- JSON存当前前3名App名称，方便复盘  
    rating\_count INTEGER,                \-- 当日App总评论数（结合看评论增长）  
    record\_date DATE NOT NULL,           \-- 记录日期 YYYY-MM-DD  
    UNIQUE(keyword\_id, app\_id, record\_date)  
);

## **五、 技术栈与分阶段开发路线图 (Roadmap)**

为了让你用最少的代码量最快用起来，推荐采用 **Python 全栈方案**（无需写复杂的前端 HTML/React）：

* **推荐技术栈：** Python 3.10+ \+ Requests (网络请求) \+ SQLite3 (本地存储) \+ Streamlit (几行代码直接生成交互式 Web 看板与折线图)。

### **阶段一：命令行脚本跑通数据（预计耗时：0.5 天）**

* 编写核心爬虫函数：输入 App ID、国家代码和一组关键词，在终端打印出当前排名和下拉联想词。  
* 验证 X-Apple-Store-Front 请求头在目标国家的准确性。

### **阶段二：数据库落盘与可视化看板（预计耗时：1\~2 天）**

* 建立 SQLite 表结构，将每天查询的结果存入 rank\_history 表。  
* 使用 Streamlit 搭建本地网页界面：左边栏切换 App 和国家，主界面展示关键词排名表格（带红绿涨跌箭头）和点击展开的历史趋势图。

### **阶段三：自动化与进阶功能（预计耗时：1 天）**

* 配置系统定时任务（Mac 使用 crontab 或 launchd，Windows 使用任务计划程序，或直接放在免费 GitHub Actions 中定时运行），每天早上 8 点自动拉取最新排名。  
* 加入“100 字符去重检测器”与“Top 10 竞品难度评分算法”，并在排名暴跌时发送飞书/微信/邮件通知。

这份需求文档已经把个人 MVP 的范围收敛到了最实用、零成本的状态。你可以告诉我你平时最顺手的编程语言（比如 Python、Node.js 或 Swift），我们可以直接开始写**阶段一的核心数据抓取脚本**，或者先对上面的某个功能模块做增删调整？

### **模块 5：AI ASO 智能决策与推荐 Agent (AI Recommendation Center)**
基于平台长期积累的监控数据，闭环输出最终可直接用于 App Store Connect 发版更新的元数据方案。
| 功能点 | 优先级 | 详细需求描述 |
| :- | :- | :- |
| **多维数据聚合与 ROI 评分** | **P0** | 综合每个关键词的搜索热度、攻克难度、近 30 天排名爬升斜率、当前卡位（重点识别 #4~#20 临门一脚冲刺词）及竞品同词排名差距，计算综合 ASO ROI 得分与单字价值密度。 |
| **三大发版元数据方案生成** | **P0** | 自动生成 3 套差异化方案（黄金平衡首推方案 / 激进冲榜抢量方案 / 蓝海长尾垄断方案），每套方案均包含严格符合字符限制且零重复冲突的 **推荐标题 (≤30字符)**、**推荐副标题 (≤30字符)** 与 **推荐 100 字符关键词串 (≤100字符)**，支持一键同步至 100 字符工作台。 |
| **双引擎 AI Agent 架构** | **P1** | 默认提供零成本免 Key 的「本地量化策略 AI Agent」，同时支持接入 OpenAI / DeepSeek / 通义千问等兼容 API 进行大模型深度推理，并将历史推荐快照落盘至 `ai_recommendations` 表。 |
