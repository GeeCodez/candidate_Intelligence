from types import SimpleNamespace

from services.browser_service import BROWSER_TIMEOUT_SECONDS, _build_task, select_relevant_sources


def test_select_relevant_sources_only_uses_github_sources():
    claim = SimpleNamespace(claim="Candidate has experience with Django.")
    requirement = SimpleNamespace(name="Django", description="Build Django APIs")
    sources = [
        SimpleNamespace(url="https://linkedin.com/in/example", source_type="other", title="LinkedIn"),
        SimpleNamespace(url="https://github.com/example", source_type="github", title="GitHub"),
        SimpleNamespace(url="https://example.com/portfolio", source_type="website", title="Portfolio"),
        SimpleNamespace(url="not-a-url", source_type="website", title="Broken"),
    ]

    selected = select_relevant_sources(claim, requirement, sources)

    assert [source.url for source in selected] == ["https://github.com/example"]


def test_build_task_limits_claim_checks_to_public_github_repositories():
    claim = SimpleNamespace(claim="Candidate has experience with Django.")
    requirement = SimpleNamespace(name="Django", description="Build Django APIs")
    sources = [SimpleNamespace(url="https://github.com/example", source_type="github", title="GitHub")]

    task = _build_task(claim, requirement, sources)

    assert "only GitHub public repositories" in task
    assert "Check up to 20 public repositories total" in task
    assert "check a minimum of 2" in task
    assert "2 minutes 30 seconds" in task
    assert "Do not use general web search" in task


def test_browser_timeout_defaults_to_two_minutes_thirty_seconds():
    assert BROWSER_TIMEOUT_SECONDS == 150


def test_load_browser_use_agent_uses_browser_use_openai_chat(monkeypatch):
    import services.browser_service as browser_service

    class FakeAgent:
        pass

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.provider = "openai"
            self.model = kwargs["model"]

    def fake_import_module(name):
        if name == "browser_use":
            return SimpleNamespace(Agent=FakeAgent)
        if name == "browser_use.llm.openai.chat":
            return SimpleNamespace(ChatOpenAI=FakeChatOpenAI)
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setenv("LLM7_API_KEY", "test-key")
    monkeypatch.setenv("LLM7_MODEL", "test-model")
    monkeypatch.setattr(browser_service.importlib, "import_module", fake_import_module)

    Agent, llm = browser_service._load_browser_use_agent()

    assert Agent is FakeAgent
    assert llm.kwargs == {
        "model": "test-model",
        "api_key": "test-key",
        "base_url": "https://api.llm7.io/v1",
        "temperature": 0.0,
        "max_completion_tokens": 4096,
        "dont_force_structured_output": True,
    }


def test_load_browser_use_agent_requires_llm7_key(monkeypatch):
    import pytest
    import services.browser_service as browser_service

    monkeypatch.delenv("LLM7_API_KEY", raising=False)

    with pytest.raises(browser_service.BrowserUseConfigurationError):
        browser_service._load_browser_use_agent()
