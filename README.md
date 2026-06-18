# CS2 Price Watcher

CS2 饰品价格监控器。实时追踪 Buff + 悠悠有品在售价格，低价/跌幅异动时弹窗+声音提醒。

## 功能

1. Buff + 悠悠有品双平台监控
2. 目标价到达提醒
3. 低于均价提醒（可配置阈值）
4. 近期跌幅提醒
5. 声音 + 弹窗提醒
6. 系统托盘常驻，低占用

## 快速开始

### 方式 1：直接运行 exe

1. 下载 `CS2-PriceWatcher.exe`
2. 运行 `install_browser.bat`（首次，安装悠悠有品浏览器组件，约 110MB）
3. 双击 `CS2-PriceWatcher.exe`

### 方式 2：从源码运行

```bash
git clone https://github.com/T1vey/cs2-price-watcher.git
cd cs2-price-watcher
pip install -r requirements.txt
python -m playwright install chromium
python tray_app.py
```

## 使用

1. 首次启动弹出设置窗口
2. 粘贴 Buff 或悠悠有品饰品链接添加监控
3. 设置目标价格（可选）
4. 保存，开始监控

## 数据源

| 平台 | 方式 | 需要登录 |
|------|------|----------|
| Buff | 直接 API | 可选 Cookie（搜索用） |
| 悠悠有品 | Playwright 浏览器自动化 | 不需要 |

## 打包 exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon app.ico --name CS2-PriceWatcher tray_app.py
```

## License

MIT
