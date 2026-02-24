import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def create_missing_profiles(apps, schema_editor):
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)
    Profile = apps.get_model("bidfall", "Profile")

    for user in User.objects.all().iterator():
        Profile.objects.get_or_create(user=user, defaults={"role": "supplier"})


class Migration(migrations.Migration):

    dependencies = [
        ("bidfall", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Profile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("buyer", "Закупщик"),
                            ("supplier", "Поставщик"),
                            ("admin", "Администратор"),
                        ],
                        default="supplier",
                        max_length=20,
                    ),
                ),
                ("company_name", models.CharField(blank=True, max_length=255)),
                ("inn", models.CharField(blank=True, max_length=12)),
                ("rating", models.DecimalField(decimal_places=2, default=0.0, max_digits=3)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.RunPython(create_missing_profiles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="auction",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("PUBLISHED", "Published"),
                    ("ACTIVE", "Active"),
                    ("FINISHED", "Finished"),
                    ("CLOSED", "Closed"),
                    ("CANCELED", "Canceled"),
                ],
                default="DRAFT",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="auctionitem",
            name="catalog_item",
            field=models.ForeignKey(
                db_constraint=False,
                on_delete=django.db.models.deletion.CASCADE,
                to="bidfall.catalogitem",
            ),
        ),
        migrations.AlterField(
            model_name="bid",
            name="comment",
            field=models.TextField(blank=True, default=""),
        ),
    ]
