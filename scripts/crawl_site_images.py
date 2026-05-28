"""Краулер картинок с vomitboycom.neocities.org → data/site_images.json"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "site_images.json"

BASE = "https://vomitboycom.neocities.org/"
PAGES = ("/", "/gallery.html", "/articles.html", "/map.html")
SKIP_PATH_PARTS = ("/banners/",)

IMG_RE = re.compile(
    r"""(?:src|href|data-src|data-original)\s*=\s*["']([^"']+\.(?:jpg|jpeg|png|gif|webp|bmp)(?:\?[^"']*)?)["']""",
    re.I,
)
CSS_URL_RE = re.compile(
    r"""url\(\s*['"]?([^'"\)]+\.(?:jpg|jpeg|png|gif|webp|bmp)(?:\?[^'"\)]*)?)['"]?\s*\)""",
    re.I,
)


def normalize(page_url: str, raw: str) -> str | None:
    full = urljoin(page_url, raw.replace("\\", "/"))
    parsed = urlparse(full)
    if not parsed.netloc.endswith("neocities.org"):
        return None
    if any(part in parsed.path.lower() for part in SKIP_PATH_PARTS):
        return None
    return full


def crawl() -> list[str]:
    found: set[str] = set()
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for page in PAGES:
            url = urljoin(BASE, page)
            try:
                r = client.get(url)
                r.raise_for_status()
            except httpx.HTTPError as exc:
                print("FAIL", url, exc)
                continue
            for rx in (IMG_RE, CSS_URL_RE):
                for match in rx.findall(r.text):
                    norm = normalize(url, match)
                    if norm:
                        found.add(norm)
            print("OK", url, "total:", len(found))
    return sorted(found)


def main() -> None:
    urls = crawl()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"source": BASE, "urls": urls}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"saved {len(urls)} urls -> {OUT}")


if __name__ == "__main__":
    main()
