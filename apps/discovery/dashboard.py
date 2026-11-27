"""Numbers and chart data for the staff recommendations dashboard (/analytics/recommendations/).

Plain Python over the impression log, like the search dashboard: one row per "Recommended for you" card shown,
at most six months of them. Every number is about cards and rows of cards, never about who saw them.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from apps.search.dashboard import (
    BAR_HEIGHT, RANGES, SHORT_BAR_HEIGHT, SOURCES, _axis, _days, _nice_ceiling, _percent, percentile,
)

from .models import RecommendationEvaluationRun, RecommendationImpression
from .recommendations import ALGORITHM_VERSION, FALLBACK_ALGORITHM_VERSION, SCORE_WEIGHTS

PARTS = [  # Score parts, each 0 to 1 before weighting.
    ('similarity', 'Similar to their taste'),
    ('follows', 'Host they follow'),
    ('popularity', 'Popularity'),
    ('proximity', 'Distance'),
    ('urgency', 'Starts soon'),
]
REACTIONS = [  # Stacking order, bottom up, with the CSS class each one is drawn in.
    ('clicked', 'Clicked', 'ai'),
    ('dismissed', 'Not interested', 'fallback'),
    ('ignored', 'No action', 'keyword'),
]
REASON_LABELS = {
    'similar': '“Similar to …”',
    'interest': '“Because you like …”',
    'follows': '“From … which you follow”',
    'nearby': '“A short walk from you”',
    '': 'No reason shown',
}
ALGORITHM_LABELS = {ALGORITHM_VERSION: 'Embedding ranking', FALLBACK_ALGORITHM_VERSION: 'Interest-tag fill-in'}
LOAD_BUCKETS = [(0, 100), (100, 250), (250, 500), (500, 1000), (1000, None)]
SCORE_BARS = 10  # 0.0–0.1 … 0.9–1.0
POSITIONS = 10
TOP_EVENTS = 8


@dataclass
class Row:
    created_at: object  # When the card was shown; named like the search rows so the day helpers work on both.
    user_id: object
    event_id: object
    rank: int
    score: float
    algorithm: str
    clicked: bool
    dismissed: bool
    parts: dict
    reason: str
    load_ms: int | None

    @property
    def reaction(self):
        return 'clicked' if self.clicked else 'dismissed' if self.dismissed else 'ignored'


def _filtered(now, days, source):
    rows = RecommendationImpression.objects.all()
    if days:
        rows = rows.filter(shown_at__gte=now - timedelta(days=days))
    if source == 'real':
        rows = rows.filter(is_simulated=False)
    elif source == 'simulated':
        rows = rows.filter(is_simulated=True)
    return rows


def load_rows(now, days, source) -> list[Row]:
    fields = ['shown_at', 'user_id', 'event_id', 'rank', 'score', 'algorithm_version', 'clicked', 'dismissed',
              'reason', 'load_ms'] + [f'part_{name}' for name, _ in PARTS]
    rows = []
    for values in _filtered(now, days, source).order_by('shown_at').values_list(*fields):
        record = dict(zip(fields, values))
        rows.append(Row(
            created_at=record['shown_at'], user_id=record['user_id'], event_id=record['event_id'],
            rank=record['rank'], score=record['score'], algorithm=record['algorithm_version'],
            clicked=record['clicked'], dismissed=record['dismissed'], reason=record['reason'],
            load_ms=record['load_ms'], parts={name: record[f'part_{name}'] for name, _ in PARTS},
        ))
    return rows


def _rate(rows, test):
    return _percent(sum(test(row) for row in rows), len(rows))


def build_kpis(rows):
    loads = [row.load_ms for row in rows if row.rank == 1]
    p50, p95 = percentile(loads, .5), percentile(loads, .95)
    clicks, dismissals = sum(row.clicked for row in rows), sum(row.dismissed for row in rows)
    fallback = sum(row.algorithm == FALLBACK_ALGORITHM_VERSION for row in rows)
    return [
        {'label': 'Cards shown', 'value': f'{len(rows):,}',
         'note': f'in {sum(row.rank == 1 for row in rows):,} rows of recommendations' if rows else 'None yet'},
        {'label': 'Students reached', 'value': f'{len({row.user_id for row in rows}):,}',
         'note': 'saw at least one row'},
        {'label': 'Click-through', 'value': f'{_percent(clicks, len(rows)):g}%' if rows else '—',
         'note': f'{clicks} of {len(rows)} cards opened', 'tone': 'navy' if clicks else ''},
        {'label': 'Not interested', 'value': f'{_percent(dismissals, len(rows)):g}%' if rows else '—',
         'note': f'{dismissals} cards dismissed', 'tone': 'accent' if dismissals else ''},
        {'label': 'Time to rank a row', 'value': f'{p50:,} ms' if p50 is not None else '—',
         'note': f'median · p95 {p95:,} ms' if p95 is not None else 'median and p95'},
        {'label': 'Interest-tag fill-in', 'value': f'{_percent(fallback, len(rows)):g}%' if rows else '—',
         'note': 'cards not ranked by embedding'},
    ]


def build_daily(rows, day_list, tz):
    per_day = defaultdict(Counter)
    for row in rows:
        per_day[timezone.localtime(row.created_at, tz).date()][row.reaction] += 1
    top = _nice_ceiling(max((sum(counts.values()) for counts in per_day.values()), default=0))
    columns = []
    for day in day_list:
        counts = per_day.get(day, Counter())
        total = sum(counts.values())
        parts = [f'{label} {counts[key]}' for key, label, _ in REACTIONS if counts[key]]
        columns.append({
            'segments': [{'css': css, 'height': round(counts[key] / top * BAR_HEIGHT)}
                         for key, _, css in REACTIONS if counts[key]],
            'tip': f'{day:%a %b} {day.day} · {total} card{"s" if total != 1 else ""}'
                   + (f' ({", ".join(parts)})' if parts else ''),
        })
    return {'columns': columns, 'top': top, 'axis': _axis(day_list),
            'legend': [{'label': label, 'css': css} for _, label, css in REACTIONS]}


def build_positions(rows):
    """Click-through and "Not interested" rate for each place in the row."""
    by_rank = defaultdict(list)
    for row in rows:
        by_rank[row.rank].append(row)
    stats = []
    for rank in range(1, POSITIONS + 1):
        group = by_rank.get(rank, [])
        stats.append({'rank': rank, 'count': len(group), 'ctr': _rate(group, lambda row: row.clicked),
                      'dismissed': _rate(group, lambda row: row.dismissed)})
    top = max((stat['ctr'] or 0 for stat in stats), default=0)
    for stat in stats:
        stat['height'] = round((stat['ctr'] or 0) / top * SHORT_BAR_HEIGHT) if top else 0
        stat['tip'] = (f'Card {stat["rank"]} · {stat["ctr"]:g}% clicked, {stat["dismissed"]:g}% not interested '
                       f'({stat["count"]} shown)' if stat['count'] else f'Card {stat["rank"]} · not shown')
    first, rest = by_rank.get(1, []), [row for row in rows if row.rank > 1]
    return {'bars': stats, 'first_ctr': _rate(first, lambda row: row.clicked),
            'rest_ctr': _rate(rest, lambda row: row.clicked)}


def build_signals(rows):
    """For each score part: its average on cards that were clicked against cards that weren't. A part that is
    clearly higher on clicked cards is one that tracks what students open."""
    scored = [row for row in rows if row.algorithm == ALGORITHM_VERSION]
    table = []
    for name, label in PARTS:
        clicked = [row.parts[name] for row in scored if row.clicked and row.parts[name] is not None]
        other = [row.parts[name] for row in scored if not row.clicked and row.parts[name] is not None]
        mean_clicked = round(sum(clicked) / len(clicked), 3) if clicked else None
        mean_other = round(sum(other) / len(other), 3) if other else None
        gap = round(mean_clicked - mean_other, 3) if mean_clicked is not None and mean_other is not None else None
        table.append({'label': label, 'weight': round(SCORE_WEIGHTS[name] * 100), 'clicked': mean_clicked,
                      'other': mean_other, 'gap': gap, 'count': len(clicked) + len(other),
                      'strong': gap is not None and gap >= 0.05})
    return {'table': table, 'count': len(scored), 'clicks': sum(row.clicked for row in scored)}


def build_score_buckets(rows):
    """Click-through by total score, for embedding-ranked cards. Rising bars mean the score predicts clicks."""
    scored = [row for row in rows if row.algorithm == ALGORITHM_VERSION]
    groups = defaultdict(list)
    for row in scored:
        groups[min(SCORE_BARS - 1, max(0, int(row.score * SCORE_BARS)))].append(row)
    rates = {index: _rate(group, lambda row: row.clicked) for index, group in groups.items()}
    top = max(rates.values(), default=0) or 0
    bars = []
    for index in range(SCORE_BARS):
        group, rate = groups.get(index, []), rates.get(index)
        low = index / SCORE_BARS
        bars.append({'height': round((rate or 0) / top * BAR_HEIGHT) if top else 0,
                     'tip': f'Score {low:.1f}–{low + 1 / SCORE_BARS:.1f} · '
                            + (f'{rate:g}% of {len(group)} cards clicked' if group else 'no cards')})
    return {'bars': bars, 'count': len(scored)}


def build_reasons(rows):
    reasons = []
    for key, label in REASON_LABELS.items():
        group = [row for row in rows if row.reason == key]
        if group:
            reasons.append({'label': label, 'count': len(group), 'ctr': _rate(group, lambda row: row.clicked) or 0,
                            'dismissed': _rate(group, lambda row: row.dismissed) or 0})
    algorithms = []
    for key, group in sorted(_group(rows, lambda row: row.algorithm).items()):
        algorithms.append({'label': ALGORITHM_LABELS.get(key, key), 'count': len(group),
                           'ctr': _rate(group, lambda row: row.clicked), 'dismissed': _rate(group, lambda row: row.dismissed)})
    return {'reasons': reasons, 'algorithms': algorithms}


def _group(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return groups


def build_load(rows):
    loads = [row.load_ms for row in rows if row.rank == 1 and row.load_ms is not None]
    counts = Counter()
    for value in loads:
        counts[next(index for index, (low, high) in enumerate(LOAD_BUCKETS) if high is None or value < high)] += 1
    top = max(counts.values(), default=0)
    p50, p95 = percentile(loads, .5), percentile(loads, .95)
    histogram = []
    for index, (low, high) in enumerate(LOAD_BUCKETS):
        marks = [name for name, value in (('p50', p50), ('p95', p95))
                 if value is not None and value >= low and (high is None or value < high)]
        histogram.append({'label': f'{low:,}–{high:,} ms' if high else f'{low:,}+ ms', 'count': counts[index],
                          'marks': marks, 'width': round(counts[index] / top * 100) if top else 0,
                          'share': _percent(counts[index], len(loads)) or 0})
    return {'histogram': histogram, 'count': len(loads), 'p50': p50, 'p95': p95}


def build_events(rows):
    """Most-shown events, and the categories most often marked "Not interested"."""
    from apps.events.models import Event

    by_event = _group(rows, lambda row: row.event_id)
    top_ids = sorted(by_event, key=lambda pk: (-len(by_event[pk]), str(pk)))[:TOP_EVENTS]
    titles = dict(Event.objects.filter(pk__in=top_ids).values_list('pk', 'title'))
    top = [{'title': titles.get(pk, 'Deleted event'), 'count': len(by_event[pk]),
            'ctr': _rate(by_event[pk], lambda row: row.clicked), 'dismissed': sum(row.dismissed for row in by_event[pk])}
           for pk in top_ids]

    categories = defaultdict(set)
    for pk, name in (Event.interests.through.objects.filter(event_id__in=by_event)
                     .values_list('event_id', 'interest__name')):
        categories[pk].add(name)
    shown, dismissed = Counter(), Counter()
    for row in rows:
        for name in categories.get(row.event_id, ()):
            shown[name] += 1
            dismissed[name] += row.dismissed
    disliked = [{'name': name, 'dismissed': count, 'shown': shown[name], 'rate': _percent(count, shown[name])}
                for name, count in dismissed.most_common() if count][:TOP_EVENTS]
    return {'top': top, 'disliked': disliked, 'distinct': len(by_event)}


EVAL_METHODS = [('embedding', 'Embedding'), ('interest_tags', 'Interest tags'), ('soonest', 'Soonest first')]
EVAL_METRICS = [('hit_rate', 'Hit rate'), ('recall', 'Recall@10'), ('precision_at4', 'Precision@4'), ('mrr', 'MRR'),
                ('empty_rate', 'Shown nothing'), ('diversity', 'Categories per row'), ('coverage', 'Coverage'),
                ('holdout_hit_rate', 'Hidden event found'), ('holdout_mrr', 'Hidden event MRR')]


def build_evaluation(run: RecommendationEvaluationRun | None):
    if run is None:
        return None
    rows = []
    for key, label in EVAL_METRICS:
        values = [run.summary.get(method, {}).get(key) for method, _ in EVAL_METHODS]
        known = [value for value in values if value is not None]
        best = None
        if len(set(known)) > 1 and key not in ('diversity', 'coverage'):  # More of those isn't always better.
            best = (min if key == 'empty_rate' else max)(known)
        rows.append({'label': label, 'cells': [{'value': value, 'best': value is not None and value == best}
                                               for value in values]})
    misses = [row for row in run.per_persona if row['relevant'] and (row['embedding']['recall'] or 0) < 1]
    return {
        'run': run, 'methods': [label for _, label in EVAL_METHODS], 'rows': rows,
        'misses': [{'persona': row['persona'], 'about': row['about'], 'recall': row['embedding']['recall'],
                    'missing': [key for key in row['relevant'] if key not in row['embedding']['shown']]}
                   for row in sorted(misses, key=lambda row: row['embedding']['recall'] or 0)[:6]],
        'lost': [{'persona': row['persona'], 'event': item['event'], 'action': item['action']}
                 for row in run.per_persona for item in row.get('holdouts', []) if item['embedding'] is None],
    }


def get_recommendation_dashboard(now, tz, range_key='30', source='real') -> dict:
    range_key = range_key if range_key in RANGES else '30'
    source = source if source in SOURCES else 'real'
    days = RANGES[range_key][1]
    rows = load_rows(now, days, source)
    return {
        'range_key': range_key, 'source': source, 'ranges': RANGES, 'sources': SOURCES,
        'rows_count': len(rows),
        'simulated_count': RecommendationImpression.objects.filter(is_simulated=True).count(),
        'kpis': build_kpis(rows),
        'daily': build_daily(rows, _days(rows, now, days, tz), tz),
        'positions': build_positions(rows),
        'signals': build_signals(rows),
        'score_buckets': build_score_buckets(rows),
        'reasons': build_reasons(rows),
        'load': build_load(rows),
        'events': build_events(rows),
        'evaluation': build_evaluation(RecommendationEvaluationRun.objects.first()),
    }
