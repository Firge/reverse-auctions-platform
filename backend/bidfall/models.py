from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class Profile(models.Model):
    class Role(models.TextChoices):
        BUYER = "buyer", "Закупщик"
        SUPPLIER = "supplier", "Поставщик"
        ADMIN = "admin", "Администратор"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.SUPPLIER)
    company_name = models.CharField(max_length=255, blank=True)
    inn = models.CharField(max_length=12, blank=True)
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00)

    def __str__(self):
        return f"{self.user.username} ({self.role})"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        Profile.objects.create(user=instance)
    instance.profile.save()


class CatalogNode(models.Model):
    class Kind(models.TextChoices):
        SECTION = "section", "Секция"
        SUBSECTION = "subsection", "Подсекция"
        GROUP = "group", "Группа"
        SPEC = "spec", "Спецификация"

    id = models.BigAutoField(primary_key=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    name = models.CharField(max_length=255)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        db_column='parent_id'
    )

    class Meta:
        managed = False
        db_table = 'catalog_nodes'
        indexes = [
            models.Index(fields=['parent'], name='catalog_nodes_parent_idx'),
        ]


class CatalogSource(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.TextField(unique=True)

    class Meta:
        managed = False
        db_table = 'catalog_sources'


class CatalogItem(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.TextField()
    name = models.TextField()
    unit = models.TextField()
    price_release = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    price_estimate = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    node = models.ForeignKey(
        CatalogNode,
        on_delete=models.CASCADE,
        db_column='node_id',
        null=True,
        blank=True,
    )
    source = models.ForeignKey(
        CatalogSource,
        on_delete=models.CASCADE,
        db_column='source_id'
    )

    class Meta:
        managed = False
        db_table = 'catalog_items'


class Auction(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"
        ACTIVE = "ACTIVE"
        FINISHED = "FINISHED"
        CLOSED = "CLOSED"
        CANCELED = "CANCELED"
    id = models.AutoField(primary_key=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField()
    start_price = models.DecimalField(max_digits=10, decimal_places=2)
    current_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    winner_bid = models.ForeignKey(
        'Bid',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='won_auctions',
    )
    winner_determined_at = models.DateTimeField(null=True, blank=True)

    auction_type = models.ForeignKey(ContentType, on_delete=models.CASCADE,
                                     limit_choices_to={'app_label': 'bidfall'})
    object_id = models.PositiveIntegerField()
    specific_auction = GenericForeignKey('auction_type', 'object_id')

    catalog_items = models.ManyToManyField(
        CatalogItem,
        through='AuctionItem',
        related_name='auctions'
    )


class AuctionItem(models.Model):
    id = models.AutoField(primary_key=True)
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='items')
    # Catalog tables are managed by external loader, so keep app migrations independent.
    catalog_item = models.ForeignKey(CatalogItem, on_delete=models.CASCADE, db_constraint=False)
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=1.00,
    )

    class Meta:
        db_table = 'auction_items'
        unique_together = ('auction', 'catalog_item')


class Bid(models.Model):
    id = models.AutoField(primary_key=True)
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='bids')
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    bid = models.DecimalField(max_digits=12, decimal_places=2)
    comment = models.TextField(blank=True, default="")


class ReverseEnglishAuction(models.Model):
    id = models.AutoField(primary_key=True)
    min_bid_decrement = models.DecimalField(max_digits=12, decimal_places=2, default=1.00)
