# 参考调研 - 业界/学界/民间的资产配置流程

> 目的：为 V2「量化层（配置步骤 2）」找可借鉴的成熟流程。
> 方法：3 个并行子代理分别从①高质量论文②头部机构③中文高价值创作者三个角度调研。
> 日期：2026-06-02

---

## 🎯 核心结论：三个角度共同指向的 5 件事

> 按"几个角度同时强调"排序——越多来源汇聚，越值得优先做。

| # | 可借鉴环节 | 论文 | 机构 | 民间 | 我现状 |
|---|-----------|:----:|:----:|:----:|--------|
| 1 | **规则化再平衡纪律**（阈值/年度触发，机械执行） | ○ | ✅NBIM±2pp/Swensen/AQR | ✅张潇雨实证 | ❌ 完全没有 |
| 2 | **风险/相关性维度**（风险贡献、相关性矩阵、风险平价） | ✅ERC/Ledoit-Wolf | ✅桥水/AQR/GIC | ✅风险平价整理 | ❌ 完全没有 |
| 3 | **宏观周期/regime 前置定位**（增长×通胀四象限） | ✅Ang-Bekaert | ✅Dalio经济机器/全天候 | ✅美林时钟 | ⚠️ 隐含在LLM里，未结构化 |
| 4 | **Black-Litterman 框架**融合"大师观点"→量化权重 | ✅BL经典 | （GIC观点叠加思想） | — | ❌ 现在是直接拍倾斜 |
| 5 | **用成熟库+收缩估计+1/N基准**（工程稳健性） | ✅DeMiguel/Ledoit-Wolf | ✅AQR风险模型 | ✅Skfolio/HRP | ❌ 未涉及 |

**一句话**：头部机构的通用流程 = `风险偏好层 → SAA → TAA(带风险预算) → 规则化再平衡`，全程用**风险+相关性**而非资金比例衡量。我已有 TAA(M2/M3) 和隐含 SAA(固定比例)，**最该补：再平衡纪律、风险/相关性维度、宏观周期前置**。

---

## 📐 落到我们系统的 V2 行动建议（按性价比）

### ① 规则化再平衡层（最高性价比，先做）
- 在 M3 之后加一层：每个大类设**偏离容忍带**，超出即机械触发再平衡回目标
- 参数可直接定型：**年度 + 阈值触发（偏离目标 ±5%）**（张潇雨引用的实证：月/季/年再平衡差异不显著 → 年度即可省成本）
- 来源：NBIM ±2pp、Swensen 铁律再平衡、AQR 阈值带

### ② 风险/相关性维度（补配置的另一半本质）
- 加**大类相关性矩阵** + 滚动波动率 → 算每类资产的**真实风险贡献**，识别"假分散"（如股+高风险币高度相关）
- 给 M3 战术倾斜设**风险预算上限**
- 工程：协方差用 **Ledoit-Wolf 收缩**（`sklearn.covariance.LedoitWolf`）；组合优化优先用 **PyPortfolioOpt / Skfolio**（含 HRP 层次风险平价，对估计误差更稳）
- 来源：桥水/AQR 风险平价、ERC 论文、Ledoit-Wolf

### ③ 宏观周期前置层（强化"宏观"差异化）
- 在 M1→M2 之间插入「环境定位」：用 GDP↑↓ × CPI↑↓ 定到**美林时钟四象限**（复苏/过热/滞胀/衰退）
- 作为 4 大师评分(M2) 和倾斜(M3) 的**统一锚点 + 可解释来源**，并检查组合对各象限暴露是否平衡
- 来源：Dalio 经济机器+债务周期、桥水全天候环境矩阵、美林时钟

### ④ Black-Litterman 融合框架（让 M2→M3 更严谨）
- 把"4 大师 LLM 评分"接成 BL 的**观点向量 Q + 置信度 Ω**（评分分歧大→Ω大→倾斜小）
- 以固定大类比例反推**均衡收益 Π**(prior) → BL 融合出后验收益 → 优化得权重
- 替代现在"凭评分直接拍 ±2% 倾斜"，理论一致且天然控制极端权重
- 来源：Black-Litterman 经典

---

## 📚 附一：高质量论文（按期刊+引用加权）

> 完整 12 篇见子代理原始产出；下列为对本项目最相关的核心。

1. **Black-Litterman (1992)** · FAJ｜~4000+ 引｜把市场均衡先验与投资者观点贝叶斯融合 → **你系统的核心骨架**，大师评分=观点 Q
2. **DeMiguel, Garlappi & Uppal (2009)** · RFS｜~6000+｜14种优化模型样本外打不赢 1/N → **立基准与护栏**，优化器会放大估计误差
3. **Maillard, Roncalli & Teiletche (2010)** · JPM｜风险平价/等风险贡献(ERC) → **无收益预测时的兜底权重方案**
4. **Ang & Bekaert (2002)** · RFS｜~3000+｜regime-switching，危机时相关性飙升 → **regime 配置直接对标**，相关性非常数
5. **Fama-French 五因子 (2015)** · JFE｜~13000+｜→ 因子层配置(factor budgeting)
6. **Asness, Moskowitz & Pedersen (2013)** Value & Momentum · JF｜~5000+｜→ 跨资产价值×动量倾斜信号（二者负相关，并用更稳）
7. **Moskowitz, Ooi & Pedersen (2012)** 时间序列动量 · JFE｜~3000+｜→ 最易落地的 risk-on/off 择时 + 波动率目标定仓
8. **Ledoit & Wolf (2004)** 协方差收缩｜~4000+｜→ 优化前必做的工程步骤，解决 Σ 不稳

## 🏛 附二：头部机构流程

- **桥水 All Weather**：Alpha/Beta 分离 + 增长×通胀4环境矩阵 + 按风险贡献配置(不按资金) + 温和杠杆 + "balance not predict"
- **NBIM 挪威主权基金**：固定 70/30 基准 + 跟踪误差约束偏离 + **±2pp 阈值规则化再平衡（事先公开、机械执行）**
- **GIC 新加坡**：三层解耦 Reference(风险偏好)→Policy(SAA)→Active(战术,借风险预算) + "prepare not predict"
- **AQR**：波动率预测 + 相关性建模 + 均衡风险贡献 + 适度杠杆 + 再平衡成本意识（不必高频）
- **耶鲁/Swensen**：深度分散(另类) + 长期假设SAA + **再平衡作为收益来源**(逆向高抛低吸)
- **Dalio**：经济机器三力模型(生产率+短/长债务周期) + 周期定位驱动配置

## 📱 附三：中文高价值创作者（精选）

> ⚠️ 诚实声明：WebSearch 为美国区，**小红书原生笔记完全无法访问、B站配置方法论类未找到可验证高互动内容**（B站强在量化代码实操、弱在配置方法论）。下列以**可验证的方法论实质**为准，互动量为估计。建议你登录境内账号自行核实小红书/B站。

1. **ETF拯救世界(E大)/长赢计划** · 雪球微博｜估值分位驱动加减仓 + 公开实盘规则化网格 → 战术倾斜的量化触发器范本
2. **张潇雨《个人投资课》** · 得到｜永久组合/全天候/斯文森组合**现成清单** + 再平衡实证(年度即可) → 你已在读(Finance.md)
3. **银行螺丝钉** · 雪球｜指数估值表三档(低估/正常/高估)，可量化可自动化的打分流程
4. **孟岩/有知有行** · 播客App｜"四笔钱"按用途+期限分层 → 固定比例之上的顶层框架
5. **知乎「Python组合优化实战」** · 三步法求有效前沿 + **Skfolio 库**(含HRP) → 量化层工程脚手架
6. **知乎「美林时钟+风险平价整理」** · 四象限轮动规则表 + 风险平价因子框架

---

## 🔗 与 PRD 的关系

本调研支撑 [PRD.md](../PRD.md) 「十、版本路线图」的 **V2 量化层**。V2 优先级建议落地顺序：**① 再平衡纪律 → ② 风险/相关性维度 → ③ 宏观周期前置 → ④ Black-Litterman 融合**（从低成本高确定性，到高价值高难度）。

---

# 选基模块调研（券商分析师角色）

> 目的：为 [PRD.md](../PRD.md)「十一、选基模块」找"最合适基金"的可量化打分方法。
> 方法：3 个并行子代理分别从①学术论文②开源/机构③中文社区三角度调研。
> 日期：2026-06-04（分支 `feat/fund-selector`）

## 三角度共同指向的结论（越多来源汇聚越优先）

1. **被动主题工具(ETF/指数基金)选基，权重排序：成本(费率) + 跟踪(TD/TE) + 流动性 > 风险调整收益 > 历史裸收益。** 三方一致（Sharpe1966/Carhart1997/Frino-Gallagher；蚂蚁金选硬标准；中国基金报实操）。
2. **历史收益排名：顶部无持续性、底部有持续性 → 用来"避雷"不"追星"。** Carhart(1997) 决定性结论，社区/机构均印证。
3. **打分方法首选「同类百分位排名」(晨星 MRAR/夏普) 而非拍脑袋加权**——鲁棒、无权重玄学。细分主题候选池小→退化为"夏普+最大回撤"双指标决胜。
4. **费率是文献中最稳健的未来业绩预测器**，且对长期复利是确定性损耗。
5. **QDII(美股低波/石油)必须额外盯：折溢价(>2%提示/>5%排除) + 是否暂停申购 + 汇率/展期成本**——这些让"跟同一指数"的基金实际收益差很大。
6. **数据可得性几乎无障碍**：akshare 覆盖净值/费率/规模/排名/ETF折价/QDII折溢价/看穿持仓/评级；`fund_individual_analysis_xq` 甚至预置近1/3/5年夏普/最大回撤/年化波动。难自动化：晨星星级&风格箱(无API)、蚂蚁金选、跟踪误差(需爬天天基金F10页)。

## 各角度要点 + 来源

**① 学术论文**：风险调整收益(夏普/Jensen α/信息比率/Sortino/Calmar)、回撤、费率、规模双向阈值(规模不经济 vs 清盘)、指数基金特有的**跟踪误差TE(复制稳定性) + 跟踪差异TD(系统性落后,长期持有更关键)**；合成法 DEA(无需预设权重)/TOPSIS/晨星MRAR。
- [Carhart 1997 业绩持续性](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1997.tb03808.x)｜[Sharpe1966/Jensen1968 综述](https://leeds-faculty.colorado.edu/bhagat/Evaluating-MFunds.pdf)｜[Frino-Gallagher 跟踪误差](https://digitalcommons.csbsju.edu/cgi/viewcontent.cgi?article=1006&context=acct_pubs)｜[Basso-Funari DEA选基](https://www.sciencedirect.com/science/article/abs/pii/S0377221700003118)

**② 开源/机构**：晨星 MRAR(γ=2)+同类百分位切五星(10/22.5/35/22.5/10,满3年)；银河三类指标(收益/风险/风险调整)；开源最贴合的是 piginzoo/fund_analysis(硬过滤规模≥10亿/类型/经理在任 → 夏普排序 → α辅助)。
- [piginzoo/fund_analysis](https://github.com/piginzoo/fund_analysis)｜[xalpha ~2.5k★](https://github.com/refraction-ray/xalpha)｜[晨星评级方法](https://www.morningstar.cn/help/data/fundrating.html)｜[基金业协会评价入口](https://www.amac.org.cn/fwdt/wyc/jjpjcx/)｜[akshare 公募数据](https://akshare.akfamily.xyz/data/fund/fund_public.html)

**③ 中文社区/平台**：散户ETF硬规则——规模>2亿(防清盘)、日均成交>1000万、跟踪误差<0.5%、费率≤0.6%、成立>3年；蚂蚁金选指数基金硬标准(跟踪误差宽基≤1.5%/行业≤2%)；晨星风格箱(市值×价值成长 看真实风格)；QDII折溢价经验线 2%/5%。
- [中国基金报-同标的多只ETF怎么选](https://www.chnfund.com/article/AR2024032617555547920470)｜[晨星风格箱](https://www.morningstar.cn/help/data/fundstylebox.html)｜[QDII折溢价注意](https://www.yanglee.com/Information/Details.aspx?i=131627)｜[akshare QDII折溢价(qdii_e_comm_jsl 等)](https://akshare.akfamily.xyz/data/qdii/qdii.html)

## 🔗 与 PRD 的关系

支撑 [PRD.md](../PRD.md)「十一、选基模块」。收敛出的打分模型 MVP（硬过滤门槛 + 分组百分位打分 + 数据源映射）已写入 PRD。

---

# M2 四大师 Persona 多智能体调研（外部依据）

> 目的：为 M2「4 位投资大师 persona 各打分 + Moderator 综合」的设计找外部佐证——这套做法是否可行、有无成熟先例。
> 方法：3 个并行子代理（论文 / 开源·企业 / 中文社区）。日期：2026-06-08。

## 🎯 核心结论

**范式成熟且是当前热点（GitHub 两旗舰合计 14 万+ star），我们的做法有大量同行先例、可行；但成熟度=「研究/教育成熟、实盘不成熟」，学术上对其有效性有同等量级质疑 → 应定位为决策辅助/想法生成器，而非可信赚钱引擎**（本项目正是此定位：M3 产出是建议、需人工 review）。

## 真实项目例子（开源，按 star 实测排序，2026-06）

| 项目 | ⭐ | 与本项目相似度 | 架构 |
|---|---|---|---|
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | ~60k | **几乎同构** | 13+ 投资人 persona agent（巴菲特/芒格/Graham/Ackman/Cathie Wood/Burry/Taleb 风险/Druckenmiller 宏观/Damodaran 估值…）→ Risk Manager → **Portfolio Manager 综合（=我们的 Moderator）**。**无现成达利欧/马克斯/索罗斯**（Druckenmiller 近似索罗斯式宏观）→ 我们的大师阵容是自有特色 |
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | ~84k | 范式同、分工不同 | 按**职能角色**（基本面/情绪/新闻/技术分析师 + **多空研究员辩论** + 交易员 + 风控 + PM），核心是辩论而非打分。论文 [arXiv:2412.20138](https://arxiv.org/abs/2412.20138) |
| [hsliuping/TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) | — | 中文化 | 接入 Tushare/AkShare 适配 A股/港股，支持国产模型 |
| [24mlight/A_Share_investment_Agent](https://github.com/24mlight/A_Share_investment_Agent) | — | A股原创 | 分析师→多空辩论室→风控→组合经理 |

## 学术：支持 vs 质疑

**支持（实证）**：
- 多智能体辩论提升推理/减少幻觉 — [Du et al. 2023, arXiv:2305.14325](https://arxiv.org/abs/2305.14325)
- persona+记忆产生可信角色 — [Generative Agents, arXiv:2304.03442](https://arxiv.org/abs/2304.03442)
- 金融多智能体正向回测 — [FinMem, arXiv:2311.13743](https://arxiv.org/abs/2311.13743)、TradingAgents

**质疑（同样实证，更该警惕）**：
- **Persona collapse**：不同人设群体仍趋同，"分歧"可能是表演性
- **CoT 是事后合理化** — [Turpin et al., arXiv:2305.04388](https://arxiv.org/abs/2305.04388) → **别信 persona 自报逻辑做归因**
- **Moderator/judge 位置偏差** — [arXiv:2406.07791](https://arxiv.org/abs/2406.07791)
- **回测前视/记忆污染** — [Glasserman-Lin, arXiv:2309.17322](https://arxiv.org/abs/2309.17322)；[Memorization Problem, arXiv:2504.14765](https://arxiv.org/html/2504.14765)
> 另有结论方向吻合但 arXiv 编号疑似未来日期(2604.x persona collapse / single-agent vs multi-agent)的文章，**标为待二次核验**，未当主证据。

## ✅ 本项目已踩对的最佳实践 / ⚠️ 该补的

**已做对**：
- self-consistency 中位数投票(3次/temp0.2) → 治"temperature 随机、不可复现"坑
- Moderator 用异构模型(deepseek-reasoner vs persona 的 deepseek-chat) → 部分缓解 judge 自偏好
- 季度运行 + 人工 review → 避开 TradingAgents"每决策 11 次 LLM 调用"成本失控、符合"辅助非自动交易"
- 风格来源靠 RBSA 数据不靠名字 → 避开 LLM 幻觉污染量化层

**该补**：
1. 量化 persona 打分**离散度**：发散/趋同显式标注；离散度过低=可能表演性趋同，Moderator 别给极端分
2. persona 的 reason **只当方向票**、不做因果归因（现状已如此，保持）
3. 回测做 **out-of-sample / 前视审计**（回测期在模型知识截止之后）

## 中文社区主流看法

- **正面**：框架/工程价值认可，多空辩论避免单视角偏差，小样本实盘尚可（[6个AI炒股半年多数跑赢大盘](https://m.aitntnews.com/newDetail.html?newId=23798)）
- **质疑**：[「Agent 能复刻投资哲学，不复刻投资结果」](https://www.qbitai.com/2026/04/400350.html)；alpha 衰减、低信噪比过拟合、预测不了拐点（[大模型炒股靠谱吗](https://www.tmtpost.com/7676605.html)）。最实在中文复盘：[知乎 ai-hedge-fund A股实测](https://zhuanlan.zhihu.com/p/2027098910850658391)（收益/回撤/改造踩坑）

## 🔗 与设计的关系

支撑 M2（`m2_analysis/`，4 大师 persona + Moderator）。结论：范式可行、有成熟同行（ai-hedge-fund 即 13-persona 版），本项目已规避多个公认坑；剩余风险（persona 趋同/归因不可信/回测污染）靠"当辅助 + 人工 review + 数据化量化层"兜底。

---

# 个股选择层调研（卫星仓·应用金融 skills）

> 用户收藏的 11 篇中文资料（10 公众号 + 1 小红书，2026-06-15 经 OpenCLI 真实 Chrome 读取）。支撑 PRD 第十二章 12.1 个股选择层。设计见 `docs/superpowers/specs/2026-06-15-stock-selector-design.md`。

## 🎯 核心收敛洞察

11 篇高度收敛于一点：**把"选股方法论"封装成 `SKILL.md`(Agent Skills 标准)，让 AI 照着执行**。Anthropic 官方库、中金分析师蒸馏、量化策略自进化、himself65、Serenity 系列——全是这套。且共守一条铁律 **"AI drafts, humans sign off"**(AI 起草、人签字)，与本项目"输出建议、人在回路"完全一致。

## 📚 5 类来源

**A. Anthropic 官方金融库（5 篇）** — `github.com/anthropics/financial-services`(16.9k⭐)：10 端到端 Agent + 7~9 垂直 Skill 包(含 **equity-research**：财报笔记/首次覆盖/模型更新) + 11 个 MCP 数据源(Morningstar/S&P/FactSet/Moody's/Daloopa/LSEG/PitchBook…多需付费)。两种部署(Cowork 交互 / Managed API 批跑)。
- [二星讲AI·SOP被公开](https://mp.weixin.qq.com/s/z5cPreA2pGL2lTv3uQblew) ｜ [深度拆解16.9k⭐](https://mp.weixin.qq.com/s/w1qPgYteUA5jedYlA6bwpQ) ｜ [中文全解·10agent/9插件](https://mp.weixin.qq.com/s/w-4hoSO-j0Uy_uw2KcwkEw) ｜ [11数据源MCP端点](https://mp.weixin.qq.com/s/eSoXVeWedNFpWCioio0_rg) ｜ 小红书同主题

**B. 券商分析师 Skill 蒸馏（1 篇）** — 中金「老于」把首席 30 万字研报蒸馏成 SKILL.md，框架 **假设验证→盈利预测(底中顶三情景)→估值锚定(历史中枢±行业溢价)→风险清单(≥3条可证伪)**。东财/国君/广发/国信都在做。→ 本设计评估层"分析师四步法"直接取自此。
- [中金老于·分析师Skill](https://mp.weixin.qq.com/s/-yh-MNukPx3NLJYZr6m44Q)

**C. 量化策略自进化（1 篇）** — AutoResearch：选股逻辑写进 Skill(策略内核/因子边界/组合约束/迭代边界/评价体系)，**训练/验证/测试集隔离防过拟合**。稳健低波价值策略 13.47%→15.67% 年化、夏普 0.69→0.89。
- [AutoResearch选股自进化](https://mp.weixin.qq.com/s/5ERIAdoHCmu1JhzA0Me5yQ)

**D. 开源量化工具栈（2 篇）** — OpenBB(免费彭博)/qlib(微软)/Lean/Backtrader/Riskfolio-Lib/yfinance/FinanceToolkit/vectorbt；himself65 `finance-skills`(20 技能：earnings-preview/recap、etf-premium、options-payoff、**sepa-strategy**[Minervini]、stock-correlation、stock-liquidity，底层 yfinance)。⚠️ 多基于 yfinance(美股友好、A 股弱)，本项目 A 股用 akshare。
- [Thea·10个开源金融工具](https://mp.weixin.qq.com/s/ald970zsyAYrctYRCaWK_Q) ｜ [himself65·20金融skill](https://mp.weixin.qq.com/s/suEXbqcamVUvZKszBbFUMg)

**E. 产业链选股法 / AI 实盘（2 篇）** — Serenity「白毛股神」**产业链五步法**：系统变化→拆产业链→锁稀缺环节→找未覆盖公司→证伪(WindClaw 做成数字人+Skill)；另一篇 Gate.io 模拟盘 AI 交易实践。→ 本设计发现层产业链召回取自此(仅借通用框架，不复用网红本人/不抄产品)。
- [WindClaw×Serenity产业链选股](https://mp.weixin.qq.com/s/L2ZDdYEfOa2jMAB0Lz6vyw) ｜ [Gate.io模拟盘AI交易](https://mp.weixin.qq.com/s/CxnfmTxfnOD0h2fFFqt5FQ)

## 🔗 与设计的关系

支撑个股选择层(`stock_selector/`)。结论：①"方法论 Skill 化"是行业共识，本设计走方案 B(SKILL.md 编排)；②可复用方法论 = 产业链五步(发现层) + 分析师四步法(评估层)；③工具/数据多基于 yfinance(美股)，本项目 A 股用 akshare、留抽象层扩美股；④付费数据源(Morningstar/S&P)先不接。⚠️ 注意 Serenity 类网红法有幸存者偏差，本设计用多源印证 + 数据铁律 + 证伪检查兜底。
