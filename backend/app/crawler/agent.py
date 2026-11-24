"""采集 Agent：目标—规划—执行—检查 的自主采集闭环。

相比固定爬虫，Agent 的关键能力：
- 执行阶段用大模型判别每条新内容的相关性（是否与学生/教师相关、是否可被问询的
  操作性政策），过滤获奖报道等无关内容，而不是无差别全量入库；
- 检查阶段校验入库文本与原文一致性、核对采集完整性，通过后才算一次成功循环；
- 大模型不可用时自动降级为规则判定（过滤 news 类），保证系统始终可用。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from ..config import settings
from ..llm import GLMError, client
from ..kb.store import store
from ..service import ingest_documents, ingest_files
from .base import crawl_all, crawl_files, extract_content, extract_links, fetch
from .sites import CATEGORY_CN, SITES

logger = logging.getLogger("ginkgo.agent")

JUDGE_SYSTEM = (
    "你是校园知识库的采集审核 Agent。请判断一条网页内容是否值得收录进面向师生的 AI 校园助手知识库。\n"
    "【应当收录】与学生或教师相关、可能被问询、具有操作性的内容：通知公告、政策制度、办事指南/流程、"
    "选课/考试/课表安排、奖助贷、毕业学位、校园服务（图书馆/校园卡/宿舍/网络等）。\n"
    "【应当过滤】纯新闻、获奖成果报道、领导来访、活动宣传等与师生办事无关的内容。\n"
    "只输出一个 JSON 对象（不要 Markdown 代码块、不要解释），格式如下：\n"
    '{"relevant": true 或 false, "category": "分类键", "audience": "student/teacher/all", "reason": "一句话理由"}\n'
    f"category 必须是以下之一：{', '.join(CATEGORY_CN.keys())}"
)


def _parse_json(text: str) -> Optional[Dict]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


class CollectAgent:
    def __init__(self):
        self._llm_ok: Optional[bool] = None

    # ------------------------------------------------------------ LLM 可用性
    def _llm_available(self) -> bool:
        if self._llm_ok is None:
            try:
                client.chat([{"role": "user", "content": "仅回复：OK"}], max_tokens=5)
                self._llm_ok = True
            except Exception:  # noqa: BLE001
                self._llm_ok = False
        return self._llm_ok

    # ------------------------------------------------------------ 1. 目标
    def _define_goal(self) -> str:
        hours = "、".join(f"{h}:00" for h in sorted(settings.collect_hours)) or "上班时段"
        return (
            f"每天上班时段定时采集（{hours}），采集与学生、教师相关的、可能被问询的、"
            "操作性的通知政策要求，过滤获奖报道等无关内容，并自动分类入库。"
        )

    # ------------------------------------------------------------ 2. 规划
    def _plan(self) -> List[Dict]:
        plan = []
        for site in SITES:
            for col in site.columns:
                plan.append({
                    "step": "爬取", "site": site.name, "column": col.name,
                    "url": col.url, "category": col.category, "tool": "crawl_column",
                })
        plan.append({"step": "爬取附件", "tool": "crawl_files", "note": "校历/表格等可下载文件"})
        plan.append({"step": "判别", "tool": "GLM 相关性判断", "note": "过滤无关内容（获奖报道等）"})
        plan.append({"step": "入库", "tool": "知识库 store", "note": "按分类落入合适位置"})
        plan.append({"step": "检查", "tool": "一致性/完整性校验", "note": "通过则验收成功"})
        return plan

    # ------------------------------------------------------------ 3. 执行
    def _judge(self, doc: Dict) -> Dict:
        """LLM 判别相关性；不可用时降级为规则（过滤 news 类）。"""
        def rule():
            cat = doc.get("category", "general")
            return {
                "relevant": cat != "news",
                "category": cat,
                "audience": doc.get("audience", "all"),
                "reason": "规则降级：过滤新闻类",
            }
        if not self._llm_available():
            return rule()

        snippet = (doc.get("title", "") or "") + "\n" + ((doc.get("text", "") or "")[:1200])
        prompt = (
            f"来源：{doc.get('source', '')}｜原始栏目分类：{doc.get('category', '')}\n"
            f"内容：\n{snippet}\n\n请判断并输出 JSON。"
        )
        try:
            raw = client.chat(
                [{"role": "system", "content": JUDGE_SYSTEM},
                 {"role": "user", "content": prompt}],
                temperature=0, max_tokens=200,
            )
            data = _parse_json(raw)
            if not data or "relevant" not in data:
                return rule()
            cat = data.get("category", doc.get("category", "general"))
            if cat not in CATEGORY_CN:
                cat = doc.get("category", "general")
            aud = str(data.get("audience", "")).strip().lower()
            if aud not in ("student", "teacher", "all"):
                aud = "all"  # 归一化非标准值（如 student/teacher）
            return {
                "relevant": bool(data.get("relevant")),
                "category": cat,
                "audience": aud,
                "reason": data.get("reason", ""),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM 判别失败，降级规则：%s", e)
            return rule()

    def _execute(self) -> Dict:
        result = {
            "collected": 0, "new": 0, "relevant": 0, "filtered": 0,
            "ingested": 0, "files": 0, "content_ids": [], "filtered_titles": [],
        }
        docs = crawl_all()
        result["collected"] = len(docs)

        to_ingest = []
        for doc in docs:
            # 只对「新增或内容变化」的文档做判别，避免重复调用大模型
            if not store.is_new_or_changed(doc["content_id"], doc["text"]):
                continue
            result["new"] += 1
            dec = self._judge(doc)
            if dec["relevant"]:
                doc["category"] = dec["category"]
                doc["audience"] = dec["audience"]
                to_ingest.append(doc)
                result["relevant"] += 1
                result["content_ids"].append(doc["content_id"])
            else:
                result["filtered"] += 1
                result["filtered_titles"].append((doc.get("title") or "")[:40])

        if to_ingest:
            result["ingested"] = ingest_documents(to_ingest)
        try:
            result["files"] = ingest_files(crawl_files())
        except Exception as e:  # noqa: BLE001
            logger.warning("附件采集失败: %s", e)
        return result

    # ------------------------------------------------------------ 4. 检查
    def _check_completeness(self) -> Dict:
        """重新拉取列表页，统计应采详情链接的覆盖情况。"""
        total, covered = 0, 0
        for site in SITES:
            for col in site.columns:
                try:
                    html = fetch(col.url)
                    links = extract_links(html, site.base_url, col, limit=50)
                except Exception:  # noqa: BLE001
                    continue
                for url in links:
                    m = re.search(r"content[_-](\d+)\.html", url)
                    if not m:
                        continue
                    cid = f"{site.name}:{m.group(1)}"
                    total += 1
                    if store.has_document(cid):
                        covered += 1
        return {"total": total, "covered": covered}

    def _check_consistency(self, content_ids: List[str], sample: int = 3) -> Dict:
        """抽样重新抓取，比对入库文本与原文（规范化后）是否一致。"""
        if not content_ids:
            return {"sample": 0, "mismatch": 0}
        checked, mismatch = 0, 0
        for cid in content_ids[:sample]:
            doc = store.get_document_by_content_id(cid)
            if not doc or not doc.get("url"):
                continue
            try:
                html = fetch(doc["url"])
                new_text = extract_content(BeautifulSoup(html, "lxml"))
            except Exception:  # noqa: BLE001
                continue
            if new_text and _norm(new_text)[:3000] != _norm(doc.get("text", ""))[:3000]:
                mismatch += 1
            checked += 1
        return {"sample": checked, "mismatch": mismatch}

    def _verify(self, result: Dict) -> Dict:
        checks = []
        comp = self._check_completeness()
        checks.append(f"完整性：{comp['covered']}/{comp['total']} 条目标通知已入库")
        cons = self._check_consistency(result.get("content_ids", []), sample=3)
        checks.append(f"一致性：抽样 {cons['sample']} 条，{cons['mismatch']} 条与原文不一致")
        ok = (comp["covered"] >= comp["total"] * 0.9 if comp["total"] else True) and cons["mismatch"] == 0
        return {"verified": ok, "checks": checks}

    # ------------------------------------------------------------ 主循环
    def run(self) -> Dict:
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report = {
            "started_at": started,
            "goal": self._define_goal(),
            "plan": self._plan(),
            "success": False,
        }
        try:
            result = self._execute()
            report.update(result)
        except Exception as e:  # noqa: BLE001
            report["error"] = str(e)
            return report
        verify = self._verify(result)
        report["checks"] = verify["checks"]
        report["verified"] = verify["verified"]
        report["success"] = verify["verified"]
        return report


agent = CollectAgent()
