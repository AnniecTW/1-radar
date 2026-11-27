"""Numbers and chart data for the staff search dashboard (/analytics/search/).

Plain Python over the search log rows: the table holds at most 180 days of searches, so one query and
some counting is enough. Days are campus days, so an evening search counts on the day it happened.
"""
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from .models import SearchEvaluationRun, SearchQueryLog
from .services import search_outcome

RANGES = {'7': ('Last 7 days', 7), '30': ('Last 30 days', 30), 'all': ('All time', None)}
SOURCES = {'real': 'Real searches', 'simulated': 'Simulated', 'all': 'Real and simulated'}
OUTCOMES = [  # Stacking order, bottom up, with the CSS class each one is drawn in.
    (SearchQueryLog.Outcome.AI_RANKED, 'AI ranked', 'ai'),
    (SearchQueryLog.Outcome.AI_NO_MATCH, 'AI: no close match', 'nomatch'),
    (SearchQueryLog.Outcome.FALLBACK, 'Fell back to keywords', 'fallback'),
    (SearchQueryLog.Outcome.KEYWORD, 'Keyword search', 'keyword'),
]
LATENCY_BUCKETS = [(0, 250), (250, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, None)]
SIMILARITY_START, SIMILARITY_STEP, SIMILARITY_BARS = 0.30, 0.05, 13  # 0.30 to 0.95
WORD_BUCKETS = [(1, '1 word'), (2, '2 words'), (3, '3 words'), (4, '4–5 words'), (6, '6+ words')]
BAR_HEIGHT = 150
SHORT_BAR_HEIGHT = 100  # The click-position chart (.bars.short is 110px tall).
TOP_QUERIES = 10


@dataclass
class Row:
    created_at: object
    query: str
    outcome: str
    ai: bool
    category: str
    shown: list
    result_count: int
    latency_ms: int | None
    embedding_ms: int | None
    error_code: str
    top_similarity: float | None
    clicked_id: str | None

    @property
    def clicked_position(self):
        if not self.clicked_id:
            return None
        return next((position for position, (event_id, _) in enumerate(self.shown, 1)
                     if event_id == self.clicked_id), None)


def percentile(values, share):
    """Nearest-rank percentile, so the answer is always one of the measured times."""
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    return values[max(0, math.ceil(share * len(values)) - 1)]


def _percent(part, whole):
    return round(part * 100 / whole, 1) if whole else None


def _nice_ceiling(value):
    if value <= 4:
        return 4
    step = 10 ** math.floor(math.log10(value))
    return next(int(multiple * step) for multiple in (1, 2, 2.5, 5, 10) if value <= multiple * step)


def load_rows(now, days, source) -> list[Row]:
    logs = SearchQueryLog.objects.all()
    if days:
        logs = logs.filter(created_at__gte=now - timedelta(days=days))
    if source == 'real':
        logs = logs.filter(is_simulated=False)
    elif source == 'simulated':
        logs = logs.filter(is_simulated=True)
    rows = []
    for values in logs.order_by('created_at').values_list(
            'created_at', 'raw_query', 'outcome', 'parsed_filters', 'result_count', 'latency_ms', 'embedding_ms',
            'error_code', 'top_similarity', 'clicked_event_id'):
        created_at, query, outcome, filters, result_count, latency, embedding, error, top, clicked = values
        filters = filters or {}
        ai = filters.get('mode') == 'ai'
        rows.append(Row(
            created_at=created_at, query=query,
            # Rows logged before outcomes were saved: work it out from the mode and fallback flag.
            outcome=outcome or search_outcome(ai, bool(filters.get('fallback')), result_count),
            ai=ai, category=filters.get('category') or '', shown=filters.get('results') or [],
            result_count=result_count, latency_ms=latency, embedding_ms=embedding, error_code=error,
            top_similarity=top, clicked_id=str(clicked) if clicked else None,
        ))
    return rows


def build_kpis(rows):
    ai_rows = [row for row in rows if row.ai]
    with_results = [row for row in rows if row.result_count]
    fallbacks = sum(row.outcome == SearchQueryLog.Outcome.FALLBACK for row in ai_rows)
    p50, p95 = percentile([row.latency_ms for row in ai_rows], .5), percentile([row.latency_ms for row in ai_rows], .95)
    return [
        {'label': 'Searches', 'value': f'{len(rows):,}',
         'note': f'{_percent(len(ai_rows), len(rows)) or 0:g}% used AI search' if rows else 'None yet'},
        {'label': 'AI search time', 'value': f'{p50:,} ms' if p50 is not None else '—',
         'note': f'median · p95 {p95:,} ms' if p95 is not None else 'median and p95'},
        {'label': 'Fell back to keywords', 'value': f'{_percent(fallbacks, len(ai_rows)):g}%' if ai_rows else '—',
         'note': f'{fallbacks} of {len(ai_rows)} AI searches', 'tone': 'accent' if fallbacks else ''},
        {'label': 'No results', 'value': f'{_percent(len(rows) - len(with_results), len(rows)):g}%' if rows else '—',
         'note': f'{len(rows) - len(with_results)} searches showed nothing'},
        {'label': 'Click-through', 'value': f'{_percent(sum(bool(row.clicked_id) for row in with_results), len(with_results)):g}%'
         if with_results else '—', 'note': 'searches with results where one was opened'},
    ]


def _days(rows, now, days, tz):
    end = timezone.localtime(now, tz).date()
    if days:
        start = end - timedelta(days=days - 1)
    else:
        start = timezone.localtime(rows[0].created_at, tz).date() if rows else end
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _axis(day_list):
    if not day_list:
        return []
    picks = [day_list[0], day_list[len(day_list) // 2], day_list[-1]]
    return [f'{day:%b} {day.day}' for day in dict.fromkeys(picks)]


def build_daily_outcomes(rows, day_list, tz):
    per_day = defaultdict(Counter)
    for row in rows:
        per_day[timezone.localtime(row.created_at, tz).date()][row.outcome] += 1
    top = _nice_ceiling(max((sum(counts.values()) for counts in per_day.values()), default=0))
    columns = []
    for day in day_list:
        counts = per_day.get(day, Counter())
        total = sum(counts.values())
        parts = [f'{label} {counts[value]}' for value, label, _ in OUTCOMES if counts[value]]
        columns.append({
            'segments': [{'css': css, 'height': round(counts[value] / top * BAR_HEIGHT)}
                         for value, _, css in OUTCOMES if counts[value]],
            'tip': f'{day:%a %b} {day.day} · {total} search{"es" if total != 1 else ""}'
                   + (f' ({", ".join(parts)})' if parts else ''),
        })
    return {'columns': columns, 'top': top, 'axis': _axis(day_list),
            'legend': [{'label': label, 'css': css} for _, label, css in OUTCOMES]}


def build_cloudflare_calls(rows, day_list, tz):
    """Each AI search embeds its text once (twice when the first try fails, which isn't counted here)."""
    per_day = Counter(timezone.localtime(row.created_at, tz).date() for row in rows if row.ai)
    top = _nice_ceiling(max(per_day.values(), default=0))
    total = sum(per_day.values())
    return {
        'bars': [{'height': round(per_day.get(day, 0) / top * BAR_HEIGHT),
                  'tip': f'{day:%a %b} {day.day} · {per_day.get(day, 0)} call{"s" if per_day.get(day, 0) != 1 else ""}'}
                 for day in day_list],
        'top': top, 'axis': _axis(day_list), 'total': total,
        'per_day': round(total / len(day_list), 1) if day_list else 0, 'busiest': max(per_day.values(), default=0),
    }


def build_latency(rows):
    def stats(label, subset, key=lambda row: row.latency_ms, part=False):
        values = [key(row) for row in subset]
        return {'label': label, 'part': part, 'count': sum(value is not None for value in values),
                'p50': percentile(values, .5), 'p95': percentile(values, .95)}

    ai_rows = [row for row in rows if row.ai]
    ranked = [row for row in ai_rows if row.outcome != SearchQueryLog.Outcome.FALLBACK]
    table = [
        stats('AI search, whole search', ai_rows),
        stats('Cloudflare embedding call', ranked, lambda row: row.embedding_ms, part=True),
        stats('Ranking in the database', ranked, lambda row: None if row.latency_ms is None or row.embedding_ms is None
              else max(0, row.latency_ms - row.embedding_ms), part=True),
        stats('AI search that fell back', [row for row in ai_rows if row.outcome == SearchQueryLog.Outcome.FALLBACK]),
        stats('Keyword search', [row for row in rows if not row.ai]),
    ]
    counts = Counter()
    for row in ai_rows:
        if row.latency_ms is None:
            continue
        for index, (low, high) in enumerate(LATENCY_BUCKETS):
            if high is None or row.latency_ms < high:
                counts[index] += 1
                break
    top = max(counts.values(), default=0)
    p50, p95 = percentile([row.latency_ms for row in ai_rows], .5), percentile([row.latency_ms for row in ai_rows], .95)
    histogram = []
    for index, (low, high) in enumerate(LATENCY_BUCKETS):
        label = f'{low:,}–{high:,} ms' if high else f'{low:,}+ ms'
        marks = [name for name, value in (('p50', p50), ('p95', p95))
                 if value is not None and value >= low and (high is None or value < high)]
        histogram.append({'label': label, 'count': counts[index], 'marks': marks,
                          'width': round(counts[index] / top * 100) if top else 0,
                          'share': _percent(counts[index], sum(counts.values())) or 0})
    return {'table': table, 'histogram': histogram}


def build_errors(rows):
    ai_count = sum(row.ai for row in rows)
    by_code = defaultdict(list)
    for row in rows:
        if row.error_code:
            by_code[row.error_code].append(row.created_at)
    return [{'code': code, 'count': len(times), 'share': _percent(len(times), ai_count), 'last': max(times)}
            for code, times in sorted(by_code.items(), key=lambda item: -len(item[1]))]


def build_queries(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.query.casefold().strip()].append(row)

    def summary(text, group):
        with_results = [row for row in group if row.result_count]
        return {'query': group[-1].query, 'count': len(group),
                'ai_share': round(_percent(sum(row.ai for row in group), len(group))),
                'mean_results': round(sum(row.result_count for row in group) / len(group), 1),
                'clicks': sum(bool(row.clicked_id) for row in with_results)}

    top = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))[:TOP_QUERIES]
    empty = [(text, [row for row in group if not row.result_count]) for text, group in grouped.items()]
    empty = sorted([item for item in empty if item[1]], key=lambda item: (-len(item[1]), item[0]))[:TOP_QUERIES]
    categories = Counter(row.category for row in rows if row.category)
    return {
        'top': [summary(text, group) for text, group in top],
        'empty': [{'query': group[-1].query, 'count': len(group),
                   'modes': ' and '.join(sorted({'AI' if row.ai else 'keyword' for row in group}))}
                  for text, group in empty],
        'categories': [{'slug': slug, 'count': count, 'percent': round(_percent(count, len(rows)))}
                       for slug, count in categories.most_common(6)],
        'category_share': _percent(sum(categories.values()), len(rows)) or 0,
    }


def build_query_length(rows):
    def bucket(row):
        words = len(row.query.split())
        return next(start for start, _ in reversed(WORD_BUCKETS) if words >= start)

    grouped = defaultdict(list)
    for row in rows:
        grouped[bucket(row)].append(row)
    table = []
    for start, label in WORD_BUCKETS:
        group = grouped.get(start, [])
        ai = [row.result_count for row in group if row.ai]
        keyword = [row.result_count for row in group if not row.ai]
        table.append({
            'label': label, 'count': len(group),
            'ai_results': round(sum(ai) / len(ai), 1) if ai else None,
            'keyword_results': round(sum(keyword) / len(keyword), 1) if keyword else None,
            'empty': _percent(sum(not row.result_count for row in group), len(group)),
        })
    return table


def build_clicks(rows):
    with_results = [row for row in rows if row.result_count]
    by_outcome = []
    for value, label, css in OUTCOMES:
        group = [row for row in with_results if row.outcome == value]
        if group:
            clicked = sum(bool(row.clicked_id) for row in group)
            by_outcome.append({'label': label, 'css': css, 'count': len(group), 'clicked': clicked,
                               'percent': _percent(clicked, len(group)) or 0})
    positions = Counter(row.clicked_position for row in with_results if row.clicked_position)
    top = max(positions.values(), default=0)
    total = sum(positions.values())
    return {
        'by_outcome': by_outcome,
        'positions': [{'position': position, 'count': positions[position],
                       'height': round(positions[position] / top * SHORT_BAR_HEIGHT) if top else 0,
                       'tip': f'Result {position} · {positions[position]} click{"s" if positions[position] != 1 else ""}'}
                      for position in range(1, 13)],
        'first_share': _percent(positions[1], total),
        'total': total,
    }


def build_similarity(rows, cutoff):
    """How close the best match was, for AI searches that reached the ranking step."""
    values = [row.top_similarity for row in rows if row.ai and row.top_similarity is not None]
    counts = Counter(min(SIMILARITY_BARS - 1, max(0, int((value - SIMILARITY_START) // SIMILARITY_STEP)))
                     for value in values)
    top = max(counts.values(), default=0)
    bars = []
    for index in range(SIMILARITY_BARS):
        low = round(SIMILARITY_START + index * SIMILARITY_STEP, 2)
        high = round(low + SIMILARITY_STEP, 2)
        bars.append({'height': round(counts[index] / top * BAR_HEIGHT) if top else 0,
                     'below': high <= cutoff, 'tip': f'{low:.2f}–{high:.2f} · {counts[index]} search'
                     f'{"es" if counts[index] != 1 else ""}'})
    return {'bars': bars, 'count': len(values), 'cutoff': cutoff,
            'below': _percent(sum(value < cutoff for value in values), len(values)),
            'cutoff_left': round((cutoff - SIMILARITY_START) / (SIMILARITY_STEP * SIMILARITY_BARS) * 100, 1),
            'axis': [f'{SIMILARITY_START:.2f}', f'{SIMILARITY_START + SIMILARITY_STEP * SIMILARITY_BARS / 2:.2f}',
                     f'{SIMILARITY_START + SIMILARITY_STEP * SIMILARITY_BARS:.2f}']}


EVAL_METRICS = [('precision', 'Precision'), ('recall', 'Recall'), ('f1', 'F1'), ('mrr', 'MRR'),
                ('zero_result_rate', 'No results'), ('correctly_empty_rate', 'Correctly empty')]
SWEEP_LEFT, SWEEP_RIGHT, SWEEP_TOP, SWEEP_BOTTOM = 44, 590, 16, 186


def _score(value):
    return '—' if value is None else f'{value:.2f}'


def build_evaluation(run: SearchEvaluationRun | None):
    if run is None:
        return None
    rows = []
    for key, label in EVAL_METRICS:
        ai, keyword = run.summary['ai'].get(key), run.summary['keyword'].get(key)
        better = None
        if ai is not None and keyword is not None and ai != keyword:
            lower_is_better = key == 'zero_result_rate'
            better = 'ai' if (ai < keyword) == lower_is_better else 'keyword'
        rows.append({'label': label, 'ai': ai, 'keyword': keyword, 'better': better})

    sweep = run.cutoff_sweep
    low, high = sweep[0]['cutoff'], sweep[-1]['cutoff']

    def x(cutoff):
        return SWEEP_LEFT + (cutoff - low) / (high - low) * (SWEEP_RIGHT - SWEEP_LEFT)

    def y(value):
        return SWEEP_BOTTOM - (value or 0) * (SWEEP_BOTTOM - SWEEP_TOP)

    def segments(key):
        """Polyline point lists, broken where the value is undefined (e.g. precision when nothing was shown)."""
        runs, current = [], []
        for row in sweep:
            if row[key] is None:
                runs, current = runs + [current] if current else runs, []
            else:
                current.append(f'{x(row["cutoff"]):.1f},{y(row[key]):.1f}')
        return [' '.join(points) for points in runs + [current] if points]

    lines = {key: segments(key) for key in ('precision', 'recall', 'f1')}
    best = max(sweep, key=lambda row: (row['f1'], -abs(row['cutoff'] - run.min_similarity)))
    misses = [row for row in run.per_query if row['relevant'] and (row['ai']['recall'] or 0) < 1]
    return {
        'run': run, 'rows': rows, 'lines': lines, 'best': best,
        'current_x': f'{x(min(max(run.min_similarity, low), high)):.1f}', 'best_x': f'{x(best["cutoff"]):.1f}',
        'points': [{'x': f'{x(row["cutoff"]):.1f}', 'band_x': f'{x(row["cutoff"]) - 13:.1f}',
                    'tip': f'Cutoff {row["cutoff"]:.2f} · precision {_score(row["precision"])}, recall '
                           f'{_score(row["recall"])}, F1 {_score(row["f1"])}'} for row in sweep],
        'axis': [f'{low:.2f}', f'{(low + high) / 2:.2f}', f'{high:.2f}'],
        'misses': [{'query': row['query'], 'missing': [key for key in row['relevant'] if key not in row['ai']['shown']],
                    'recall': row['ai']['recall']} for row in sorted(misses, key=lambda row: row['ai']['recall'] or 0)[:6]],
    }


def get_search_dashboard(now, tz, range_key='30', source='real') -> dict:
    from apps.discovery.selectors import semantic_min_similarity

    range_key = range_key if range_key in RANGES else '30'
    source = source if source in SOURCES else 'real'
    days = RANGES[range_key][1]
    rows = load_rows(now, days, source)
    day_list = _days(rows, now, days, tz)
    cutoff = semantic_min_similarity()
    return {
        'range_key': range_key, 'source': source, 'ranges': RANGES, 'sources': SOURCES,
        'rows_count': len(rows),
        'simulated_count': SearchQueryLog.objects.filter(is_simulated=True).count(),
        'kpis': build_kpis(rows),
        'daily': build_daily_outcomes(rows, day_list, tz),
        'calls': build_cloudflare_calls(rows, day_list, tz),
        'latency': build_latency(rows),
        'errors': build_errors(rows),
        'queries': build_queries(rows),
        'query_length': build_query_length(rows),
        'clicks': build_clicks(rows),
        'similarity': build_similarity(rows, cutoff),
        'evaluation': build_evaluation(SearchEvaluationRun.objects.first()),
    }
