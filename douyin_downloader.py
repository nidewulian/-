#!/usr/bin/env python3
"""
抖音视频下载工具 - 使用 Playwright + 系统浏览器
用法: python douyin_downloader.py <抖音视频URL> [输出目录]
示例: python douyin_downloader.py "https://www.douyin.com/video/7643030177089824868"
"""

import re
import sys
import json
import time
import requests
from pathlib import Path
from datetime import datetime
from urllib.parse import unquote
from playwright.sync_api import sync_playwright

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.douyin.com/",
}


def extract_video_id(url: str) -> str:
    for pattern in [r"/video/(\d+)", r"modal_id=(\d+)", r"(\d{15,20})"]:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    raise ValueError(f"无法从URL中提取视频ID: {url}")


def sanitize_filename(name: str) -> str:
    """清理文件名，去除非法字符"""
    name = re.sub(r'[\n\r\t]', ' ', name)
    name = re.sub(r'[\\/:*?"<>|]', '', name)
    return re.sub(r'\s+', ' ', name).strip()


def clean_title(title: str) -> str:
    """去 emoji、去 #话题，保留中文/英文/数字/空格"""
    title = re.sub(r'#', '', title)
    result = []
    for ch in title:
        if ch.isspace():
            result.append(' ')
        elif '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿':
            result.append(ch)
        elif '　' <= ch <= '〿':
            result.append(ch)
        elif '＀' <= ch <= '￯':
            result.append(ch)
        elif ch.isascii() and (ch.isalnum() or ch in '.-_()'):
            result.append(ch)
    cleaned = ''.join(result)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = cleaned.strip('.-_ ')
    return cleaned


def fmt_date(ts: int) -> str:
    dt = datetime.fromtimestamp(ts)
    return f'{dt.year}.{dt.month}.{dt.day}'


def build_filename(title: str, create_time: int = 0) -> str:
    if create_time:
        date_str = fmt_date(create_time)
        cleaned = clean_title(title)
        if cleaned:
            return sanitize_filename(f'{date_str}_{cleaned}.mp4')
        return sanitize_filename(f'{date_str}_.mp4')
    return sanitize_filename(f'{title}.mp4')


def launch_browser(p):
    """在已有 playwright 实例中启动 Chromium 浏览器，自动尝试 chrome/msedge/内置"""
    for channel in ["chrome", "msedge", None]:
        try:
            return p.chromium.launch(channel=channel, headless=True)
        except Exception:
            continue
    raise RuntimeError("无法启动任何浏览器")


def fetch_video_page(video_id: str):
    """
    打开抖音视频页，同时监听 API 响应和收集 HTML
    返回 (html, aweme_data)
    """
    page_url = f"https://www.douyin.com/video/{video_id}"

    with sync_playwright() as p:
        browser = launch_browser(p)

        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        aweme_data = []

        def on_response(response):
            if (
                "/aweme/v1/web/aweme/detail/" in response.url
                and response.status == 200
            ):
                try:
                    body = response.text()
                    if body and "aweme_detail" in body:
                        aweme_data.append(json.loads(body))
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

        for _ in range(15):
            if aweme_data:
                break
            time.sleep(1)

        html = page.content()
        browser.close()

        return html, aweme_data[0] if aweme_data else None


def extract_from_html(html: str) -> tuple[str, str] | None:
    """从 HTML 中直接提取视频地址和标题。返回 (url, title) 或 None"""

    # 提取标题
    title = "douyin_video"

    # 从 RENDER_DATA 中提取 desc
    m = re.search(r'id="RENDER_DATA"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            data = unquote(m.group(1))
            title_match = re.search(r'"desc"\s*:\s*"([^"]+)"', data)
            if title_match:
                title = sanitize_filename(title_match.group(1))
        except Exception:
            pass

    # 从 page title 提取
    if title == "douyin_video":
        m = re.search(r"<title>([^<]+)</title>", html)
        if m:
            raw_title = m.group(1).replace(" - 抖音", "").strip()
            title = sanitize_filename(raw_title)

    # 提取视频 URL（优先选最高清）
    video_urls = re.findall(
        r'https?://[^"\s<>]+?douyinvod\.com/[^"\s<>]+',
        html,
    )

    if not video_urls:
        # 再试 RENDER_DATA
        m = re.search(r'id="RENDER_DATA"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                data = unquote(m.group(1))
                video_urls = re.findall(
                    r'https?://[^"\\\s]+?douyinvod\.com[^"\\\s]+',
                    data,
                )
            except Exception:
                pass

    if video_urls:
        # 清理 URL 中的 HTML 实体和解码
        url = video_urls[0]
        url = url.replace("&amp;", "&")
        url = url.split('"')[0].split("'")[0]
        # 如果 URL 被截断包含 &br=，说明有不同的清晰度选项
        # 尝试在 HTML 中找到更高清版本
        for u in video_urls:
            u = u.replace("&amp;", "&")
            u_br = re.search(r"[&?]br=(\d+)", u)
            if u_br:
                return (u, title)
        return (url, title)

    return None


def extract_from_api(aweme_data: dict) -> tuple[str, str, int] | None:
    """从 aweme/detail API 响应中提取视频地址。返回 (url, title, create_time) 或 None"""
    aweme = aweme_data.get("aweme_detail", {})

    desc = sanitize_filename(aweme.get("desc", "douyin_video"))
    create_time = aweme.get("create_time", 0)
    video = aweme.get("video", {})

    # download_addr（含音视频，可能有水印）优先
    for key in ["download_addr", "play_addr", "play_addr_h264"]:
        addr = video.get(key, {})
        url_list = addr.get("url_list", [])
        if url_list:
            return (url_list[0], desc, create_time)

    # bit_rate 码率流作为备选（可能只有视频流，无音频）
    bit_rate_list = video.get("bit_rate", [])
    if bit_rate_list:
        for br in sorted(bit_rate_list, key=lambda x: x.get("bit_rate", 0), reverse=True):
            play_addr = br.get("play_addr", {})
            url_list = play_addr.get("url_list", [])
            if url_list:
                return (url_list[0], desc, create_time)

    return None


def download_video(url: str, filepath: str, quiet: bool = False):
    """下载视频文件"""
    resp = requests.get(
        url,
        headers={**HEADERS, "Range": "bytes=0-"},
        stream=True,
        timeout=120,
    )
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0

    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total and not quiet:
                    pct = downloaded / total * 100
                    mb = downloaded / (1024 * 1024)
                    total_mb = total / (1024 * 1024)
                    print(
                        f"\r  下载进度: {mb:.1f}/{total_mb:.1f} MB ({pct:.0f}%)",
                        end="",
                        flush=True,
                    )

    if total and not quiet:
        print()
    if not quiet:
        try:
            print(f"  已保存: {filepath} ({downloaded / (1024*1024):.1f} MB)")
        except UnicodeEncodeError:
            safe_name = Path(filepath).name.encode("ascii", errors="replace").decode("ascii")
            print(f"  已保存: {safe_name} ({downloaded / (1024*1024):.1f} MB)")
    return downloaded


def main():
    if len(sys.argv) < 2:
        print("用法: python douyin_downloader.py <抖音视频URL> [输出目录]")
        sys.exit(1)

    url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "output"

    video_id = extract_video_id(url)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print(f"视频ID: {video_id}")
    print(f"输出目录: {output_dir}/")
    print()

    print("启动浏览器获取视频信息...")
    html, aweme_data = fetch_video_page(video_id)

    # 优先用 API 数据（含无水印、多码率），其次用 HTML 数据
    result = None
    if aweme_data:
        result = extract_from_api(aweme_data)

    if not result:
        result = extract_from_html(html)

    if not result:
        print("失败: 未能提取视频地址")
        sys.exit(1)

    video_url, title = result[:2]
    print(f"视频标题: {title}")
    print(f"视频地址: {video_url[:100]}...")
    print()

    filename = f"{title}.mp4"
    filepath = str(Path(output_dir) / filename)

    # 避免覆盖已有文件
    counter = 1
    while Path(filepath).exists():
        filename = f"{title}_{counter}.mp4"
        filepath = str(Path(output_dir) / filename)
        counter += 1

    print(f"开始下载: {filename}")
    download_video(video_url, filepath)
    print()
    print("下载完成!")


if __name__ == "__main__":
    main()
