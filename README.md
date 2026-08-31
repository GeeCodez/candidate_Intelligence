# Candidate Intelligence Agent

An AI-powered recruitment research agent that goes beyond the information provided on a candidate's CV by verifying claims against public evidence.

## Overview

A recruiter provides a **Job Description (JD)** and a **Candidate CV (PDF)**. The agent extracts structured information, investigates public sources, and produces evidence-backed assessments rather than simple match scores.

## Architecture Flow

```
RECRUITER
   │
   ├── Job Description
   └── Candidate CV (PDF)
          │
          ▼
┌─────────────────────────┐
│  1. PDF EXTRACTION      │
│  PyMuPDF                │
└────────────┬────────────┘
             │
             ├── CV text
             └── URLs found
                    │
                    ▼
┌─────────────────────────┐
│  2. GEMINI              │
│  STRUCTURING            │
└────────────┬────────────┘
             │
             ├── Requirements
             ├── Candidate Claims
             └── Sources / URLs
                    │
                    ▼
┌─────────────────────────┐
│  3. DATABASE             │
│                          │
│ Investigation            │
│ Requirements             │
│ Candidate Claims         │
│ Sources                  │
└────────────┬────────────┘
             │
             ▼
      VERIFICATION STAGE
             │
             ▼
┌─────────────────────────┐
│  4. CLAIM VERIFICATION  │
│                         │
│ For each CandidateClaim │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  5. BROWSER USE         │
│                         │
│ Start with candidate    │
│ public URLs              │
│                         │
│ Follow relevant links   │
│ and sub-pages            │
└────────────┬────────────┘
             │
             ▼
      PUBLIC RESEARCH
             │
      ┌──────┼─────────┐
      ▼      ▼         ▼
   GitHub  Website   Portfolio
      │      │         │
      ▼      ▼         ▼
 Repositories
 README
 Code/files
 Project pages
             │
             ▼
┌─────────────────────────┐
│  6. RAW RESEARCH        │
│     FINDINGS             │
│                         │
│ Concrete facts found   │
│ from public sources     │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  7. GEMINI              │
│     EVIDENCE EVALUATION │
│                         │
│ Claim + Requirement     │
│ + Research Findings     │
└────────────┬────────────┘
             │
             ├── finding
             ├── evidence_strength
             ├── status
             └── details
                    │
                    ▼
┌─────────────────────────┐
│  8. EVIDENCE DATABASE   │
│                         │
│ Evidence                │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  9. FINAL RESULT        │
│                         │
│ Requirement             │
│ Evidence                │
│ Status                  │
└─────────────────────────┘
```

## Stage Details

### Stage 1 — PDF Extraction
**Technology:** PyMuPDF

PyMuPDF does not understand the candidate. It simply provides:
- CV text
- URLs found in the document

**Example Output:**
```
CV text: "John Doe - Senior Python Developer..."
URLs: ["github.com/GeeCodez", "mlchousing.com"]
```

### Stage 2 — Gemini Structuring
**Technology:** LLM7 (OpenAI-compatible API)

Gemini takes:
- Job Description
- CV text  
- Extracted URLs

And creates:
- **Requirement**: Job requirements extracted from JD
- **CandidateClaim**: What the candidate claims, supported by CV
- **Source**: Public URLs for verification

**Example Output:**
```json
{
  "requirements": [
    {
      "name": "Django",
      "description": "Experience building Django web applications",
      "importance": "high"
    }
  ],
  "claims": [
    {
      "requirement": "Django",
      "claim": "Candidate has experience building applications using Django",
      "source_from_cv": "Built Django applications for MLC Housing project"
    }
  ],
  "urls": ["https://github.com/GeeCodez", "https://mlchousing.com"]
}
```

**Important:** Gemini is NOT verifying anything here—only structuring information.

### Stage 3 — Database
**Technology:** Django ORM

We store the structured information in the database:
- **Investigation**: Main investigation record
- **Requirements**: Job requirements 
- **CandidateClaims**: Claims matched to requirements
- **Sources**: Public URLs for verification

### Stage 4 — Verification
This is where the agent starts working. For each CandidateClaim, we gather available sources (GitHub, websites, portfolios, etc.).

### Stage 5 — Browser Use
**Technology:** Browser Use

Browser Use is the investigator. It starts from supplied public sources:

**For GitHub:**
```
GitHub Profile → Repositories → Relevant repositories → 
Repository pages → README / files / technology evidence
```

**For websites:**
```
Website → Relevant pages → Projects / About / Technology pages
```

It gathers concrete facts. It should NOT conclude "Verified." Instead, it produces research like:

```
Investigated 8 repositories.
5 repositories are relevant to backend development.
4 repositories contain Django-related implementation.
3 repositories use Django REST Framework.
MLC Housing publicly describes Django as part of its technology stack.
```

### Stage 6 — Research Findings
This is the important middle layer. We now have:
- Claim
- Actual things discovered on the web

This is what we send to Gemini for evaluation.

### Stage 7 — Gemini Evidence Evaluation
**Technology:** LLM7 (OpenAI-compatible API)

Gemini evaluates only the evidence provided:

**Input:**
```
Requirement: Django
Claim: Candidate has experience building applications using Django.
Research: 8 repositories investigated, 5 relevant, Django found in 4, 
          DRF found in 3, MLC Housing uses Django
```

**Output:**
```json
{
  "finding": "4 of 8 investigated repositories contain Django-related implementation, with Django REST Framework present in 3 repositories. The candidate's MLC Housing project also publicly identifies Django.",
  "evidence_strength": "high",
  "status": "verified",
  "details": {
    "sources_checked": 8,
    "relevant_sources": 5,
    "key_findings": ["Django in 4 repos", "DRF in 3 repos", "MLC Housing uses Django"]
  }
}
```

This is where the final Verified / Unverified decision happens.

### Stage 8 — Evidence Database
**Technology:** Django ORM

We save the evaluation results:
- **Evidence**: investigation, claim, source, finding, evidence_strength, status, details

Multiple evidence records can exist per claim if multiple sources provide useful evidence.

### Stage 9 — Final UI
The recruiter sees a clean summary:

| Requirement | Evidence | Status |
|-------------|----------|---------|
| Python | 4 relevant repositories and production projects demonstrate Python usage | ✅ Verified |
| Django | 4 repositories contain Django implementations | ✅ Verified |
| AWS | EC2/RDS evidence found, but no evidence of S3/Lambda | ⚠️ Unverified |
| PostgreSQL | PostgreSQL found across multiple projects | ✅ Verified |

They can expand rows to see detailed evidence breakdowns.

## Key Architecture Principle

**Browser Use finds the evidence. Gemini interprets the evidence. Django stores the evidence.**

We do NOT introduce unnecessary abstractions like:
- Additional "reasoning agents"
- Vector databases
- RAG systems  
- Celery pipelines

Unless we actually hit a problem that requires them.

## Setup

### Prerequisites
- Python 3.8+
- Django 4.x
- LLM7 API key
- Browser Use API key (for verification stage)

### Installation

1. Clone the repository and navigate to the project directory
2. Create and activate a virtual environment
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and configure your API keys
5. Run migrations:
   ```bash
   python manage.py migrate
   ```
6. Start the development server:
   ```bash
   python manage.py runserver
   ```

### Environment Variables

Required variables in `.env`:
```
LLM7_API_KEY=your_llm7_api_key
LLM7_MODEL=default
BROWSER_USE_API_KEY=your_browser_use_api_key
BROWSER_USE_GEMINI_MODEL=gemini-3-flash-preview
DJANGO_KEY=True
```

## Current Implementation Status

✅ **Stage 1 (PDF Extraction):** Fully implemented  
✅ **Stage 2 (Gemini Structuring):** Fully implemented  
✅ **Stage 3 (Database):** Fully implemented  
🚧 **Stage 4-8 (Verification):** Ready for implementation  
🚧 **Stage 9 (Final UI):** Partially implemented  

## Usage

1. Access the web interface at `http://localhost:8000`
2. Upload a candidate CV (PDF)
3. Paste the job description
4. Click "Investigate Candidate"
5. Review the structured requirements and claims
6. (Coming soon) Trigger verification for specific claims
7. (Coming soon) View evidence-backed assessments

## Development

### Run Tests
```bash
python manage.py test
```

### Database Management
```bash
python manage.py makemigrations
python manage.py migrate
```

### Manual Claim Verification
For testing verification stages:
```bash
python manage.py verify_claim <claim_id>
```

## License

Confidential & Secure - Internal Use Only
