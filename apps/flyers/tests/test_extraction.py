import io
import json
import urllib.error
from datetime import date, time
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.flyers.extraction import (
    ExtractionError,
    FlyerImageError,
    build_form_values,
    call_vision_model,
    match_categories,
    match_venue,
    parse_answer,
    parse_flyer_date,
    parse_flyer_times,
    prepare_image,
    read_stream,
)

TODAY = date(2026, 11, 15)  # a Sunday
INTERESTS = [SimpleNamespace(pk=i, name=name, slug=name.lower()) for i, name in enumerate(
    ['Tech', 'Career', 'Food', 'Music', 'Sports'], start=1)]
VENUES = [
    SimpleNamespace(pk=1, name='Siebel Center for Computer Science', aliases=[], building_code=None, location=None),
    SimpleNamespace(pk=2, name='Siebel Center for Design', aliases=[], building_code=None, location=None),
    SimpleNamespace(pk=3, name='Activities and Recreation Center (ARC)', aliases=[], building_code=None, location=None),
    SimpleNamespace(pk=4, name='Illini Union', aliases=['The Union'], building_code=None, location=None),
]


def raw(**fields):
    base = {key: '' for key in ('title', 'description', 'date', 'start_time', 'end_time', 'location',
                                'organizer', 'price', 'registration_url')}
    base['categories'] = []
    base.update(fields)
    return base


class ParseAnswerTests(SimpleTestCase):
    def test_reads_json_inside_a_code_fence(self):
        data = parse_answer('```json\n{"title": "Robot Night", "date": "Nov 21", "categories": "#tech, robots"}\n```')
        self.assertEqual(data['title'], 'Robot Night')
        self.assertEqual(data['categories'], ['tech', 'robots'])

    def test_treats_placeholder_words_as_empty(self):
        data = parse_answer('{"title": "Robot Night", "price": "N/A", "location": "TBA", "organizer": null}')
        self.assertEqual((data['price'], data['location'], data['organizer']), ('', '', ''))

    def test_rejects_answers_without_json(self):
        for answer in ['This is a poster for a concert.', '[1, 2]', '{"title": ', '{"organizer": "Robotics Club"}']:
            with self.subTest(answer=answer), self.assertRaises(ExtractionError):
                parse_answer(answer)


class DateAndTimeTests(SimpleTestCase):
    def test_dates_without_a_year_pick_the_next_one(self):
        self.assertEqual(parse_flyer_date('Nov 21', TODAY), (date(2026, 11, 21), 1.0))
        self.assertEqual(parse_flyer_date('Jan 9', TODAY), (date(2027, 1, 9), 0.8))

    def test_a_weekday_that_does_not_match_the_date_lowers_confidence(self):
        day, confidence = parse_flyer_date('Friday, Nov 21', TODAY)  # Nov 21, 2026 is a Saturday
        self.assertEqual((day, confidence), (date(2026, 11, 21), 0.5))

    def test_only_a_weekday_means_the_next_one(self):
        self.assertEqual(parse_flyer_date('Friday', TODAY), (date(2026, 11, 20), 0.6))

    def test_unreadable_dates_are_missing(self):
        self.assertEqual(parse_flyer_date('soon!', TODAY), (None, 0.0))

    def test_time_ranges_and_am_pm(self):
        self.assertEqual(parse_flyer_times('7-9 PM', '')[:2], (time(19), time(21)))
        self.assertEqual(parse_flyer_times('11 AM', '1 PM')[:2], (time(11), time(13)))
        self.assertEqual(parse_flyer_times('noon', '2pm')[:2], (time(12), time(14)))
        self.assertEqual(parse_flyer_times('19:00', '21:30')[:2], (time(19), time(21, 30)))

    def test_times_without_am_pm_are_evening_but_need_a_check(self):
        start, end, start_conf, end_conf = parse_flyer_times('7', '9')
        self.assertEqual((start, end), (time(19), time(21)))
        self.assertLess(start_conf, 0.8)

    def test_an_end_before_the_start_is_dropped(self):
        self.assertEqual(parse_flyer_times('9 PM', '8 PM')[1], None)


class MatchingTests(SimpleTestCase):
    def test_venue_with_room(self):
        venue, room, score = match_venue('Room 1404, Siebel Center for Computer Science', VENUES)
        self.assertEqual((venue.pk, room, score), (1, 'Room 1404', 1.0))

    def test_short_names_and_aliases(self):
        self.assertEqual(match_venue('ARC', VENUES)[0].pk, 3)
        self.assertEqual(match_venue('The Union, 2nd floor', VENUES)[:2], (VENUES[3], '2nd floor'))

    def test_ambiguous_or_unknown_places_stay_as_text(self):
        self.assertEqual(match_venue('Siebel Center', VENUES), (None, 'Siebel Center', 0.0))
        self.assertEqual(match_venue('the north lawn', VENUES), (None, 'the north lawn', 0.0))

    def test_categories_from_topic_words_and_title(self):
        self.assertEqual([i.name for i in match_categories(['#robotics', 'free pizza'], '', INTERESTS)],
                         ['Tech', 'Food'])
        self.assertEqual([i.name for i in match_categories([], 'Resume review with free pizza', INTERESTS)],
                         ['Career', 'Food'])


class BuildFormValuesTests(SimpleTestCase):
    def build(self, **fields):
        return build_form_values(raw(**fields), today=TODAY, interests=INTERESTS, venues=VENUES, organizations=[])

    def test_a_complete_free_flyer(self):
        values, confidence, review = self.build(
            title='Robot Battle Night', description='Build a bot, then battle it.', date='Nov 21',
            start_time='7 PM', end_time='9 PM', location='Siebel Center for Computer Science 1404',
            price='Free', registration_url='go.illinois.edu/robots', categories=['robotics'],
        )
        self.assertEqual(values['date'], '2026-11-21')
        self.assertEqual((values['start_time'], values['end_time']), ('19:00', '21:00'))
        self.assertEqual((values['venue'], values['location_text']), (1, '1404'))
        self.assertEqual((values['kind'], values['interests']), ('rsvp', [1]))
        self.assertIn('Register: https://go.illinois.edu/robots', values['description'])
        self.assertEqual(review, {})

    def test_a_paid_flyer_keeps_its_price_and_ticket_link(self):
        values, _, review = self.build(title='Gala', price='$15', registration_url='https://tix.example.com/gala')
        self.assertEqual((values['kind'], values['price_text'], values['external_url']),
                         ('paid', '$15', 'https://tix.example.com/gala'))
        self.assertNotIn('external_url', review)

    def test_missing_fields_are_flagged_for_review(self):
        _, confidence, review = self.build(title='Open Mic', date='Friday')
        self.assertEqual(confidence['title'], 1.0)
        self.assertEqual(review['date'], 'check')
        for field in ('description', 'start_time', 'end_time', 'location_text'):
            self.assertEqual(review[field], 'missing')

    def test_organizer_matches_the_hosts_organization(self):
        org = SimpleNamespace(name='Robotics Club', slug='robotics-club')
        values, _, review = build_form_values(raw(title='Bot Night', organizer='UIUC Robotics Club'), today=TODAY,
                                              interests=INTERESTS, venues=VENUES, organizations=[org])
        self.assertEqual(values['host'], 'robotics-club')
        self.assertNotIn('host', review)


def png_bytes(size=(600, 800), mode='RGB'):
    from PIL import Image

    output = io.BytesIO()
    Image.new(mode, size, 'white').save(output, format='PNG')
    output.seek(0)
    return output


class PrepareImageTests(SimpleTestCase):
    def test_converts_to_a_smaller_jpeg(self):
        from PIL import Image

        jpeg = prepare_image(png_bytes((3000, 4000), 'RGBA'))
        image = Image.open(io.BytesIO(jpeg))
        self.assertEqual((image.format, max(image.size)), ('JPEG', 1600))

    def test_rejects_non_images_and_tiny_images(self):
        for upload in [io.BytesIO(b'%PDF-1.7 not an image'), png_bytes((80, 80))]:
            with self.subTest(), self.assertRaises(FlyerImageError):
                prepare_image(upload)


def stream_lines(pieces, cumulative=True):
    """Server-sent events shaped like the live Cloudflare response for Moondream (Nov 2026)."""
    usage0 = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0, 'neurons': 0}
    events = [
        {'id': 'abc', 'status': 'processing', 'usage': usage0},
        {'mode': 'replace', 'name': 'input_tokens', 'value': 764,
         'usage': {'prompt_tokens': 764, 'completion_tokens': 0, 'total_tokens': 764, 'neurons': 20.8}},
        {'mode': 'replace', 'name': 'output_tokens', 'value': 75,
         'usage': {'prompt_tokens': 764, 'completion_tokens': 75, 'total_tokens': 839, 'neurons': 27.7}},
    ]
    sent = ''
    for index, piece in enumerate(pieces):
        sent += piece
        events.append({'chunk': {'answer': sent if cumulative else piece, 'caption': None, 'finish_reason': '',
                                 'objects': None, 'points': None, 'reasoning': None},
                       'index': index, 'usage': usage0})
    lines = [f'data: {json.dumps(event)}\n'.encode() for event in events]
    return [line for pair in zip(lines, [b'\n'] * len(lines)) for line in pair] + [b'data: [DONE]\n']


def response(lines):
    body = mock.MagicMock()
    body.__enter__.return_value = iter(lines)
    return body


class ReadStreamTests(SimpleTestCase):
    def test_rebuilds_the_answer_from_cumulative_pieces(self):
        answer, usage = read_stream(stream_lines(['{', '\n', '"title": "Robot Night"', '\n}']))
        self.assertEqual(json.loads(answer), {'title': 'Robot Night'})
        self.assertEqual(usage, {'prompt_tokens': 764, 'completion_tokens': 75, 'neurons': 27.7})

    def test_also_joins_plain_deltas(self):
        answer, _ = read_stream(stream_lines(['{"title": ', '"Robot Night"}'], cumulative=False))
        self.assertEqual(answer, '{"title": "Robot Night"}')

    def test_an_empty_stream_has_no_answer(self):
        self.assertEqual(read_stream([b'data: {"result": {}}\n', b'data: [DONE]\n'])[0], '')

    def test_errors_in_the_stream_raise(self):
        with self.assertRaises(ExtractionError):
            read_stream([b'data: {"errors": [{"code": 3010, "message": "bad image"}]}\n'])


@override_settings(CLOUDFLARE_ACCOUNT_ID='acct', CLOUDFLARE_API_TOKEN='token', FLYER_TIMEOUT=1)
class CallVisionModelTests(SimpleTestCase):
    @override_settings(CLOUDFLARE_ACCOUNT_ID='', CLOUDFLARE_API_TOKEN='')
    def test_needs_cloudflare_keys(self):
        with self.assertRaises(ExtractionError):
            call_vision_model(b'jpeg')

    @mock.patch('apps.flyers.extraction.urllib.request.urlopen')
    def test_streams_the_request_and_returns_the_answer(self, urlopen):
        urlopen.return_value = response(stream_lines(['{"title"', ': "x"}']))
        self.assertEqual(call_vision_model(b'jpeg'), '{"title": "x"}')
        sent = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual((sent['task'], sent['stream'], sent['reasoning']), ('query', True, False))
        self.assertTrue(sent['image'].startswith('data:image/jpeg;base64,'))

    @mock.patch('apps.flyers.extraction.urllib.request.urlopen')
    def test_an_empty_result_is_an_error(self, urlopen):
        # What the live API returns when streaming is off.
        urlopen.return_value = response([b'{"result":{},"success":true,"errors":[],"messages":[]}'])
        with self.assertRaises(ExtractionError):
            call_vision_model(b'jpeg')

    @mock.patch('apps.flyers.extraction.time.sleep')
    @mock.patch('apps.flyers.extraction.urllib.request.urlopen')
    def test_retries_once_on_a_server_error(self, urlopen, _sleep):
        error = urllib.error.HTTPError('url', 503, 'busy', {}, None)
        urlopen.side_effect = [error, response(stream_lines(['ok']))]
        self.assertEqual(call_vision_model(b'jpeg'), 'ok')
        self.assertEqual(urlopen.call_count, 2)

    @mock.patch('apps.flyers.extraction.urllib.request.urlopen')
    def test_does_not_retry_a_bad_request(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError('url', 400, 'bad', {}, None)
        with self.assertRaises(ExtractionError):
            call_vision_model(b'jpeg')
        self.assertEqual(urlopen.call_count, 1)

    @mock.patch('apps.flyers.extraction.time.sleep')
    @mock.patch('apps.flyers.extraction.urllib.request.urlopen')
    def test_gives_up_after_two_timeouts(self, urlopen, _sleep):
        urlopen.side_effect = TimeoutError
        with self.assertRaises(ExtractionError):
            call_vision_model(b'jpeg')
        self.assertEqual(urlopen.call_count, 2)


class RealFlyerAnswerTests(SimpleTestCase):
    """Moondream's actual answers for real campus flyers (live test, Nov 15 2026)."""

    venues = VENUES + [SimpleNamespace(pk=5, name='State Farm Center', aliases=[], building_code=None, location=None)]
    interests = INTERESTS + [SimpleNamespace(pk=9, name='Activism', slug='activism')]

    def build(self, answer):
        return build_form_values(parse_answer(answer), today=TODAY, interests=self.interests,
                                 venues=self.venues, organizations=[])

    def test_bargaining_session_flyer(self):
        values, _, review = self.build(
            '{\n  "title": "THE MOST IMPORTANT CONTRACT BARGAINING SESSION",\n  "description": "We are nearing the end '
            'of contract negotiations.",\n  "date": "03/24TH/2023",\n  "start_time": "10AM",\n  "end_time": "5PM",\n'
            '  "location": "SDRP, 301 E Gregory, Champaign (aka Ikenberry)",\n  "organizer": "GEO",\n  "price": "free",'
            '\n  "registration_url": null,\n  "categories": [\n    "contract",\n    "bargaining"\n  ]\n}'
        )
        self.assertEqual(values['date'], '2023-03-24')  # "24TH" no longer breaks the date
        self.assertEqual(review['date'], 'check')  # and a past date is flagged
        self.assertEqual((values['start_time'], values['end_time']), ('10:00', '17:00'))
        self.assertEqual(values['interests'], [9])  # bargaining → Activism

    def test_tailgate_flyer_matches_the_arena_but_asks_for_a_check(self):
        values, _, review = self.build(
            '{"title": "Homecoming Tailgate", "date": "Saturday, October 3rd", "start_time": "9:00 AM", '
            '"end_time": "9:00 PM", "location": "Tailgate Village (Outside State Farm Arena)", "organizer": "SHPE", '
            '"price": "free", "registration_url": null, "categories": ["tailgate", "football"]}'
        )
        self.assertEqual(values['venue'], 5)
        self.assertEqual(values['location_text'], 'Tailgate Village (Outside State Farm Arena)')
        self.assertEqual(review['location_text'], 'check')
        self.assertEqual(review['date'], 'check')  # Oct 3 with no year is ~11 months away: probably an old flyer

    def test_placeholder_words_and_overnight_end(self):
        values, _, review = self.build(
            '{"title": "Welcome Week Party", "date": "Friday, November 20", "start_time": "10PM", "end_time": "2AM", '
            '"location": "Champaign, Illinois", "organizer": "N/A", "price": "free", "registration_url": "N/A", '
            '"categories": ["music"]}'
        )
        self.assertEqual(values['start_time'], '22:00')
        self.assertEqual(values['end_time'], '')  # the form can't hold an end after midnight yet
        self.assertEqual(review['end_time'], 'missing')
        self.assertNotIn('Register', values['description'])

    def test_a_start_without_am_pm_takes_the_end_times(self):
        values, _, _ = self.build(
            '{"title": "Cancel Debt Teach-In", "date": "Monday, Feb. 22, 2021", "start_time": "5:00", '
            '"end_time": "6:30pm", "location": "CST", "price": "free", "registration_url": "tinyurl.com/CancelDebtTeachIn",'
            ' "categories": ["austerity", "debt"]}'
        )
        self.assertEqual((values['start_time'], values['end_time']), ('17:00', '18:30'))
        self.assertIn('Register: https://tinyurl.com/CancelDebtTeachIn', values['description'])


class CampusBuildingAliasTests(SimpleTestCase):
    """The building list from apps/venues/campus_buildings.py against Moondream's real location text."""

    def setUp(self):
        from apps.venues.campus_buildings import BUILDINGS

        self.venues = [
            SimpleNamespace(pk=i, name=b['name'], aliases=b.get('aliases', []), building_code=b.get('code'), location=None)
            for i, b in enumerate(BUILDINGS, start=1)
        ]

    def match(self, text):
        venue, room, score = match_venue(text, self.venues)
        return (venue.name if venue else None, room, score)

    def test_locations_from_real_flyers(self):
        self.assertEqual(self.match('OUTSIDE THE HENRY ADMINISTRATION BUILDING, WEST SIDE'),
                         ('Henry Administration Building', 'OUTSIDE THE HENRY ADMINISTRATION BUILDING, WEST SIDE', 1.0))
        self.assertEqual(self.match('UIUC SMITH MEMORIAL HALL'), ('Smith Memorial Hall', '', 1.0))
        self.assertEqual(self.match('SDRP, 301 E Gregory, Champaign (aka Ikenberry)')[0],
                         'Student Dining and Residential Programs Building')
        self.assertEqual(self.match('Tailgate Village (Outside State Farm Arena)')[0], 'State Farm Center')

    def test_short_names_students_use(self):
        for text, name in [('ECEB 1002', 'Electrical and Computer Engineering Building'),
                           ('BIF Atrium', 'Business Instructional Facility'),
                           ('Room 1404, Siebel Center for Computer Science', 'Siebel Center for Computer Science'),
                           ('Assembly Hall', 'State Farm Center'),
                           ('Smith Music Hall, Room 25', 'Smith Memorial Hall')]:
            with self.subTest(text=text):
                self.assertEqual(self.match(text)[0], name)

    def test_vague_places_stay_unmatched(self):
        for text in ['University of Illinois Urbana-Champaign', 'Champaign, Illinois', 'CST', 'Zoom']:
            with self.subTest(text=text):
                self.assertIsNone(self.match(text)[0])
