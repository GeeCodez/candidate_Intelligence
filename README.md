**Candidate Intelligence Agent** is an AI-powered recruitment research agent that goes beyond the information provided on a candidate's CV.

A recruiter provides a **Job Description (JD)** and a **Candidate CV**.

The agent:

1. Extracts the requirements of the job.
2. Extracts the candidate's claims from their CV.
3. Matches the candidate's claims against the job requirements.
4. Identifies important claims that require verification.
5. Discovers public links provided by the candidate.
6. Investigates relevant public sources.
7. Collects concrete evidence supporting or failing to support candidate claims.
8. Compares the evidence against the job requirements.
9. Produces an evidence-backed candidate assessment.

The system **shows the evidence behind its assessment**, rather than simply generating a match score.


## Web investigation provider

Claim verification uses MultiOn to browse candidate-provided public URLs and collect raw findings for Gemini evaluation. Configure `MULTION_API_KEY` in the environment before running verification.
