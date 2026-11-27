from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.search.evaluation import run_evaluation

METRICS = [
    ('precision', 'Precision', 'share of shown events that are relevant'),
    ('recall', 'Recall', 'share of relevant events that are shown'),
    ('f1', 'F1', 'balance of the two'),
    ('mrr', 'MRR', '1 / position of the first relevant event'),
    ('zero_result_rate', 'No results', 'answerable queries that showed nothing'),
    ('correctly_empty_rate', 'Correctly empty', 'no-answer queries that showed nothing'),
    ('mean_shown', 'Shown per query', 'average number of events shown'),
]


def _cell(value):
    return '—' if value is None else f'{value:.2f}'


class Command(BaseCommand):
    help = ('Score AI search and keyword search on labelled queries (apps/search/eval_data). The test events '
            'are rolled back; only the scores are saved, as a SearchEvaluationRun for the search dashboard.')

    def add_arguments(self, parser):
        parser.add_argument('--offline', action='store_true',
                            help="Use only cached embeddings; fail instead of calling Cloudflare.")
        parser.add_argument('--no-save', action='store_true', help="Print the scores but don't save the run.")
        parser.add_argument('--note', default='', help='A short note saved with the run, e.g. "cutoff 0.55".')
        parser.add_argument('--queries', action='store_true', help='Also list every query with what each search showed.')

    def handle(self, *args, **options):
        try:
            report = run_evaluation(timezone.now(), offline=options['offline'])
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc
        out = self.stdout.write
        summary = report['summary']
        out(f"{report['query_count']} labelled queries over {report['event_count']} test events · "
            f"{report['embedding_model']} · cutoff {report['min_similarity']:.2f} · "
            f"{report['cloudflare_calls']} Cloudflare calls (the rest were cached)\n")
        out(f"{'':18}{'AI':>8}{'Keyword':>10}")
        for key, label, meaning in METRICS:
            out(f"{label:18}{_cell(summary['ai'][key]):>8}{_cell(summary['keyword'][key]):>10}   {meaning}")

        best = max(report['cutoff_sweep'], key=lambda row: (row['f1'], -abs(row['cutoff'] - report['min_similarity'])))
        out(f"\nAI search at other cutoffs (best F1 at {best['cutoff']:.2f}):")
        out(f"{'cutoff':>8}{'precision':>11}{'recall':>8}{'F1':>7}{'no results':>12}")
        for row in report['cutoff_sweep'][::2]:
            mark = ' ← current' if abs(row['cutoff'] - report['min_similarity']) < 0.011 else ''
            out(f"{row['cutoff']:>8.2f}{_cell(row['precision']):>11}{_cell(row['recall']):>8}{_cell(row['f1']):>7}"
                f"{_cell(row['zero_result_rate']):>12}{mark}")

        misses = [row for row in report['per_query'] if row['relevant'] and (row['ai']['recall'] or 0) < 1]
        if misses:
            out('\nQueries where AI search missed relevant events:')
            for row in sorted(misses, key=lambda row: row['ai']['recall'] or 0)[:8]:
                missing = [key for key in row['relevant'] if key not in row['ai']['shown']]
                out(f"  {row['query']!r}: missed {', '.join(missing)}")
        if options['queries']:
            out('\nEvery query (relevant, ~acceptable → AI | keyword):')
            for row in report['per_query']:
                labels = row['relevant'] + [f'~{key}' for key in row.get('acceptable', [])]
                out(f"  {row['query']!r}: {labels or 'nothing'} → {row['ai']['shown']} | {row['keyword']['shown']}")

        if not options['no_save']:
            from apps.search.models import SearchEvaluationRun

            run = SearchEvaluationRun.objects.create(
                embedding_model=report['embedding_model'], min_similarity=report['min_similarity'],
                query_count=report['query_count'], event_count=report['event_count'], summary=summary,
                per_query=report['per_query'], cutoff_sweep=report['cutoff_sweep'], note=options['note'][:200],
            )
            out(self.style.SUCCESS(f'\nSaved evaluation run {run.pk}; the search dashboard shows the latest run.'))
