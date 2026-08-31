2026-08-31T00:00:00Z Started debugging claim verification errors from server logs; initial focus is async ORM writes in bulk verification and invalid LLM7 evidence schema responses.
2026-08-31T00:00:01Z Removed raw Pydantic JSON schema from evidence evaluation prompt because LLM7 was echoing the schema instead of producing an evidence object.
2026-08-31T00:00:02Z Changed async evidence creation to use claim.investigation_id instead of claim.investigation to avoid lazy ORM access in async verification.
2026-08-31T00:00:03Z Ran pytest -q; 11 tests passed and test_build_task_limits_claim_checks_to_public_github_repositories failed because the current task prompt lacks expected GitHub-only/time-limit wording.
2026-08-31T00:00:04Z Restored GitHub-only browser task guardrails including repository and 2m30s limits to satisfy existing browser_service tests.
2026-08-31T00:00:05Z Ran pytest -q after browser task prompt update; all 12 tests passed with two existing PytestReturnNotNone warnings.
2026-08-31T00:00:06Z Added a regression test ensuring the evidence prompt shows an instance JSON object and does not include Pydantic schema keys that LLM7 may echo.
2026-08-31T00:00:07Z Ran pytest -q after adding evidence prompt regression coverage; all 13 tests passed with two existing PytestReturnNotNone warnings.
2026-08-31T00:00:08Z Reviewed git diff; pending changes are AGENTS_LOG.md, browser_service async evidence/prompt guardrails, llm_service prompt cleanup, and prompt regression test.
