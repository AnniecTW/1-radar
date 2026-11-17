from datetime import datetime

from django import forms
from django.core import signing
from django.utils import timezone

from apps.interests.models import Interest
from apps.venues.models import Venue

from .models import Event

MAX_COVER_BYTES = 5 * 1024 * 1024
MAX_CATEGORIES = 3
PENDING_COVER_SALT = 'events.pending-cover'
PENDING_COVER_MAX_AGE = 60 * 60 * 24
KIND_CHOICES = [
    ('rsvp', 'Free, RSVP required'),
    ('drop_in', 'Free, drop-in'),
    ('paid', 'Paid'),
]
VISIBILITY_NOTES = {
    Event.Visibility.PUBLIC: 'Listed on the feed, map, search and your organization page.',
    Event.Visibility.CAMPUS_ONLY: 'Listed everywhere with a "Campus only" badge. Only verified students can RSVP.',
    Event.Visibility.UNLISTED: 'Hidden from listings. Only people with the link can find it.',
}


class EventForm(forms.Form):
    """The manual Create/Edit Event form (FR-17). `publishing` turns on the publish-only rules."""

    host = forms.ChoiceField(label='Post as')
    title = forms.CharField(max_length=150, required=False)
    description = forms.CharField(widget=forms.Textarea(attrs={'rows': 5}), required=False, max_length=5000)
    interests = forms.ModelMultipleChoiceField(
        queryset=Interest.objects.none(), required=False, widget=forms.CheckboxSelectMultiple, label='Categories'
    )
    date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    start_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={'type': 'time'}), label='Starts')
    end_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={'type': 'time'}), label='Ends')
    venue = forms.ModelChoiceField(queryset=Venue.objects.none(), required=False, empty_label='Choose a building…',
                                   label='Campus building')
    location_text = forms.CharField(max_length=255, required=False, label='Room or other details')
    latitude = forms.FloatField(required=False, min_value=-90, max_value=90, widget=forms.HiddenInput)
    longitude = forms.FloatField(required=False, min_value=-180, max_value=180, widget=forms.HiddenInput)
    cover = forms.ImageField(required=False, label='Cover image')
    remove_cover = forms.BooleanField(required=False)
    # Signed link to a photo uploaded on an earlier try that had a mistake, so it isn't lost.
    pending_cover = forms.CharField(required=False, widget=forms.HiddenInput)
    kind = forms.ChoiceField(choices=KIND_CHOICES, initial='rsvp', widget=forms.RadioSelect)
    capacity = forms.IntegerField(required=False, min_value=1, max_value=100000)
    waitlist_enabled = forms.BooleanField(required=False, initial=True, label="Open a waitlist when it's full")
    price_text = forms.CharField(max_length=60, required=False, label='Price')
    external_url = forms.URLField(max_length=255, required=False, assume_scheme='https', label='Ticket link')
    contact_info = forms.CharField(max_length=254, required=False, label='Or a contact for tickets')
    visibility = forms.ChoiceField(choices=Event.Visibility.choices, initial=Event.Visibility.PUBLIC,
                                   widget=forms.RadioSelect)

    def __init__(self, *args, host_choices, tz, publishing=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.tz = tz
        self.publishing = publishing
        self.fields['host'].choices = host_choices
        self.fields['interests'].queryset = Interest.objects.filter(is_active=True).order_by('name')
        self.fields['venue'].queryset = Venue.objects.filter(is_campus=True).order_by('name')
        placeholders = {
            'title': 'e.g. Robot Battle Night',
            'location_text': 'e.g. Room 1404, or "north lawn by the fountain"',
            'price_text': 'e.g. $10, $5 for members',
            'external_url': 'https://',
            'contact_info': 'Email or phone',
        }
        for name, text in placeholders.items():
            self.fields[name].widget.attrs['placeholder'] = text
        self.fields['description'].widget.attrs['maxlength'] = 5000

    @classmethod
    def initial_from_event(cls, event, tz):
        start = timezone.localtime(event.start_at, tz) if event.start_at else None
        end = timezone.localtime(event.end_at, tz) if event.end_at else None
        kind = 'paid' if not event.is_free else ('drop_in' if not event.rsvp_required else 'rsvp')
        return {
            'host': event.organization.slug if event.organization_id else 'me',
            'title': event.title,
            'description': event.description,
            'interests': list(event.interests.values_list('pk', flat=True)),
            'date': start.date() if start else None,
            'start_time': start.time().replace(second=0, microsecond=0) if start else None,
            'end_time': end.time().replace(second=0, microsecond=0) if end else None,
            'venue': event.venue_id,
            'location_text': event.location_text,
            'latitude': event.location.y if event.location else None,
            'longitude': event.location.x if event.location else None,
            'kind': kind,
            'capacity': event.capacity,
            'waitlist_enabled': event.waitlist_enabled,
            'price_text': event.price_text,
            'external_url': event.external_url or '',
            'contact_info': event.contact_info or '',
            'visibility': event.visibility,
        }

    def clean_interests(self):
        interests = self.cleaned_data['interests']
        if len(interests) > MAX_CATEGORIES:
            raise forms.ValidationError(f'Pick up to {MAX_CATEGORIES} categories.')
        return interests

    def clean_pending_cover(self):
        token = self.cleaned_data.get('pending_cover')
        if not token:
            return ''
        try:
            return signing.loads(token, salt=PENDING_COVER_SALT, max_age=PENDING_COVER_MAX_AGE)
        except signing.BadSignature:
            return ''

    def clean_cover(self):
        cover = self.cleaned_data.get('cover')
        if cover and cover.size > MAX_COVER_BYTES:
            raise forms.ValidationError('Choose an image under 5 MB.')
        return cover

    def _combine(self, day, time):
        return timezone.make_aware(datetime.combine(day, time), self.tz)

    def clean(self):
        data = super().clean()
        day, start, end = data.get('date'), data.get('start_time'), data.get('end_time')
        data['start_at'] = self._combine(day, start) if day and start else None
        data['end_at'] = self._combine(day, end) if day and end else None
        if data['start_at'] and data['end_at'] and data['end_at'] <= data['start_at']:
            self.add_error('end_time', 'The end time must be after the start time.')
        if (data.get('latitude') is None) != (data.get('longitude') is None):
            self.add_error('location_text', 'Drop the pin again: its position was incomplete.')

        kind = data.get('kind')
        if kind != 'rsvp':
            data['capacity'] = None
        if kind != 'paid':
            data['price_text'], data['external_url'], data['contact_info'] = '', '', ''

        if self.publishing:
            self._check_publish_requirements(data)
        return data

    def _check_publish_requirements(self, data):
        required = {
            'title': 'Add a title.',
            'description': 'Add a description so people know what to expect.',
            'date': 'Pick a date.',
            'start_time': 'Pick a start time.',
            'end_time': 'Pick an end time.',
        }
        for field, message in required.items():
            if not data.get(field) and field not in self.errors:
                self.add_error(field, message)
        if not data.get('interests') and 'interests' not in self.errors:
            self.add_error('interests', 'Pick at least one category so people can find your event.')
        if not data.get('venue') and not (data.get('location_text') or '').strip():
            self.add_error('location_text', 'Choose a building or describe where it is.')
        if data.get('kind') == 'paid':
            if not (data.get('price_text') or '').strip():
                self.add_error('price_text', 'Add a price.')
            if not data.get('external_url') and not (data.get('contact_info') or '').strip():
                self.add_error('external_url', 'Add a ticket link or a contact.')
        if data.get('start_at') and data['start_at'] <= timezone.now():
            self.add_error('date', 'Pick a time in the future.')
