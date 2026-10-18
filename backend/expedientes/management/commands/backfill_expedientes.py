"""Creates the automatic draft of every (scene, watching ONG) pair that has none. Dry run without --yes."""
from collections import Counter

from django.core.management.base import BaseCommand

from expedientes.autodraft import create_drafts, missing_pairs


class Command(BaseCommand):
    help = 'Lists the (scene, ONG) pairs without an expediente; with --yes creates their prefilled drafts.'

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='Create the drafts (otherwise only count them).')

    def handle(self, *args, yes=False, **options):
        pairs = missing_pairs()
        by_ong = Counter(ong.display_name for _, ong in pairs)
        self.stdout.write(f'{len(pairs)} pairs without an expediente')
        for name, n in by_ong.most_common():
            self.stdout.write(f'  {name}: {n}')
        if not yes or not pairs:
            return
        created = 0
        for image in dict.fromkeys(image for image, _ in pairs):
            created += len(create_drafts(image))
        self.stdout.write(self.style.SUCCESS(f'{created} drafts created'))
