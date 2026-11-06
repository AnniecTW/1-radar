import uuid

from django.conf import settings
from django.db import models
from django.db import transaction


class Organization(models.Model):
    class OrgType(models.TextChoices):
        RSO = 'rso', 'RSO'
        DEPARTMENT = 'department', 'Department'
        CAMPUS_OFFICE = 'campus_office', 'Campus office'
        OTHER = 'other', 'Other'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150, unique=True)
    org_type = models.CharField(max_length=20, choices=OrgType.choices)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to='organization_logos/', max_length=255, blank=True)
    contact_email = models.EmailField(max_length=254, blank=True)
    website_url = models.CharField(max_length=255, null=True, blank=True)
    instagram_url = models.CharField(max_length=255, null=True, blank=True)
    # Set by a platform admin.
    is_verified = models.BooleanField(default=False)
    # Cached counter, updated on follow/unfollow.
    follower_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_organizations'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        creating = self._state.adding
        with transaction.atomic():
            super().save(*args, **kwargs)
            if creating:
                OrganizationMembership.objects.create(
                    organization=self,
                    user=self.created_by,
                    role=OrganizationMembership.Role.OWNER,
                    invited_by=self.created_by,
                )

    def __str__(self):
        return self.name


class OrganizationMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = 'owner'
        ADMIN = 'admin'
        CHECKIN_STAFF = 'checkin_staff', 'Check-in staff'

    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='memberships')
    # Must be campus-verified; enforced in the invite flow, not the database.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=Role.choices)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['organization', 'user'], name='unique_org_membership'),
            models.UniqueConstraint(
                fields=['organization'],
                condition=models.Q(role='owner'),
                name='unique_organization_owner',
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=['owner', 'admin', 'checkin_staff']),
                name='organization_membership_valid_role',
            ),
        ]

    def __str__(self):
        return f'{self.user} ({self.role}) @ {self.organization}'


class OrganizationFollow(models.Model):
    class Source(models.TextChoices):
        ORG_PAGE = 'org_page'
        EVENT_PAGE = 'event_page'
        EVENT_CARD = 'event_card'
        ONBOARDING = 'onboarding'
        LANDING = 'landing'

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='follows')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='follows')
    # False = muted: still followed and still boosted in the feed, but no notifications.
    notify = models.BooleanField(default=True)
    source = models.CharField(max_length=20, choices=Source.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'organization'], name='unique_org_follow')]

    def __str__(self):
        return f'{self.user} follows {self.organization}'
