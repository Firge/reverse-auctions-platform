from django.apps import AppConfig
from django.db.models.signals import post_migrate


def create_periodic_tasks(sender, **kwargs):
    from django_celery_beat.models import PeriodicTask, IntervalSchedule
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=10,
        period=IntervalSchedule.SECONDS,
    )
    PeriodicTask.objects.get_or_create(
        name='Автоматический старт аукционов',
        task='bidfall.tasks.start_published_auctions',
        defaults={
            'interval': interval,
            'enabled': True,
        }
    )
    PeriodicTask.objects.get_or_create(
        name='Автоматический старт аукционов',
        task='bidfall.tasks.start_published_auctions',
        defaults={
            'interval': interval,
            'enabled': True,
        }
    )
    PeriodicTask.objects.get_or_create(
        name='Автоматическое окончание аукционов',
        task='bidfall.tasks.finish_expired_auctions',
        defaults={
            'interval': interval,
            'enabled': True,
        }
    )
    PeriodicTask.objects.get_or_create(
        name='Изменение статуса ставок в обработке',
        task='bidfall.tasks.update_pending_bids',
        defaults={
            'interval': interval,
            'enabled': True,
        }
    )
    PeriodicTask.objects.get_or_create(
        name='Разморозка проигравших ставок',
        task='bidfall.tasks.process_pending_cancel_bids',
        defaults={
            'interval': interval,
            'enabled': True,
        }
    )


class BidfallAppConfig(AppConfig):
    name = 'bidfall'

    def ready(self):
        post_migrate.connect(create_periodic_tasks, sender=self)
