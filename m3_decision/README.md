# M3 决策模块

**职责**：把"方向观点"映射到具体二级权重。

## 输入
- `outputs/directions.json`（M2 输出）
- `config/holdings.yaml`（SAA 锚 + 当前持仓）
- `config/settings.yaml`（步长、上限）

## 输出
- `outputs/allocations.md`（人工 review 后追加到 Finance.md）

## 方法：Tactical Tilting + Equal Weight Baseline

```
Step 1  等权基准：每个 sleeve 内部先平均分
Step 2  评分调整：每 +1 评分 → 权重 +2%（step_per_score）
Step 3  守恒约束：sleeve 总额保持不变（从中性品种均匀扣减）
Step 4  边界约束：单次 ≤5% / 累计偏离 ≤10% / 单只 ≤10%
```

## 参数（决策4、5）
- `step_per_score = 0.02`（2%）
- `max_deviation = 0.10`（10%）

## 示例：商品 sleeve（15%）
| 品种 | 等权基准 | 评分 | 调整 | 最终 |
|------|---------|------|------|------|
| 黄金 | 5% | +2 | +4% | 9% |
| 综合 | 5% | 0 | -2% | 3% |
| 石油 | 5% | 0 | -2% | 3% |

## 待实现（Day 5）
- [ ] 等权基准计算
- [ ] 评分 → 调整量映射
- [ ] 守恒 + 边界约束
- [ ] 用当前持仓手算验证
