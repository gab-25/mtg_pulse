from django.contrib.postgres.operations import UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('prices', '0005_ranking_preferences'),
    ]

    operations = [
        UnaccentExtension(),
    ]
