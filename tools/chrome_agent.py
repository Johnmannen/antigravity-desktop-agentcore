"""Visual Google Chrome automation tool for C:\\juno-agy.

Runs Google Chrome visibly (headless=False, channel='chrome') with an isolated
persistent profile, visible cursor overlay, and automatic routing through
desktop_bridge.py so windows open on John's real desktop and stay open.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "tools"
PROFILE_DIR = ROOT / ".chrome-agent-profile"
SCREENSHOT_DIR = ROOT / "logs" / "chrome_screenshots"
sys.path.insert(0, str(TOOLS_DIR))

import bridge_client  # noqa: E402
import llm_router  # noqa: E402

CURSOR_SCRIPT = """
(() => {
  const addCursor = () => {
    if (document.getElementById('juno-cursor')) return;
    const dot = document.createElement('div');
    dot.id = 'juno-cursor';
    Object.assign(dot.style, {
      position: 'fixed', left: '20px', top: '20px', width: '18px', height: '18px',
      borderRadius: '50%', background: 'rgba(0, 229, 255, 0.85)',
      border: '2px solid #ffffff', boxShadow: '0 0 10px rgba(0, 229, 255, 0.9)',
      pointerEvents: 'none', zIndex: '2147483647', transform: 'translate(-50%, -50%)',
      transition: 'left 0.04s linear, top 0.04s linear'
    });
    (document.body || document.documentElement).appendChild(dot);
    window.addEventListener('mousemove', e => {
      dot.style.left = e.clientX + 'px';
      dot.style.top = e.clientY + 'px';
    }, {passive: true});
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', addCursor);
  else addCursor();
})();
"""


def _launch_context(playwright):
    """Launch a new visible Chrome window, falling back to an ephemeral window if profile is locked."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    stealth_args = [
        "--start-maximized",
        "--disable-blink-features=AutomationControlled",
    ]
    try:
        ctx = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            args=stealth_args,
            ignore_default_args=["--enable-automation"],
            no_viewport=True,
        )
    except Exception:
        browser = playwright.chromium.launch(
            channel="chrome",
            headless=False,
            args=stealth_args,
            ignore_default_args=["--enable-automation"],
        )
        ctx = browser.new_context(no_viewport=True)
    ctx.add_init_script(CURSOR_SCRIPT)
    return ctx


def _visual_sweep(page) -> None:
    """Move cursor smoothly and scroll slightly so activity is clearly visible."""
    page.bring_to_front()
    page.mouse.move(320, 240, steps=15)
    page.mouse.move(640, 380, steps=15)
    page.mouse.wheel(0, 260)


def _extract_page_summary(page, max_chars: int = 2000) -> dict:
    """Return title, final URL, text excerpt, and top links from the active page."""
    title = page.title()
    body_text = page.evaluate("() => (document.body ? document.body.innerText : '')")
    clean_text = " ".join(body_text.split())[:max_chars]
    links = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href]'))
            .slice(0, 12)
            .map(a => ({text: (a.innerText || '').trim().slice(0, 80), href: a.href}))
            .filter(x => x.text && x.href.startsWith('http'))"""
    )
    return {"title": title, "url": page.url, "excerpt": clean_text, "links": links}


def _sync_notebooklm_storage(ctx) -> None:
    """Persist Playwright storage state to NotebookLM CLI profile when Google SID cookie is present."""
    try:
        state = ctx.storage_state()
        cookies = state.get("cookies", [])
        if any(c.get("name") == "SID" and "google" in c.get("domain", "") for c in cookies):
            nb_storage = Path.home() / ".notebooklm" / "profiles" / "default" / "storage_state.json"
            nb_storage.parent.mkdir(parents=True, exist_ok=True)
            nb_storage.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _emit_and_maybe_keep_open(ctx, payload: dict, args: argparse.Namespace) -> None:
    """Write result to file/stdout and keep Chrome open until John closes it if requested."""
    _sync_notebooklm_storage(ctx)
    if args.result_file:
        Path(args.result_file).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)

    if args.keep_open:
        ticks = 0
        try:
            while ctx.pages:
                ctx.pages[0].wait_for_timeout(500)
                ticks += 1
                if ticks % 4 == 0:
                    _sync_notebooklm_storage(ctx)
        except Exception:
            pass


def cmd_open(args: argparse.Namespace) -> None:
    """Open a URL visibly in Chrome and extract a summary."""
    with sync_playwright() as p:
        ctx = _launch_context(p)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(args.url, wait_until="domcontentloaded", timeout=20000)
            _visual_sweep(page)
            time.sleep(args.wait)
            summary = {"status": "ok", **_extract_page_summary(page)}
            if args.screenshot:
                SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
                shot_path = SCREENSHOT_DIR / f"chrome_{int(time.time())}.png"
                page.screenshot(path=str(shot_path))
                summary["screenshot"] = str(shot_path)
            _emit_and_maybe_keep_open(ctx, summary, args)
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def _expand_queries(raw_query: str) -> list[str]:
    """Use llm_router to build 1 compact, clean space-separated search string (1 tab)."""
    prompt = (
        f"Skapa exakt 1 kompakt, effektiv DuckDuckGo-söksträng för: {raw_query}\n"
        "Regler:\n"
        "- Använd ENBART vanliga ord med mellanslag (4–6 nyckelord totalt).\n"
        "- Använd ALDRIG parenteser (), OR, +, citattecken, kommatecken eller site:-operatorer.\n"
        "- Blanda gärna de 2 vanligaste stavningarna om det passar (t.ex. 'begagnad elscooter elsparkcykel Haninge').\n"
        'Svara ENBART med själva söksträngen, inget annat.'
    )
    try:
        res = llm_router.ask(prompt, system="Du skriver korta, effektiva söksträngar med vanliga ord.")
        cleaned = re.sub(r'[()+",`]', " ", res["reply"]).strip().splitlines()[0]
        cleaned = " ".join(cleaned.split())
        if cleaned:
            return [cleaned]
    except Exception:
        pass
    return [raw_query]


def cmd_search(args: argparse.Namespace) -> None:
    """Visually open DuckDuckGo search results in Chrome and collect top results."""
    queries = _expand_queries(args.query) if args.smart else [args.query]
    with sync_playwright() as p:
        ctx = _launch_context(p)
        try:
            all_results: list[dict[str, str]] = []
            seen_urls: set[str] = set()
            last_url = ""
            for idx, q in enumerate(queries):
                page = (ctx.pages[0] if ctx.pages else ctx.new_page()) if idx == 0 else ctx.new_page()
                search_url = f"https://duckduckgo.com/?q={quote_plus(q)}"
                page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                try:
                    page.wait_for_selector("article h2 a, a[data-testid='result-title-a']", timeout=6000)
                except Exception:
                    pass
                _visual_sweep(page)
                time.sleep(args.wait)
                last_url = page.url
                hits = page.evaluate(
                    """() => Array.from(document.querySelectorAll('a[data-testid="result-title-a"], article h2 a'))
                        .slice(0, 6)
                        .map(a => ({title: (a.innerText || '').trim(), url: a.href}))
                        .filter(x => x.title && x.url)"""
                )
                for h in hits:
                    if h["url"] not in seen_urls:
                        seen_urls.add(h["url"])
                        all_results.append({**h, "query": q})

            payload = {
                "status": "ok",
                "original_query": args.query,
                "queries_used": queries,
                "url": last_url,
                "results": all_results,
            }
            _emit_and_maybe_keep_open(ctx, payload, args)
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def _move_and_click_locator(page, locator, steps: int = 10) -> bool:
    """Move the visible cursor smoothly to the center of a locator and click it."""
    try:
        box = locator.bounding_box()
        if not box or box["width"] <= 0 or box["height"] <= 0:
            return False
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        page.mouse.move(cx, cy, steps=steps)
        page.mouse.click(cx, cy)
        return True
    except Exception:
        return False


def cmd_demo(args: argparse.Namespace) -> None:
    """Open a URL visibly, start and interact with a live demo/game, then report."""
    with sync_playwright() as p:
        ctx = _launch_context(p)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(args.url, wait_until="domcontentloaded", timeout=20000)
            page.bring_to_front()
            page.wait_for_timeout(300)

            start_btn = page.locator("#startBtn, button.btn-primary").first
            if start_btn.count() > 0 and start_btn.is_visible():
                _move_and_click_locator(page, start_btn, steps=10)
                page.wait_for_timeout(150)

            deadline = time.monotonic() + max(0.0, float(args.duration))
            demo_clicks = 0
            while time.monotonic() < deadline:
                target = page.locator(".hole.up:not(.decoy):not([data-kind='decoy'])").first
                if target.count() == 0 or not target.is_visible():
                    target = page.locator(".hole.up").first
                if target.count() > 0 and target.is_visible():
                    if _move_and_click_locator(page, target, steps=8):
                        demo_clicks += 1
                page.wait_for_timeout(120)

            screenshot_path = None
            if args.screenshot:
                SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
                shot_path = SCREENSHOT_DIR / f"chrome_demo_{int(time.time())}.png"
                page.screenshot(path=str(shot_path))
                screenshot_path = str(shot_path)

            page_info = _extract_page_summary(page)
            payload = {
                "status": "ok",
                "title": page_info["title"],
                "url": page_info["url"],
                "demo_clicks": demo_clicks,
                "excerpt": page_info["excerpt"],
                "screenshot": screenshot_path,
            }
            _emit_and_maybe_keep_open(ctx, payload, args)
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Juno-AGY Visual Chrome Agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in ("open", "search"):
        p_sub = sub.add_parser(name)
        p_sub.add_argument("target")
        p_sub.add_argument("--wait", type=float, default=1.5)
        p_sub.add_argument("--screenshot", action="store_true")
        p_sub.add_argument("--smart", action="store_true", help="Expand query into bilingual OR strings")
        p_sub.add_argument("--keep-open", action="store_true", help="Leave Chrome open after completion")
        p_sub.add_argument("--local", action="store_true", help="Run directly without bridge")
        p_sub.add_argument("--result-file", default=None)

    p_demo = sub.add_parser("demo")
    p_demo.add_argument("url")
    p_demo.add_argument("--duration", type=float, default=5.0)
    p_demo.add_argument("--keep-open", action="store_true", help="Leave Chrome open after completion")
    p_demo.add_argument("--screenshot", action="store_true")
    p_demo.add_argument("--local", action="store_true", help="Run directly without bridge")
    p_demo.add_argument("--result-file", default=None)

    args = parser.parse_args()
    if args.cmd == "open":
        args.url = args.target
    elif args.cmd == "search":
        args.query = args.target

    if not args.local and bridge_client.is_bridge_running():
        if args.cmd == "demo":
            forward_args = [args.cmd, args.url, "--duration", str(args.duration)]
        else:
            forward_args = [args.cmd, args.target, "--wait", str(args.wait)]
            if args.smart:
                forward_args.append("--smart")
        if args.screenshot:
            forward_args.append("--screenshot")
        res = bridge_client.run_via_bridge("chrome_agent", forward_args, keep_open=args.keep_open)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    {"open": cmd_open, "search": cmd_search, "demo": cmd_demo}[args.cmd](args)


if __name__ == "__main__":
    main()
