import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_service import evaluate_url_relevance


class MockClaim:
    def __init__(self):
        self.claim = "Candidate has experience with Django and Python web development"


class MockRequirement:
    def __init__(self):
        self.name = "Django"
        self.description = "Experience with Django framework for web development"


def test_url_relevance():
    claim = MockClaim()
    requirement = MockRequirement()

    urls = [
        "https://github.com/johndoe",
        "https://linkedin.com/in/johndoe",
        "https://mlchousing.com",
        "https://afrinex.com",
        "https://johndoe.dev",
        "https://medium.com/@johndoe",
    ]

    print("Testing URL relevance evaluation...")
    print(f"Claim: {claim.claim}")
    print(f"Requirement: {requirement.name}")
    print(f"\nEvaluating {len(urls)} URLs...\n")

    try:
        results = evaluate_url_relevance(claim, requirement, urls)

        print("Results:")
        for result in results:
            print(f"  URL: {result['url']}")
            print(f"  Relevance: {result['relevance']}")
            print(f"  Reason: {result['reason']}")
            print()

        high_relevance = [r for r in results if r["relevance"] == "high"]
        print(f"High relevance URLs: {len(high_relevance)}")

        return True
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_url_relevance()
    sys.exit(0 if success else 1)


def test_url_relevance_is_deterministic_and_does_not_call_llm(monkeypatch):
    import services.llm_service as llm_service

    def fail_if_called():
        raise AssertionError("LLM client should not be used for URL relevance")

    monkeypatch.setattr(llm_service, "_get_client", fail_if_called)

    results = evaluate_url_relevance(
        MockClaim(),
        MockRequirement(),
        [
            "github.com/example",
            "https://github.com/example/project",
            "https://github.com/topics/django",
            "https://linkedin.com/in/example",
        ],
    )

    assert [item["relevance"] for item in results] == ["high", "high", "low", "low"]
