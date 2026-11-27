"""Embedding-based "Recommended for you" (PRD §3.8, FR-40 to FR-42).

Each page load builds the user's profile vector from vectors already stored in the database: the
events they acted on and the interests they chose. Nothing here calls Cloudflare. Upcoming events are
then ranked in one query by similarity to that vector, blended with follows, popularity, distance and
how soon the event starts, minus a penalty for events close to ones the user marked "Not interested".
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.contrib.gis.db.models.functions import Distance
from django.core import signing
from django.contrib.gis.geos import Point
from django.db.models import (
    Case, CharField, Exists, ExpressionWrapper, F, FloatField, Func, Max, Min, OuterRef, Q, QuerySet, Value, When,
)
from django.db.models.functions import Cast, Coalesce, Greatest, Least
from pgvector.django import CosineDistance

from apps.attendance.models import CheckIn
from apps.engagement.models import EventLike, EventSave, EventView
from apps.events.models import Event
from apps.events.semantic_search import cosine
from apps.interests.models import UserInterest
from apps.organizations.models import OrganizationFollow, OrganizationMembership
from apps.rsvps.models import RSVP

from .models import RecommendationImpression

# v2 added the "Not interested" penalty; v3 rescales similarity per user (see rank_events).
ALGORITHM_VERSION = 'embedding-v3'
FALLBACK_ALGORITHM_VERSION = 'interest-tags-v1'
CAROUSEL_SIZE = 10
SIMILARITY_MIN_SPREAD = 0.01  # Below this, candidates are equally close and similarity isn't rescaled.

# How much one action says about a user's taste. All RSVP statuses count the same: whether a user ends
# up "going", "waitlisted" or "interested" depends on how the event is set up, not on how keen they are.
CHECKIN_WEIGHT = 5.0
RSVP_WEIGHT = 4.0
SAVE_WEIGHT = 3.0
LIKE_WEIGHT = 2.0
VIEW_WEIGHT = 1.0  # A cancelled RSVP also counts as one view.
MAX_VIEWS_PER_EVENT = 2
INTEREST_WEIGHT = 3.0  # Each interest the user chose. These don't fade over time.

# An action loses half its weight every 30 days. After 180 days it is worth about 1/64, so older rows
# aren't read at all, which keeps the work the same size however long someone has used Radar.
HALF_LIFE_DAYS = 30
LOOKBACK_DAYS = 180
MAX_ROWS_PER_ACTION = 200

SCORE_WEIGHTS = {'similarity': 0.45, 'follows': 0.15, 'popularity': 0.15, 'proximity': 0.15, 'urgency': 0.10}
URGENCY_WINDOW = timedelta(days=14)
WALK_METERS = 1250  # FR-12's 15-minute walk.
FAR_METERS = 5000
CATEGORY_CAP = 4  # No category takes more than 40% of the top 10.
RANKED_POOL = 40  # Ranked candidates read back, so the category cap has events to choose from.

# "Not interested" (FR-43): events close to a dismissed one lose up to DISMISS_PENALTY from their score (which
# tops out around 1). Nothing below 0.75 similarity, rising evenly to the full penalty at 0.90, where repeats of
# the same series sit. An event near several dismissals takes the biggest penalty, not the sum, so a few
# dismissals can't bury a whole topic. The penalty fades with the same 30-day half-life as other actions.
DISMISS_PENALTY = 0.2
DISMISS_SIMILARITY_START = 0.75
DISMISS_SIMILARITY_FULL = 0.90
MAX_DISMISSALS = 20  # The most recent ones; older ones have mostly faded anyway.

# For the "Similar to <event>" reason. BGE scores related text highly, so this is deliberately strict.
SIMILAR_REASON_MIN = 0.8
REASON_ANCHORS = 10

# A quiet refresh runs within seconds of the page loading; anything logged in this window is its first set.
REPLACE_WINDOW = timedelta(minutes=2)
# Impressions older than this are deleted, matching how far back the profile reads activity. Six months is
# plenty to measure click-through rate and tune the weights, and it keeps the table from growing forever.
IMPRESSION_RETENTION_DAYS = LOOKBACK_DAYS

# A shared location lives in a signed cookie on the user's device, never in the database. Six hours keeps
# it fresh enough for campus-scale distances without re-reading it on every visit.
LOCATION_COOKIE = 'radar_rec_location'
LOCATION_COOKIE_SALT = 'discovery.recommendation-location'
LOCATION_MAX_AGE = timedelta(hours=6)
# Locations snap to a grid of 0.005 degrees: about 555 m north-south and 425 m east-west on campus, so a point
# is at most about 350 m off. That shifts an event's score by about 0.01. The browser snaps before sending
# (landing-location.js), so the exact position never leaves the device; the server snaps again regardless.
LOCATION_GRID_DEGREES = 0.005


# Profile vector ----------------------------------------------------------------------------------------

def decay(at: datetime, now: datetime) -> float:
    age_days = max(0.0, (now - at).total_seconds() / 86400)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


@dataclass
class EventSignal:
    """Everything one user did to one event."""
    strong_weight: float = 0.0  # The strongest action (check-in, RSVP, save or like), after decay.
    first_strong_at: datetime | None = None
    soft_times: list[datetime] = field(default_factory=list)  # Views and cancelled RSVPs.

    def add_strong(self, weight: float, at: datetime, now: datetime) -> None:
        self.strong_weight = max(self.strong_weight, weight * decay(at, now))
        if self.first_strong_at is None or at < self.first_strong_at:
            self.first_strong_at = at

    def weight(self, now: datetime) -> float:
        """The strongest action, plus up to two views. Views made after a stronger action don't count,
        because people revisit an event they've committed to just to check the time or place."""
        views = sorted(
            (at for at in self.soft_times if self.first_strong_at is None or at < self.first_strong_at),
            reverse=True,
        )[:MAX_VIEWS_PER_EVENT]
        return self.strong_weight + sum(VIEW_WEIGHT * decay(at, now) for at in views)


def weighted_average(pairs) -> list[float] | None:
    """Average of (vector, weight) pairs, or None when there is nothing to average."""
    total = 0.0
    summed = None
    for vector, weight in pairs:
        if weight <= 0 or vector is None:
            continue
        if summed is None:
            summed = [0.0] * len(vector)
        for i, value in enumerate(vector):
            summed[i] += weight * value
        total += weight
    if summed is None:
        return None
    return [value / total for value in summed]


def hosted_event_ids(user) -> QuerySet:
    """Events the user runs: as the individual host, or as an Owner or Admin of the organization."""
    managed = OrganizationMembership.objects.filter(
        user=user, role__in=[OrganizationMembership.Role.OWNER, OrganizationMembership.Role.ADMIN],
    ).values('organization_id')
    return Event.objects.filter(Q(host_user=user) | Q(organization_id__in=managed)).values('pk')


STRONG_WEIGHTS = {'checkin': CHECKIN_WEIGHT, 'rsvp': RSVP_WEIGHT, 'save': SAVE_WEIGHT, 'like': LIKE_WEIGHT}


# What a "Not interested" cancels when it came before the dismissal. Saves, RSVPs and check-ins always count:
# they are a clear yes (and Recommended never shows an event the user has saved, RSVP'd to or checked in to).
CANCELLED_BY_DISMISSAL = {'view', 'cancelled', 'like'}


def history_start(user, now: datetime) -> datetime:
    """The oldest activity recommendations read: six months back, or the last "Clear recommendation history"
    on Account & privacy if that is more recent. Clearing deletes nothing; older rows are just ignored."""
    from apps.accounts.selectors import get_recommendation_reset_at
    from apps.accounts.services import get_or_create_profile

    reset_at = get_recommendation_reset_at(get_or_create_profile(user))
    lookback = now - timedelta(days=LOOKBACK_DAYS)
    return max(lookback, reset_at) if reset_at else lookback


def dismissals(user, since: datetime | None = None) -> QuerySet:
    """The user's "Not interested" rows (since the last history reset, when `since` is given), each with
    `dismissed_when`. Dismissals from before dismissed_at existed fall back to when the card was shown."""
    rows = (RecommendationImpression.objects.filter(user=user, dismissed=True)
            .annotate(dismissed_when=Coalesce('dismissed_at', 'shown_at')))
    return rows if since is None else rows.filter(dismissed_when__gte=since)


def dismissed_event_ids(user, since: datetime | None = None) -> QuerySet:
    return dismissals(user, since).values('event_id')


def collect_signals(user, now: datetime, since: datetime | None = None) -> dict:
    """The user's actions since `since` (default: history_start), grouped by event, in one round trip.
    Leaves out events they host. A "Not interested" cancels the views, likes and cancelled RSVPs of that event
    from before it, so viewing an event and then dismissing it doesn't still pull the profile toward it.
    Anything after it (coming back to the event from search, say) counts again."""
    cutoff = since or history_start(user, now)
    hosted = hosted_event_ids(user)

    def rows(model, time_field, kind):
        queryset = model.objects.filter(user=user, **{f'{time_field}__gte': cutoff}).exclude(event_id__in=hosted)
        return (queryset.annotate(kind=kind, at=F(time_field)).order_by(f'-{time_field}')
                .values_list('event_id', 'at', 'kind')[:MAX_ROWS_PER_ACTION])

    rsvp_kind = Case(When(status=RSVP.Status.CANCELLED, then=Value('cancelled')), default=Value('rsvp'),
                     output_field=CharField())
    actions = rows(CheckIn, 'checked_in_at', Value('checkin', output_field=CharField())).union(
        rows(RSVP, 'created_at', rsvp_kind),
        rows(EventSave, 'created_at', Value('save', output_field=CharField())),
        rows(EventLike, 'created_at', Value('like', output_field=CharField())),
        rows(EventView, 'created_at', Value('view', output_field=CharField())),
        all=True,
    )
    dismissed_when = dict(dismissals(user, cutoff).order_by('dismissed_when').values_list('event_id', 'dismissed_when'))
    signals: dict = {}
    for event_id, at, kind in actions:
        if kind in CANCELLED_BY_DISMISSAL and event_id in dismissed_when and at <= dismissed_when[event_id]:
            continue  # dismissed_when holds the latest dismissal, if there were several.
        signal = signals.setdefault(event_id, EventSignal())
        if kind in STRONG_WEIGHTS:
            signal.add_strong(STRONG_WEIGHTS[kind], at, now)
        else:  # A view, or a cancelled RSVP, which counts as one.
            signal.soft_times.append(at)
    return signals


@dataclass
class Profile:
    vector: list[float] | None
    activity_weight: float  # Total decayed weight from actions: how much evidence the profile has.
    interest_weight: float
    anchors: list[tuple[str, list[float]]]  # (title, vector) of the user's strongest events, for reasons.
    chosen_interest_ids: set  # Interests the user picked, with or without a vector yet.


def build_profile(user, now: datetime, since: datetime | None = None) -> Profile:
    weights = {event_id: signal.weight(now) for event_id, signal in collect_signals(user, now, since).items()}
    event_rows = list(
        Event.objects.filter(pk__in=[event_id for event_id, weight in weights.items() if weight > 0],
                             embedding__isnull=False)
        .values_list('pk', 'title', 'embedding')
    )
    # Only interests the user picked. Inferred rows would count the same actions a second time.
    interest_rows = list(
        UserInterest.objects.filter(user=user).exclude(source=UserInterest.Source.INFERRED)
        .values_list('interest_id', 'interest__embedding', 'interest__is_active', 'weight')
    )
    event_pairs = [(vector, weights[pk]) for pk, _, vector in event_rows]
    interest_pairs = [(vector, INTEREST_WEIGHT * weight)
                      for _, vector, is_active, weight in interest_rows if is_active and vector is not None]
    strongest = sorted(event_rows, key=lambda row: weights[row[0]], reverse=True)[:REASON_ANCHORS]
    return Profile(
        vector=weighted_average(event_pairs + interest_pairs),
        activity_weight=sum(weight for _, weight in event_pairs),
        interest_weight=sum(weight for _, weight in interest_pairs),
        anchors=[(title, vector) for _, title, vector in strongest],
        chosen_interest_ids={interest_id for interest_id, *_ in interest_rows},
    )


# Ranking -----------------------------------------------------------------------------------------------

def exclude_for_user(events: QuerySet, user, since: datetime | None = None) -> QuerySet:
    """Leave out events the user already has in hand, hosts, or dismissed (since the last history reset)."""
    return (
        events.exclude(pk__in=hosted_event_ids(user))
        .exclude(pk__in=RSVP.objects.filter(user=user).exclude(status=RSVP.Status.CANCELLED).values('event_id'))
        .exclude(pk__in=EventSave.objects.filter(user=user).values('event_id'))
        .exclude(pk__in=CheckIn.objects.filter(user=user).values('event_id'))
        .exclude(pk__in=dismissed_event_ids(user, since))
    )


def score_weights(has_location: bool) -> dict:
    """Without the user's location, proximity's share is spread across the other parts."""
    if has_location:
        return dict(SCORE_WEIGHTS)
    rest = {part: weight for part, weight in SCORE_WEIGHTS.items() if part != 'proximity'}
    total = sum(rest.values())
    return {**{part: weight / total for part, weight in rest.items()}, 'proximity': 0.0}


def _clamp01(expression):
    return Greatest(Least(expression, Value(1.0)), Value(0.0))


def recent_dismissals(user, now: datetime, since: datetime | None = None) -> list[tuple[list[float], float]]:
    """(vector, strength) of the user's most recent "Not interested" events, where strength is how much of the
    penalty is left after fading since the dismissal."""
    rows = (dismissals(user, since or history_start(user, now)).filter(event__embedding__isnull=False)
            .order_by('-dismissed_when')
            .values_list('event_id', 'dismissed_when', 'event__embedding')[:MAX_DISMISSALS * 2])
    latest = {}
    for event_id, dismissed_when, embedding in rows:
        latest.setdefault(event_id, (list(embedding), decay(dismissed_when, now)))
    return list(latest.values())[:MAX_DISMISSALS]


def dismissal_penalty(dismissals):
    """The SQL for each candidate's "Not interested" penalty: the biggest one over the dismissed events."""
    span = DISMISS_SIMILARITY_FULL - DISMISS_SIMILARITY_START
    # Events without a vector yet count as unrelated. The Coalesce matters: Postgres' LEAST and GREATEST skip
    # NULLs, so without it _clamp01 would turn a missing similarity into 1 and give them the full penalty.
    terms = [
        Value(DISMISS_PENALTY * strength) * _clamp01(
            (Coalesce(Value(1.0) - CosineDistance('embedding', vector), Value(0.0)) - Value(DISMISS_SIMILARITY_START))
            / Value(span))
        for vector, strength in dismissals
    ]
    if not terms:
        return Value(0.0)
    return Greatest(Value(0.0), *terms, output_field=FloatField())


def rank_events(candidates: QuerySet, user, now: datetime, profile_vector, location=None,
                dismissals=()) -> list[Event]:
    """Score every candidate in SQL and return the best RANKED_POOL, highest first. Each event gets
    rec_score, rec_similarity, rec_follows, rec_penalty and rec_distance (metres, or None) for the reasons."""
    weights = score_weights(location is not None)
    max_popularity = candidates.aggregate(top=Max('popularity_score'))['top'] or 0

    # Raw cosine similarity sits in a narrow band (about 0.4-0.85 with BGE: unrelated events still score ~0.6),
    # so on its own it barely moves the score and "starts soon" decides the order. Rescale it per user: their
    # closest candidate gets 1, their furthest 0, like popularity is divided by the most popular event.
    # Events without a vector yet get 0, so they can still rank on the other parts.
    raw_similarity = Value(1.0) - CosineDistance('embedding', profile_vector)
    band = candidates.filter(embedding__isnull=False).aggregate(low=Min(raw_similarity), high=Max(raw_similarity))
    low, high = band['low'], band['high']
    if low is not None and high - low > SIMILARITY_MIN_SPREAD:
        # Coalesce inside the clamp: LEAST/GREATEST skip NULLs, so a vectorless event would otherwise get 1.
        similarity = _clamp01(Coalesce((raw_similarity - Value(low)) / Value(high - low), Value(0.0)))
    else:  # One candidate, or all equally close: nothing to stretch.
        similarity = Coalesce(Greatest(raw_similarity, Value(0.0)), Value(0.0))
    follows = Case(
        When(Exists(OrganizationFollow.objects.filter(user=user, organization_id=OuterRef('organization_id'))),
             then=Value(1.0)),
        default=Value(0.0), output_field=FloatField(),
    )
    if max_popularity > 0:
        popularity = _clamp01(F('popularity_score') / Value(float(max_popularity)))
    else:
        popularity = Value(0.0)
    # 1 for events starting now (or already running), falling in a straight line to 0 at 14 days away.
    start_epoch = Func(F('start_at'), template='EXTRACT(EPOCH FROM %(expressions)s)::double precision',
                       output_field=FloatField())
    deadline = (now + URGENCY_WINDOW).timestamp()
    urgency = _clamp01((Value(deadline) - start_epoch) / Value(URGENCY_WINDOW.total_seconds()))

    annotations = {'rec_similarity': similarity, 'rec_follows': follows, 'rec_popularity': popularity,
                   'rec_urgency': urgency, 'rec_penalty': dismissal_penalty(dismissals)}
    if location is not None:
        distance = Cast(Distance('location', Point(location[1], location[0], srid=4326)), FloatField())
        annotations['rec_distance'] = distance
        # 1 within a 15-minute walk, falling to 0 at 5 km. Events with no map location get 0.
        annotations['rec_proximity'] = Case(
            When(location__isnull=True, then=Value(0.0)),
            default=_clamp01((Value(float(FAR_METERS)) - distance) / Value(float(FAR_METERS - WALK_METERS))),
            output_field=FloatField(),
        )
    else:
        annotations['rec_proximity'] = Value(0.0)

    score = ExpressionWrapper(
        sum((Value(weights[part]) * F(f'rec_{part}') for part in SCORE_WEIGHTS), Value(0.0)) - F('rec_penalty'),
        output_field=FloatField(),
    )
    ranked = candidates.annotate(**annotations).annotate(rec_score=score).order_by('-rec_score', 'start_at')
    events = list(ranked[:RANKED_POOL])
    for event in events:
        event.rec_distance = getattr(event, 'rec_distance', None)
    return events


def apply_category_cap(events: list, categories_of, size: int = CAROUSEL_SIZE, cap: int = CATEGORY_CAP) -> list:
    """Take events in order, skipping any whose category already fills `cap` slots. An event counts toward
    each of its categories. If the cap leaves gaps, skipped events fill them so the row stays full."""
    picked, skipped, counts = [], [], Counter()
    for event in events:
        categories = categories_of(event)
        if any(counts[category] >= cap for category in categories):
            skipped.append(event)
            continue
        picked.append(event)
        counts.update(categories)
        if len(picked) == size:
            return picked
    return picked + skipped[:size - len(picked)]


# Reasons (FR-42) ---------------------------------------------------------------------------------------

def recommendation_reason(event, chosen_interest_ids: set, anchors, event_vector=None) -> str:
    """One short, true sentence about why this event was picked. Empty when none applies."""
    if event_vector is not None and anchors:
        best_title, best = max(((title, cosine(event_vector, vector)) for title, vector in anchors),
                               key=lambda pair: pair[1])
        if best >= SIMILAR_REASON_MIN:
            return f'Similar to {best_title}'
    matching = [interest.name for interest in event.interests.all() if interest.pk in chosen_interest_ids]
    if matching:
        return f'Because you like {matching[0]}'
    if getattr(event, 'rec_follows', 0) and event.organization:
        return f'From {event.organization.name}, which you follow'
    distance = getattr(event, 'rec_distance', None)
    if distance is not None and distance <= WALK_METERS:
        return 'A short walk from you'
    return ''


# Entry point -------------------------------------------------------------------------------------------

def recommend_events(user, now: datetime, location=None) -> list[Event]:
    """Up to 10 events for the "Recommended for you" row. Ranks by the profile vector, then fills any gap
    with upcoming events in the user's chosen interests. Empty when the user has neither."""
    from .selectors import list_upcoming_events

    since = history_start(user, now)
    candidates = exclude_for_user(list_upcoming_events(now), user, since)
    profile = build_profile(user, now, since)
    events = []
    if profile.vector is not None:
        ranked = rank_events(candidates, user, now, profile.vector, location, recent_dismissals(user, now, since))
        events = apply_category_cap(ranked, lambda event: [interest.pk for interest in event.interests.all()])
        for event in events:
            event.recommendation_algorithm = ALGORITHM_VERSION

    if len(events) < CAROUSEL_SIZE and profile.chosen_interest_ids:
        shown = [event.pk for event in events]
        matched = (candidates.filter(interests__in=profile.chosen_interest_ids).exclude(pk__in=shown).distinct()
                   .order_by('-popularity_score', 'start_at')[:CAROUSEL_SIZE - len(events)])
        for event in matched:
            event.recommendation_algorithm = FALLBACK_ALGORITHM_VERSION
            event.rec_score = 0.0
            events.append(event)

    for event in events:
        event.recommendation_reason = recommendation_reason(
            event, profile.chosen_interest_ids, profile.anchors, event.embedding)
    return events


# Impressions and clicks ---------------------------------------------------------------------------------

def log_impressions(user, events: list[Event], now: datetime) -> None:
    """One row per card shown, so click-through rate can be measured and the weights tuned (PRD §3.8).
    Also prunes this user's old rows, so the table stays bounded without a scheduled job."""
    prune_impressions(now, user=user)
    RecommendationImpression.objects.bulk_create([
        RecommendationImpression(
            user=user, event=event, rank=rank, score=float(getattr(event, 'rec_score', 0.0) or 0.0),
            algorithm_version=getattr(event, 'recommendation_algorithm', ALGORITHM_VERSION),
        )
        for rank, event in enumerate(events, start=1)
    ])


def prune_impressions(now: datetime, user=None, days: int = IMPRESSION_RETENTION_DAYS) -> int:
    """Delete impressions shown more than `days` ago, for one user or (user=None) everyone. A dismissed row
    stays until its event has ended, because it is what keeps a "Not interested" event out of the row.
    Returns how many rows were deleted."""
    event_over = Q(event__end_at__lt=now) | Q(event__end_at__isnull=True, event__start_at__lt=now)
    old = RecommendationImpression.objects.filter(shown_at__lt=now - timedelta(days=days))
    if user is not None:
        old = old.filter(user=user)
    deleted, _ = old.filter(Q(dismissed=False) | event_over).delete()
    return deleted


def discard_replaced_impressions(user, now: datetime) -> None:
    """A quiet location refresh re-ranks the row a moment after the page loaded, so the set logged by
    that page load was barely on screen. Drop it rather than count both. Clicked and dismissed rows stay."""
    (RecommendationImpression.objects
     .filter(user=user, shown_at__gte=now - REPLACE_WINDOW, clicked=False, dismissed=False)
     .delete())


def mark_recommendation_clicked(user, event, now: datetime) -> None:
    """The user opened an event from their Recommended row: mark the latest showing of it as clicked."""
    impression = (RecommendationImpression.objects
                  .filter(user=user, event=event, shown_at__gte=now - timedelta(days=1))
                  .order_by('-shown_at').first())
    if impression and not impression.clicked:
        RecommendationImpression.objects.filter(pk=impression.pk).update(clicked=True)


def dismiss_recommendation(user, event, now: datetime, rank: int = 0) -> None:
    """"Not interested" on a Recommended card: mark the latest showing of that event as dismissed, now. If
    there is none (it was pruned, say), log one, so the event still stays out of the row."""
    latest = RecommendationImpression.objects.filter(user=user, event=event).order_by('-shown_at').first()
    if latest is None:
        RecommendationImpression.objects.create(user=user, event=event, rank=rank, score=0.0,
                                                algorithm_version=ALGORITHM_VERSION, dismissed=True, dismissed_at=now)
    elif not latest.dismissed:
        RecommendationImpression.objects.filter(pk=latest.pk).update(dismissed=True, dismissed_at=now)


def undo_dismissal(user, event) -> None:
    """Undo on the "Hidden" message: the event can be recommended again, and what the user did to it counts again."""
    (RecommendationImpression.objects.filter(user=user, event=event, dismissed=True)
     .update(dismissed=False, dismissed_at=None))


# Location (a signed cookie on the user's device, never in the database) ----------------------------------

def round_location(latitude: float, longitude: float) -> tuple[float, float]:
    """Snap to the ~500 m grid. The final round() only removes floating-point noise like 40.110000000000004."""
    def snap(value):
        return round(round(value / LOCATION_GRID_DEGREES) * LOCATION_GRID_DEGREES, 3)
    return snap(latitude), snap(longitude)


def remember_location(response, request, location: tuple[float, float], now: datetime) -> None:
    """Store the rounded location in a cookie the browser deletes after six hours. It is signed so it can't
    be edited, records who shared it so another account on the same browser ignores it, and is HttpOnly
    because no script needs to read it."""
    value = signing.dumps({'user': str(request.user.pk), 'lat': location[0], 'lng': location[1],
                           'at': now.timestamp()}, salt=LOCATION_COOKIE_SALT, compress=True)
    response.set_cookie(LOCATION_COOKIE, value, max_age=int(LOCATION_MAX_AGE.total_seconds()),
                        httponly=True, samesite='Lax', secure=request.is_secure())


def read_location(request, now: datetime) -> tuple[float, float] | None:
    """The signed-in user's shared location, or None when they haven't shared it in the last six hours."""
    raw = request.COOKIES.get(LOCATION_COOKIE)
    if not raw:
        return None
    try:
        stored = signing.loads(raw, salt=LOCATION_COOKIE_SALT)
        if stored['user'] != str(request.user.pk):
            return None
        if now.timestamp() - float(stored['at']) > LOCATION_MAX_AGE.total_seconds():
            return None
        return float(stored['lat']), float(stored['lng'])
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None
