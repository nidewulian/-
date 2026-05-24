#!/usr/bin/env python3
"""
抖音图片合集（图集/notes）下载工具
用法: python download_notes.py <notes_json文件> [输出目录] [选项]
"""
import json
import re
import sys
import time
import requests
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from douyin_downloader import (
    HEADERS, sanitize_filename, clean_title, fmt_date, launch_browser,
)


def fetch_all_notes(notes: list[dict]) -> list[dict]:
    """使用单个浏览器实例为所有图集获取图片 URL 和元数据，避免每个图集启动一次浏览器"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = launch_browser(p)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        # 先导航到抖音建立 domain 上下文，后续 API 调用共享同一来源
        page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)

        enriched = []
        for i, note in enumerate(notes):
            note_id = note["id"]
            print(f"\r  收集图集信息... [{i+1}/{len(notes)}] {note_id}", end="", flush=True)

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

            if api_raw:
                data = json.loads(api_raw)
                enriched.append({
                    "id": note_id,
                    "title": data.get("desc", "douyin_note"),
                    "create_time": data.get("create_time", 0),
                    "images": data.get("images", []),
                })
            else:
                enriched.append({**note, "images": [], "title": note.get("title", "douyin_note"), "create_time": note.get("create_time", 0)})

        print()  # 换行结束进度行
        browser.close()

    return enriched


def build_note_dirname(title: str, create_time: int) -> str:
    """构建图集文件夹名称：日期_清理标题"""
    cleaned = clean_title(title)
    if create_time and cleaned:
        date_str = fmt_date(create_time)
        return sanitize_filename(f"{date_str}_{cleaned}")
    if cleaned:
        return sanitize_filename(cleaned)
    return sanitize_filename(title)


def download_image(url: str, filepath: str, max_retries: int = 3) -> int:
    """下载单张图片，先尝试去 ~tplv 获取无水印原图，失败自动重试。"""
    clean_url = re.sub(r'~tplv-[^?&]+', '', url)
    urls_to_try = [clean_url, url] if clean_url != url else [url]

    for attempt in range(max_retries):
        for u in urls_to_try:
            try:
                resp = requests.get(u, headers=HEADERS, timeout=60)
                resp.raise_for_status()
                with open(filepath, "wb") as f:
                    f.write(resp.content)
                return len(resp.content)
            except Exception:
                continue
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    raise RuntimeError(f"所有 URL 均下载失败: {filepath}")


def download_note(note: dict, output_dir: str, lock: threading.Lock, stats: dict) -> bool:
    """下载单个图集的所有图片到文件夹（不再启动浏览器，使用已收集的数据）"""
    note_id = note["id"]

    try:
        img_urls = note.get("images", [])
        title = note.get("title", "douyin_note")
        create_time = note.get("create_time", 0)

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


def run_notes_download(
    notes_list: list,
    output_dir: str,
    threads: int = 8,
    max_count: int = 0,
) -> dict:
    """批量下载图集。返回统计信息，包含 failed_ids 列表。"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    notes = list(notes_list)
    if max_count:
        notes = notes[:max_count]

    print(f"共 {len(notes)} 个图片合集待下载")
    print(f"输出目录: {output_dir}/")
    print()

    # 单浏览器收集全部图集信息
    print("正在收集图集信息...")
    notes = fetch_all_notes(notes)
    valid = sum(1 for n in notes if n.get("images"))
    print(f"收集完成: {valid}/{len(notes)} 个图集有图片\n")

    lock = threading.Lock()
    stats = {"success": 0, "fail": 0}
    failed_ids = []

    workers = max(1, min(threads, len(notes)))
    print(f"使用 {workers} 个线程并行下载...\n")

    # 用 wrapper 捕获失败 ID
    def download_one(note: dict) -> bool:
        result = download_note(note, str(output_path), lock, stats)
        if not result:
            with lock:
                failed_ids.append(note["id"])
        return result

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(download_one, note) for note in notes]
        for _ in as_completed(futures):
            pass

    # 写失败 ID 列表
    if failed_ids:
        failed_file = output_path / "failed_notes.txt"
        with open(failed_file, "w", encoding="utf-8") as f:
            for nid in failed_ids:
                f.write(f"{nid}\n")
        print(f"\n失败 ID 已写入: {failed_file}")

    print()
    print("=" * 50)
    print("图集下载完成!")
    print(f"  成功: {stats['success']} 个")
    print(f"  失败: {stats['fail']} 个")
    print(f"  保存至: {output_path.resolve()}/")

    return {"success": stats["success"], "fail": stats["fail"], "failed_ids": failed_ids}


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
    max_count = 0

    skip_next = False
    for i, arg in enumerate(args[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if arg == "--threads" and i + 1 < len(args):
            threads = int(args[i + 1])
            skip_next = True
        elif arg == "--max" and i + 1 < len(args):
            max_count = int(args[i + 1])
            skip_next = True
        elif not arg.startswith("--"):
            output_dir = arg

    with open(notes_file, encoding="utf-8") as f:
        notes = json.load(f)

    run_notes_download(notes, output_dir, threads, max_count)


if __name__ == "__main__":
    main()
