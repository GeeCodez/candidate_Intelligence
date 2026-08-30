from django.db import models


class Investigation(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    candidate_name = models.CharField(max_length=255)
    cv_details = models.TextField(blank=True,null=True)
    job_description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.candidate_name} - {self.status}"


class Requirement(models.Model):
    IMPORTANCE_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]

    investigation = models.ForeignKey(
        Investigation,
        on_delete=models.CASCADE,
        related_name='requirements'
    )
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    importance = models.CharField(
        max_length=20,
        choices=IMPORTANCE_CHOICES,
        default='medium'
    )

    def __str__(self):
        return f"{self.name} ({self.importance})"


class CandidateClaim(models.Model):
    investigation = models.ForeignKey(
        Investigation,
        on_delete=models.CASCADE,
        related_name='candidate_claims'
    )
    requirement = models.ForeignKey(
        Requirement,
        on_delete=models.CASCADE,
        related_name='candidate_claims'
    )
    claim = models.TextField()
    source_from_cv = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.claim[:50]}..." if len(self.claim) > 50 else self.claim


class Source(models.Model):
    SOURCE_TYPE_CHOICES = [
        ('github', 'GitHub'),
        ('portfolio', 'Portfolio'),
        ('website', 'Website'),
        ('other', 'Other'),
    ]

    investigation = models.ForeignKey(
        Investigation,
        on_delete=models.CASCADE,
        related_name='sources'
    )
    url = models.URLField()
    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_TYPE_CHOICES,
        default='other',
        null=True
    )
    title = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"{self.title or self.url} ({self.source_type})"


class Evidence(models.Model):
    EVIDENCE_STRENGTH_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]

    STATUS_CHOICES = [
        ('verified', 'Verified'),
        ('unverified', 'Unverified'),
    ]

    investigation = models.ForeignKey(
        Investigation,
        on_delete=models.CASCADE,
        related_name='evidence'
    )
    claim = models.ForeignKey(
        CandidateClaim,
        on_delete=models.CASCADE,
        related_name='evidence'
    )
    source = models.ForeignKey(
        Source,
        on_delete=models.CASCADE,
        related_name='evidence'
    )
    finding = models.TextField()
    evidence_strength = models.CharField(
        max_length=20,
        choices=EVIDENCE_STRENGTH_CHOICES,
        default='medium'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='unverified'
    )
    details = models.JSONField(default=dict)

    def __str__(self):
        return f"{self.finding[:50]}..." if len(self.finding) > 50 else self.finding
