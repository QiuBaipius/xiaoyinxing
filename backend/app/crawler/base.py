"""通用站点爬虫：抓取列表页 -> 提取详情链接 -> 解析正文 -> 结构化文档。

设计要点：
- 详情页 URL 统一为 content_{id}.html，用 content_id 作为去重主键。
- 正文清洗去掉脚本/样式/导航，保留标题、日期、正文纯文本。
- 输出 dict 与知识库入库字段对齐。
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .sites import Site, Column

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

DETAIL_PATTERN = re.compile(r"content[_-](\d+)\.html")
CONTENT_SELECTORS = [
    "div.article-content", "div.content", "div.article", "div.detail",
    "div.v_news_content", "div.TRS_Editor", "div#zoom", "div.main-content",
    "div.article_content", "td.article", "div.news-content",
]


def fetch(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def clean_text(node) -> str:
    for tag in node.find_all(["script", "style", "noscript"]):
        tag.decompose()
    text = node.get_text("\n", strip=True)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip()
    # 去站点名/栏目后缀
    t = re.sub(r"\s*(?:[-—–|]\s*东北财经大学.*|_[^_]*)$", "", t)
    # 去重复段（如 “标题 -- 标题 -- 站点名”）
    parts = re.split(r"\s*(?:--|——|—|－|\|)\s*", t)
    if len(parts) > 1:
        seen, out = set(), []
        for p in parts:
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        t = " - ".join(out[:2])
    return t.strip()


def extract_title(soup: BeautifulSoup) -> str:
    for sel in ["h1", ".article-title", ".newstitle", ".title"]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return _clean_title(el.get_text(" ", strip=True))
    if soup.title and soup.title.string:
        return _clean_title(soup.title.string)
    return ""


def extract_date(soup: BeautifulSoup, html: str) -> str:
    # 常见日期格式：2026.11.10 / 2026-11-10 / 2026年11月10日
    patterns = [
        r"20\d{2}[.\-/年]\s*\d{1,2}[.\-/月]\s*\d{1,2}日?",
        r"\d{1,2}[.\-/]\s*\d{1,2}",
    ]
    text = " ".join(
        el.get_text(" ", strip=True)
        for el in soup.select(".time, .date, .info, .pubdate, .article-info")
    )
    if not text:
        text = html
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return ""


def extract_content(soup: BeautifulSoup) -> str:
    for sel in CONTENT_SELECTORS:
        node = soup.select_one(sel)
        if node:
            text = clean_text(node)
            if len(text) > 50:
                return text
    # 兜底：取正文最长的容器
    best, best_len = "", 0
    for tag in soup.find_all(["div", "article", "section"]):
        text = clean_text(tag)
        if len(text) > best_len:
            best, best_len = text, len(text)
    return best


def parse_detail(url: str, source: str, category: str, audience: str) -> Optional[Dict]:
    """解析详情页，返回结构化文档 dict，失败返回 None。"""
    try:
        html = fetch(url)
        soup = BeautifulSoup(html, "lxml")
        title = extract_title(soup)
        content = extract_content(soup)
        if not content:
            content = clean_text(soup.body) if soup.body else ""
        date_str = extract_date(soup, html)
        m = DETAIL_PATTERN.search(url)
        content_id = m.group(1) if m else url

        return {
            "content_id": f"{source}:{content_id}",
            "title": title or content[:40],
            "url": url,
            "source": source,
            "category": category,
            "audience": audience,
            "date": date_str,
            "text": content,
        }
    except Exception:
        return None


def extract_links(html: str, base_url: str, column: Column, limit: int = 30) -> List[str]:
    """从列表页提取详情链接（去重、限幅）。"""
    soup = BeautifulSoup(html, "lxml")
    seen, links = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not column.list_href_pattern or not re.search(column.list_href_pattern, href):
            continue
        full = urljoin(base_url, href)
        if full in seen:
            continue
        seen.add(full)
        links.append(full)
        if len(links) >= limit:
            break
    return links


def crawl_column(site: Site, column: Column, limit: int = 30) -> List[Dict]:
    """抓取单个栏目，返回文档列表。"""
    docs: List[Dict] = []
    try:
        html = fetch(column.url)
    except Exception:
        return docs

    links = extract_links(html, site.base_url, column, limit)
    for url in links:
        doc = parse_detail(url, site.name, column.category, column.audience)
        if doc and doc["text"]:
            docs.append(doc)
        time.sleep(0.3)  # 礼貌限速
    return docs


def crawl_site(site: Site, limit_per_column: int = 30) -> List[Dict]:
    docs: List[Dict] = []
    for col in site.columns:
        docs.extend(crawl_column(site, col, limit_per_column))
    return docs


def crawl_all(limit_per_column: int = 30) -> List[Dict]:
    from .sites import SITES

    all_docs: List[Dict] = []
    for site in SITES:
        all_docs.extend(crawl_site(site, limit_per_column))
    return all_docs


FILE_EXT = re.compile(r"\.(pdf|doc|docx|xls|xlsx|zip|rar|png|jpe?g)$", re.I)


def crawl_files(limit: int = 30) -> List[Dict]:
    """抓取可下载文件（校历、表格、模板等）：从站点首页与下载专区提取文件链接。"""
    from .sites import SITES

    files: List[Dict] = []
    seen = set()
    for site in SITES:
        urls = [site.homepage]
        urls += [c.url for c in site.columns if "xzzq" in c.url or "download" in c.url.lower()]
        for url in urls:
            try:
                html = fetch(url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not FILE_EXT.search(href):
                    continue
                full = urljoin(site.base_url, href)
                if full in seen:
                    continue
                seen.add(full)
                name = a.get_text(" ", strip=True) or full.rsplit("/", 1)[-1]
                files.append({
                    "name": name, "url": full, "category": "file",
                    "source": site.name, "description": name,
                })
                if len(files) >= limit:
                    return files
            time.sleep(0.3)
    return files
