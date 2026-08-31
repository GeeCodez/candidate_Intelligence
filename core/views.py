import logging
import asyncio
from asgiref.sync import async_to_sync
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from .models import Investigation, Requirement, CandidateClaim, Source, Evidence
from services.pdf_extraction import extract_cv_content, PDFExtractionError
from services.llm_service import (
    analyze_candidate,
    LLMConfigurationError,
    LLMAPIError,
    LLMResponseError,
    LLMValidationError,
)
from services.browser_service import verify_claim

logger = logging.getLogger(__name__)


def index(request):
    return render(request, 'core.html')


def extract_candidate_name(cv_text):
    lines = cv_text.split('\n')
    for line in lines[:5]:
        line = line.strip()
        if line and len(line) < 50 and not any(char.isdigit() for char in line):
            return line
    return "Unknown Candidate"


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

    investigation = None
    try:
        logger.info("Starting CV processing")
        
        extracted_data = extract_cv_content(cv_file)
        logger.info(f"PDF extracted: {extracted_data['page_count']} pages, {len(extracted_data['urls'])} URLs")
        
        candidate_name = extract_candidate_name(extracted_data['text'])
        logger.info(f"Candidate name extracted: {candidate_name}")

        investigation = Investigation.objects.create(
            candidate_name=candidate_name,
            cv_details=extracted_data['text'],
            job_description=job_description,
            status='processing'
        )
        logger.info(f"Investigation created: {investigation.id}")

        # Stage 2: Gemini Structuring
        logger.info("Stage 2: Gemini Structuring - Analyzing candidate")
        llm_data = analyze_candidate(
            cv_text=extracted_data['text'],
            job_description=job_description,
            extracted_urls=extracted_data['urls']
        )
        logger.info(f"Gemini structuring complete: {len(llm_data['requirements'])} requirements, {len(llm_data['claims'])} claims, {len(llm_data['urls'])} sources")

        # Stage 3: Database - Store structured information
        logger.info("Stage 3: Database - Storing structured information")
        
        # Create Requirements
        requirement_map = {}
        for req_data in llm_data['requirements']:
            requirement = Requirement.objects.create(
                investigation=investigation,
                name=req_data['name'],
                description=req_data.get('description', ''),
                importance=req_data['importance']
            )
            requirement_map[req_data['name']] = requirement
            logger.info(f"Requirement created: {req_data['name']} ({req_data['importance']})")

        # Create Sources
        source_map = {}
        for url in llm_data['urls']:
            source_type = 'other'
            if 'github.com' in url:
                source_type = 'github'
            elif 'portfolio' in url.lower():
                source_type = 'portfolio'
            elif any(domain in url for domain in ['.com', '.org', '.net', '.io']):
                source_type = 'website'
            
            source = Source.objects.create(
                investigation=investigation,
                url=url,
                source_type=source_type,
                title=url
            )
            source_map[url] = source
            logger.info(f"Source created: {url} ({source_type})")

        # Create Candidate Claims
        for claim_data in llm_data['claims']:
            requirement = requirement_map.get(claim_data['requirement'])
            if requirement:
                claim = CandidateClaim.objects.create(
                    investigation=investigation,
                    requirement=requirement,
                    claim=claim_data['claim'],
                    source_from_cv=claim_data.get('source_from_cv', '')
                )
                logger.info(f"Candidate claim created: {claim_data['claim'][:50]}...")

        investigation.status = 'completed'
        investigation.save()
        logger.info(f"Investigation {investigation.id} completed Stage 2 successfully")
        
        # Prepare response data
        response_data = {
            'investigation_id': investigation.id,
            'candidate_name': candidate_name,
            'extraction': {
                'page_count': extracted_data['page_count'],
                'urls': extracted_data['urls']
            },
            'requirements': [
                {
                    'id': req.id,
                    'name': req.name,
                    'description': req.description,
                    'importance': req.importance
                }
                for req in investigation.requirements.all()
            ],
            'claims': [
                {
                    'id': claim.id,
                    'claim': claim.claim,
                    'requirement': claim.requirement.name,
                    'source_from_cv': claim.source_from_cv
                }
                for claim in investigation.candidate_claims.all()
            ],
            'sources': [
                {
                    'id': source.id,
                    'url': source.url,
                    'source_type': source.source_type,
                    'title': source.title
                }
                for source in investigation.sources.all()
            ]
        }
        
        return JsonResponse({
            'success': True,
            'data': response_data,
        })

    except PDFExtractionError as e:
        logger.error(f"PDF extraction error: {str(e)}", exc_info=True)
        if investigation:
            investigation.status = 'failed'
            investigation.save()
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

    except LLMConfigurationError as e:
        logger.error(f"LLM configuration error: {str(e)}", exc_info=True)
        if investigation:
            investigation.status = 'failed'
            investigation.save()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

    except (LLMAPIError, LLMResponseError, LLMValidationError) as e:
        logger.error(f"LLM processing error: {str(e)}", exc_info=True)
        if investigation:
            investigation.status = 'failed'
            investigation.save()
        return JsonResponse({'success': False, 'error': str(e)}, status=502)

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        if investigation:
            investigation.status = 'failed'
            investigation.save()
        return JsonResponse(
            {'success': False, 'error': f'An unexpected error occurred: {str(e)}'},
            status=500,
        )


@method_decorator(csrf_exempt, name='dispatch')
class VerifyClaimView(View):
    def post(self, request):
        """Verify a specific candidate claim using Browser Use + Gemini evaluation"""
        claim_id = request.POST.get('claim_id')
        
        if not claim_id:
            return JsonResponse(
                {'success': False, 'error': 'No claim_id provided'},
                status=400,
            )
        
        try:
            claim = CandidateClaim.objects.select_related(
                'investigation', 'requirement'
            ).get(id=claim_id)
            
            sources = list(Source.objects.filter(investigation=claim.investigation))
            
            if not sources:
                return JsonResponse(
                    {'success': False, 'error': 'No sources available for this investigation'},
                    status=400,
                )
            
            logger.info(f"Starting verification for claim {claim_id}: {claim.claim}")
            
            # Run the async verification process
            result = async_to_sync(verify_claim)(
                claim, 
                claim.requirement, 
                sources
            )
            
            logger.info(f"Verification complete for claim {claim_id}: {result.get('status')}")
            
            # Prepare response data
            response_data = {
                'claim_id': claim.id,
                'claim': claim.claim,
                'requirement': claim.requirement.name,
                'status': result.get('status'),
                'evaluation': result.get('evaluation'),
                'evidence_count': len(result.get('evidence', [])),
                'research_summary': result.get('research', {}).get('raw_findings', '')[:200],
            }
            
            return JsonResponse({
                'success': True,
                'data': response_data,
            })
            
        except CandidateClaim.DoesNotExist:
            return JsonResponse(
                {'success': False, 'error': 'Claim not found'},
                status=404,
            )
        except Exception as e:
            logger.error(f"Verification error for claim {claim_id}: {str(e)}", exc_info=True)
            return JsonResponse(
                {'success': False, 'error': f'Verification failed: {str(e)}'},
                status=500,
            )


@method_decorator(csrf_exempt, name='dispatch') 
class VerifyAllClaimsView(View):
    def post(self, request):
        """Verify all claims for an investigation"""
        investigation_id = request.POST.get('investigation_id')
        
        if not investigation_id:
            return JsonResponse(
                {'success': False, 'error': 'No investigation_id provided'},
                status=400,
            )
        
        try:
            investigation = Investigation.objects.get(id=investigation_id)
            claims = CandidateClaim.objects.filter(
                investigation=investigation
            ).select_related('requirement')
            
            sources = list(Source.objects.filter(investigation=investigation))
            
            if not sources:
                return JsonResponse(
                    {'success': False, 'error': 'No sources available for this investigation'},
                    status=400,
                )
            
            logger.info(f"Starting verification for all {claims.count()} claims in investigation {investigation_id}")
            
            results = []
            for claim in claims:
                try:
                    logger.info(f"Verifying claim {claim.id}: {claim.claim}")
                    result = async_to_sync(verify_claim)(
                        claim,
                        claim.requirement,
                        sources
                    )
                    
                    results.append({
                        'claim_id': claim.id,
                        'claim': claim.claim,
                        'requirement': claim.requirement.name,
                        'status': result.get('status'),
                        'evidence_count': len(result.get('evidence', [])),
                    })
                    
                    logger.info(f"Claim {claim.id} verification complete: {result.get('status')}")
                    
                except Exception as e:
                    logger.error(f"Failed to verify claim {claim.id}: {str(e)}")
                    results.append({
                        'claim_id': claim.id,
                        'claim': claim.claim,
                        'requirement': claim.requirement.name,
                        'status': 'error',
                        'error': str(e),
                    })
            
            # Update investigation status
            investigation.status = 'completed'
            investigation.save()
            
            return JsonResponse({
                'success': True,
                'data': {
                    'investigation_id': investigation.id,
                    'total_claims': claims.count(),
                    'verified': len([r for r in results if r.get('status') == 'verified']),
                    'unverified': len([r for r in results if r.get('status') == 'unverified']),
                    'errors': len([r for r in results if r.get('status') == 'error']),
                    'results': results,
                },
            })
            
        except Investigation.DoesNotExist:
            return JsonResponse(
                {'success': False, 'error': 'Investigation not found'},
                status=404,
            )
        except Exception as e:
            logger.error(f"Bulk verification error: {str(e)}", exc_info=True)
            return JsonResponse(
                {'success': False, 'error': f'Bulk verification failed: {str(e)}'},
                status=500,
            )
