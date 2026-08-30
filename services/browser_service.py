import asyncio
import importlib
import json
import logging
import os
from urllib.parse import urlparse

from asgiref.sync import sync_to_async

from core.models import Evidence

logger = logging.getLogger(__name__)

MAX_SOURCES_PER_CLAIM = 5
BROWSER_TIMEOUT_SECONDS = int(os.getenv("BROWSER_USE_TIMEOUT_SECONDS", "180"))


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


def select_relevant_sources(claim, requirement, sources):
    valid_sources = [source for source in sources if _valid_url(source.url)]
    ranked = sorted(
        valid_sources,
        key=lambda source: _source_score(claim, requirement, source),
        reverse=True,
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
- Start from the supplied URLs and follow only relevant internal links, sub-pages, GitHub repositories, README files, code files, project pages, and profile links needed to evaluate the claim.
- Do not browse unrelated domains or perform broad web search.
- Avoid duplicate URLs and skip inaccessible, private, deleted, or irrelevant pages after noting them.
- Gather concrete factual findings only. Do not decide verified/unverified.
- Do not invent evidence. If evidence is absent, say what was checked.
- Stop once enough useful evidence has been collected or the relevant sources are exhausted.

Return concise raw findings with: URLs visited, pages/repositories checked, relevant evidence found, inaccessible pages, and counts when possible.
"""


def _load_browser_use_agent():
    if not os.getenv("BROWSER_USE_API_KEY"):
        raise BrowserUseConfigurationError(
            "BROWSER_USE_API_KEY environment variable is not set."
        )
    browser_use = importlib.import_module("browser_use")
    Agent = getattr(browser_use, "Agent")
    llm_module = importlib.import_module("browser_use.llm")
    ChatGoogle = getattr(llm_module, "ChatGoogle")
    return Agent, ChatGoogle


async def investigate_claim(claim, requirement, sources):
    selected_sources = select_relevant_sources(claim, requirement, sources)
    if not selected_sources:
        return {
            "raw_findings": "No valid public source URLs were available for investigation.",
            "sources": [],
            "errors": [],
        }

    task = _build_task(claim, requirement, selected_sources)
    logger.info("Investigating claim %s with %s source(s)", claim.id, len(selected_sources))

    try:
        Agent, ChatGoogle = _load_browser_use_agent()
        llm = ChatGoogle(
            model=os.getenv(
                "BROWSER_USE_GEMINI_MODEL",
                os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
            )
        )
        agent = Agent(task=task, llm=llm)
        result = await asyncio.wait_for(agent.run(), timeout=BROWSER_TIMEOUT_SECONDS)
    except BrowserUseConfigurationError:
        raise
    except Exception as e:
        raise BrowserUseInvestigationError(f"Browser Use investigation failed: {e}") from e

    return {
        "raw_findings": str(result),
        "sources": selected_sources,
        "errors": [],
    }


async def _create_evidence(investigation, claim, source, evaluation):
    return await sync_to_async(Evidence.objects.create)(
        investigation=investigation,
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
        logger.warning("Gemini evidence evaluation failed for claim %s: %s", claim.id, e)
        return {
            "claim_id": claim.id,
            "status": "unverified",
            "evidence": [],
            "error": str(e),
            "research": research,
        }

    logger.info("Gemini evaluation for claim %s: %s", claim.id, json.dumps(evaluation))

    evidence_records = []
    if evaluation["status"] == "verified":
        for source in research["sources"]:
            evidence = await _create_evidence(claim.investigation, claim, source, evaluation)
            evidence_records.append(evidence)
            logger.info(
                "Saved evidence %s for claim %s and source %s",
                evidence.id,
                claim.id,
                source.id,
            )

    return {
        "claim_id": claim.id,
        "status": evaluation["status"],
        "evaluation": evaluation,
        "evidence": evidence_records,
        "research": research,
    }
