import asyncio
import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from asgiref.sync import sync_to_async

from core.models import Evidence

logger = logging.getLogger(__name__)

MAX_SOURCES_PER_CLAIM = 5
MULTION_API_BASE_URL = os.getenv("MULTION_API_BASE_URL", "https://api.multion.ai")
MULTION_TIMEOUT_SECONDS = int(
    os.getenv("MULTION_TIMEOUT_SECONDS", os.getenv("BROWSER_USE_TIMEOUT_SECONDS", "180"))
)
MULTION_MAX_CONTINUE_STEPS = int(os.getenv("MULTION_MAX_CONTINUE_STEPS", "3"))


class BrowserUseConfigurationError(Exception):
    pass


class BrowserUseInvestigationError(Exception):
    pass


class MultiOnConfigurationError(BrowserUseConfigurationError):
    pass


class MultiOnInvestigationError(BrowserUseInvestigationError):
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


def _get_multion_api_key():
    api_key = os.getenv("MULTION_API_KEY") or os.getenv("BROWSER_USE_API_KEY")
    if not api_key:
        raise MultiOnConfigurationError(
            "MULTION_API_KEY environment variable is not set."
        )
    return api_key


def _multion_request(path, payload):
    url = f"{MULTION_API_BASE_URL.rstrip('/')}{path}"
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "X_MULTION_API_KEY": _get_multion_api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=MULTION_TIMEOUT_SECONDS) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise MultiOnInvestigationError(
            f"MultiOn API request failed with HTTP {e.code}: {error_body}"
        ) from e
    except URLError as e:
        raise MultiOnInvestigationError(f"MultiOn API request failed: {e}") from e

    try:
        return json.loads(response_body)
    except json.JSONDecodeError as e:
        raise MultiOnInvestigationError(
            f"MultiOn API returned invalid JSON: {response_body[:500]}"
        ) from e


def _browse_with_multion(task, start_url):
    payload = {"cmd": task, "url": start_url}
    responses = []

    for _ in range(MULTION_MAX_CONTINUE_STEPS + 1):
        response = _multion_request("/v1/web/browse", payload)
        responses.append(response)
        if response.get("status") != "CONTINUE":
            break
        if response.get("session_id"):
            payload["session_id"] = response["session_id"]

    return responses


def _format_multion_findings(responses):
    sections = []
    for index, response in enumerate(responses, start=1):
        sections.append(
            "\n".join(
                [
                    f"MultiOn step {index}:",
                    f"Status: {response.get('status', 'unknown')}",
                    f"URL: {response.get('url', 'unknown')}",
                    f"Session ID: {response.get('session_id', 'unknown')}",
                    f"Message: {response.get('message', '')}",
                ]
            )
        )
    return "\n\n".join(sections)


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
        responses = await asyncio.wait_for(
            asyncio.to_thread(_browse_with_multion, task, selected_sources[0].url),
            timeout=MULTION_TIMEOUT_SECONDS,
        )
    except BrowserUseConfigurationError:
        raise
    except BrowserUseInvestigationError:
        raise
    except Exception as e:
        raise MultiOnInvestigationError(f"MultiOn investigation failed: {e}") from e

    return {
        "raw_findings": _format_multion_findings(responses),
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
