#!/usr/bin/env python3
"""
抖音图片合集（图集/notes）下载工具
用法: python download_notes.py <notes_json文件> [输出目录] [选项]
"""
import json
import re
import sys
import requests
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from douyin_downloader import HEADERS, sanitize_filename, clean_title, fmt_date


def fetch_note_page(note_id: str) -> tuple[list[str], str, int]:
    """
    通过 detail API 获取图集原图 URL、标题和发布时间。
    不再从 DOM 抓取（画质差且慢），直接从 API 提取 download_url_list。
    """
    from playwright.sync_api import sync_playwright

    page_url = f"https://www.douyin.com/note/{note_id}"

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            try:
                browser = p.chromium.launch(channel="msedge", headless=True)
            except Exception:
                browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

        # 通过 SPA fetch 调用 detail API，提取无水印原图 URL
        api_raw = page.evaluate(f"""
            async () => {{
                try {{
                    const resp = await fetch(
                        'https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={note_id}&device_platform=webapp&aid=6383&channel=channel_pc_web',
                        {{ credentials: 'include', headers: {{ 'Accept': 'application/json' }} }}
                    );
                    const data = await resp.json();
                    if (data.aweme_detail) {{
                        const ad = data.aweme_detail;
                        const imageUrls = [];
                        if (ad.images && ad.images.length) {{
                            ad.images.forEach(img => {{
                                // 用 url_list（p3-sign 域名，无需复杂鉴权），
                                // 去掉 ~tplv 后缀尝试获取无水印原图
                                let url = (img.url_list && img.url_list[0]) || '';
                                if (!url) {{
                                    url = (img.download_url_list && img.download_url_list[0]) || '';
                                }}
                                if (url) imageUrls.push(url);
                            }});
                        }}
                        return JSON.stringify({{
                            desc: ad.desc || '',
                            create_time: ad.create_time || 0,
                            images: imageUrls
                        }});
                    }}
                }} catch(e) {{}}
                return null;
            }}
        """)

        browser.close()

    if api_raw:
        data = json.loads(api_raw)
        img_urls = data.get("images", [])
        title = sanitize_filename(data.get("desc", "douyin_note"))
        create_time = data.get("create_time", 0)
    else:
        img_urls = []
        title = "douyin_note"
        create_time = 0

    return img_urls, title, create_time


def build_note_dirname(title: str, create_time: int) -> str:
    """构建图集文件夹名称：日期_清理标题"""
    cleaned = clean_title(title)
    if create_time and cleaned:
        date_str = fmt_date(create_time)
        return sanitize_filename(f"{date_str}_{cleaned}")
    if cleaned:
        return sanitize_filename(cleaned)
    return sanitize_filename(title)


def download_image(url: str, filepath: str) -> int:
    """下载单张图片。先尝试去 ~tplv 后缀获取无水印原图，失败则用原 URL。"""
    # 去掉 ~tplv 后缀拿到可能无水印的原始图片 URL
    clean_url = re.sub(r'~tplv-[^?&]+', '', url)
    urls_to_try = [clean_url, url] if clean_url != url else [url]

    for u in urls_to_try:
        try:
            resp = requests.get(u, headers=HEADERS, timeout=60)
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(resp.content)
            return len(resp.content)
        except Exception:
            continue

    raise RuntimeError(f"所有 URL 均下载失败: {filepath}")


def download_note(note: dict, output_dir: str, lock: threading.Lock, stats: dict) -> bool:
    """下载单个图集的所有图片到文件夹"""
    note_id = note["id"]

    try:
        img_urls, title, create_time = fetch_note_page(note_id)

        if not img_urls:
            with lock:
                stats["fail"] += 1
                print(f"  [{note_id}] 未提取到图片")
            return False

        dirname = build_note_dirname(title, create_time)
        folder = Path(output_dir) / dirname
        folder.mkdir(parents=True, exist_ok=True)

        # 下载所有图片
        for i, url in enumerate(img_urls, start=1):
            ext = ".webp" if "webp" in url.split("?")[0].lower() else ".jpg"
            filename = f"{i:02d}{ext}"
            filepath = folder / filename

            # 跳过已下载
            if filepath.exists():
                continue

            download_image(url, str(filepath))

        with lock:
            stats["success"] += 1
            print(f"  [{note_id}] {dirname}/ ({len(img_urls)} 张图)")

        return True

    except Exception as e:
        with lock:
            stats["fail"] += 1
            print(f"  [{note_id}] 错误: {e}")
        return False


def main():
    args = sys.argv[1:]
    if not args:
        print("用法: python download_notes.py <notes_json文件> [输出目录]")
        print("选项:")
        print("  --threads N  并行数（默认 8）")
        print("  --max N      最大下载数（默认全部）")
        sys.exit(1)

    notes_file = args[0]
    output_dir = "output"
    threads = 8
    max_notes = 0

    skip = False
    for i, arg in enumerate(args[1:], start=1):
        if skip:
            skip = False
            continue
        if arg == "--threads" and i + 1 < len(args):
            threads = int(args[i + 1])
            skip = True
        elif arg == "--max" and i + 1 < len(args):
            max_notes = int(args[i + 1])
            skip = True
        elif not arg.startswith("--"):
            output_dir = arg

    with open(notes_file, encoding="utf-8") as f:
        notes = json.load(f)

    if max_notes:
        notes = notes[:max_notes]

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print(f"共 {len(notes)} 个图片合集待下载")
    print(f"输出目录: {output_dir}/")
    print(f"线程数: {threads}")
    print()

    lock = threading.Lock()
    stats = {"success": 0, "fail": 0}

    workers = max(1, min(threads, len(notes)))
    print(f"使用 {workers} 个线程并行下载...\n")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(download_note, note, output_dir, lock, stats)
            for note in notes
        ]
        for _ in as_completed(futures):
            pass

    print()
    print("=" * 50)
    print("图集下载完成!")
    print(f"  成功: {stats['success']} 个")
    print(f"  失败: {stats['fail']} 个")
    print(f"  保存至: {Path(output_dir).resolve()}/")


if __name__ == "__main__":
    main()
