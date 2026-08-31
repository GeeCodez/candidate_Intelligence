import asyncio
import importlib
import json
import logging
import os
from urllib.parse import urlparse

from asgiref.sync import sync_to_async
from dotenv import load_dotenv
from openai import OpenAI as OpenAIClient
load_dotenv()

from core.models import Evidence

logger = logging.getLogger(__name__)

MAX_SOURCES_PER_CLAIM = 5
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


def _is_github_source(source):
    host = urlparse(source.url).netloc.lower()
    return host == "github.com" or host.endswith(".github.com")


def select_relevant_sources(claim, requirement, sources):
    valid_sources = [
        source for source in sources
        if _valid_url(source.url) and _is_github_source(source)
    ]
    
    if not valid_sources:
        return []
    
    try:
        from services.llm_service import evaluate_url_relevance
        urls = [source.url for source in valid_sources]
        relevance_results = evaluate_url_relevance(claim, requirement, urls)
        
        relevance_map = {item["url"]: item["relevance"] for item in relevance_results}
        
        def combined_score(source):
            relevance = relevance_map.get(source.url, "low")
            keyword_score = _source_score(claim, requirement, source)
            
            if relevance == "high":
                return keyword_score + 10
            elif relevance == "medium":
                return keyword_score + 5
            else:
                return keyword_score
        
        ranked = sorted(
            valid_sources,
            key=combined_score,
            reverse=True,
        )
        
        logger.info(
            "LLM relevance filtering: %d sources evaluated, top %d selected",
            len(valid_sources),
            min(len(ranked), MAX_SOURCES_PER_CLAIM)
        )
        
        return ranked[:MAX_SOURCES_PER_CLAIM]
        
    except Exception as e:
        logger.warning("LLM relevance filtering failed, using keyword scoring: %s", e)
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
    
    # Create custom LLM7 provider since browser_use doesn't have OpenAI provider
    class LLM7Provider:
        """Custom LLM provider for browser_use using LLM7 instead of Gemini"""
        def __init__(self, api_key, base_url, model):
            self.client = OpenAIClient(
                api_key=api_key,
                base_url=base_url,
            )
            self.model = model
            self.model_name = model  # browser_use expects model_name
            self.name = "LLM7"
            # Add provider attribute that browser_use expects
            self.provider = "openai"  # Tell browser_use we're using OpenAI-compatible API
        
        async def ainvoke(self, messages, *args, **kwargs):
            """Async invoke method expected by browser_use (BaseChatModel interface)"""
            # Filter out unsupported kwargs that browser_use passes but OpenAI doesn't accept
            unsupported_kwargs = ['session_id', 'session', 'metadata', 'response_format']
            filtered_kwargs = {k: v for k, v in kwargs.items() if k not in unsupported_kwargs}
            
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        **filtered_kwargs
                    )
                )
                
                # Return a response object that browser_use expects with usage attribute
                class LLM7Response:
                    def __init__(self, content, usage=None):
                        self.content = content
                        self.usage = usage or {}
                
                usage = {
                    'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
                    'completion_tokens': response.usage.completion_tokens if response.usage else 0,
                    'total_tokens': response.usage.total_tokens if response.usage else 0
                }
                
                return LLM7Response(
                    content=response.choices[0].message.content,
                    usage=usage
                )
            except Exception as e:
                # Log the error for debugging
                logger.error(f"LLM7 API error: {str(e)}")
                # Return a fallback response to prevent agent from crashing
                class LLM7Response:
                    def __init__(self, content, usage=None):
                        self.content = content
                        self.usage = usage or {}
                
                return LLM7Response(
                    content=f"Error: Unable to process request due to API error: {str(e)}",
                    usage={}
                )
    
    llm = LLM7Provider(
        api_key=os.getenv("LLM7_API_KEY"),
        base_url="https://api.llm7.io/v1",
        model=os.getenv("LLM7_MODEL", "default"),
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

    task = _build_task(claim, requirement, selected_sources)
    logger.info("Investigating claim %s with %s source(s)", claim.id, len(selected_sources))

    try:
        Agent, llm = _load_browser_use_agent()
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
    for source in research["sources"]:
        evidence = await _create_evidence(claim.investigation_id, claim, source, evaluation)
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
