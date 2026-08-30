from django.shortcuts import render
from django.http import JsonResponse
from .models import Investigation, Requirement, CandidateClaim, Source
from services.pdf_extraction import extract_cv_content, PDFExtractionError
from asgiref.sync import async_to_sync

from services.browser_service import verify_claim
from services.llm_service import (
    analyze_candidate,
    LLMConfigurationError,
    LLMAPIError,
    LLMResponseError,
    LLMValidationError,
)


def index(request):
    return render(request, 'core.html')


def extract_candidate_name(cv_text):
    lines = cv_text.split('\n')
    for line in lines[:5]:
        line = line.strip()
        if line and len(line) < 50 and not any(char.isdigit() for char in line):
            return line
    return "Unknown Candidate"


def determine_source_type(url):
    url_lower = url.lower()
    if 'github.com' in url_lower:
        return 'github'
    elif 'portfolio' in url_lower or 'behance' in url_lower or 'dribbble' in url_lower:
        return 'portfolio'
    elif 'http' in url_lower or 'www' in url_lower:
        return 'website'
    return 'other'


def process_cv(request):
    if request.method != 'POST':
        return JsonResponse(
            {'success': False, 'error': 'Invalid request method'},
            status=405,
        )

    cv_file = request.FILES.get('cv_file')
    job_description = request.POST.get('job_description', '').strip()

    if not cv_file:
        return JsonResponse(
            {'success': False, 'error': 'No CV file provided'},
            status=400,
        )

    if not job_description:
        return JsonResponse(
            {'success': False, 'error': 'No job description provided'},
            status=400,
        )

    try:
        extracted_data = extract_cv_content(cv_file)
        candidate_name = extract_candidate_name(extracted_data['text'])

        investigation = Investigation.objects.create(
            candidate_name=candidate_name,
            cv_details=extracted_data,
            job_description=job_description,
            status='processing'
        )

        for url in extracted_data['urls']:
            Source.objects.create(
                investigation=investigation,
                url=url,
                source_type=determine_source_type(url),
                title=url
            )

        analysis = analyze_candidate(
            cv_text=extracted_data['text'],
            job_description=job_description,
            extracted_urls=extracted_data['urls'],
        )

        if 'requirements' in analysis:
            requirement_map = {}
            
            for req_data in analysis['requirements']:
                requirement = Requirement.objects.create(
                    investigation=investigation,
                    name=req_data.get('name', ''),
                    description=req_data.get('description', ''),
                    importance=req_data.get('importance', 'medium')
                )
                requirement_map[requirement.name] = requirement

            if 'claims' in analysis:
                for claim_data in analysis['claims']:
                    requirement_name = claim_data.get('requirement', '')
                    requirement = requirement_map.get(requirement_name)
                    
                    if requirement:
                        claim = CandidateClaim.objects.create(
                            investigation=investigation,
                            requirement=requirement,
                            claim=claim_data.get('claim', ''),
                            source_from_cv=claim_data.get('source_from_cv', '')
                        )
                        sources = list(investigation.sources.all())
                        async_to_sync(verify_claim)(claim, requirement, sources)

        investigation.status = 'completed'
        investigation.save()
        
        return JsonResponse({
            'success': True,
            'data': {
                'investigation_id': investigation.id,
                'extraction': extracted_data,
                'analysis': analysis,
            },
        })

    except PDFExtractionError as e:
        if 'investigation' in locals():
            investigation.status = 'failed'
            investigation.save()
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

    except LLMConfigurationError as e:
        if 'investigation' in locals():
            investigation.status = 'failed'
            investigation.save()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

    except (LLMAPIError, LLMResponseError, LLMValidationError) as e:
        if 'investigation' in locals():
            investigation.status = 'failed'
            investigation.save()
        return JsonResponse({'success': False, 'error': str(e)}, status=502)

    except Exception as e:
        if 'investigation' in locals():
            investigation.status = 'failed'
            investigation.save()
        return JsonResponse(
            {'success': False, 'error': f'An unexpected error occurred: {str(e)}'},
            status=500,
        )
