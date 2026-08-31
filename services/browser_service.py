import asyncio
import importlib
import logging
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from asgiref.sync import sync_to_async
from dotenv import load_dotenv

from core.models import Evidence

load_dotenv()

logger = logging.getLogger(__name__)


# ============================================================
# Configuration
# ============================================================

MAX_SOURCES_PER_CLAIM = int(
    os.getenv("MAX_SOURCES_PER_CLAIM", "5")
)

MAX_REPOSITORIES_PER_CLAIM = int(
    os.getenv("MAX_REPOSITORIES_PER_CLAIM", "20")
)

BROWSER_TIMEOUT_SECONDS = int(
    os.getenv("BROWSER_USE_TIMEOUT_SECONDS", "150")
)

LLM7_MODEL = os.getenv(
    "LLM7_MODEL",
    "default",
)


# ============================================================
# Exceptions
# ============================================================

class BrowserUseConfigurationError(Exception):
    pass


class BrowserUseInvestigationError(Exception):
    pass


# ============================================================
# URL Helpers
# ============================================================

def _valid_url(url):
    parsed = urlparse(
        (url or "").strip()
    )

    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
    )


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
    if not _valid_url(source.url):
        return False

    host = urlparse(
        source.url
    ).netloc.lower()

    return (
        host == "github.com"
        or host.endswith(".github.com")
    )


def _github_url(url):
    return (
        _valid_url(url)
        and (
            urlparse(url).netloc.lower() == "github.com"
            or urlparse(url).netloc.lower().endswith(
                ".github.com"
            )
        )
    )


# ============================================================
# Source Selection
# ============================================================

def select_relevant_sources(
    claim,
    requirement,
    sources,
):
    """
    Select actual developer evidence starting points.

    We deliberately do NOT send every public CV URL to Browser Use.

    For this MVP, GitHub is the only starting source.

    Browser Use can then traverse:
        GitHub profile
            ↓
        repositories
            ↓
        README
            ↓
        source files
            ↓
        relevant internal GitHub pages
    """

    github_sources = [
        source
        for source in sources
        if _is_github_source(source)
    ]

    if not github_sources:
        return []

    # Remove duplicates while preserving order.
    unique_sources = []
    seen = set()

    for source in github_sources:

        normalized = source.url.rstrip("/")

        if normalized in seen:
            continue

        seen.add(normalized)
        unique_sources.append(source)

    return unique_sources[
        :MAX_SOURCES_PER_CLAIM
    ]


# ============================================================
# Allowed Domains
# ============================================================

def _allowed_hosts(sources):

    hosts = []

    for source in sources:

        host = urlparse(
            source.url
        ).netloc.lower()

        if host and host not in hosts:
            hosts.append(host)

    return hosts


# ============================================================
# Browser Use Task
# ============================================================

def _build_task(
    claim,
    requirement,
    sources,
):

    source_lines = "\n".join(
        f"- {source.url}"
        for source in sources
    )

    hosts = ", ".join(
        _allowed_hosts(sources)
    )

    return f"""
You are a public-source evidence investigator.

Your ONLY job is to investigate public developer evidence
for ONE candidate claim.

You are NOT the final evaluator.

Candidate claim:
{claim.claim}

Job requirement:
{requirement.name} - {requirement.description or ""}

Starting GitHub URLs:
{source_lines}

Allowed domains:
{hosts}

INVESTIGATION OBJECTIVE

Determine what publicly observable developer evidence exists
that could support the candidate's specific claim.

SOURCE RESTRICTIONS

- Start ONLY from the supplied GitHub URLs.
- Browse ONLY GitHub.
- Do NOT use Google.
- Do NOT perform general web searches.
- Do NOT visit LinkedIn.
- Do NOT visit social media.
- Do NOT visit unrelated personal websites.
- Do NOT navigate to unrelated external domains.
- Only follow relevant GitHub links.

TRAVERSAL RULES

If a supplied URL is a GitHub profile:

1. Inspect the profile.
2. Identify repositories that appear relevant to the claim.
3. Open relevant repositories.
4. Inspect their README/documentation.
5. Inspect relevant source files.
6. Inspect dependency/configuration files when useful.
7. Inspect project structure when useful.
8. Follow relevant GitHub internal links when necessary.

Do NOT inspect every repository blindly.

Prioritize repositories whose:
- name relates to the claim,
- description relates to the claim,
- README relates to the claim,
- technologies relate to the requirement,
- implementation appears relevant.

Repository limit:
{MAX_REPOSITORIES_PER_CLAIM}

INVESTIGATION RULES

- Gather factual observations only.
- Do NOT decide verified or unverified.
- Do NOT infer facts that are not visible.
- Do NOT invent technologies.
- Do NOT invent project ownership.
- Do NOT invent employers.
- Do NOT invent dates.
- Do NOT invent repository counts.
- If evidence is absent, report that clearly.
- If a page is inaccessible, record it.
- Avoid duplicate URLs.
- Stop when enough relevant evidence has been collected.

IMPORTANT

Evidence that only proves that a technology exists in a
repository should be recorded as such.

Do not transform:

"Django appears in requirements.txt"

into:

"Candidate built a Django application."

Return concise factual research containing:

1. STARTING URLS
2. GITHUB PROFILE(S) CHECKED
3. REPOSITORIES CHECKED
4. RELEVANT PAGES / FILES CHECKED
5. CONCRETE EVIDENCE FOUND
6. INACCESSIBLE PAGES
7. REPOSITORIES SKIPPED AND WHY
8. SUMMARY OF FACTUAL FINDINGS

Do not return a final verified/unverified decision.
"""


# ============================================================
# Browser Use Agent Loader
# ============================================================

def _load_browser_use_agent():

    if not os.getenv("LLM7_API_KEY"):
        raise BrowserUseConfigurationError(
            "LLM7_API_KEY environment variable is not set."
        )

    try:

        browser_use = importlib.import_module(
            "browser_use"
        )

        Agent = getattr(
            browser_use,
            "Agent",
        )

        chat_module = importlib.import_module(
            "browser_use.llm.openai.chat"
        )

        ChatOpenAI = getattr(
            chat_module,
            "ChatOpenAI",
        )

    except Exception as e:

        raise BrowserUseConfigurationError(
            f"Could not load Browser Use: {e}"
        ) from e

    try:

        llm = ChatOpenAI(
            model=LLM7_MODEL,
            api_key=os.getenv("LLM7_API_KEY"),
            base_url="https://api.llm7.io/v1",
            temperature=0.0,

            # IMPORTANT:
            #
            # Do NOT set:
            # dont_force_structured_output=True
            #
            # Browser Use 0.11.13 expects its own agent
            # output format. Allow Browser Use to manage
            # the structured action response.
            #
            # The previous setting allowed LLM7 to return
            # fenced Markdown JSON, which caused:
            #
            # Invalid JSON: expected value at line 1 column 1

            max_completion_tokens=4096,
        )

    except Exception as e:

        raise BrowserUseConfigurationError(
            f"Could not configure Browser Use LLM: {e}"
        ) from e

    return Agent, llm


# ============================================================
# Browser Investigation
# ============================================================

async def investigate_claim(
    claim,
    requirement,
    sources,
):
    """
    Run Browser Use against already-selected GitHub sources.

    IMPORTANT:
    This function does NOT call select_relevant_sources().
    Source selection happens exactly once in verify_claim().
    """

    selected_sources = [
        source
        for source in sources
        if _is_github_source(source)
    ]

    if not selected_sources:

        return {
            "raw_findings": (
                "No valid public GitHub source URLs "
                "were available for investigation."
            ),
            "sources": [],
            "errors": [],
        }

    task = _build_task(
        claim,
        requirement,
        selected_sources,
    )

    logger.info(
        "Investigating claim %s with %s GitHub source(s)",
        claim.id,
        len(selected_sources),
    )

    try:

        Agent, llm = _load_browser_use_agent()

        agent = Agent(
            task=task,
            llm=llm,
        )

        result = await asyncio.wait_for(
            agent.run(),
            timeout=BROWSER_TIMEOUT_SECONDS,
        )

    except BrowserUseConfigurationError:
        raise

    except asyncio.TimeoutError as e:

        raise BrowserUseInvestigationError(
            (
                "Browser Use investigation timed out "
                f"after {BROWSER_TIMEOUT_SECONDS} seconds."
            )
        ) from e

    except Exception as e:

        raise BrowserUseInvestigationError(
            f"Browser Use investigation failed: {e}"
        ) from e

    # --------------------------------------------------------
    # Extract useful Browser Use history
    # --------------------------------------------------------

    try:

        if hasattr(result, "final_result"):

            final_result = result.final_result()

            if final_result:
                raw_findings = str(
                    final_result
                )

            else:
                raw_findings = str(result)

        else:

            raw_findings = str(result)

    except Exception:

        raw_findings = str(result)

    if not raw_findings.strip():

        raise BrowserUseInvestigationError(
            "Browser Use returned no research findings."
        )

    logger.info(
        "Browser research completed for claim %s",
        claim.id,
    )

    return {
        "raw_findings": raw_findings,
        "sources": selected_sources,
        "errors": [],
    }


# ============================================================
# Evidence Database Helper
# ============================================================

async def _create_evidence(
    investigation_id,
    claim,
    source,
    evaluation,
):

    return await sync_to_async(
        Evidence.objects.create
    )(
        investigation_id=investigation_id,
        claim=claim,
        source=source,
        finding=evaluation["finding"],
        evidence_strength=evaluation[
            "evidence_strength"
        ],
        status=evaluation["status"],
        details=evaluation.get(
            "details",
            {},
        ),
    )


# ============================================================
# Claim Verification
# ============================================================

async def verify_claim(
    claim,
    requirement,
    sources,
):

    from services.llm_service import (
        evaluate_evidence,
    )

    # --------------------------------------------------------
    # STEP 1: Select GitHub sources ONCE
    # --------------------------------------------------------

    selected_sources = select_relevant_sources(
        claim,
        requirement,
        sources,
    )

    if not selected_sources:

        return {
            "claim_id": claim.id,
            "status": "unverified",
            "evidence": [],
            "error": (
                "No valid public GitHub sources "
                "were available."
            ),
        }

    logger.info(
        "Selected %s GitHub source(s) for claim %s",
        len(selected_sources),
        claim.id,
    )

    # --------------------------------------------------------
    # STEP 2: Browser investigation
    # --------------------------------------------------------

    try:

        research = await investigate_claim(
            claim,
            requirement,
            selected_sources,
        )

    except BrowserUseInvestigationError as e:

        logger.warning(
            "Browser investigation failed for claim %s: %s",
            claim.id,
            e,
        )

        # IMPORTANT:
        #
        # Do NOT send browser failure text to the
        # evidence evaluator.
        #
        # Browser failure != evidence.
        #

        return {
            "claim_id": claim.id,
            "status": "unverified",
            "evidence": [],
            "error": str(e),
        }

    except Exception as e:

        logger.exception(
            "Unexpected browser investigation error "
            "for claim %s",
            claim.id,
        )

        return {
            "claim_id": claim.id,
            "status": "unverified",
            "evidence": [],
            "error": str(e),
        }

    raw_findings = research.get(
        "raw_findings",
        "",
    )

    if not raw_findings.strip():

        return {
            "claim_id": claim.id,
            "status": "unverified",
            "evidence": [],
            "error": (
                "Browser Use completed without "
                "returning research findings."
            ),
            "research": research,
        }

    logger.info(
        "Raw research for claim %s: %s",
        claim.id,
        raw_findings,
    )

    # --------------------------------------------------------
    # STEP 3: LLM7 evaluates the evidence
    # --------------------------------------------------------

    try:

        evaluation = evaluate_evidence(
            claim,
            requirement,
            raw_findings,
        )

    except Exception as e:

        logger.warning(
            "LLM7 evidence evaluation failed "
            "for claim %s: %s",
            claim.id,
            e,
        )

        return {
            "claim_id": claim.id,
            "status": "unverified",
            "evidence": [],
            "error": str(e),
            "research": research,
        }

    logger.info(
        "LLM7 evaluation for claim %s: %s",
        claim.id,
        evaluation,
    )

    # --------------------------------------------------------
    # STEP 4: Save evidence
    # --------------------------------------------------------
    #
    # IMPORTANT:
    #
    # We currently have one claim-level evaluation and
    # selected starting sources.
    #
    # For the MVP, we associate the evaluation with the
    # starting source.
    #
    # Later, we can improve this by having Browser Use
    # return evidence grouped by repository URL.
    #

    evidence_records = []

    primary_source = selected_sources[0]

    evidence = await _create_evidence(
        claim.investigation_id,
        claim,
        primary_source,
        evaluation,
    )

    evidence_records.append(
        evidence
    )

    logger.info(
        "Saved evidence %s for claim %s "
        "and primary source %s (status: %s)",
        evidence.id,
        claim.id,
        primary_source.id,
        evaluation["status"],
    )

    # --------------------------------------------------------
    # STEP 5: Return final result
    # --------------------------------------------------------

    return {
        "claim_id": claim.id,
        "status": evaluation["status"],
        "evaluation": evaluation,
        "evidence": evidence_records,
        "research": research,
    }