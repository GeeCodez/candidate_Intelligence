# Candidate Intelligence System - Architecture Flow

## System Overview

The Candidate Intelligence System evaluates CVs against job requirements using a two-step LLM process, providing evidence-based assessments with page references and detailed breakdowns.

## Complete Flow

```
USER UPLOADS
       │
       ▼
   CV (PDF)
       │
       ▼
2. PDF EXTRACTION
   PyMuPDF traverses every page
       │
       ├── Text
       ├── URLs
       └── Page numbers
       │
       ▼
3. JOB REQUIREMENTS
   User/system provides the job description
       │
       ▼
4. REQUIREMENT EXTRACTION (LLM #1)
   LLM reads the job description
       │
       ▼
   Structured requirements
       │
       ├── Requirement 1 (REQ-001)
       ├── Requirement 2 (REQ-002)
       ├── Requirement 3 (REQ-003)
       └── ...
       │
       ▼
5. CV + REQUIREMENTS ANALYSIS (LLM #2)
   LLM receives:
       │
       ├── Complete CV text
       └── Structured requirements
       │
       ▼
6. EVIDENCE MATCHING
   For EACH requirement:
       │
       ├── Find supporting evidence in CV
       ├── Determine status (MET/PARTIAL/NOT_MET)
       ├── Extract evidence text with page numbers
       └── Explain the decision
       │
       ▼
7. STRUCTURED EVALUATION
       │
       ├── Requirement ID
       ├── Evidence text
       ├── Page number
       ├── Status (MET/PARTIAL/NOT_MET)
       └── Breakdown explanation
       │
       ▼
8. VALIDATE
   Django validates LLM response
       │
       ▼
9. DATABASE
   Save evaluation
       │
       ▼
10. FRONTEND
    Display final evaluation
```

## Two LLM Jobs

### LLM #1 — Understand the Job

**Input:**
- Job Description

**Output:**
```json
{
  "requirements": [
    {
      "id": "REQ-001",
      "requirement": "3+ years of Python experience",
      "type": "experience"
    },
    {
      "id": "REQ-002", 
      "requirement": "Experience with Django",
      "type": "technical_skill"
    },
    {
      "id": "REQ-003",
      "requirement": "Bachelor's degree in Computer Science or related field",
      "type": "education"
    }
  ]
}
```

This gives us a standardized list of things to evaluate.

### LLM #2 — Evaluate the Candidate

**Input:**
- STRUCTURED REQUIREMENTS
- CV CONTENT

**Process:**
For every requirement:
- Find evidence in the CV
- If evidence exists, determine whether the requirement is satisfied
- If evidence is insufficient, say so
- Never invent evidence

**Output:**
```json
{
  "evaluation": [
    {
      "requirement_id": "REQ-001",
      "status": "PARTIAL",
      "evidence": [
        {
          "text": "Software Developer with hands-on experience building...",
          "page": 1
        }
      ],
      "breakdown": "Python experience is demonstrated, but the CV does not establish three years of experience."
    },
    {
      "requirement_id": "REQ-002",
      "status": "MET",
      "evidence": [
        {
          "text": "Engineered a web-based accommodation booking engine using Python (Django)...",
          "page": 1
        }
      ],
      "breakdown": "Django is explicitly demonstrated through multiple projects."
    },
    {
      "requirement_id": "REQ-003",
      "status": "MET",
      "evidence": [
        {
          "text": "Bsc Information Technology",
          "page": 2
        }
      ],
      "breakdown": "The candidate lists a BSc in Information Technology."
    }
  ]
}
```

## Database Structure

```
Investigation
│
├── Candidate
├── Job Description
│
└── Requirements
      │
      ├── Requirement
      │      ├── requirement_id
      │      ├── requirement_text
      │      ├── requirement_type
      │      └── Evidence
      │           ├── evidence_text
      │           ├── page_number
      │           ├── status (MET/PARTIAL/NOT_MET)
      │           └── breakdown
      │
      ├── Requirement
      │      └── Evidence
      │
      └── Requirement
             └── Evidence
```

## Status Definitions

- **MET**: Clear, direct evidence that the requirement is satisfied
- **PARTIAL**: Some evidence exists but is incomplete or ambiguous
- **NOT_MET**: No evidence found or evidence contradicts the requirement

## Frontend Display

The frontend displays:

| Requirement | Evidence | Page | Status |
|-------------|----------|------|--------|
| Django experience | Built MLC Housing using Django | 1 | MET |
| 3+ years Python | Python listed, but dates insufficient | 1 | PARTIAL |
| AWS experience | EC2, RDS, S3 infrastructure | 2 | MET |

## Key Principles

1. **Never invent evidence** - Only use text actually present in the CV
2. **Never assume dates, durations, or quantities** not explicitly stated
3. **If information is missing, state that clearly** in the breakdown
4. **PARTIAL does not mean false** - It means evidence is insufficient
5. **Evidence must be traceable** to specific page numbers in the CV

## Error Handling

The system includes comprehensive error logging:
- All errors are logged to the command line with full stack traces
- LLM API errors are caught and reported
- JSON parsing errors are handled with markdown stripping
- Database errors are caught and logged
- Failed investigations are marked as 'failed' in the database

## Rate Limiting

To prevent exhausting API quotas:
- Default: 90 requests per 60 seconds
- Configurable via environment variables
- Automatic waiting when limit is reached
- Applied to all LLM calls

## Environment Variables

Required:
```bash
LLM7_API_KEY=your_api_key_here
LLM7_MODEL=default
DJANGO_KEY=True
```

Optional:
```bash
RATE_LIMIT_MAX_REQUESTS=90
RATE_LIMIT_TIME_WINDOW=60
```

## Running the System

1. Ensure virtual environment is activated
2. Install dependencies: `pip install -r requirements.txt`
3. Run migrations: `python manage.py migrate`
4. Start server: `python manage.py runserver`
5. Access at: http://127.0.0.1:8000

## Usage

1. Upload a CV (PDF format)
2. Provide a job description
3. System automatically:
   - Extracts text and URLs from CV
   - Extracts requirements from job description (LLM #1)
   - Evaluates CV against requirements (LLM #2)
   - Saves evidence with page numbers
   - Displays results with status breakdowns
