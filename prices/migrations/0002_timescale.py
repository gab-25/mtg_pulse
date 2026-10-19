from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('prices', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE EXTENSION IF NOT EXISTS timescaledb;
                SELECT create_hypertable('prices_pricesnapshot', by_range('date'), migrate_data => true);
                ALTER TABLE prices_pricesnapshot SET (
                    timescaledb.compress,
                    timescaledb.compress_segmentby = 'card_id',
                    timescaledb.compress_orderby = 'date'
                );
                SELECT add_compression_policy('prices_pricesnapshot', INTERVAL '30 days');
            """,
            reverse_sql="""
                SELECT remove_compression_policy('prices_pricesnapshot', if_exists => true);
            """,
        ),
    ]
