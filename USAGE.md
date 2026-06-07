# 抖音爬虫使用指南

## 快速开始

### 1. 安装依赖

```bash
cd "e:\Claude code project\抖音爬虫"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. 启动 Chrome（带调试端口）

**必须先完全关闭所有 Chrome 窗口！** 否则参数不生效。

```bash
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```

### 3. 登录抖音

在刚启动的 Chrome 中打开 https://www.douyin.com ，扫码登录。

### 4. 运行下载

```bash
# 一键下载某用户全部视频和图集
python douyin_crawler.py "https://www.douyin.com/user/MS4wLjABAAAA..." -o output/用户名

# 仅收集不下载，先看看有多少内容
python douyin_crawler.py "https://www.douyin.com/user/MS4wLjABAAAA..." -o output/用户名 --dry-run

# 下载完成后自动清理中间 JSON 文件
python douyin_crawler.py "https://www.douyin.com/user/MS4wLjABAAAA..." -o output/用户名 --cleanup
```

### 常用选项

| 选项 | 说明 |
|------|------|
| `-o DIR` | 输出目录（必填） |
| `--date-from YYYY-MM-DD` | 仅下载此日期之后 |
| `--date-to YYYY-MM-DD` | 仅下载此日期之前 |
| `--max N` | 最大收集数 |
| `--threads N` | 下载线程数（默认 8） |
| `--no-videos` | 跳过视频，只下图集 |
| `--no-notes` | 跳过图集，只下视频 |
| `--dry-run` | 仅收集，不下载 |
| `--cleanup` | 下载完删中间 JSON |

## 故障排查

### Chrome 调试端口（9222）连接失败

最常见的原因有两个：

**1. Chrome 启动前未完全关闭**

Chrome 已在运行时，再次执行 `chrome.exe --remote-debugging-port=9222` 只会在已有实例中打开新窗口，**调试端口参数不会生效**。

解决：先彻底关闭所有 Chrome 窗口和后台进程，再重新启动。

**2. 默认用户数据目录被锁定**

即使杀掉了所有 Chrome 进程，默认的 User Data 目录（`C:\Users\<用户名>\AppData\Local\Google\Chrome\User Data`）可能仍被锁定，导致调试参数被静默忽略。

症状：Chrome 正常启动，但 `netstat -ano | findstr 9222` 看不到端口监听。

解决：启动时指定一个独立的临时用户数据目录：

```bash
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=%TEMP%\chrome_cdp
```

代价是这个临时目录没有你的书签和插件，需要重新登录抖音。但 CDP 端口稳定可用。

### 验证 CDP 端口是否开启

```bash
# PowerShell
netstat -ano | findstr 9222

# 或者浏览器访问
http://127.0.0.1:9222/json/version
```
