# 抖音视频爬虫 - 项目配置

## 项目概述

抖音用户主页视频批量下载工具。支持：
- 单个视频下载（`douyin_downloader.py`）
- 批量下载用户全部视频（`douyin_batch_downloader.py`）
- 通过 API 收集用户视频列表（`collect_user_videos.py`）

## 可用 Skills

使用 `/skill-name` 调用：

| Skill | 用途 |
|-------|------|
| `grill-me` | 严格代码审查 |
| `to-prd` | 需求转 PRD 文档 |
| `to-issues` | 需求拆分为 Issues |
| `tdd` | 测试驱动开发 |
| `diagnose` | 系统性问题诊断 |
| `git-guardrails` | Git 安全护栏 |
| `improve-codebase-architecture` | 架构分析改进 |
| `request-refactor-plan` | 重构计划 |

## 技术栈

- Python 3.x
- Playwright (浏览器自动化)
- requests (HTTP 下载)

## 关键发现

- 抖音 `/aweme/v1/web/aweme/post/` API 第一页（max_cursor=0）无需签名
- 分页需要 `a_bogus` 签名（由 SPA 的 `window.byted_acrawler` 生成）
- Chrome 登录态可通过 `launch_persistent_context` + 复制 User Data 保留
- Cookie 文件使用 Windows DPAPI 加密，不可直接读取

## Git 规范

- 不提交敏感文件（cookies, .env, credentials）
- 不提交临时测试文件
- 不提交 __pycache__
