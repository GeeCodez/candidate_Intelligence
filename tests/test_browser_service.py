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
