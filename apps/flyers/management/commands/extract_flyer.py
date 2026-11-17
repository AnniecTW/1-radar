"""Read one or more flyer images with the vision model and print what Radar would fill in.

Saves nothing. Use it to try the Cloudflare connection and to collect evaluation results:

    python manage.py extract_flyer flyers/robot-night.jpg flyers/career-fair.png
"""
import json
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.flyers.extraction import (
    ExtractionError,
    FlyerImageError,
    build_form_values,
    call_vision_model,
    model_id,
    parse_answer,
    prepare_image,
)


class Command(BaseCommand):
    help = 'Read flyer images with the vision model and print the extracted event fields (saves nothing).'

    def add_arguments(self, parser):
        parser.add_argument('paths', nargs='+', help='Flyer image files (JPG, PNG or WebP).')
        parser.add_argument('--raw', action='store_true', help="Also print the model's raw answer.")

    def handle(self, *args, **options):
        from apps.discovery.selectors import get_campus_timezone
        from apps.interests.models import Interest
        from apps.venues.models import Venue

        today = timezone.localtime(timezone.now(), get_campus_timezone()).date()
        interests = list(Interest.objects.filter(is_active=True))
        names = {interest.pk: interest.name for interest in interests}
        venues = list(Venue.objects.filter(is_campus=True))
        venue_names = {venue.pk: venue.name for venue in venues}
        self.stdout.write(f'Model: {model_id()}  ·  dates resolved from {today}')
        failures = 0
        for path in options['paths']:
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n{path}'))
            try:
                with open(path, 'rb') as handle:
                    jpeg = prepare_image(handle)
            except OSError as exc:
                raise CommandError(f"Can't open {path}: {exc}") from None
            except FlyerImageError as exc:
                self.stdout.write(self.style.ERROR(str(exc)))
                failures += 1
                continue
            started = time.monotonic()
            try:
                answer = call_vision_model(jpeg)
                latency = round((time.monotonic() - started) * 1000)
                if options['raw']:
                    self.stdout.write(f'Raw answer:\n{answer}\n')
                raw = parse_answer(answer)
            except ExtractionError as exc:
                self.stdout.write(self.style.ERROR(f'Failed after {round((time.monotonic() - started) * 1000)} ms: {exc}'))
                failures += 1
                continue
            values, confidence, review = build_form_values(
                raw, today=today, interests=interests, venues=venues, organizations=[],
            )
            values['interests'] = [names[pk] for pk in values.get('interests', [])]
            if values.get('venue'):
                values['venue'] = venue_names[values['venue']]
            self.stdout.write(f'Latency: {latency} ms')
            self.stdout.write('Model fields:\n' + json.dumps(raw, indent=2, ensure_ascii=False))
            self.stdout.write('Form values:\n' + json.dumps(values, indent=2, ensure_ascii=False))
            self.stdout.write('Confidence: ' + json.dumps(confidence))
            self.stdout.write('Needs review: ' + (json.dumps(review) if review else 'nothing'))
        if failures:
            self.stdout.write(self.style.WARNING(f'\n{failures} of {len(options["paths"])} flyers failed.'))
