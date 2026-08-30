import os
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")


class LLMConfigurationError(Exception):
    pass


class LLMAPIError(Exception):
    pass


class LLMResponseError(Exception):
    pass


class LLMValidationError(Exception):
    pass


class RequirementItem(BaseModel):
    name: str = Field(description="Short name of the requirement, e.g. 'Django'")
    description: str = Field(description="What the requirement entails")
    importance: Literal["high", "medium", "low"]


class ClaimItem(BaseModel):
    requirement: str = Field(description="Name of the matched requirement")
    claim: str = Field(description="What the candidate claims, supported by the CV")
    source_from_cv: str = Field(
        description="Excerpt from the CV that supports this claim"
    )


class CandidateAnalysisResult(BaseModel):
    requirements: list[RequirementItem]
    claims: list[ClaimItem]
    urls: list[str] = Field(
        description="Public URLs found in the CV, normalized with https://"
    )


SYSTEM_INSTRUCTIONS = """You are a recruitment data extraction assistant. Extract and structure information only. Do NOT verify claims.

Tasks:
1. Extract job requirements from the Job Description.
2. Extract candidate claims from the CV that are relevant to those requirements. Only include claims clearly supported by the CV text.
3. Match each claim to one of the extracted requirement names.
4. Extract all useful public URLs from the CV. Include URLs from the pre-extracted URL list that belong to the candidate.
5. Normalize all URLs to include the https:// prefix (e.g. github.com/user becomes https://github.com/user).

Rules:
- Do not invent requirements, claims, or URLs.
- Do not verify whether claims are true.
- Use only high, medium, or low for requirement importance.
- Return only the requested structured JSON output."""


def _build_prompt(cv_text: str, job_description: str, extracted_urls: list[str]) -> str:
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
"""


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return url
    if url.startswith("http://"):
        url = "https://" + url[7:]
    elif not url.startswith("https://"):
        url = "https://" + url
    return url


def _merge_urls(llm_urls: list[str], extracted_urls: list[str]) -> list[str]:
    seen = set()
    merged = []
    for url in llm_urls + extracted_urls:
        normalized = _normalize_url(url)
        if normalized and normalized not in seen:
            seen.add(normalized)
            merged.append(normalized)
    return merged


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise LLMConfigurationError(
            "GEMINI_API_KEY environment variable is not set."
        )
    return genai.Client(api_key=api_key)


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
    client = _get_client()
    prompt = _build_prompt(cv_text, job_description, extracted_urls)

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=CandidateAnalysisResult.model_json_schema(),
    )

    try:
        chat = client.chats.create(model=GEMINI_MODEL, config=config)
        response = chat.send_message(prompt)
    except Exception as e:
        raise LLMAPIError(f"Gemini API request failed: {e}") from e

    if not response.text:
        raise LLMResponseError("Gemini returned an empty response.")

    try:
        result = CandidateAnalysisResult.model_validate_json(response.text)
    except ValidationError as e:
        raise LLMValidationError(
            f"Invalid structured output from Gemini: {e}"
        ) from e

    data = result.model_dump()
    data["urls"] = _merge_urls(data["urls"], extracted_urls)
    return data
