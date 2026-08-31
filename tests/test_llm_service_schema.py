import json

from services.llm_service import CandidateAnalysisResult, _build_prompt


def test_candidate_analysis_accepts_legacy_llm_shape_from_error_log():
    content = json.dumps(
        {
            "requirements": [
                {"name": "Python", "importance": "high"},
            ],
            "claims": [
                {
                    "name": "Python",
                    "claim": "Built applications using Python",
                },
            ],
            "urls": [],
        }
    )

    result = CandidateAnalysisResult.model_validate_json(content).model_dump()

    assert result["requirements"] == [
        {"name": "Python", "description": "", "importance": "high"},
    ]
    assert result["claims"] == [
        {
            "requirement": "Python",
            "claim": "Built applications using Python",
            "source_from_cv": "Built applications using Python",
        },
    ]


def test_candidate_analysis_prompt_documents_required_nested_fields():
    prompt = _build_prompt(
        cv_text="Built Django APIs.",
        job_description="Need Django experience.",
        extracted_urls=[],
    )

    assert '"description": "Experience building applications with Django"' in prompt
    assert '"requirement": "Django"' in prompt
    assert '"source_from_cv"' in prompt
