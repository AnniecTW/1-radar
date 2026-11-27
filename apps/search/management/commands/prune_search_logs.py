from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.search.services import RETENTION_DAYS, prune_search_logs


class Command(BaseCommand):
    help = 'Delete logged searches older than --days. Searching already prunes at most once an hour.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=RETENTION_DAYS,
                            help=f'Keep searches from the last this many days (default {RETENTION_DAYS})')

    def handle(self, *args, **options):
        if options['days'] < 1:
            raise CommandError('--days must be at least 1.')
        deleted = prune_search_logs(timezone.now(), days=options['days'])
        self.stdout.write(f'Deleted {deleted} searches older than {options["days"]} days.')
