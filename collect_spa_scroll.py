#!/usr/bin/env python3
"""
抖音用户视频和图集收集器 - CDP 自动模式

工作原理:
  1. 连接到用户已打开的 Chrome（CDP 协议）
  2. 从页面上下文直接调用 post API（利用 SPA 的 byted_acrawler.sign() 生成 a_bogus）
  3. 自动翻页直到 has_more=0，收集全部视频和图集数据
  4. 自动提取每个视频的 ID、标题、最高清无水印 URL

用法:
  # 第一步：启动 Chrome（带调试端口）
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222

  # 第二步：在 Chrome 中登录 douyin.com，打开目标用户主页
  # （比如 https://www.douyin.com/user/MS4wLjABAAAA...）

  # 第三步：运行脚本（自动收集，无需手动操作）
  python collect_spa_scroll.py <用户主页URL>

选项:
  --cdp-port N       CDP 端口（默认 9222）
  -o FILE            输出文件（默认 collected_videos.json）
  --max N            最大收集数（默认不限）
"""

import re
import sys
import json
import time
from pathlib import Path


def extract_sec_uid(url: str) -> str:
    m = re.search(r"/user/([^/?&]+)", url)
    if m:
        return m.group(1)
    raise ValueError(f"无法从URL中提取用户ID: {url}")


def collect_via_cdp(
    sec_uid: str,
    cdp_port: int = 9222,
    max_videos: int = 0,
) -> tuple[list[dict], list[dict]]:
    """
    CDP 模式主流程：
    - 连接到用户已打开的 Chrome
    - 从页面上下文直接调用 post API（使用 SPA 的 byted_acrawler.sign() 生成 a_bogus）
    - 自动翻页直到 has_more=0，收集全部视频数据
    """
    from playwright.sync_api import sync_playwright

    url = f"https://www.douyin.com/user/{sec_uid}"

    with sync_playwright() as p:
        # ======== 连接 Chrome ========
        print(f"连接 Chrome (端口 {cdp_port})...")
        try:
            browser = p.chromium.connect_over_cdp(f"http://localhost:{cdp_port}")
        except Exception as e:
            print(f"\n[错误] 无法连接到 Chrome: {e}")
            print(f"\n请先启动 Chrome 并开启调试端口：")
            print(f'  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port={cdp_port}')
            print(f"\n然后在 Chrome 中：")
            print(f"  1. 登录 douyin.com")
            print(f"  2. 打开目标用户主页（{url}）")
            print(f"\n最后重新运行本脚本。")
            return []

        context = browser.contexts[0]
        print("  已连接")

        # ======== 找到或创建页面 ========
        douyin_pages = [pg for pg in context.pages if "douyin.com" in pg.url]
        if douyin_pages:
            page = douyin_pages[0]
            print(f"  复用页面: {page.url[:80]}")
        else:
            page = context.new_page()
            print(f"  创建新页面")

        # 导航：仅当不在目标页面时才导航（绝不 reload，避免风控）
        if sec_uid not in page.url:
            print(f"  导航到目标用户主页...")
            page.goto(url, wait_until="load", timeout=60000)
            print(f"  页面已加载")
        else:
            print(f"  已在目标用户主页，保持当前状态（不刷新）")

        # ======== 从页面上下文直接调用 API ========
        print("正在通过页面 SPA 签名调用 API 收集全部视频...")
        result = page.evaluate(f"""
            async () => {{
                const secUid = '{sec_uid}';
                const allVideos = [];
                const allNotes = [];
                const seen = new Set();
                let cursor = 0;
                let hasMore = true;
                let pageNum = 0;
                const maxPages = 80;

                while (hasMore && pageNum < maxPages) {{
                    pageNum++;
                    let params = 'device_platform=webapp&aid=6383&channel=channel_pc_web'
                        + '&sec_user_id=' + secUid
                        + '&max_cursor=' + cursor
                        + '&count=20&version_name=1.0.0&version_code=170400';

                    // 第2页起需要 a_bogus 签名
                    if (cursor > 0 && window.byted_acrawler && window.byted_acrawler.sign) {{
                        const queryStr = 'device_platform=webapp&aid=6383&channel=channel_pc_web'
                            + '&sec_user_id=' + secUid
                            + '&max_cursor=' + cursor
                            + '&count=20';
                        try {{
                            const aBogus = window.byted_acrawler.sign(queryStr);
                            params += '&a_bogus=' + encodeURIComponent(aBogus);
                        }} catch(e) {{
                            break;
                        }}
                    }}

                    try {{
                        const resp = await fetch(
                            'https://www.douyin.com/aweme/v1/web/aweme/post/?' + params,
                            {{ credentials: 'include', headers: {{ 'Accept': 'application/json' }} }}
                        );
                        const data = await resp.json();
                        if (!data.aweme_list) break;

                        for (const aweme of data.aweme_list) {{
                            const vid = aweme.aweme_id;
                            if (!vid || seen.has(vid)) continue;
                            seen.add(vid);

                            // 图集优先：有 images 就当图集，不再当视频
                            if (aweme.images && aweme.images.length) {{
                                allNotes.push({{
                                    id: vid,
                                    title: aweme.desc || '',
                                    create_time: aweme.create_time || 0
                                }});
                            }} else {{
                                // 视频 URL 优先级：download_addr（含音视频）> play_addr > bit_rate
                                let bestUrl = aweme.video?.download_addr?.url_list?.[0] || '';
                                if (!bestUrl) {{
                                    bestUrl = aweme.video?.play_addr?.url_list?.[0] || '';
                                }}
                                if (!bestUrl) {{
                                    const bitRates = aweme.video?.bit_rate || [];
                                    if (bitRates.length) {{
                                        const best = bitRates.reduce(
                                            (a, b) => (b.bit_rate || 0) > (a.bit_rate || 0) ? b : a
                                        );
                                        bestUrl = best.play_addr?.url_list?.[0] || '';
                                    }}
                                }}

                                allVideos.push({{
                                    id: vid,
                                    title: aweme.desc || '',
                                    url: bestUrl,
                                    create_time: aweme.create_time || 0
                                }});
                            }}
                        }}

                        hasMore = data.has_more === 1;
                        cursor = data.max_cursor || 0;
                    }} catch(e) {{
                        break;
                    }}

                    // 页间短暂延迟，避免触发频率限制
                    await new Promise(r => setTimeout(r, 300));
                }}

                return JSON.stringify({{ total: allVideos.length, videos: allVideos, notesTotal: allNotes.length, notes: allNotes }});
            }}
        """)

        browser.close()

    data = json.loads(result)
    videos = data["videos"]
    notes = data.get("notes", [])
    print(f"  收集完成: {len(videos)} 个视频, {len(notes)} 个图集")
    return videos, notes


def main():
    args = sys.argv[1:]
    if not args:
        print("用法: python collect_spa_scroll.py <用户主页URL> [选项]")
        print()
        print("CDP 自动模式：")
        print("  python collect_spa_scroll.py <用户主页URL>")
        print()
        print("  步骤：")
        print("    1. 启动 Chrome 调试端口：")
        print(r'       "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222')
        print("    2. 在 Chrome 中登录 douyin.com，打开目标用户主页")
        print("    3. 运行脚本，自动分页收集全部视频")
        print()
        print("选项:")
        print("  --cdp-port N     CDP 端口（默认 9222）")
        print("  -o FILE          输出文件（默认 collected_videos.json）")
        print("  --max N          最大收集数（默认不限）")
        sys.exit(1)

    url = args[0]
    output_file = "collected_videos.json"
    cdp_port = 9222
    max_videos = 0

    skip_next = False
    for i, arg in enumerate(args[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if arg == "--cdp-port" and i + 1 < len(args):
            cdp_port = int(args[i + 1])
            skip_next = True
        elif arg == "-o" and i + 1 < len(args):
            output_file = args[i + 1]
            skip_next = True
        elif arg == "--max" and i + 1 < len(args):
            max_videos = int(args[i + 1])
            skip_next = True

    sec_uid = extract_sec_uid(url)

    print("=" * 50)
    print("抖音用户视频收集器 - CDP 自动模式")
    print("=" * 50)
    print(f"用户 ID: {sec_uid}")
    print(f"用户主页: https://www.douyin.com/user/{sec_uid}")
    if max_videos:
        print(f"最大收集: {max_videos} 个")
    print()

    videos, notes = collect_via_cdp(
        sec_uid,
        cdp_port=cdp_port,
        max_videos=max_videos,
    )

    if not videos and not notes:
        print("\n未收集到任何视频或图集。")
        print("请确认 Chrome 中已登录 douyin.com 且当前页面是用户主页。")
        sys.exit(1)

    # 保存视频和图集（在打印之前，防止编码崩溃丢数据）
    notes_file = None

    if videos:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(videos, f, ensure_ascii=False, indent=2)
        print(f"\n视频已保存到: {output_file} ({len(videos)} 个)")

        ids_file = str(Path(output_file).with_suffix("")) + "_ids.json"
        with open(ids_file, "w") as f:
            json.dump([v["id"] for v in videos], f)
        print(f"ID 列表保存到: {ids_file}")

    if notes:
        notes_file = str(Path(output_file).with_suffix("")) + "_notes.json"
        with open(notes_file, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)
        print(f"图集已保存到: {notes_file} ({len(notes)} 个)")

    # 打印预览（捕获编码异常）
    if videos:
        try:
            print(f"\n前 5 个视频:")
            for v in videos[:5]:
                print(f"  [{v['id']}] {v['title'][:60]}")
            if len(videos) > 5:
                print(f"  ... 共 {len(videos)} 个 ...")
                print(f"后 3 个视频:")
                for v in videos[-3:]:
                    print(f"  [{v['id']}] {v['title'][:60]}")
        except UnicodeEncodeError:
            print(f"  (共 {len(videos)} 个，标题含特殊字符)")

    if notes:
        try:
            for n in notes[:3]:
                print(f"  [{n['id']}] {n['title'][:60]}")
            if len(notes) > 3:
                print(f"  ... 共 {len(notes)} 个")
        except UnicodeEncodeError:
            print(f"  (共 {len(notes)} 个，标题含特殊字符)")

    print(f"\n{'=' * 50}")
    print(f"下一步：用收集的数据批量下载")
    if videos:
        print(f"  视频: python douyin_batch_downloader.py {output_file} output/")
    if notes:
        print(f"  图集: python download_notes.py {notes_file} output/")


if __name__ == "__main__":
    main()
