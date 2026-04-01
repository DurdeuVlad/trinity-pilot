"""Browser automation adapter."""
import asyncio
import re
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from browser_agent.main import run_browser_task
from browser_agent.core.io_models import BrowserAgentOutput
from ..adapter import TaskAdapter
from ..models import TaskInput, TaskResult, ExecutionLog


DEFAULT_CONTRACT_TIMEOUT_SECONDS = 600.0
AUTH_TOKENS = ("api_key_invalid", "invalid api key", "api key not valid", "unauthenticated", "authentication failed")
USER_ERROR_TOKENS = ("verification failed", "clarify", "need assistance", "unable to verify", "not visually confirmed")

_WIKIPEDIA_TOPIC_PATTERNS = (
    re.compile(r"wikipedia page for ([a-z0-9 _()-]+)", re.IGNORECASE),
    re.compile(r"wikipedia article for ([a-z0-9 _()-]+)", re.IGNORECASE),
    re.compile(r"navigate to (?:the )?[\"']?([a-z0-9 _()-]+)[\"']? page", re.IGNORECASE),
    re.compile(r"from (?:the )?[\"']([a-z0-9 _()-]+)[\"'] wikipedia page", re.IGNORECASE),
    re.compile(r"page of ([a-z0-9 _()-]+)", re.IGNORECASE),
    re.compile(r"search (?:the web )?for [\"']?([a-z0-9 _()-]+?) wikipedia[\"']?", re.IGNORECASE),
    re.compile(r"/wiki/([^\s/?#]+)", re.IGNORECASE),
)
_URL_PATTERN = re.compile(r"https?://[^\s)>\]\"']+", re.IGNORECASE)
_SEARCH_QUERY_PATTERNS = (
    re.compile(r"search(?: the web)? for ['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(
        r"search(?: the web)? for ([a-z0-9][^.,;\n]+?)(?:\s+(?:using|and|then|in|on)\b|$)",
        re.IGNORECASE,
    ),
    re.compile(r"searched for ['\"]([^'\"]+)['\"]", re.IGNORECASE),
)
_GENERIC_CONTENT_SCOPE_SELECTOR = (
    "main p, article p, [role='main'] p, .entry-content p, .post-content p, "
    ".article-content p, .content p, .prose p, section p"
)


def _extract_topic_from_text(text: str | None) -> str | None:
    if not text:
        return None

    for pattern in _WIKIPEDIA_TOPIC_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        topic = match.group(1).strip().strip(" .,!?:;")
        if "/wiki/" in match.group(0):
            topic = unquote(topic).replace("_", " ")
        if topic:
            return topic
    return None


def _extract_url_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = _URL_PATTERN.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?)")


def _extract_search_query_from_text(text: str | None) -> str | None:
    if not text:
        return None

    for pattern in _SEARCH_QUERY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        query = match.group(1).strip().strip(" .,!?:;")
        if query:
            return query
    return None


def _infer_wikipedia_topic(task: TaskInput) -> str | None:
    candidates: list[str] = [task.description, task.expected_outcome or ""]
    prior_results = task.context.get("_prior_results") or {}
    for prior in prior_results.values():
        if not isinstance(prior, dict):
            continue
        candidates.append(str(prior.get("desc", "")))
        candidates.append(str(prior.get("result", "")))

    for candidate in candidates:
        topic = _extract_topic_from_text(candidate)
        if topic:
            return topic
    return None


def _infer_target_url(task: TaskInput) -> str | None:
    candidates: list[str] = [task.description, task.expected_outcome or ""]
    prior_results = task.context.get("_prior_results") or {}
    for prior in prior_results.values():
        if not isinstance(prior, dict):
            continue
        candidates.append(str(prior.get("desc", "")))
        candidates.append(str(prior.get("result", "")))

    for candidate in candidates:
        url = _extract_url_from_text(candidate)
        if url:
            return url
    return None


def _infer_search_query(task: TaskInput) -> str | None:
    candidates: list[str] = [task.description, task.expected_outcome or ""]
    prior_results = task.context.get("_prior_results") or {}
    for prior in prior_results.values():
        if not isinstance(prior, dict):
            continue
        candidates.append(str(prior.get("desc", "")))
        candidates.append(str(prior.get("result", "")))

    for candidate in candidates:
        query = _extract_search_query_from_text(candidate)
        if query:
            return query
    return None


def _normalize_extracted_text(text: str) -> str:
    cleaned = re.sub(r"\[\d+\]", "", text or "")
    return " ".join(cleaned.split())


@dataclass(frozen=True)
class TextCandidate:
    """Visible text block metadata used for paragraph-like extraction."""

    text: str
    tag: str = "div"
    top: float = 0.0
    in_content_area: bool = False
    in_preferred_scope: bool = False
    block_child_count: int = 0
    link_density: float = 0.0

    @property
    def normalized_text(self) -> str:
        return _normalize_extracted_text(self.text)


def _select_first_meaningful_text(candidates: list[str], *, min_chars: int = 40) -> str:
    normalized = [_normalize_extracted_text(candidate) for candidate in candidates]
    for candidate in normalized:
        if len(candidate) >= min_chars:
            return candidate
    for candidate in normalized:
        if candidate:
            return candidate
    return ""


def _score_text_candidate(candidate: TextCandidate, *, min_chars: int = 40) -> float:
    text = candidate.normalized_text
    if not text:
        return float("-inf")

    words = text.split()
    word_count = len(words)
    sentence_count = max(1 if len(text) >= min_chars else 0, len(re.findall(r"[.!?](?:\s|$)", text)))
    lowered = text.lower()

    score = 0.0
    score += min(len(text), 320) / 8
    score += min(word_count, 60) * 1.1
    score += sentence_count * 12

    tag = candidate.tag.lower()
    if tag == "p":
        score += 18
    elif tag in {"blockquote", "article", "section"}:
        score += 10
    elif tag == "div":
        score += 6

    if candidate.in_content_area:
        score += 20
    if candidate.in_preferred_scope:
        score += 14

    if candidate.top < 80:
        score -= 18
    elif candidate.top < 700:
        score += 18
    elif candidate.top < 1600:
        score += 8
    else:
        score -= min((candidate.top - 1600) / 120, 35)

    score -= candidate.block_child_count * 8
    score -= candidate.link_density * 70

    if len(text) < min_chars:
        score -= 20
    if len(text) > 900:
        score -= 25
    if word_count < 8:
        score -= 18

    noisy_phrases = (
        "subscribe",
        "sign up",
        "cookie",
        "privacy policy",
        "all rights reserved",
        "table of contents",
        "jump to content",
        "share this",
        "follow us",
        "updated ",
        "last updated",
    )
    if any(phrase in lowered for phrase in noisy_phrases):
        score -= 35

    if re.fullmatch(r"(updated|posted|published)(?:\s+[a-z]+)?(?:\s+\d{1,2})?(?:,\s+\d{4})?", lowered):
        score -= 30

    if ":" in text and sentence_count == 1 and len(text) < 80:
        score -= 12

    return score


def _select_best_text_candidate(
    candidates: list[TextCandidate],
    *,
    min_chars: int = 40,
) -> TextCandidate | None:
    if not candidates:
        return None

    ranked = sorted(
        (
            (
                _score_text_candidate(candidate, min_chars=min_chars),
                candidate.in_preferred_scope,
                candidate.in_content_area,
                candidate.tag.lower() == "p",
                -candidate.top,
                -len(candidate.normalized_text),
                candidate,
            )
            for candidate in candidates
        ),
        reverse=True,
    )
    best_score, *_rest, best_candidate = ranked[0]
    if best_score == float("-inf"):
        return None
    return best_candidate


def _build_text_candidate(payload: dict) -> TextCandidate | None:
    text = str(payload.get("text", "") or "")
    if not _normalize_extracted_text(text):
        return None
    return TextCandidate(
        text=text,
        tag=str(payload.get("tag", "div") or "div"),
        top=float(payload.get("top", 0.0) or 0.0),
        in_content_area=bool(payload.get("in_content_area", False)),
        in_preferred_scope=bool(payload.get("in_preferred_scope", False)),
        block_child_count=int(payload.get("block_child_count", 0) or 0),
        link_density=float(payload.get("link_density", 0.0) or 0.0),
    )


async def _extract_first_meaningful_text(
    page,
    selector: str | None,
    *,
    timeout: int = 15000,
    min_chars: int = 40,
) -> str:
    wait_error: Exception | None = None
    scoped_candidates: list[str] = []
    paragraph = ""

    if selector:
        try:
            await page.wait_for_function(
                """
                ({ selector, minChars }) => {
                  const normalize = (value) =>
                    (value || "")
                      .replace(/\\[\\d+\\]/g, " ")
                      .replace(/\\s+/g, " ")
                      .trim();
                  const texts = Array.from(document.querySelectorAll(selector))
                    .map((node) => normalize(node.innerText || node.textContent || ""));
                  return texts.some((text) => text.length >= minChars) || texts.some((text) => text.length > 0);
                }
                """,
                {"selector": selector, "minChars": min_chars},
                timeout=timeout,
            )
        except Exception as exc:
            wait_error = exc

        scoped_candidates = await page.eval_on_selector_all(
            selector,
            """
            (nodes) => nodes.map((node) => node.innerText || node.textContent || "")
            """,
        )
        paragraph = _select_first_meaningful_text(scoped_candidates, min_chars=min_chars)

    candidate_payloads = await page.evaluate(
        """
        ({ selector }) => {
          const normalize = (value) =>
            (value || "")
              .replace(/\\[\\d+\\]/g, " ")
              .replace(/\\s+/g, " ")
              .trim();

          const isVisible = (node) => {
            if (!(node instanceof Element)) return false;
            const style = window.getComputedStyle(node);
            if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity || "1") === 0) {
              return false;
            }
            const rect = node.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          };

          const blockTags = new Set([
            "article", "aside", "blockquote", "div", "figcaption", "li", "main", "p", "section"
          ]);
          const contentSelector = "main, article, [role='main'], .mw-parser-output, #content, .content, .entry-content, .post-content";
          const generalSelector = [
            "main p",
            "article p",
            "[role='main'] p",
            ".mw-parser-output > p",
            "section p",
            "p",
            "blockquote",
            "main div",
            "article div",
            "[role='main'] div",
            "section div",
            "div"
          ].join(", ");
          const disallowedClosest = "nav, header, footer, aside, form, button, dialog, menu";
          const seen = new Set();
          const collected = [];

          const pushNode = (node, inPreferredScope) => {
            if (!(node instanceof Element) || !isVisible(node) || node.closest(disallowedClosest)) {
              return;
            }
            const tag = (node.tagName || "").toLowerCase();
            const text = normalize(node.innerText || node.textContent || "");
            if (!text) {
              return;
            }
            const rect = node.getBoundingClientRect();
            const blockChildCount = Array.from(node.children || []).filter((child) => {
              const childTag = (child.tagName || "").toLowerCase();
              return blockTags.has(childTag) && isVisible(child);
            }).length;
            const linkTextLength = Array.from(node.querySelectorAll("a"))
              .map((anchor) => normalize(anchor.innerText || anchor.textContent || "").length)
              .reduce((sum, length) => sum + length, 0);
            const signature = `${tag}:${text.slice(0, 160)}`;
            if (seen.has(signature)) {
              return;
            }
            seen.add(signature);
            collected.push({
              text,
              tag,
              top: rect.top + window.scrollY,
              in_content_area: Boolean(node.closest(contentSelector)),
              in_preferred_scope: inPreferredScope,
              block_child_count: blockChildCount,
              link_density: text.length ? linkTextLength / text.length : 0,
            });
          };

          if (selector) {
            Array.from(document.querySelectorAll(selector)).forEach((node) => pushNode(node, true));
          }
          Array.from(document.querySelectorAll(generalSelector)).forEach((node) => pushNode(node, false));
          return collected;
        }
        """,
        {"selector": selector or ""},
    )
    semantic_candidates = [
        candidate
        for payload in candidate_payloads
        if (candidate := _build_text_candidate(payload)) is not None
    ]
    semantic_choice = _select_best_text_candidate(semantic_candidates, min_chars=min_chars)
    if semantic_choice is not None:
        return semantic_choice.normalized_text
    if paragraph:
        return paragraph
    if wait_error is not None:
        raise wait_error
    return ""


async def _extract_wikipedia_first_paragraph(topic: str) -> str:
    url = f"https://en.wikipedia.org/wiki/{quote(topic.replace(' ', '_'))}"
    return await _extract_semantic_text_from_url(
        url,
        selector="#mw-content-text .mw-parser-output > p",
    )


async def _extract_semantic_text_from_url(
    url: str,
    *,
    selector: str | None = _GENERIC_CONTENT_SCOPE_SELECTOR,
) -> str:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            paragraph = await _extract_first_meaningful_text(
                page,
                selector,
                timeout=15000,
            )
        finally:
            await browser.close()

    if not paragraph:
        raise RuntimeError(f"Could not extract semantic paragraph text from '{url}'.")
    return paragraph


async def _extract_page_title_from_url(url: str) -> str:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            title = (await page.title()).strip()
        finally:
            await browser.close()

    if not title:
        raise RuntimeError(f"Could not read page title from '{url}'.")
    return title


async def _extract_first_search_result_title(query: str) -> tuple[str, str]:
    search_url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
    request = Request(
        search_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )

    with urlopen(request, timeout=15) as response:
        html = response.read().decode("utf-8", errors="replace")

    soup = BeautifulSoup(html, "html.parser")
    for selector in ("a.result__a", ".result__title a"):
        node = soup.select_one(selector)
        if node is None:
            continue
        title = _normalize_extracted_text(node.get_text(" ", strip=True))
        if title:
            return title, search_url

    raise RuntimeError(f"Could not extract the first search result title for '{query}'.")


def _open_wikipedia_topic_in_browser(topic: str) -> str:
    url = f"https://en.wikipedia.org/wiki/{quote(topic.replace(' ', '_'))}"
    if not webbrowser.open(url, new=2):
        raise RuntimeError(f"Could not open Wikipedia page for '{topic}' in the system browser.")
    return url


def _looks_like_semantic_paragraph_request(task: TaskInput) -> bool:
    description = f"{task.description or ''} {task.expected_outcome or ''}".lower()
    paragraph_terms = ("first paragraph", "opening paragraph", "lead paragraph", "intro paragraph")
    read_terms = ("copy", "read", "extract", "grab")
    return any(term in description for term in paragraph_terms) and any(
        term in description for term in read_terms
    )


def _looks_like_page_title_request(task: TaskInput) -> bool:
    description = f"{task.description or ''} {task.expected_outcome or ''}".lower()
    return "page title" in description or ("title" in description and "webpage" in description)


def _looks_like_search_request(task: TaskInput) -> bool:
    description = f"{task.description or ''} {task.expected_outcome or ''}".lower()
    return "search" in description and "wikipedia" not in description


def _looks_like_first_search_result_request(task: TaskInput) -> bool:
    description = f"{task.description or ''} {task.expected_outcome or ''}".lower()
    return "first search result" in description or "first result title" in description

class BrowserAdapter(TaskAdapter):
    """Adapter for browser-gui-automation module."""
    
    def __init__(self):
        self.module_name = "browser-gui-automation"

    def _effective_timeout(self, task: TaskInput) -> float:
        return float(task.timeout) if task.timeout is not None else DEFAULT_CONTRACT_TIMEOUT_SECONDS

    def _is_cancelled(self, task: TaskInput) -> bool:
        cancel_event = getattr(task, "cancel_event", None)
        return bool(cancel_event is not None and cancel_event.is_set())

    def _contract_metadata(self, task: TaskInput, *, effective_timeout: float, raw_result: dict | None = None) -> dict:
        metadata = {
            "module": self.module_name,
            "effective_timeout_seconds": effective_timeout,
            "effective_max_retries": task.max_retries,
        }
        if raw_result is not None:
            metadata["raw_result"] = raw_result
        return metadata

    def _contract_failure(self, task: TaskInput, *, effective_timeout: float, category: str, error: str) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            status="failure",
            category=category,
            error=error,
            execution_log=[],
            artifacts=[],
            metadata=self._contract_metadata(task, effective_timeout=effective_timeout),
        )

    def _normalize_category(self, status: str, error: str | None) -> str:
        if status == "success":
            return "success"
        if status == "need_assistance":
            return "user_error"

        lowered = (error or "").lower()
        if any(token in lowered for token in AUTH_TOKENS):
            return "auth_failure"
        if any(token in lowered for token in USER_ERROR_TOKENS):
            return "user_error"
        return "backend_error"

    async def _try_wikipedia_copy_fast_path(
        self,
        task: TaskInput,
        *,
        effective_timeout: float,
    ) -> TaskResult | None:
        description = (task.description or "").lower()
        if "first paragraph" not in description:
            return None

        prior_results = task.context.get("_prior_results") or {}
        combined_context = " ".join(
            [
                task.description or "",
                task.expected_outcome or "",
                *[
                    f"{prior.get('desc', '')} {prior.get('result', '')}"
                    for prior in prior_results.values()
                    if isinstance(prior, dict)
                ],
            ]
        ).lower()
        if "wikipedia" not in combined_context:
            return None

        topic = _infer_wikipedia_topic(task)
        if not topic:
            return None

        paragraph = await _extract_wikipedia_first_paragraph(topic)
        timestamp = datetime.now().isoformat()
        raw_result = {
            "fast_path": "wikipedia_first_paragraph",
            "topic": topic,
            "text_output": paragraph,
        }
        return TaskResult(
            task_id=task.task_id,
            status="success",
            category="success",
            error=None,
            execution_log=[
                ExecutionLog(
                    step=1,
                    action=f"Extract first paragraph from Wikipedia page for {topic}",
                    result="success",
                    details=paragraph,
                    timestamp=timestamp,
                )
            ],
            artifacts=[],
            metadata=self._contract_metadata(
                task,
                effective_timeout=effective_timeout,
                raw_result=raw_result,
            )
            | {"text_output": paragraph, "fast_path": "wikipedia_first_paragraph", "topic": topic},
        )

    async def _try_semantic_copy_fast_path(
        self,
        task: TaskInput,
        *,
        effective_timeout: float,
    ) -> TaskResult | None:
        if not _looks_like_semantic_paragraph_request(task):
            return None

        source_url = _infer_target_url(task)
        if not source_url:
            return None

        selector = "#mw-content-text .mw-parser-output > p" if "wikipedia.org" in source_url.lower() else _GENERIC_CONTENT_SCOPE_SELECTOR
        paragraph = await _extract_semantic_text_from_url(source_url, selector=selector)
        timestamp = datetime.now().isoformat()
        raw_result = {
            "fast_path": "semantic_first_paragraph",
            "source_url": source_url,
            "text_output": paragraph,
        }
        return TaskResult(
            task_id=task.task_id,
            status="success",
            category="success",
            error=None,
            execution_log=[
                ExecutionLog(
                    step=1,
                    action=f"Extract semantic paragraph text from {source_url}",
                    result="success",
                    details=paragraph,
                    timestamp=timestamp,
                )
            ],
            artifacts=[],
            metadata=self._contract_metadata(
                task,
                effective_timeout=effective_timeout,
                raw_result=raw_result,
            )
            | {"text_output": paragraph, "fast_path": "semantic_first_paragraph", "source_url": source_url},
        )

    async def _try_page_title_fast_path(
        self,
        task: TaskInput,
        *,
        effective_timeout: float,
    ) -> TaskResult | None:
        if not _looks_like_page_title_request(task):
            return None

        source_url = _infer_target_url(task)
        if not source_url:
            return None

        title = await _extract_page_title_from_url(source_url)
        output = f"Page title: {title}"
        timestamp = datetime.now().isoformat()
        raw_result = {
            "fast_path": "page_title",
            "source_url": source_url,
            "output": output,
        }
        return TaskResult(
            task_id=task.task_id,
            status="success",
            category="success",
            error=None,
            execution_log=[
                ExecutionLog(
                    step=1,
                    action=f"Read page title from {source_url}",
                    result="success",
                    details=title,
                    timestamp=timestamp,
                )
            ],
            artifacts=[],
            metadata=self._contract_metadata(
                task,
                effective_timeout=effective_timeout,
                raw_result=raw_result,
            )
            | {"output": output, "fast_path": "page_title", "source_url": source_url, "page_title": title},
        )

    async def _try_search_fast_path(
        self,
        task: TaskInput,
        *,
        effective_timeout: float,
    ) -> TaskResult | None:
        query = _infer_search_query(task)
        if not query:
            return None
        if not (_looks_like_search_request(task) or _looks_like_first_search_result_request(task)):
            return None

        first_title, search_url = await _extract_first_search_result_title(query)
        if _looks_like_first_search_result_request(task):
            output = first_title
            action = f"Extract first search result title for '{query}'"
        else:
            output = f"Searched the web for '{query}'. First result: {first_title}"
            action = f"Search DuckDuckGo for '{query}'"
        timestamp = datetime.now().isoformat()
        raw_result = {
            "fast_path": "search",
            "query": query,
            "search_url": search_url,
            "first_result_title": first_title,
            "output": output,
        }
        return TaskResult(
            task_id=task.task_id,
            status="success",
            category="success",
            error=None,
            execution_log=[
                ExecutionLog(
                    step=1,
                    action=action,
                    result="success",
                    details=output,
                    timestamp=timestamp,
                )
            ],
            artifacts=[],
            metadata=self._contract_metadata(
                task,
                effective_timeout=effective_timeout,
                raw_result=raw_result,
            )
            | {
                "output": output,
                "fast_path": "search",
                "query": query,
                "search_url": search_url,
                "first_result_title": first_title,
            },
        )

    async def _try_wikipedia_open_fast_path(
        self,
        task: TaskInput,
        *,
        effective_timeout: float,
    ) -> TaskResult | None:
        combined_context = " ".join(
            [
                task.description or "",
                task.expected_outcome or "",
            ]
        ).lower()
        if "wikipedia" not in combined_context:
            return None
        if (
            "open the wikipedia page" not in combined_context
            and "navigate to the wikipedia page" not in combined_context
            and "navigate to the" not in combined_context
            and "open wikipedia" not in combined_context
            and "search the web for" not in combined_context
        ):
            return None

        topic = _infer_wikipedia_topic(task)
        if not topic:
            return None

        url = _open_wikipedia_topic_in_browser(topic)
        timestamp = datetime.now().isoformat()
        raw_result = {
            "fast_path": "wikipedia_open",
            "topic": topic,
            "output": f"Opened {url}",
        }
        return TaskResult(
            task_id=task.task_id,
            status="success",
            category="success",
            error=None,
            execution_log=[
                ExecutionLog(
                    step=1,
                    action=f"Open Wikipedia page for {topic}",
                    result="success",
                    details=f"Opened {url}",
                    timestamp=timestamp,
                )
            ],
            artifacts=[],
            metadata=self._contract_metadata(
                task,
                effective_timeout=effective_timeout,
                raw_result=raw_result,
            )
            | {"output": f"Opened {url}", "fast_path": "wikipedia_open", "topic": topic},
        )

    async def _run_with_contract(
        self,
        task: TaskInput,
        *,
        effective_timeout: float,
    ) -> BrowserAgentOutput | TaskResult:
        prior_results = task.context.get("_prior_results")  # Layer 2
        browser_task = asyncio.create_task(
            run_browser_task(
                objective=task.description,
                session_id=task.task_id,
                expected_outcome=task.expected_outcome,
                max_retries=task.max_retries,
                prior_results=prior_results,
            )
        )
        deadline = asyncio.get_running_loop().time() + effective_timeout

        while True:
            if self._is_cancelled(task):
                browser_task.cancel()
                await asyncio.gather(browser_task, return_exceptions=True)
                return self._contract_failure(
                    task,
                    effective_timeout=effective_timeout,
                    category="cancelled",
                    error="Task cancelled before completion.",
                )

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                browser_task.cancel()
                await asyncio.gather(browser_task, return_exceptions=True)
                return self._contract_failure(
                    task,
                    effective_timeout=effective_timeout,
                    category="timeout",
                    error=f"Browser task timed out after {int(effective_timeout)}s.",
                )

            done, _ = await asyncio.wait({browser_task}, timeout=min(0.1, remaining))
            if done:
                return await browser_task
    
    async def execute(self, task: TaskInput) -> TaskResult:
        """Execute browser task using backend wrapper."""
        effective_timeout = self._effective_timeout(task)
        if self._is_cancelled(task):
            return self._contract_failure(
                task,
                effective_timeout=effective_timeout,
                category="cancelled",
                error="Task cancelled before execution started.",
            )

        try:
            open_fast_path_result = await self._try_wikipedia_open_fast_path(
                task,
                effective_timeout=effective_timeout,
            )
            if open_fast_path_result is not None:
                return open_fast_path_result

            fast_path_result = await self._try_wikipedia_copy_fast_path(
                task,
                effective_timeout=effective_timeout,
            )
            if fast_path_result is not None:
                return fast_path_result

            semantic_fast_path_result = await self._try_semantic_copy_fast_path(
                task,
                effective_timeout=effective_timeout,
            )
            if semantic_fast_path_result is not None:
                return semantic_fast_path_result

            page_title_fast_path = await self._try_page_title_fast_path(
                task,
                effective_timeout=effective_timeout,
            )
            if page_title_fast_path is not None:
                return page_title_fast_path

            search_fast_path = await self._try_search_fast_path(
                task,
                effective_timeout=effective_timeout,
            )
            if search_fast_path is not None:
                return search_fast_path

            typed_result = await self._run_with_contract(task, effective_timeout=effective_timeout)
            if isinstance(typed_result, TaskResult):
                return typed_result

            status = self._map_status(typed_result.result)
            category = self._normalize_category(status, typed_result.error_details)
            metadata = self._contract_metadata(
                task,
                effective_timeout=effective_timeout,
                raw_result=typed_result.model_dump(),
            )
            if typed_result.extracted_text:
                metadata["text_output"] = typed_result.extracted_text

            # Translate TaskInput to backend parameters
            return TaskResult(
                task_id=task.task_id,
                status=status,
                category=category,
                error=typed_result.error_details,
                execution_log=[
                    ExecutionLog(
                        step=i + 1,
                        action=str(action),
                        result="success",
                        details=typed_result.attempt_log.observations[i] if i < len(typed_result.attempt_log.observations) else None,
                        timestamp=datetime.now().isoformat()
                    )
                    for i, action in enumerate(typed_result.attempt_log.actions)
                ],
                artifacts=self._extract_artifacts(typed_result),
                metadata=metadata,
            )
        except Exception as e:
            return self._contract_failure(
                task,
                effective_timeout=effective_timeout,
                category="backend_error",
                error=f"Browser adapter error: {str(e)}",
            )
    
    async def health_check(self) -> bool:
        """Check if browser module is available."""
        try:
            from browser_agent.core.agent import BrowserAgent
            return True
        except ImportError:
            return False
    
    def get_capabilities(self) -> Dict:
        """Return browser module capabilities."""
        return {
            "domain": "web",
            "async": True,
            "thread_safe": True,
            "glass_box": True,
            "flight_reports": True,
            "platforms": ["Windows", "macOS", "Linux"]
        }
    
    def _map_status(self, result: str) -> str:
        """Map browser result to unified status."""
        mapping = {
            "success": "success",
            "failure": "failure",
            "need_assistance": "need_assistance"
        }
        return mapping.get(result.lower(), "failure")
    
    def _extract_artifacts(self, result: BrowserAgentOutput) -> List[str]:
        """Extract artifact paths from result."""
        artifacts = []
        if screenshot := result.screenshot_path:
            artifacts.append(screenshot)
        return artifacts
