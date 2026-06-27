# M2 分析模块

**职责**：把 M1 的资讯转化为结构化"方向观点"。

## 输入
- `outputs/raw_news.json`（M1 输出）
- `config/holdings.yaml`（当前持仓上下文）

## 输出
- `outputs/directions.json`

```json
{
  "directions": {
    "AI": { "view": "overweight", "strength": 2, "reason": "..." }
  },
  "regions": {
    "US": { "view": "overweight", "strength": 1 }
  },
  "commodities": {
    "gold": { "view": "overweight", "strength": 2 },
    "oil":  { "view": "neutral", "strength": 0 },
    "broad":{ "view": "neutral", "strength": 0 }
  }
}
```

评分尺度：`-2`极度看空 ~ `+2`极度看好

## 选型（决策2、3、6）
- 4 位大师 Persona：达利欧 / 霍华德·马克斯 / 巴菲特 / 索罗斯
- **并行**调用（背对背独立观点）→ Moderator 综合
- V1 不加置信度过滤

## 待实现（Day 3~4）
- [ ] 4 个大师 Persona prompt
- [ ] Moderator 综合 prompt
- [ ] 并行调用 Claude + 输出 directions.json
- 参考：AI Hedge Fund / TradingAgents-CN 的 prompt 模板
