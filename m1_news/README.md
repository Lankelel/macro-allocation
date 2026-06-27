# M1 资讯模块

**职责**：采集全球资讯，按 6 大方向归类整理（不做判断）。

## 输入
- `config/settings.yaml` 的 `directions`（6 大方向）
- Horizon 生成的日报/简报

## 输出
- `outputs/raw_news.json`

```json
{
  "timestamp": "2026-Q2",
  "macro_indicators": { "US_CPI": null, "CN_PMI": null, "Fed_rate": null },
  "news_by_direction": {
    "AI": [], "energy": [], "medical": [],
    "military": [], "consumer": [], "finance": []
  },
  "geo_events": []
}
```

## 选型（决策1）
- **Horizon**（`Thysrael/Horizon`）：AI 新闻雷达，中英双语日报
- daily_stock_analysis 留作 V2 个股分析层参考

## 待实现（Day 2）
- [ ] 部署/订阅 Horizon
- [ ] 配置 6 大方向关键词
- [ ] 把 Horizon 输出解析成 raw_news.json
