import asyncio
import importlib
import json
import logging
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from asgiref.sync import sync_to_async
from dotenv import load_dotenv

load_dotenv()

from core.models import Evidence

logger = logging.getLogger(__name__)

MAX_SOURCES_PER_CLAIM = 5
GITHUB_REPOSITORY_LIMIT = int(os.getenv("GITHUB_REPOSITORY_LIMIT", "20"))
GITHUB_REQUEST_TIMEOUT_SECONDS = int(os.getenv("GITHUB_REQUEST_TIMEOUT_SECONDS", "12"))
BROWSER_TIMEOUT_SECONDS = int(os.getenv("BROWSER_USE_TIMEOUT_SECONDS", "150"))
LLM7_MODEL = os.getenv("LLM7_MODEL", "default")


class BrowserUseConfigurationError(Exception):
    pass


class BrowserUseInvestigationError(Exception):
    pass


def _valid_url(url):
    parsed = urlparse((url or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _source_score(claim, requirement, source):
    text = f"{claim.claim} {requirement.name} {requirement.description or ''}".lower()
    url = source.url.lower()
    title = (source.title or "").lower()
    source_type = (source.source_type or "").lower()
    score = 0
    if source_type == "github" or "github.com" in url:
        score += 5
    if source_type in {"portfolio", "website"}:
        score += 2
    for token in set(text.replace("/", " ").replace("-", " ").split()):
        if len(token) > 3 and (token in url or token in title):
            score += 1
    return score


def _github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "candidate-intelligence-agent",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_api_get(path: str):
    request = Request(
        f"https://api.github.com{path}",
        headers=_github_headers(),
    )
    with urlopen(request, timeout=GITHUB_REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _is_github_source(source):
    host = urlparse(source.url).netloc.lower()
    return host == "github.com"


def _github_url_kind(url: str):
    """Return ('profile', owner, None) or ('repo', owner, repo) for safe GitHub URLs."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) == 1 and re.fullmatch(r"[A-Za-z0-9_.-]+", parts[0]):
        return ("profile", parts[0], None)
    if len(parts) >= 2 and all(
        re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts[:2]
    ):
        if parts[0].lower() not in {
            "topics",
            "trending",
            "marketplace",
            "orgs",
            "explore",
            "features",
            "settings",
        }:
            return ("repo", parts[0], parts[1])
    return None


def _repo_is_open_source(repo: dict) -> tuple[bool, str]:
    if repo.get("private") is True:
        return False, "repository is private"
    license_info = repo.get("license") or {}
    spdx_id = license_info.get("spdx_id")
    license_name = license_info.get("name")
    if not spdx_id or spdx_id == "NOASSERTION":
        return False, "no recognized open-source license is reported by GitHub"
    return True, f"license: {spdx_id or license_name}"


def _claim_tokens(claim, requirement):
    text = f"{getattr(claim, 'claim', '')} {getattr(requirement, 'name', '')} {getattr(requirement, 'description', '') or ''}".lower()
    stop = {
        "candidate",
        "experience",
        "using",
        "with",
        "that",
        "this",
        "have",
        "has",
        "and",
        "the",
        "for",
        "from",
        "built",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9+#.:-]{2,}", text)
        if token not in stop
    }


def _repo_relevance_score(repo: dict, tokens: set[str]) -> int:
    repo_text = " ".join(
        str(repo.get(key) or "")
        for key in ("name", "description", "language", "topics")
    ).lower()
    return sum(
        3 if token in (repo.get("name") or "").lower() else 1
        for token in tokens
        if token in repo_text
    )


def _safe_file_text(
    owner: str, repo: str, branch: str, path: str, max_chars: int = 12000
) -> tuple[str | None, str | None]:
    quoted_path = "/".join(quote(part) for part in path.split("/"))
    quoted_branch = quote(branch or "HEAD")
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{quoted_branch}/{quoted_path}"
    try:
        request = Request(url, headers={"User-Agent": "candidate-intelligence-agent"})
        with urlopen(request, timeout=GITHUB_REQUEST_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("content-type", "")
            if (
                "text" not in content_type
                and "json" not in content_type
                and "xml" not in content_type
            ):
                return None, "not a text file"
            return response.read(max_chars).decode("utf-8", errors="replace"), None
    except Exception as exc:
        return None, str(exc)


def _list_candidate_repos(selected_sources, claim, requirement):
    tokens = _claim_tokens(claim, requirement)
    repos, inaccessible, profiles_checked = [], [], []
    seen = set()

    for source in selected_sources:
        parsed = _github_url_kind(source.url)
        if not parsed:
            inaccessible.append(
                f"{source.url} - skipped because it is not a GitHub profile or repository URL"
            )
            continue
        kind, owner, repo_name = parsed
        try:
            if kind == "repo":
                repo = _github_api_get(f"/repos/{quote(owner)}/{quote(repo_name)}")
                candidates = [repo]
            else:
                profiles_checked.append(f"https://github.com/{owner}")
                candidates = _github_api_get(
                    f"/users/{quote(owner)}/repos?per_page=100&sort=updated"
                )
            for repo in candidates:
                full_name = repo.get("full_name")
                if full_name and full_name not in seen:
                    seen.add(full_name)
                    repos.append(repo)
        except HTTPError as exc:
            inaccessible.append(f"{source.url} - GitHub API returned HTTP {exc.code}")
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            inaccessible.append(f"{source.url} - {exc}")

    repos.sort(
        key=lambda repo: (
            _repo_relevance_score(repo, tokens),
            repo.get("updated_at") or "",
        ),
        reverse=True,
    )
    return repos[:GITHUB_REPOSITORY_LIMIT], inaccessible, profiles_checked


def _inspect_github_research(claim, requirement, selected_sources):
    tokens = _claim_tokens(claim, requirement)
    repos, inaccessible, profiles_checked = _list_candidate_repos(
        selected_sources, claim, requirement
    )
    checked, skipped, pages, evidence = [], [], [], []

    for repo in repos:
        html_url = repo.get("html_url")
        full_name = repo.get("full_name") or html_url
        is_open, reason = _repo_is_open_source(repo)
        if not is_open:
            skipped.append(f"{html_url} - skipped: {reason}")
            continue

        owner, repo_name = full_name.split("/", 1)
        checked.append(f"{html_url} ({reason})")
        if repo.get("description"):
            evidence.append(f"{html_url} description: {repo['description']}")
        if repo.get("language"):
            evidence.append(
                f"{html_url} primary language reported by GitHub: {repo['language']}"
            )
        topics = repo.get("topics") or []
        if topics:
            evidence.append(
                f"{html_url} topics reported by GitHub: {', '.join(topics[:10])}"
            )

        branch = repo.get("default_branch") or "main"
        for path in (
            "README.md",
            "requirements.txt",
            "pyproject.toml",
            "package.json",
            "Pipfile",
            "composer.json",
        ):
            text, err = _safe_file_text(owner, repo_name, branch, path)
            url = f"{html_url}/blob/{branch}/{path}"
            if text:
                pages.append(url)
                matching = sorted(token for token in tokens if token in text.lower())[
                    :8
                ]
                if matching:
                    evidence.append(
                        f"{url} contains claim/requirement terms: {', '.join(matching)}"
                    )
            elif path == "README.md" and err:
                inaccessible.append(f"{url} - {err}")

    starting = [source.url for source in selected_sources]
    return "\n".join(
        [
            "1. STARTING URLS",
            *[f"- {url}" for url in starting],
            "2. GITHUB PROFILE(S) CHECKED",
            *([f"- {url}" for url in profiles_checked] or ["- None"]),
            "3. REPOSITORIES CHECKED",
            *([f"- {item}" for item in checked] or ["- None"]),
            "4. RELEVANT PAGES / FILES CHECKED",
            *([f"- {item}" for item in pages] or ["- None"]),
            "5. CONCRETE EVIDENCE FOUND",
            *(
                [f"- {item}" for item in evidence]
                or [
                    "- No concrete matching evidence found in checked open-source repositories."
                ]
            ),
            "6. INACCESSIBLE PAGES",
            *([f"- {item}" for item in inaccessible] or ["- None"]),
            "7. REPOSITORIES SKIPPED AND WHY",
            *([f"- {item}" for item in skipped] or ["- None"]),
            "8. SUMMARY OF FACTUAL FINDINGS",
            f"- Checked {len(checked)} open-source repositories and {len(pages)} repository files/pages. No final verified/unverified decision is included.",
        ]
    )


def select_relevant_sources(claim, requirement, sources):
    valid_sources = [
        source
        for source in sources
        if _valid_url(source.url)
        and _is_github_source(source)
        and _github_url_kind(source.url)
    ]

    ranked = sorted(
        valid_sources,
        key=lambda source: _source_score(claim, requirement, source),
        reverse=True,
    )
    logger.info(
        "Deterministic GitHub source filtering: %d source(s), top %d selected",
        len(valid_sources),
        min(len(ranked), MAX_SOURCES_PER_CLAIM),
    )
    return ranked[:MAX_SOURCES_PER_CLAIM]


def _allowed_hosts(sources):
    hosts = []
    for source in sources:
        host = urlparse(source.url).netloc.lower()
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _build_task(claim, requirement, sources):
    source_lines = "\n".join(f"- {source.url}" for source in sources)
    hosts = ", ".join(_allowed_hosts(sources))
    return f"""Investigate a candidate claim using only the supplied public sources and relevant linked pages.

Claim: {claim.claim}
Requirement: {requirement.name} - {requirement.description or ''}
Allowed starting URLs:
{source_lines}
Allowed domains: {hosts}

Rules:
- Investigate only GitHub public repositories from the supplied URLs.
- Start from the supplied URLs and follow only relevant GitHub internal links, repositories, README files, code files, project pages, and profile links needed to evaluate the claim.
- Do not browse unrelated domains or perform broad web search.
- Do not use general web search.
- Check up to 20 public repositories total, and for profile pages check a minimum of 2 relevant repositories when available.
- Complete the investigation within 2 minutes 30 seconds.
- Avoid duplicate URLs and skip inaccessible, private, deleted, or irrelevant pages after noting them.
- Gather concrete factual findings only. Do not decide verified/unverified.
- Do not invent evidence. If evidence is absent, say what was checked.
- Stop once enough useful evidence has been collected, the relevant sources are exhausted, or the time/repository limits are reached.

Return concise raw findings with: URLs visited, pages/repositories checked, relevant evidence found, inaccessible pages, and counts when possible.
"""


def _load_browser_use_agent():
    if not os.getenv("LLM7_API_KEY"):
        raise BrowserUseConfigurationError(
            "LLM7_API_KEY environment variable is not set."
        )

    browser_use = importlib.import_module("browser_use")
    Agent = getattr(browser_use, "Agent")

    chat_module = importlib.import_module("browser_use.llm.openai.chat")
    ChatOpenAI = getattr(chat_module, "ChatOpenAI")

    llm = ChatOpenAI(
        model=os.getenv("LLM7_MODEL", "default"),
        api_key=os.getenv("LLM7_API_KEY"),
        base_url="https://api.llm7.io/v1",
        temperature=0.0,
        max_completion_tokens=4096,
        dont_force_structured_output=True,
    )

    return Agent, llm


async def investigate_claim(claim, requirement, sources):
    selected_sources = select_relevant_sources(claim, requirement, sources)
    if not selected_sources:
        return {
            "raw_findings": "No valid public source URLs were available for investigation.",
            "sources": [],
            "errors": [],
        }

    logger.info(
        "Investigating claim %s with %s deterministic GitHub source(s)",
        claim.id,
        len(selected_sources),
    )

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _inspect_github_research, claim, requirement, selected_sources
            ),
            timeout=BROWSER_TIMEOUT_SECONDS,
        )
    except Exception as e:
        raise BrowserUseInvestigationError(f"GitHub investigation failed: {e}") from e

    return {
        "raw_findings": result,
        "sources": selected_sources,
        "errors": [],
    }


async def _create_evidence(investigation_id, claim, source, evaluation):
    return await sync_to_async(Evidence.objects.create)(
        investigation_id=investigation_id,
        claim=claim,
        source=source,
        finding=evaluation["finding"],
        evidence_strength=evaluation["evidence_strength"],
        status=evaluation["status"],
        details=evaluation.get("details", {}),
    )


async def verify_claim(claim, requirement, sources):
    from services.llm_service import evaluate_evidence

    selected_sources = select_relevant_sources(claim, requirement, sources)
    if not selected_sources:
        return {
            "claim_id": claim.id,
            "status": "unverified",
            "evidence": [],
            "error": "No valid sources.",
        }

    try:
        research = await investigate_claim(claim, requirement, selected_sources)
    except Exception as e:
        logger.warning("Browser investigation failed for claim %s: %s", claim.id, e)
        research = {
            "raw_findings": f"Browser investigation failed: {e}",
            "sources": selected_sources,
            "errors": [str(e)],
        }

    logger.info("Raw research for claim %s: %s", claim.id, research["raw_findings"])

    try:
        evaluation = evaluate_evidence(claim, requirement, research["raw_findings"])
    except Exception as e:
        logger.warning(
            "Gemini evidence evaluation failed for claim %s: %s", claim.id, e
        )
        return {
            "claim_id": claim.id,
            "status": "unverified",
            "evidence": [],
            "error": str(e),
            "research": research,
        }

    logger.info("Gemini evaluation for claim %s: %s", claim.id, json.dumps(evaluation))

    evidence_records = []
    for source in research["sources"]:
        evidence = await _create_evidence(
            claim.investigation_id, claim, source, evaluation
        )
        evidence_records.append(evidence)
        logger.info(
            "Saved evidence %s for claim %s and source %s (status: %s)",
            evidence.id,
            claim.id,
            source.id,
            evaluation["status"],
        )

    return {
        "claim_id": claim.id,
        "status": evaluation["status"],
        "evaluation": evaluation,
        "evidence": evidence_records,
        "research": research,
    }
