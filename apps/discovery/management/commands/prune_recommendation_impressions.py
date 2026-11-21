from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.discovery.recommendations import IMPRESSION_RETENTION_DAYS, prune_impressions


class Command(BaseCommand):
    help = ('Delete recommendation impressions older than --days for every user. The home page already '
            'prunes each user\'s own rows; this also covers users who stopped visiting.')

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=IMPRESSION_RETENTION_DAYS,
                            help=f'Keep impressions from the last this many days (default {IMPRESSION_RETENTION_DAYS})')

    def handle(self, *args, **options):
        if options['days'] < 1:
            raise CommandError('--days must be at least 1.')
        deleted = prune_impressions(timezone.now(), days=options['days'])
        self.stdout.write(f'Deleted {deleted} impressions older than {options["days"]} days.')
