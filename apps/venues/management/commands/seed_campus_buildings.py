"""Add UIUC campus buildings (with flyer-style aliases) to Radar's venue list.

    python manage.py seed_campus_buildings --dry-run   # show what would change
    python manage.py seed_campus_buildings

New buildings are placed on the map by looking up their street address with MapTiler
(MAPTILER_API_KEY, the key the Explore Map already uses). Buildings that already exist keep their
pin; only missing aliases and short codes are added. Safe to run more than once.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db.models.functions import Lower

from apps.venues.campus_buildings import BUILDINGS, CAMPUS_BBOX, CAMPUS_CENTER
from apps.venues.models import Venue


class GeocodeError(Exception):
    pass


def geocode(query, key):
    """Return (lon, lat, place_name) for an address in Champaign-Urbana, using MapTiler."""
    params = urllib.parse.urlencode({
        'key': key,
        'proximity': f'{CAMPUS_CENTER[0]},{CAMPUS_CENTER[1]}',
        'bbox': ','.join(str(value) for value in CAMPUS_BBOX),
        'country': 'us',
        'limit': 1,
    })
    url = f'https://api.maptiler.com/geocoding/{urllib.parse.quote(query)}.json?{params}'
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Radar'}), timeout=15) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise GeocodeError(f'MapTiler returned HTTP {exc.code}') from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GeocodeError(f'MapTiler unavailable ({type(exc).__name__})') from None
    features = data.get('features') or []
    if not features:
        raise GeocodeError('no match')
    feature = features[0]
    lon, lat = (feature.get('center') or feature.get('geometry', {}).get('coordinates') or [None, None])[:2]
    west, south, east, north = CAMPUS_BBOX
    if lon is None or not (west <= lon <= east and south <= lat <= north):
        raise GeocodeError('match is outside Champaign-Urbana')
    return lon, lat, feature.get('place_name', '')


class Command(BaseCommand):
    help = 'Add UIUC campus buildings and flyer-style aliases to the venue list.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would change without saving.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        key = getattr(settings, 'MAPTILER_API_KEY', '')
        by_name = {venue.lower_name: venue for venue in Venue.objects.annotate(lower_name=Lower('name'))}
        created = updated = skipped = 0
        for building in BUILDINGS:
            venue = by_name.get(building['name'].lower())
            wanted_aliases = building.get('aliases', [])
            code = building.get('code')
            if venue:
                new_aliases = [a for a in wanted_aliases if a.lower() not in {x.lower() for x in venue.aliases}]
                set_code = bool(code and not venue.building_code)
                set_address = bool(building.get('address') and not venue.address)
                if not (new_aliases or set_code or set_address):
                    continue
                self.stdout.write(f'Update  {venue.name}: + {", ".join(new_aliases + ([code] if set_code else [])) or "address"}')
                if not dry_run:
                    venue.aliases = [*venue.aliases, *new_aliases]
                    if set_code:
                        venue.building_code = code
                    if set_address:
                        venue.address = f"{building['address']}, {building['city']}, IL"
                    venue.save(update_fields=['aliases', 'building_code', 'address', 'updated_at'])
                updated += 1
                continue
            if not building.get('address'):
                continue  # demo-only places (e.g. Main Quad) are never created here
            if 'lat' in building:
                lon, lat, found = building['lon'], building['lat'], 'coordinates from the building list'
            else:
                if not key:
                    raise CommandError('Set MAPTILER_API_KEY in .env: new buildings need a map position.')
                try:
                    lon, lat, found = geocode(f"{building['address']}, {building['city']}, IL", key)
                except GeocodeError as error:
                    self.stdout.write(self.style.WARNING(f"Skip    {building['name']}: {error}"))
                    skipped += 1
                    continue
                time.sleep(0.2)
            self.stdout.write(f"Add     {building['name']} at {lat:.5f}, {lon:.5f}  ({found})")
            if not dry_run:
                Venue.objects.create(
                    name=building['name'], building_code=code, aliases=wanted_aliases,
                    address=f"{building['address']}, {building['city']}, IL",
                    location=Point(lon, lat, srid=4326), is_campus=True,
                )
            created += 1
        verb = 'Would add' if dry_run else 'Added'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {created} buildings, updated {updated}, skipped {skipped}.'
            + ('  (dry run: nothing saved)' if dry_run else '')
        ))
