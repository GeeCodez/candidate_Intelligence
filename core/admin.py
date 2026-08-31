from django.contrib import admin
from .models import (
    Investigation,
    Requirement,
    CandidateClaim,
    Source,
    Evidence,
)


@admin.register(Investigation)
class InvestigationAdmin(admin.ModelAdmin):
    list_display = (
        'candidate_name',
        'status',
        'created_at',
    )
    list_filter = ('status', 'created_at')
    search_fields = (
        'candidate_name',
        'job_description',
        'cv_details',
    )
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)


@admin.register(Requirement)
class RequirementAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'investigation',
        'importance',
    )
    list_filter = ('importance',)
    search_fields = (
        'name',
        'description',
        'investigation__candidate_name',
    )


@admin.register(CandidateClaim)
class CandidateClaimAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'claim_preview',
        'investigation',
        'requirement',
    )
    search_fields = (
        'claim',
        'source_from_cv',
        'investigation__candidate_name',
        'requirement__name',
    )

    @admin.display(description='Claim')
    def claim_preview(self, obj):
        return obj.claim[:80]


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'url',
        'source_type',
        'investigation',
    )
    list_filter = ('source_type',)
    search_fields = (
        'title',
        'url',
        'investigation__candidate_name',
    )


@admin.register(Evidence)
class EvidenceAdmin(admin.ModelAdmin):
    list_display = (
        'finding_preview',
        'claim',
        'source',
        'evidence_strength',
        'status',
        'investigation',
    )
    list_filter = (
        'evidence_strength',
        'status',
    )
    search_fields = (
        'finding',
        'details',
        'claim__claim',
        'source__title',
        'source__url',
        'investigation__candidate_name',
    )

    @admin.display(description='Finding')
    def finding_preview(self, obj):
        return obj.finding[:80]