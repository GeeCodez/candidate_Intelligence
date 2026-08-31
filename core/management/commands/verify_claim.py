from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand, CommandError

from core.models import CandidateClaim, Source
from services.browser_service import verify_claim


class Command(BaseCommand):
    help = "Run MultiOn + Gemini verification for one candidate claim."

    def add_arguments(self, parser):
        parser.add_argument("claim_id", type=int)

    def handle(self, *args, **options):
        claim = CandidateClaim.objects.select_related("investigation", "requirement").get(
            id=options["claim_id"]
        )
        sources = list(Source.objects.filter(investigation=claim.investigation))
        if not sources:
            raise CommandError("No sources exist for this investigation.")

        self.stdout.write(f"Investigating claim {claim.id}: {claim.claim}")
        self.stdout.write(f"Sources: {', '.join(source.url for source in sources)}")
        result = async_to_sync(verify_claim)(claim, claim.requirement, sources)
        self.stdout.write(f"Research: {result.get('research', {}).get('raw_findings', '')}")
        self.stdout.write(f"Evaluation: {result.get('evaluation', result.get('error', ''))}")
        self.stdout.write(f"Evidence saved: {len(result.get('evidence', []))}")
