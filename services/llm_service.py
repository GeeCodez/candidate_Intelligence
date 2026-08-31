import json
import logging
import os
import time
from typing import Literal
from threading import Lock

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError, model_validator
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, max_requests=100, time_window=60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self.lock = Lock()
    
    def wait_if_needed(self):
        with self.lock:
            now = time.time()
            self.requests = [req_time for req_time in self.requests if now - req_time < self.time_window]
            
            if len(self.requests) >= self.max_requests:
                sleep_time = self.time_window - (now - self.requests[0]) + 1
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    self.requests = []
            
            self.requests.append(now)

_rate_limiter = RateLimiter(max_requests=90, time_window=60)

RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "90"))
RATE_LIMIT_TIME_WINDOW = int(os.getenv("RATE_LIMIT_TIME_WINDOW", "60"))

if RATE_LIMIT_MAX_REQUESTS != 90 or RATE_LIMIT_TIME_WINDOW != 60:
    _rate_limiter = RateLimiter(max_requests=RATE_LIMIT_MAX_REQUESTS, time_window=RATE_LIMIT_TIME_WINDOW)

# --- LLM Configuration ---

LLM7_BASE_URL = "https://api.llm7.io/v1"
LLM7_MODEL = os.getenv("LLM7_MODEL", "default")


# --- Custom Exceptions ---

class LLMConfigurationError(Exception):
    pass


class LLMAPIError(Exception):
    pass


class LLMResponseError(Exception):
    pass


class LLMValidationError(Exception):
    pass


# --- Pydantic Response Models ---

class RequirementItem(BaseModel):
    name: str = Field(description="Short name of the requirement, e.g. 'Django'")
    description: str = Field(
        default="",
        description="What the requirement entails",
    )
    importance: Literal["high", "medium", "low"]


class ClaimItem(BaseModel):
    requirement: str = Field(description="Name of the matched requirement")
    claim: str = Field(description="What the candidate claims, supported by the CV")
    source_from_cv: str = Field(
        default="",
        description="Excerpt from the CV that supports this claim",
    )

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_claim_keys(cls, data):
        if not isinstance(data, dict):
            return data

        normalized = data.copy()
        if "requirement" not in normalized and "name" in normalized:
            normalized["requirement"] = normalized["name"]

        if "source_from_cv" not in normalized:
            for fallback_key in ("source", "evidence", "cv_source"):
                if fallback_key in normalized:
                    normalized["source_from_cv"] = normalized[fallback_key]
                    break

        if "source_from_cv" not in normalized:
            normalized["source_from_cv"] = normalized.get("claim", "")

        return normalized


class EvidenceDetails(BaseModel):
    sources_checked: int = 0
    relevant_sources: int = 0
    key_findings: list[str] = Field(default_factory=list)


class URLRelevanceItem(BaseModel):
    url: str = Field(description="The URL being evaluated")
    relevance: Literal["high", "medium", "low"] = Field(description="How likely this URL contains evidence for the claim")
    reason: str = Field(description="Brief explanation of why this URL is or isn't relevant")


class EvidenceEvaluationResult(BaseModel):
    finding: str
    evidence_strength: Literal["high", "medium", "low"]
    status: Literal["verified", "unverified"]
    details: EvidenceDetails = Field(default_factory=EvidenceDetails)


class CandidateAnalysisResult(BaseModel):
    requirements: list[RequirementItem]
    claims: list[ClaimItem]
    urls: list[str] = Field(
        description="Public URLs found in the CV, normalized with https://"
    )


# --- System Instructions ---

SYSTEM_INSTRUCTIONS = """You are a recruitment data extraction assistant.

Extract and structure information only.
Do NOT verify claims.

Tasks:
1. Extract job requirements from the Job Description.
2. Extract candidate claims from the CV that are relevant to those requirements.
   Only include claims clearly supported by the CV text.
3. Match each claim to one of the extracted requirement names.
4. Extract all useful public URLs from the CV.
   Include URLs from the pre-extracted URL list that belong to the candidate.
5. Normalize all URLs to include the https:// prefix.
   Example: github.com/user becomes https://github.com/user.

Rules:
- Do not invent requirements, claims, or URLs.
- Do not verify whether claims are true.
- Use only high, medium, or low for requirement importance.
- Every requirement object MUST include: name, description, importance.
- Every claim object MUST include: requirement, claim, source_from_cv.
- Do NOT use name instead of requirement inside claim objects.
- Return ONLY valid JSON.
- The JSON must contain exactly these top-level fields:
  requirements, claims, urls.
"""


# --- Prompt Builders ---

def _build_prompt(
    cv_text: str,
    job_description: str,
    extracted_urls: list[str],
) -> str:
    urls_section = (
        "\n".join(f"- {url}" for url in extracted_urls)
        if extracted_urls
        else "(none)"
    )

    return f"""{SYSTEM_INSTRUCTIONS}

## Job Description

{job_description}

## CV Text

{cv_text}

## Pre-extracted URLs from PDF

{urls_section}

Return JSON in this exact shape:
{{
  "requirements": [
    {{
      "name": "Django",
      "description": "Experience building applications with Django",
      "importance": "high"
    }}
  ],
  "claims": [
    {{
      "requirement": "Django",
      "claim": "Candidate built a booking engine using Django",
      "source_from_cv": "Engineered a web-based accommodation booking engine using Python (Django)"
    }}
  ],
  "urls": ["https://github.com/example"]
}}
"""


def _build_evidence_prompt(
    claim,
    requirement,
    research_findings: str,
) -> str:

    return f"""You evaluate browser research about ONE candidate claim.

Claim:
{claim.claim}

Requirement:
{requirement.name} - {requirement.description or ''}

Browser research findings:
{research_findings}

Your task:

Determine whether the browser research provides sufficient public
evidence to support the candidate's claim.

Return EXACTLY ONE JSON OBJECT.

The JSON MUST have these fields:

{{
    "finding": "A concise explanation of what the evidence shows",
    "evidence_strength": "high",
    "status": "verified",
    "details": {{
        "sources_checked": 0,
        "relevant_sources": 0,
        "key_findings": []
    }}
}}

Rules:

- "finding" must be a string.
- "evidence_strength" MUST be exactly one of:
  "high", "medium", "low".
- "status" MUST be exactly one of:
  "verified", "unverified".
- "details.sources_checked" must be an integer.
- "details.relevant_sources" must be an integer.
- "details.key_findings" must be an array of strings.
- Use ONLY the browser research findings.
- Do NOT invent facts.
- Do NOT invent URLs.
- Do NOT invent repositories.
- Do NOT invent technologies.
- Do NOT invent employers.
- Do NOT invent counts.
- "verified" means the public evidence sufficiently supports the claim.
- "unverified" means the available public evidence is insufficient.
- "unverified" does NOT mean the claim is false.
- Do NOT return a "findings" array.
- Do NOT return multiple results.
- Return ONLY the single JSON object.
"""


def _build_url_relevance_prompt(
    claim,
    requirement,
    urls: list[str],
) -> str:
    urls_section = "\n".join(f"- {url}" for url in urls)
    return f"""Evaluate which URLs could contain evidence for a candidate claim.

Claim:
{claim.claim}

Requirement:
{requirement.name} - {requirement.description or ''}

URLs to evaluate:
{urls_section}

Your task:

For each URL, determine how likely it is to contain evidence supporting the claim.
Consider the URL structure, domain, and any visible context.

Return EXACTLY ONE JSON OBJECT with this structure:

{{
    "urls": [
        {{
            "url": "https://example.com",
            "relevance": "high",
            "reason": "GitHub profile likely contains code repositories"
        }}
    ]
}}

Rules:

- "relevance" MUST be exactly one of: "high", "medium", "low".
- "high" = very likely to contain relevant evidence (e.g., GitHub for tech claims, portfolio for design)
- "medium" = might contain some relevant information
- "low" = unlikely to contain evidence for this specific claim (e.g., checking a general company website for Java experience)
- Be conservative - if uncertain, use "medium" or "low"
- Do NOT visit the URLs.
- Base judgment only on the URL itself.
- Return ALL URLs in the input list.
- Do NOT add or remove URLs.
"""





# --- JSON Helpers ---

def _extract_json_from_markdown(content: str) -> str:
    if not content:
        return content
    
    content = content.strip()
    
    if content.startswith('```json'):
        content = content[7:]
    elif content.startswith('```'):
        content = content[3:]
    
    if content.endswith('```'):
        content = content[:-3]
    
    return content.strip()


def _fix_truncated_json(content: str) -> str:
    if not content:
        return content
    
    content = content.strip()
    
    # Count brackets to see if JSON is incomplete
    open_braces = content.count('{')
    close_braces = content.count('}')
    open_brackets = content.count('[')
    close_brackets = content.count(']')
    
    # Add missing closing brackets
    missing_braces = open_braces - close_braces
    missing_brackets = open_brackets - close_brackets
    
    fixed = content
    if missing_braces > 0:
        fixed += '}' * missing_braces
    if missing_brackets > 0:
        fixed += ']' * missing_brackets
    
    # Also fix common truncation patterns
    if fixed.endswith(','):
        fixed = fixed[:-1]
    
    return fixed


# --- URL Helpers ---

def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return url

    if url.startswith("http://"):
        return "https://" + url[7:]
    elif not url.startswith("https://"):
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


# --- API Client ---

def _get_client() -> OpenAI:
    api_key = os.getenv("LLM7_API_KEY")
    if not api_key:
        raise LLMConfigurationError("LLM7_API_KEY environment variable is not set.")

    return OpenAI(
        base_url=LLM7_BASE_URL,
        api_key=api_key,
    )


# --- Main Operations ---

def analyze_candidate(
    cv_text: str,
    job_description: str,
    extracted_urls: list[str] | None = None,
) -> dict:

    if not cv_text or not cv_text.strip():
        raise LLMResponseError("CV text is empty.")

    if not job_description or not job_description.strip():
        raise LLMResponseError("Job description is empty.")

    extracted_urls = extracted_urls or []
    _rate_limiter.wait_if_needed()
    client = _get_client()
    prompt = _build_prompt(cv_text, job_description, extracted_urls)

    try:
        response = client.chat.completions.create(
            model=LLM7_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=8000,
        )
    except Exception as e:
        raise LLMAPIError(f"LLM7 API request failed: {e}") from e

    content = response.choices[0].message.content
    if not content:
        raise LLMResponseError("LLM7 returned an empty response.")

    content = _extract_json_from_markdown(content)
    content = _fix_truncated_json(content)

    try:
        result = CandidateAnalysisResult.model_validate_json(content)
    except ValidationError as e:
        logger.error(f"LLM response content: {content[:500]}...")
        raise LLMValidationError(f"Invalid structured output from LLM7: {e}") from e

    data = result.model_dump()
    data["urls"] = _merge_urls(data["urls"], extracted_urls)

    return data


def evaluate_evidence(
    claim,
    requirement,
    research_findings: str,
) -> dict:

    if not research_findings or not research_findings.strip():
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

    schema = EvidenceEvaluationResult.model_json_schema()

    try:
        response = client.chat.completions.create(
            model=LLM7_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a recruitment evidence evaluation assistant. "
                        "You MUST return exactly one JSON object matching the "
                        "provided schema. "
                        "Do not return arrays. "
                        "Do not create a 'findings' field. "
                        "Do not add extra top-level fields."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        "IMPORTANT: Return exactly this JSON structure:\n"
                        f"{schema}"
                    ),
                },
            ],
            response_format={
                "type": "json_object"
            },
            temperature=0.0,
        )

    except Exception as e:
        raise LLMAPIError(
            f"LLM7 evidence evaluation failed: {e}"
        ) from e

    content = response.choices[0].message.content

    if not content:
        raise LLMResponseError(
            "LLM7 returned an empty evidence response."
        )

    content = _extract_json_from_markdown(content)
    
    try:
        result = EvidenceEvaluationResult.model_validate_json(
            content
        )

    except ValidationError as e:
        raise LLMValidationError(
            f"Invalid evidence output from LLM7: {e}\n"
            f"Raw LLM7 response: {content}"
        ) from e

    return result.model_dump()


def evaluate_url_relevance(
    claim,
    requirement,
    urls: list[str],
) -> list[dict]:

    if not urls:
        return []

    _rate_limiter.wait_if_needed()
    client = _get_client()

    prompt = _build_url_relevance_prompt(
        claim,
        requirement,
        urls,
    )

    try:
        response = client.chat.completions.create(
            model=LLM7_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a URL relevance evaluator. "
                        "You MUST return exactly one JSON object with a 'urls' array. "
                        "Each item must have 'url', 'relevance', and 'reason' fields."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
    except Exception as e:
        raise LLMAPIError(f"LLM7 URL relevance evaluation failed: {e}") from e

    content = response.choices[0].message.content

    if not content:
        raise LLMResponseError("LLM7 returned an empty URL relevance response.")

    content = _extract_json_from_markdown(content)
    
    try:
        data = json.loads(content)
        if "urls" not in data:
            raise LLMResponseError("Response missing 'urls' field")
        
        validated = []
        for item in data["urls"]:
            validated.append(URLRelevanceItem.model_validate(item).model_dump())
        
        return validated
    except (json.JSONDecodeError, ValidationError) as e:
        raise LLMValidationError(
            f"Invalid URL relevance output from LLM7: {e}\n"
            f"Raw LLM7 response: {content}"
        ) from e