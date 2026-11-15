import io
import json
from unittest import mock

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.venues.campus_buildings import BUILDINGS
from apps.venues.management.commands import seed_campus_buildings as command
from apps.venues.models import Venue

GEOCODE = 'apps.venues.management.commands.seed_campus_buildings.geocode'
# In an empty database every building with an address is looked up, except those with fixed coordinates.
LOOKED_UP = [b for b in BUILDINGS if b.get('address') and 'lat' not in b]


def fake_geocode(query, key):
    return -88.2272, 40.1020, f'{query} (test)'


@override_settings(MAPTILER_API_KEY='test-key')
class SeedCampusBuildingsTests(TestCase):
    def run_command(self, *args):
        out = io.StringIO()
        with mock.patch(GEOCODE, side_effect=fake_geocode) as geo, mock.patch.object(command.time, 'sleep'):
            call_command('seed_campus_buildings', *args, stdout=out)
        return out.getvalue(), geo

    def test_adds_buildings_with_codes_and_aliases(self):
        output, geo = self.run_command()
        self.assertEqual(geo.call_count, len(LOOKED_UP))
        sdrp = Venue.objects.get(name='Student Dining and Residential Programs Building')
        self.assertEqual(sdrp.building_code, 'SDRP')
        self.assertIn('Ikenberry Commons', sdrp.aliases)
        self.assertEqual(sdrp.address, '301 E Gregory Dr, Champaign, IL')
        stadium = Venue.objects.get(name='Memorial Stadium')  # fixed coordinates, no lookup
        self.assertAlmostEqual(stadium.location.y, 40.09917)
        self.assertIn('Added', output)

    def test_existing_buildings_keep_their_pin_and_get_aliases(self):
        union = Venue.objects.create(name='Illini Union', location=Point(-88.1, 40.0, srid=4326))
        self.run_command()
        union.refresh_from_db()
        self.assertEqual((union.location.x, union.location.y), (-88.1, 40.0))
        self.assertIn('The Union', union.aliases)
        self.assertEqual(Venue.objects.filter(name='Illini Union').count(), 1)

    def test_running_twice_changes_nothing(self):
        self.run_command()
        count = Venue.objects.count()
        output, geo = self.run_command()
        self.assertEqual(Venue.objects.count(), count)
        self.assertEqual(geo.call_count, 0)
        self.assertIn('Added 0 buildings, updated 0', output)

    def test_dry_run_saves_nothing(self):
        output, _ = self.run_command('--dry-run')
        self.assertFalse(Venue.objects.exists())
        self.assertIn('dry run', output)

    def test_a_failed_lookup_skips_only_that_building(self):
        def flaky(query, key):
            if query.startswith('805 S Mathews'):
                raise command.GeocodeError('no match')
            return fake_geocode(query, key)
        out = io.StringIO()
        with mock.patch(GEOCODE, side_effect=flaky), mock.patch.object(command.time, 'sleep'):
            call_command('seed_campus_buildings', stdout=out)
        self.assertFalse(Venue.objects.filter(name='Smith Memorial Hall').exists())
        self.assertTrue(Venue.objects.filter(name='Altgeld Hall').exists())
        self.assertIn('Skip    Smith Memorial Hall: no match', out.getvalue())

    @override_settings(MAPTILER_API_KEY='')
    def test_needs_a_maptiler_key_for_new_buildings(self):
        with self.assertRaises(CommandError):
            call_command('seed_campus_buildings', stdout=io.StringIO())


class GeocodeTests(TestCase):
    def response(self, payload):
        body = mock.MagicMock()
        body.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        return body

    @mock.patch('apps.venues.management.commands.seed_campus_buildings.urllib.request.urlopen')
    def test_reads_the_first_result_inside_champaign_urbana(self, urlopen):
        urlopen.return_value = self.response({'features': [
            {'center': [-88.2263, 40.1052], 'place_name': '805 South Mathews Avenue, Urbana'}]})
        self.assertEqual(command.geocode('805 S Mathews Ave, Urbana, IL', 'k'),
                         (-88.2263, 40.1052, '805 South Mathews Avenue, Urbana'))
        url = urlopen.call_args.args[0].full_url
        self.assertIn('bbox=', url)
        self.assertIn('proximity=', url)

    @mock.patch('apps.venues.management.commands.seed_campus_buildings.urllib.request.urlopen')
    def test_rejects_results_outside_the_area(self, urlopen):
        urlopen.return_value = self.response({'features': [{'center': [-87.6, 41.9], 'place_name': 'Chicago'}]})
        with self.assertRaises(command.GeocodeError):
            command.geocode('somewhere', 'k')
