#!/usr/bin/env python3
"""
重命名视频和图集文件夹，添加日期前缀
用法: python rename_with_dates.py <collected_json> <output_dir> [--cdp-port N]
"""
import json
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from douyin_downloader import (
    HEADERS, sanitize_filename, clean_title, fmt_date, build_filename,
)


def get_video_create_time(video_id: str, page) -> dict | None:
    """打开视频页获取 create_time 和 title，返回 {'id':, 'title':, 'create_time':}"""
    page_url = f"https://www.douyin.com/video/{video_id}"

    api_data = []
    def on_response(response):
        if "/aweme/v1/web/aweme/detail/" in response.url and response.status == 200:
            try:
                body = response.text()
                if body and "aweme_detail" in body:
                    api_data.append(json.loads(body))
            except Exception:
                pass

    page.on("response", on_response)
    page.goto(page_url, wait_until="domcontentloaded", timeout=20000)

    for _ in range(10):
        if api_data:
            break
        time.sleep(0.5)

    if api_data:
        aweme = api_data[0].get("aweme_detail", {})
        return {
            "id": video_id,
            "title": aweme.get("desc", ""),
            "create_time": aweme.get("create_time", 0),
        }

    # Fallback: try HTML
    try:
        html = page.content()
        from urllib.parse import unquote
        m = re.search(r'id="RENDER_DATA"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            data = unquote(m.group(1))
            ct_match = re.search(r'"create_time"\s*:\s*(\d+)', data)
            title_match = re.search(r'"desc"\s*:\s*"([^"]+)"', data)
            return {
                "id": video_id,
                "title": title_match.group(1) if title_match else "",
                "create_time": int(ct_match.group(1)) if ct_match else 0,
            }
    except Exception:
        pass

    return None


def get_note_create_time(note_id: str, page) -> dict | None:
    """打开笔记页获取 create_time 和 title"""
    page_url = f"https://www.douyin.com/note/{note_id}"

    api_data = []
    def on_response(response):
        if "/aweme/v1/web/aweme/detail/" in response.url and response.status == 200:
            try:
                body = response.text()
                if body and "aweme_detail" in body:
                    api_data.append(json.loads(body))
            except Exception:
                pass

    page.on("response", on_response)
    page.goto(page_url, wait_until="domcontentloaded", timeout=20000)

    for _ in range(10):
        if api_data:
            break
        time.sleep(0.5)

    if api_data:
        aweme = api_data[0].get("aweme_detail", {})
        return {
            "id": note_id,
            "title": aweme.get("desc", ""),
            "create_time": aweme.get("create_time", 0),
        }

    return None


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print("用法: python rename_with_dates.py <collected_dir_or_json> <output_dir> [--cdp-port N]")
        print("示例: python rename_with_dates.py collected_videos.json output/")
        sys.exit(1)

    collected = args[0]
    output_dir = args[1]
    cdp_port = 9222
    if len(args) > 2 and args[2] == "--cdp-port" and len(args) > 3:
        cdp_port = int(args[3])

    print(f"连接 Chrome (端口 {cdp_port})...")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{cdp_port}")
        page = browser.contexts[0].new_page()

        # ====== 处理视频 ======
        videos_file = os.path.join(collected, "collected_videos.json") if os.path.isdir(collected) else collected
        if os.path.exists(videos_file):
            with open(videos_file, encoding="utf-8") as f:
                videos = json.load(f)
            print(f"\n处理 {len(videos)} 个视频...")

            renamed = 0
            skipped = 0
            failed = 0

            for i, v in enumerate(videos):
                vid = v["id"]
                print(f"\r  [{i+1}/{len(videos)}] {vid}...", end="", flush=True)

                # Find current file (by old naming: sanitize_filename(title).mp4)
                info = get_video_create_time(vid, page)
                if not info or not info["create_time"]:
                    failed += 1
                    continue

                ct = info["create_time"]
                title = info["title"]

                # Old filename (no date)
                old_name = sanitize_filename(title)
                old_path = os.path.join(output_dir, f"{old_name}.mp4")

                # New filename
                new_name = build_filename(title, ct)
                new_path = os.path.join(output_dir, new_name)

                # Find the actual file (might have _N suffix)
                actual_old = None
                if os.path.exists(old_path):
                    actual_old = old_path
                else:
                    counter = 1
                    while True:
                        alt_path = os.path.join(output_dir, f"{old_name}_{counter}.mp4")
                        if os.path.exists(alt_path):
                            actual_old = alt_path
                            break
                        counter += 1
                        if counter > 50:
                            break
                    if not actual_old:
                        # Search more broadly
                        for f in os.listdir(output_dir):
                            if f.startswith(old_name[:20]) and f.endswith(".mp4"):
                                actual_old = os.path.join(output_dir, f)
                                break

                if actual_old and os.path.exists(actual_old):
                    if actual_old == new_path:
                        skipped += 1
                    else:
                        # Handle name collision
                        final_path = new_path
                        counter = 1
                        while os.path.exists(final_path) and final_path != actual_old:
                            stem = Path(new_name).stem
                            final_path = os.path.join(output_dir, f"{stem}_{counter}.mp4")
                            counter += 1
                        os.rename(actual_old, final_path)
                        renamed += 1
                else:
                    failed += 1

            print(f"\r  视频: 重命名 {renamed}, 已正确 {skipped}, 失败 {failed}")

        # ====== 处理图集 ======
        notes_file = os.path.join(collected, "collected_notes.json") if os.path.isdir(collected) else collected.replace("videos", "notes")
        if os.path.exists(notes_file):
            with open(notes_file, encoding="utf-8") as f:
                notes = json.load(f)
            print(f"\n处理 {len(notes)} 个图集...")

            renamed = 0
            failed = 0

            for i, n in enumerate(notes):
                nid = n["id"]
                print(f"\r  [{i+1}/{len(notes)}] {nid}...", end="", flush=True)

                info = get_note_create_time(nid, page)
                if not info or not info["create_time"]:
                    failed += 1
                    continue

                ct = info["create_time"]
                title = info["title"]

                # Find current folder (old naming: cleaned title without date)
                cleaned = clean_title(title) if title else ""
                old_dirname = sanitize_filename(cleaned or title)
                old_path = os.path.join(output_dir, old_dirname)

                # New dirname
                if ct and cleaned:
                    date_str = fmt_date(ct)
                    new_dirname = sanitize_filename(f"{date_str}_{cleaned}")
                else:
                    new_dirname = old_dirname

                new_path = os.path.join(output_dir, new_dirname)

                if os.path.isdir(old_path) and old_path != new_path:
                    counter = 1
                    final_path = new_path
                    while os.path.exists(final_path):
                        final_path = os.path.join(output_dir, f"{new_dirname}_{counter}")
                        counter += 1
                    os.rename(old_path, final_path)
                    renamed += 1
                elif os.path.isdir(old_path) and old_path == new_path:
                    pass  # Already correct

            print(f"\r  图集: 重命名 {renamed}, 失败 {failed}")

        page.close()
        browser.close()

    print("\n完成!")


if __name__ == "__main__":
    main()
