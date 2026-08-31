import json
import logging
import os
import time
from threading import Lock
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError, model_validator

load_dotenv()

logger = logging.getLogger(__name__)


# ============================================================
# RATE LIMITER
# ============================================================

class RateLimiter:
    def __init__(self, max_requests=100, time_window=60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self.lock = Lock()

    def wait_if_needed(self):
        with self.lock:
            now = time.time()

            self.requests = [
                request_time
                for request_time in self.requests
                if now - request_time < self.time_window
            ]

            if len(self.requests) >= self.max_requests:
                sleep_time = (
                    self.time_window
                    - (now - self.requests[0])
                    + 1
                )

                if sleep_time > 0:
                    time.sleep(sleep_time)

                self.requests = []

            self.requests.append(time.time())


RATE_LIMIT_MAX_REQUESTS = int(
    os.getenv("RATE_LIMIT_MAX_REQUESTS", "90")
)

RATE_LIMIT_TIME_WINDOW = int(
    os.getenv("RATE_LIMIT_TIME_WINDOW", "60")
)

_rate_limiter = RateLimiter(
    max_requests=RATE_LIMIT_MAX_REQUESTS,
    time_window=RATE_LIMIT_TIME_WINDOW,
)


# ============================================================
# LLM CONFIGURATION
# ============================================================

LLM7_BASE_URL = os.getenv(
    "LLM7_BASE_URL",
    "https://api.llm7.io/v1",
)

LLM7_MODEL = os.getenv(
    "LLM7_MODEL",
    "default",
)


# ============================================================
# EXCEPTIONS
# ============================================================


class LLMConfigurationError(Exception):
    pass


class LLMAPIError(Exception):
    pass


class LLMResponseError(Exception):
    pass


class LLMValidationError(Exception):
    pass


# ============================================================
# RESPONSE MODELS
# ============================================================


class RequirementItem(BaseModel):
    name: str = Field(
        description="Short name of the requirement"
    )

    description: str = Field(
        default="",
        description="What the requirement entails",
    )

    importance: Literal[
        "high",
        "medium",
        "low",
    ]


class ClaimItem(BaseModel):
    requirement: str = Field(
        description="Name of the matched requirement"
    )

    claim: str = Field(
        description="What the candidate claims"
    )

    source_from_cv: str = Field(
        default="",
        description="CV excerpt supporting the claim",
    )

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_claim_keys(cls, data):
        if not isinstance(data, dict):
            return data

        normalized = data.copy()

        if (
            "requirement" not in normalized
            and "name" in normalized
        ):
            normalized["requirement"] = normalized["name"]

        if "source_from_cv" not in normalized:
            for fallback_key in (
                "source",
                "evidence",
                "cv_source",
            ):
                if fallback_key in normalized:
                    normalized["source_from_cv"] = (
                        normalized[fallback_key]
                    )
                    break

        if "source_from_cv" not in normalized:
            normalized["source_from_cv"] = normalized.get(
                "claim",
                "",
            )

        return normalized


class EvidenceDetails(BaseModel):
    sources_checked: int = 0
    relevant_sources: int = 0
    key_findings: list[str] = Field(
        default_factory=list
    )


class EvidenceEvaluationResult(BaseModel):
    finding: str

    evidence_strength: Literal[
        "high",
        "medium",
        "low",
    ]

    status: Literal[
        "verified",
        "unverified",
    ]

    details: EvidenceDetails = Field(
        default_factory=EvidenceDetails
    )


class CandidateAnalysisResult(BaseModel):
    requirements: list[RequirementItem]

    claims: list[ClaimItem]

    urls: list[str] = Field(
        default_factory=list,
        description="Public URLs found in the CV",
    )


# ============================================================
# SYSTEM PROMPTS
# ============================================================

SYSTEM_INSTRUCTIONS = """
You are a recruitment data extraction assistant.

Your job is ONLY to extract information.

You MUST NOT verify candidate claims.

Tasks:

1. Extract job requirements from the Job Description.

2. Extract candidate claims from the CV that are relevant
   to those requirements.

3. Only include claims clearly supported by the CV text.

4. Match each claim to one extracted requirement.

5. Extract useful public URLs from the CV.

6. Normalize URLs to HTTPS.

Rules:

- Do not invent requirements.
- Do not invent claims.
- Do not invent URLs.
- Do not verify claims.
- Every requirement must contain:
  name, description, importance.
- Every claim must contain:
  requirement, claim, source_from_cv.
- Do not use "name" inside claim objects.
- importance must be high, medium, or low.
- Return ONLY JSON.

Top-level fields MUST be exactly:

requirements
claims
urls
"""



def _build_prompt(
    cv_text: str,
    job_description: str,
    extracted_urls: list[str],
) -> str:

    urls_section = (
        "\n".join(
            f"- {url}"
            for url in extracted_urls
        )
        if extracted_urls
        else "(none)"
    )

    return f"""
{SYSTEM_INSTRUCTIONS}

JOB DESCRIPTION
================

{job_description}


CV TEXT
=======

{cv_text}


PRE-EXTRACTED URLS
==================

{urls_section}


Return exactly:

{{
  "requirements": [],
  "claims": [],
  "urls": []
}}
"""


def _build_evidence_prompt(
    claim,
    requirement,
    research_findings: str,
) -> str:

    return f"""
You are a recruitment evidence evaluator.

You are evaluating ONE candidate claim.

Candidate claim:
{claim.claim}

Requirement:
{requirement.name} - {requirement.description or ""}

RAW BROWSER RESEARCH:
=====================

{research_findings}


OBJECTIVE
=========

Determine whether the supplied public GitHub research
contains sufficient evidence to support the candidate's claim.


IMPORTANT

You are NOT allowed to perform additional research.

Use ONLY the browser research above.

Do not invent:

- repositories
- URLs
- technologies
- employers
- projects
- deployment information
- counts
- dates
- facts


VERIFICATION RULE

"verified" means the supplied GitHub evidence sufficiently
supports the candidate claim.

"unverified" means the available GitHub evidence is
insufficient.

"unverified" does NOT mean the claim is false.


RETURN EXACTLY THIS JSON SHAPE:

{{
    "finding": "Concise explanation of the evidence",
    "evidence_strength": "high",
    "status": "verified",
    "details": {{
        "sources_checked": 0,
        "relevant_sources": 0,
        "key_findings": []
    }}
}}


Allowed evidence_strength values:

high
medium
low


Allowed status values:

verified
unverified


Return ONLY JSON.
"""


# ============================================================
# JSON HELPERS
# ============================================================

def _extract_json_from_markdown(content: str) -> str:
    if not content:
        return content

    content = content.strip()

    if content.startswith("```json"):
        content = content[len("```json"):]

    elif content.startswith("```"):
        content = content[len("```"):]

    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


def _parse_json(content: str) -> dict:
    content = _extract_json_from_markdown(content)

    try:
        return json.loads(content)

    except json.JSONDecodeError:

        # Attempt to locate the outermost JSON object.
        start = content.find("{")
        end = content.rfind("}")

        if start == -1 or end == -1:
            raise

        return json.loads(
            content[start:end + 1]
        )


# ============================================================
# URL HELPERS
# ============================================================


def _normalize_url(url: str) -> str:
    url = url.strip()

    if not url:
        return url

    if url.startswith("http://"):
        return "https://" + url[7:]

    if not url.startswith("https://"):
        return "https://" + url

    return url


def _merge_urls(
    llm_urls: list[str],
    extracted_urls: list[str],
) -> list[str]:

    seen = set()
    merged = []

    for url in llm_urls + extracted_urls:

        normalized = _normalize_url(url)

        if normalized and normalized not in seen:
            seen.add(normalized)
            merged.append(normalized)

    return merged


# ============================================================
# API CLIENT
# ============================================================


def _get_client() -> OpenAI:

    api_key = os.getenv("LLM7_API_KEY")

    if not api_key:
        raise LLMConfigurationError(
            "LLM7_API_KEY environment variable is not set."
        )

    return OpenAI(
        base_url=LLM7_BASE_URL,
        api_key=api_key,
    )


# ============================================================
# CANDIDATE EXTRACTION
# ============================================================


def analyze_candidate(
    cv_text: str,
    job_description: str,
    extracted_urls: list[str] | None = None,
) -> dict:

    if not cv_text or not cv_text.strip():
        raise LLMResponseError(
            "CV text is empty."
        )

    if not job_description or not job_description.strip():
        raise LLMResponseError(
            "Job description is empty."
        )

    extracted_urls = extracted_urls or []

    _rate_limiter.wait_if_needed()

    client = _get_client()

    prompt = _build_prompt(
        cv_text,
        job_description,
        extracted_urls,
    )

    try:

        response = client.chat.completions.create(
            model=LLM7_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_INSTRUCTIONS,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            response_format={
                "type": "json_object"
            },
            temperature=0.1,
            max_tokens=8000,
        )

    except Exception as e:

        raise LLMAPIError(
            f"LLM7 API request failed: {e}"
        ) from e

    content = response.choices[0].message.content

    if not content:
        raise LLMResponseError(
            "LLM7 returned an empty response."
        )

    try:

        data = _parse_json(content)

        result = CandidateAnalysisResult.model_validate(
            data
        )

    except (
        json.JSONDecodeError,
        ValidationError,
    ) as e:

        logger.error(
            "Invalid LLM response: %s",
            content[:2000],
        )

        raise LLMValidationError(
            f"Invalid structured output from LLM7: {e}"
        ) from e

    data = result.model_dump()

    data["urls"] = _merge_urls(
        data["urls"],
        extracted_urls,
    )

    return data


# ============================================================
# EVIDENCE EVALUATION
# ============================================================

def evaluate_evidence(
    claim,
    requirement,
    research_findings: str,
) -> dict:

    if (
        not research_findings
        or not research_findings.strip()
    ):
        raise LLMResponseError(
            "Browser research findings are empty."
        )

    _rate_limiter.wait_if_needed()

    client = _get_client()

    prompt = _build_evidence_prompt(
        claim,
        requirement,
        research_findings,
    )

    try:

        response = client.chat.completions.create(
            model=LLM7_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": """
You are a recruitment evidence evaluator.

Return exactly ONE JSON object.

Do not return markdown.
Do not return ```json.
Do not return arrays.
Do not add fields.
Do not perform additional research.
""",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=2000,
        )

    except Exception as e:

        raise LLMAPIError(
            f"LLM7 evidence evaluation failed: {e}"
        ) from e

    content = response.choices[0].message.content

    if not content:
        raise LLMResponseError("LLM7 returned an empty evidence response.")

    try:

        data = _parse_json(content)

        result = EvidenceEvaluationResult.model_validate(
            data
        )

    except (
        json.JSONDecodeError,
        ValidationError,
    ) as e:

        logger.error(
            "Invalid evidence response: %s",
            content[:2000],
        )

        raise LLMValidationError(
            f"Invalid evidence output from LLM7: {e}"
        ) from e

    return result.model_dump()
