#!/usr/bin/env python3
"""
抖音视频批量下载工具
用法: python douyin_batch_downloader.py <collected_json> [输出目录] [选项]

先通过 collect_spa_scroll.py 收集视频数据，再用本脚本批量下载。
"""


import sys
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from douyin_downloader import (
    HEADERS,
    extract_from_api,
    extract_from_html,
    fetch_video_page,
    download_video,
    sanitize_filename,
    build_filename,
)


def main():
    import json
    from datetime import datetime

    args = sys.argv[1:]
    if not args:
        print("用法: python douyin_batch_downloader.py <collected_json> [输出目录] [选项]")
        print()
        print("从 collect_spa_scroll.py 收集的 JSON 文件批量下载视频。")
        print()
        print("选项:")
        print("  --max N          最大下载数量（默认全部）")
        print("  --threads N      并行下载线程数（默认 10）")
        print("  --date-from DATE 仅下载此日期之后的视频（YYYY-MM-DD）")
        print("  --date-to DATE   仅下载此日期之前的视频（YYYY-MM-DD）")
        sys.exit(1)

    collected_file = args[0]
    output_dir = "output"
    max_videos = 0
    date_from = None
    date_to = None
    threads = 10

    skip_next = False
    for i, arg in enumerate(args[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if arg == "--max" and i + 1 < len(args):
            max_videos = int(args[i + 1])
            skip_next = True
        elif arg == "--date-from" and i + 1 < len(args):
            date_from = args[i + 1]
            skip_next = True
        elif arg == "--date-to" and i + 1 < len(args):
            date_to = args[i + 1]
            skip_next = True
        elif arg == "--threads" and i + 1 < len(args):
            threads = int(args[i + 1])
            skip_next = True
        elif not arg.startswith("--"):
            output_dir = arg

    date_from_ts = 0
    date_to_ts = 0
    if date_from:
        date_from_ts = datetime.strptime(date_from, "%Y-%m-%d").timestamp()
    if date_to:
        date_to_ts = datetime.strptime(date_to, "%Y-%m-%d").timestamp() + 86399

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print(f"从预收集数据读取: {collected_file}")
    with open(collected_file, encoding="utf-8") as f:
        video_data = json.load(f)
    if max_videos:
        video_data = video_data[:max_videos]
    print(f"共 {len(video_data)} 个视频\n")

    # 日期范围过滤
    if date_from_ts or date_to_ts:
        before = len(video_data)
        filtered = []
        for item in video_data:
            ts = item.get("create_time", 0)
            if not ts:
                continue
            if date_from_ts and ts < date_from_ts:
                continue
            if date_to_ts and ts > date_to_ts:
                continue
            filtered.append(item)
        video_data = filtered
        if date_from:
            print(f"日期过滤: >= {date_from}")
        if date_to:
            print(f"日期过滤: <= {date_to}")
        print(f"过滤后: {len(video_data)} 个视频（原 {before} 个）\n")

    if not video_data:
        print("未找到任何视频")
        sys.exit(1)

    total_to_download = len(video_data)
    print(f"共 {total_to_download} 个视频待下载\n")

    downloaded_log = Path(output_dir) / "downloaded.txt"
    downloaded_ids = set()
    if downloaded_log.exists():
        downloaded_ids = set(downloaded_log.read_text(encoding="utf-8").strip().splitlines())
        print(f"已下载 {len(downloaded_ids)} 个视频，将跳过\n")

    pending = [item for item in video_data if item["id"] not in downloaded_ids]
    skip = len(video_data) - len(pending)
    total_to_download = len(pending)
    print(f"待下载: {total_to_download} 个\n")

    if not pending:
        print("全部已下载，无需操作")
        print(f"  保存至: {Path(output_dir).resolve()}/")
        return

    lock = threading.Lock()
    stats = {"success": 0, "fail": 0, "total_size": 0}
    done_count = 0

    def download_one(item: dict) -> None:
        nonlocal done_count
        video_id = item["id"]
        title = item.get("title", video_id)
        video_url = item.get("url", "")

        try:
            if not video_url:
                html, aweme_data = fetch_video_page(video_id)
                result = None
                if aweme_data:
                    result = extract_from_api(aweme_data)
                if not result:
                    result = extract_from_html(html)
                if not result:
                    with lock:
                        stats["fail"] += 1
                        done_count += 1
                        print(f"[{done_count}/{total_to_download}] {video_id}  失败: 未能提取视频地址")
                    return
                video_url, title, api_create_time = result if len(result) == 3 else (*result, 0)

            create_time = item.get("create_time", 0)
            filename = build_filename(title, create_time)
            filepath = str(Path(output_dir) / filename)

            counter = 1
            while Path(filepath).exists():
                stem = Path(filename).stem
                filename = f"{stem}_{counter}.mp4"
                filepath = str(Path(output_dir) / filename)
                counter += 1

            size = download_video(video_url, filepath, quiet=True)

            with lock:
                stats["success"] += 1
                stats["total_size"] += size
                done_count += 1
                with open(downloaded_log, "a", encoding="utf-8") as log:
                    log.write(f"{video_id}\n")
                downloaded_ids.add(video_id)

                try:
                    print(f"[{done_count}/{total_to_download}] {filename} ({size / (1024*1024):.1f} MB)")
                except UnicodeEncodeError:
                    print(f"[{done_count}/{total_to_download}] {video_id} ({size / (1024*1024):.1f} MB)")

        except Exception as e:
            with lock:
                stats["fail"] += 1
                done_count += 1
                print(f"[{done_count}/{total_to_download}] {video_id}  错误: {e}")

    workers = max(1, min(threads, total_to_download))
    print(f"使用 {workers} 个线程并行下载...\n")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(download_one, item) for item in pending]
        for _ in as_completed(futures):
            pass

    print()
    print("=" * 50)
    print(f"下载完成!")
    print(f"  成功: {stats['success']} 个")
    print(f"  跳过: {skip} 个（已下载）")
    print(f"  失败: {stats['fail']} 个")
    print(f"  总大小: {stats['total_size'] / (1024 * 1024):.1f} MB")
    print(f"  保存至: {Path(output_dir).resolve()}/")


if __name__ == "__main__":
    main()
