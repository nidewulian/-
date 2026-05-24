#!/usr/bin/env python3
"""
抖音用户视频和图集一键下载工具
用法: python douyin_crawler.py <用户主页URL> -o <输出目录> [选项]

示例:
  python douyin_crawler.py "https://www.douyin.com/user/MS4wLjAB..." -o output/猫几

工作流程:
  1. 通过 CDP 连接 Chrome，自动分页收集全部视频和图集
  2. 多线程下载视频（无水印最高清）
  3. 下载图集（原图质量）
"""

import json
import re
import sys
from pathlib import Path


def extract_sec_uid(url: str) -> str:
    m = re.search(r"/user/([^/?&]+)", url)
    if m:
        return m.group(1)
    raise ValueError(f"无法从 URL 提取用户 ID: {url}")


def main():
    args = sys.argv[1:]
    if not args:
        print("用法: python douyin_crawler.py <用户主页URL> -o <输出目录> [选项]")
        print()
        print("选项:")
        print("  -o DIR            输出目录（必填，下载到 DIR/ 下）")
        print("  --cdp-port N      CDP 端口（默认 9222）")
        print("  --max N           最大收集数（默认不限）")
        print("  --threads N       下载线程数（默认 8）")
        print("  --date-from DATE  仅下载此日期之后的视频（YYYY-MM-DD）")
        print("  --date-to DATE    仅下载此日期之前的视频（YYYY-MM-DD）")
        print("  --no-videos       跳过视频下载")
        print("  --no-notes        跳过图集下载")
        print("  --cleanup         下载完成后清理中间 JSON 文件")
        print("  --dry-run         仅收集，不下载")
        print()
        print("前置步骤:")
        print(r'  1. 启动 Chrome:  "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222')
        print("  2. 在 Chrome 中登录 douyin.com，打开目标用户主页")
        print("  3. 运行本脚本")
        sys.exit(1)

    url = args[0]
    if not url.startswith("http"):
        print(f"错误: 请输入完整的用户主页 URL")
        sys.exit(1)

    output_dir = None
    cdp_port = 9222
    max_count = 0
    threads = 8
    date_from = None
    date_to = None
    no_videos = False
    no_notes = False
    cleanup = False
    dry_run = False

    skip_next = False
    for i, arg in enumerate(args[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if arg == "-o" and i + 1 < len(args):
            output_dir = args[i + 1]
            skip_next = True
        elif arg == "--cdp-port" and i + 1 < len(args):
            cdp_port = int(args[i + 1])
            skip_next = True
        elif arg == "--max" and i + 1 < len(args):
            max_count = int(args[i + 1])
            skip_next = True
        elif arg == "--threads" and i + 1 < len(args):
            threads = int(args[i + 1])
            skip_next = True
        elif arg == "--date-from" and i + 1 < len(args):
            date_from = args[i + 1]
            skip_next = True
        elif arg == "--date-to" and i + 1 < len(args):
            date_to = args[i + 1]
            skip_next = True
        elif arg == "--no-videos":
            no_videos = True
        elif arg == "--no-notes":
            no_notes = True
        elif arg == "--cleanup":
            cleanup = True
        elif arg == "--dry-run":
            dry_run = True

    if not output_dir:
        print("错误: 请用 -o 指定输出目录")
        sys.exit(1)

    sec_uid = extract_sec_uid(url)

    # ============================================================
    # 第一步：收集
    # ============================================================
    print("=" * 50)
    print("第一步: 收集视频和图集")
    print("=" * 50)
    print(f"用户 ID: {sec_uid}")
    print(f"输出目录: {output_dir}/")
    print()

    from collect_spa_scroll import collect_via_cdp

    videos, notes = collect_via_cdp(sec_uid, cdp_port=cdp_port)

    print(f"收集完成: {len(videos)} 个视频, {len(notes)} 个图集\n")

    if not videos and not notes:
        print("未收集到任何内容。请确认 Chrome 中已登录 douyin.com 且打开了目标用户主页。")
        sys.exit(1)

    # 保存中间 JSON
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    videos_file = output_path / "collected_videos.json"
    notes_file = output_path / "collected_videos_notes.json"

    if videos:
        with open(videos_file, "w", encoding="utf-8") as f:
            json.dump(videos, f, ensure_ascii=False, indent=2)

    if notes:
        with open(notes_file, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)

    if dry_run:
        print("--dry-run 模式，仅收集，跳过下载。")
        return

    # ============================================================
    # 第二步：下载视频
    # ============================================================
    video_result = None
    if videos and not no_videos:
        print("=" * 50)
        print("第二步: 下载视频")
        print("=" * 50)

        from douyin_batch_downloader import run_batch_download

        video_result = run_batch_download(
            videos, str(output_path),
            threads=threads,
            date_from=date_from,
            date_to=date_to,
        )
        print()
    elif no_videos:
        print("跳过视频下载\n")

    # ============================================================
    # 第三步：下载图集
    # ============================================================
    notes_result = None
    if notes and not no_notes:
        print("=" * 50)
        print("第三步: 下载图集")
        print("=" * 50)

        from download_notes import run_notes_download

        notes_result = run_notes_download(
            notes, str(output_path),
            threads=threads,
        )
        print()
    elif no_notes:
        print("跳过图集下载\n")

    # ============================================================
    # 汇总
    # ============================================================
    print("=" * 50)
    print("全部完成!")
    print(f"  视频: {video_result['success']} 成功, {video_result['fail']} 失败" if video_result else "  视频: 无")
    print(f"  图集: {notes_result['success']} 成功, {notes_result['fail']} 失败" if notes_result else "  图集: 无")
    print(f"  保存至: {output_path.resolve()}/")

    # 清理中间 JSON
    if cleanup:
        if videos_file.exists():
            videos_file.unlink()
        if notes_file.exists():
            notes_file.unlink()
        ids_file = output_path / "collected_videos_ids.json"
        if ids_file.exists():
            ids_file.unlink()
        print("  (中间 JSON 已清理)")


if __name__ == "__main__":
    main()
