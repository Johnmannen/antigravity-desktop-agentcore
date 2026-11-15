"""Standalone iterative Deep Research engine for C:\\juno-agy.

Uses llm_router.py for resilient LLM calls, ddgs for live web search,
and BeautifulSoup for page extraction across a 2-round gap-filling loop.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "tools"
RESEARCH_DIR = ROOT / "docs" / "research"
sys.path.insert(0, str(TOOLS_DIR))

import llm_router  # noqa: E402

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JunoResearch/1.0"


def _parse_json_list(raw: str, fallback: list[str]) -> list[str]:
    """Extract a JSON string list from LLM output, tolerating markdown code fences."""
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        return fallback
    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except json.JSONDecodeError:
        pass
    return fallback


def _search_web(query: str, max_results: int = 3) -> list[dict[str, str]]:
    """Run a DuckDuckGo text search and return normalized hit dicts."""
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=max_results))
        return [
            {
                "title": str(h.get("title", "")).strip(),
                "url": str(h.get("href", "")).strip(),
                "snippet": str(h.get("body", "")).strip(),
            }
            for h in hits
            if h.get("href")
        ]
    except Exception:
        return []


def _fetch_page_text(url: str, max_chars: int = 2500) -> str:
    """Fetch a webpage and extract clean body text, returning empty string on failure."""
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=8.0,
        )
        if resp.status_code != 200 or "text/html" not in resp.headers.get("content-type", ""):
            return ""
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        return text[:max_chars]
    except Exception:
        return ""


def _gather_sources(queries: list[str], seen_urls: set[str], max_pages: int = 5) -> list[dict[str, str]]:
    """Search queries and fetch unique webpage excerpts up to max_pages."""
    candidates: list[dict[str, str]] = []
    for q in queries:
        for hit in _search_web(q, max_results=3):
            if hit["url"] not in seen_urls:
                seen_urls.add(hit["url"])
                candidates.append(hit)

    gathered: list[dict[str, str]] = []
    for item in candidates[:max_pages]:
        excerpt = _fetch_page_text(item["url"])
        gathered.append({
            "title": item["title"] or item["url"],
            "url": item["url"],
            "content": excerpt or item["snippet"],
        })
    return gathered


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def run_research(prompt: str, *, max_rounds: int = 2) -> dict:
    """Execute iterative multi-round research and save a cited Markdown report."""
    _log("[1/4] Planerar sökfrågor...")
    plan_res = llm_router.ask(
        f"Skapa exakt 3 konkreta webbsökfrågor (på engelska eller svenska beroende på ämne) för att besvara:\n{prompt}\n"
        'Svara ENBART med en JSON-lista av strängar, t.ex. ["query 1", "query 2", "query 3"].',
        system="Du är en noggrann forskningsplanerare.",
    )
    queries_r1 = _parse_json_list(plan_res["reply"], [prompt])[:3]

    seen_urls: set[str] = set()
    _log(f"[2/4] Söker varv 1 ({len(queries_r1)} frågor)...")
    sources = _gather_sources(queries_r1, seen_urls, max_pages=5)
    all_queries = list(queries_r1)

    if max_rounds >= 2 and sources:
        _log(f"[3/4] Luckanalys & följdsökning ({len(sources)} källor hittills)...")
        digest = "\n".join(f"- {s['title']}: {s['content'][:400]}" for s in sources)
        gap_res = llm_router.ask(
            f"Ursprunglig fråga: {prompt}\n\nHittills insamlat:\n{digest}\n\n"
            "Vilka 1–2 specifika kunskapsluckor eller motsägelser behöver kollas i en följdsökning? "
            'Svara ENBART med en JSON-lista av 1–2 sökfrågor, t.ex. ["follow-up query"].',
            system="Du är en kritisk faktagranskare.",
        )
        queries_r2 = _parse_json_list(gap_res["reply"], [])[:2]
        if queries_r2:
            all_queries.extend(queries_r2)
            sources.extend(_gather_sources(queries_r2, seen_urls, max_pages=4))

    if not sources:
        raise RuntimeError("Kunde inte hämta några webbsidor eller sökresultat.")

    numbered_sources = "\n\n".join(
        f"[{i}] {s['title']}\nURL: {s['url']}\nUtdrag: {s['content']}"
        for i, s in enumerate(sources, start=1)
    )

    _log(f"[4/4] Sammanställer rapport av {len(sources)} källor...")
    report_res = llm_router.ask(
        f"Forskningsuppdrag:\n{prompt}\n\nKällor:\n{numbered_sources}\n\n"
        "Skriv en tydlig, skannbar rapport på svenska med följande rubriker:\n"
        "1. Sammanfattning\n"
        "2. Bekräftade fakta (ange källnummer som [1], [2])\n"
        "3. Motsägelser & osäkerheter\n"
        "4. Rekommendation / nästa steg\n"
        "5. Källor (lista alla använda [n] med fullständig URL)\n"
        "Hitta aldrig på fakta eller URL:er som inte finns i källorna ovan.",
        system="Du är Junos Deep Research-analytiker. Var saklig, direkt och skannbar.",
    )

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "_", prompt.lower())[:36].strip("_") or "research"
    report_path = RESEARCH_DIR / f"{ts}_{slug}.md"

    header = f"# Deep Research: {prompt}\n\n*Genererad: {ts} UTC | Motor: {report_res['provider']} ({report_res['model']})*\n\n---\n\n"
    report_path.write_text(header + report_res["reply"] + "\n", encoding="utf-8")

    return {
        "status": "ok",
        "report_path": str(report_path),
        "queries_used": all_queries,
        "sources_count": len(sources),
        "provider": report_res["provider"],
        "model": report_res["model"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Juno-AGY Iterative Deep Research Engine")
    parser.add_argument("prompt", help="Finalized research prompt")
    parser.add_argument("--rounds", type=int, default=2, choices=[1, 2], help="Search rounds (1 or 2)")
    args = parser.parse_args()

    result = run_research(args.prompt, max_rounds=args.rounds)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
