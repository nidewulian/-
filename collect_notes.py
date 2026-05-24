#!/usr/bin/env python3
"""
收集用户主页的图片合集（notes）ID 和标题
用法: python collect_notes.py <用户主页URL> [选项]
"""
import re
import sys
import json
from playwright.sync_api import sync_playwright


def extract_sec_uid(url: str) -> str:
    m = re.search(r"/user/([^/?&]+)", url)
    if m:
        return m.group(1)
    raise ValueError(f"无法从URL中提取用户ID: {url}")


def collect_notes_from_page(sec_uid: str, cdp_port: int = 9222) -> list[dict]:
    """从 CDP 连接的 Chrome 页面 DOM 中提取 note ID 和标题"""
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{cdp_port}")

        # 找已打开的 douyin 用户页面
        pages = browser.contexts[0].pages
        best_page = None
        best_count = 0
        for pg in pages:
            if "douyin.com/user/" not in pg.url:
                continue
            try:
                count = pg.evaluate(
                    '() => document.querySelectorAll(\'[data-e2e="scroll-list"] li\').length'
                )
                if count > best_count:
                    best_count = count
                    best_page = pg
            except Exception:
                pass

        if best_page is None:
            for pg in pages:
                if "douyin.com/user/" in pg.url:
                    best_page = pg
                    break

        if best_page is None:
            print("未找到 douyin 用户页面")
            browser.close()
            return []

        print(f"从页面收集（当前有 {best_count} 个列表项）...")

        # 提取所有 /note/ 链接
        raw = best_page.evaluate("""
            () => {
                const items = document.querySelectorAll('[data-e2e="scroll-list"] li');
                const result = [];
                items.forEach(li => {
                    const link = li.querySelector('a');
                    const href = link ? link.getAttribute('href') : '';
                    const text = li.innerText.trim();
                    result.push({href: href, text: text.substring(0, 200)});
                });
                return JSON.stringify(result);
            }
        """)

        items = json.loads(raw)
        notes = []
        seen = set()

        for item in items:
            nm = re.search(r"/note/(\d+)", item["href"])
            if not nm or nm.group(1) in seen:
                continue
            nid = nm.group(1)
            seen.add(nid)

            lines = [l.strip() for l in item["text"].split("\n") if l.strip()]
            title = ""
            for line in lines:
                if re.match(r"^[\d.]+[万亿w万]?$", line):
                    continue
                if line and not title:
                    title = line
            notes.append({"id": nid, "title": title, "type": "note"})

        browser.close()

    return notes


def main():
    args = sys.argv[1:]
    if not args:
        print("用法: python collect_notes.py <用户主页URL> [选项]")
        print("选项:")
        print("  --cdp-port N  CDP 端口（默认 9222）")
        print("  -o FILE       输出文件")
        sys.exit(1)

    url = args[0]
    output_file = "collected_notes.json"
    cdp_port = 9222

    skip = False
    for i, arg in enumerate(args[1:], start=1):
        if skip:
            skip = False
            continue
        if arg == "--cdp-port" and i + 1 < len(args):
            cdp_port = int(args[i + 1])
            skip = True
        elif arg == "-o" and i + 1 < len(args):
            output_file = args[i + 1]
            skip = True

    sec_uid = extract_sec_uid(url)
    print(f"用户 ID: {sec_uid}")
    print(f"收集图片合集...")
    print()

    notes = collect_notes_from_page(sec_uid, cdp_port)

    if not notes:
        print("未找到图片合集")
        sys.exit(1)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)

    print(f"共收集 {len(notes)} 个图片合集")
    print(f"已保存: {output_file}")

    for n in notes[:5]:
        print(f"  [{n['id']}] {n['title'][:60]}")
    if len(notes) > 5:
        print(f"  ... 共 {len(notes)} 个")


if __name__ == "__main__":
    main()
