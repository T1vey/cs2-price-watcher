# CS2 Price Watcher

CS2 饰品价格监控器。实时追踪 Buff 在售价格，低价/跌幅异动时弹窗+声音提醒。

## 功能

1. 监控 Buff 在售最低价
2. 设置目标价格，到达时提醒
3. 自动检测价格跌幅（可配置阈值）
4. 声音 + 弹窗提醒
5. 系统托盘常驻，低占用

## 安装

```bash
git clone https://github.com/T1vey/cs2-price-watcher.git
cd cs2-price-watcher
pip install -r requirements.txt
```

## 使用

```bash
python tray_app.py
```

首次启动弹出设置窗口，搜索添加想监控的饰品，设置目标价格即可。

## 原理

1. 定时查询 Buff 在售列表（默认 30 秒一次）
2. 记录价格变化
3. 触发条件时提醒：
   - 到达目标价格
   - 当前最低价低于在售均价 N%
   - 近期价格跌幅超过 N%

## 数据源

- [Buff](https://buff.163.com) — 公开 API，无需登录

## License

MIT
