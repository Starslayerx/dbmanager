from django.core.management.base import BaseCommand

from inventory.services.rotations import recover_stale_rotations


class Command(BaseCommand):
    help = '恢复卡在 rotating 状态的密码轮换'

    def add_arguments(self, parser):
        parser.add_argument(
            '--credential-id',
            type=int,
            help='只恢复指定凭据',
        )

    def handle(self, *args, **options):
        recovered = recover_stale_rotations(
            credential_id=options['credential_id'],
        )
        self.stdout.write(f'recovered={recovered}')
