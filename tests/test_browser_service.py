import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from types import SimpleNamespace

from services.browser_service import (
    _format_multion_findings,
    select_relevant_sources,
)


def test_select_relevant_sources_prefers_github_for_django_claim():
    claim = SimpleNamespace(claim="Candidate has experience with Django.")
    requirement = SimpleNamespace(name="Django", description="Build Django APIs")
    sources = [
        SimpleNamespace(url="https://linkedin.com/in/example", source_type="other", title="LinkedIn"),
        SimpleNamespace(url="https://github.com/example", source_type="github", title="GitHub"),
        SimpleNamespace(url="not-a-url", source_type="website", title="Broken"),
    ]

    selected = select_relevant_sources(claim, requirement, sources)

    assert [source.url for source in selected] == [
        "https://github.com/example",
        "https://linkedin.com/in/example",
    ]


def test_format_multion_findings_includes_steps_and_messages():
    findings = _format_multion_findings([
        {
            "status": "DONE",
            "url": "https://github.com/example",
            "session_id": "session-1",
            "message": "Found a Django project in the README.",
        }
    ])

    assert "MultiOn step 1" in findings
    assert "Status: DONE" in findings
    assert "URL: https://github.com/example" in findings
    assert "Found a Django project" in findings
