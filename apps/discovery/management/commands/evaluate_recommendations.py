from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.discovery.evaluation import METHODS, run_evaluation

METHOD_LABELS = {'embedding': 'Embedding', 'interest_tags': 'Tags', 'soonest': 'Soonest'}
METRICS = [
    ('hit_rate', 'Hit rate', 'personas with at least one wanted event in their top 10'),
    ('recall', 'Recall@10', 'share of wanted events in the top 10'),
    ('precision_at4', 'Precision@4', 'share of the first 4 cards that is wanted (empty slots count as misses)'),
    ('mrr', 'MRR', '1 / position of the first wanted event'),
    ('empty_rate', 'Empty', 'personas shown nothing'),
    ('diversity', 'Categories', 'different categories in a top 10'),
    ('coverage', 'Coverage', 'share of test events recommended to anyone'),
    ('holdout_hit_rate', 'Hidden hit', "hidden RSVP'd or saved events that came back in the top 10"),
    ('holdout_mrr', 'Hidden MRR', '1 / position of the hidden event (0 if it never came back)'),
]


def _cell(value):
    return '—' if value is None else f'{value:.2f}'


class Command(BaseCommand):
    help = ('Score "Recommended for you" for made-up students (apps/discovery/eval_data/personas.json) against '
            'two simple baselines. Everything is rolled back; only the scores are saved, for the staff dashboard.')

    def add_arguments(self, parser):
        parser.add_argument('--offline', action='store_true',
                            help='Use only cached embeddings; fail instead of calling Cloudflare.')
        parser.add_argument('--no-save', action='store_true', help="Print the scores but don't save the run.")
        parser.add_argument('--note', default='', help='A short note saved with the run, e.g. "similarity 0.5".')
        parser.add_argument('--personas', action='store_true', help="Also list every persona's top 10.")

    def handle(self, *args, **options):
        try:
            report = run_evaluation(timezone.now(), offline=options['offline'])
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc
        out = self.stdout.write
        summary = report['summary']
        out(f"{report['persona_count']} personas over {report['event_count']} test events · "
            f"{report['algorithm_version']} · {report['cloudflare_calls']} Cloudflare calls (the rest were cached)\n")
        out(f"{'':12}" + ''.join(f'{METHOD_LABELS[method]:>11}' for method in METHODS))
        for key, label, meaning in METRICS:
            out(f'{label:12}' + ''.join(f'{_cell(summary[method][key]):>11}' for method in METHODS) + f'   {meaning}')

        misses = [row for row in report['per_persona'] if row['relevant'] and (row['embedding']['recall'] or 0) < 1]
        if misses:
            out('\nPersonas whose top 10 missed wanted events:')
            for row in sorted(misses, key=lambda row: row['embedding']['recall'] or 0):
                missing = [key for key in row['relevant'] if key not in row['embedding']['shown']]
                out(f"  {row['persona']}: missed {', '.join(missing)}")
        lost = [(row['persona'], item) for row in report['per_persona'] for item in row.get('holdouts', [])
                if item['embedding'] is None]
        if lost:
            out('\nHidden events the embedding ranking did not bring back:')
            for persona, item in lost:
                out(f"  {persona}: {item['event']} ({item['action']})")
        if options['personas']:
            out('\nEvery persona (wanted → embedding top 10):')
            for row in report['per_persona']:
                out(f"  {row['persona']}: {row['relevant']} → {row['embedding']['shown']}")
                for item in row.get('holdouts', []):
                    out(f"    without {item['action']} of {item['event']}: rank {item['embedding'] or '—'}")

        if not options['no_save']:
            from apps.discovery.models import RecommendationEvaluationRun

            run = RecommendationEvaluationRun.objects.create(
                algorithm_version=report['algorithm_version'], embedding_model=report['embedding_model'],
                persona_count=report['persona_count'], event_count=report['event_count'], summary=summary,
                per_persona=report['per_persona'], note=options['note'],
            )
            out(self.style.SUCCESS(f'\nSaved as run {run.pk}; the recommendations dashboard shows the latest run.'))
