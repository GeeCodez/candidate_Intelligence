import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from services.llm_service import evaluate_url_relevance
from core.models import CandidateClaim, Requirement, Source

def test_url_relevance():
    claim = CandidateClaim(
        claim="Candidate has experience with Django and Python web development"
    )
    
    requirement = Requirement(
        name="Django",
        description="Experience with Django framework for web development"
    )
    
    urls = [
        "https://github.com/johndoe",
        "https://linkedin.com/in/johndoe",
        "https://mlchousing.com",
        "https://afrinex.com",
        "https://johndoe.dev",
        "https://medium.com/@johndoe"
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
        
        high_relevance = [r for r in results if r['relevance'] == 'high']
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
