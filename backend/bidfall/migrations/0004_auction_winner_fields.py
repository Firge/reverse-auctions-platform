from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("bidfall", "0003_alter_profile_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="auction",
            name="winner_bid",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="won_auctions",
                to="bidfall.bid",
            ),
        ),
        migrations.AddField(
            model_name="auction",
            name="winner_determined_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
