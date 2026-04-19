# Binance Futures Position Report

这个项目会读取 Binance U 本位合约账户的持仓，生成：

- 每 4 小时的总仓位价值 / 账户权益变化曲线图
- 从指定起始日开始统计的已实现净盈亏
- 每次运行时的仓位明细表
- 已实现盈亏 / 手续费 / 资金费流水 CSV
- 一个包含图表、按币种分组统计和仓位状态的 HTML 报告

## 功能说明

这里的“总仓位价值”定义为：

- 所有非零持仓的 `abs(持仓数量 * 标记价格)` 之和

这样可以直观看到账户每天实际暴露出去的总合约价值，不会因为多空互相抵消而失真。

报告中还会展示：

- 各币种仓位方向（多 / 空）
- 持仓数量
- 开仓价
- 标记价格
- 当前仓位价值
- 浮盈 / 浮亏
- 估算收益率

如果设置了 `BINANCE_REALIZED_SINCE` 或 `--realized-since`，还会额外统计：

- 已实现盈亏 `REALIZED_PNL`
- 手续费 `COMMISSION`
- 资金费 `FUNDING_FEE`
- 总交易盈亏 = 已实现净盈亏 + 当前未实现盈亏

实现方式是：

- 第一次会从起始日回填历史流水
- 后续运行会复用本地 `output/income_history.csv`
- 每次只增量拉取“上次同步之后”的新流水，并带一个小重叠窗口自动去重

所以不需要每次都从 `2026-04-12` 全量请求 Binance API。

## 环境准备

1. 创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. 配置 API：

```bash
cp .env.example .env
```

然后把 `.env` 里的 `BINANCE_API_KEY` 和 `BINANCE_API_SECRET` 改成你自己的值。

如果你想从某天开始累计已实现盈亏，也可以加上：

```env
BINANCE_REALIZED_SINCE=2026-04-12
```

建议这个 API Key 只开启读取权限，不要开启提币或交易权限。

## 运行

```bash
python3 src/binance_futures_report.py
```

默认会生成这些文件：

- `output/position_value_history.csv`
- `output/position_value_curve.png`
- `output/latest_positions.csv`
- `output/income_history.csv`
- `output/daily_report.html`

## 定时执行

如果你想每 4 小时记录一次，可以用 cron：

```cron
5 */4 * * * /path/to/binance_futures/scripts/run_daily_report.sh >> /path/to/binance_futures/output/cron.log 2>&1
```

这会在每天的 00:05、04:05、08:05、12:05、16:05、20:05 刷新一次快照和图表。把 `/path/to/binance_futures` 替换成你自己的项目绝对路径。

## 可选参数

```bash
python3 src/binance_futures_report.py \
  --env-file .env \
  --output-dir output \
  --history-file output/position_value_history.csv \
  --chart-file output/position_value_curve.png \
  --positions-file output/latest_positions.csv \
  --html-file output/daily_report.html \
  --income-file output/income_history.csv \
  --realized-since 2026-04-12
```
