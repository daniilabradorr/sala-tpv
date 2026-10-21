"""Read-only receipt growth metrics; intentionally no purge/TTL operation."""

import json
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Count, Min, Max
from apps.sales.models import CartOperation


class Command(BaseCommand):
    help = "Métricas agregadas de CartOperation. No borra ni modifica recibos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--exact", action="store_true", help="COUNT completo (puede ser costoso)."
        )

    def handle(self, *args, **options):
        result = {
            "vendor": connection.vendor,
            "retention": "sale_lifetime",
            "writes": False,
        }
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT n_live_tup, n_dead_tup, pg_total_relation_size(relid), "
                    "pg_indexes_size(relid) FROM pg_stat_user_tables WHERE relid = %s::regclass",
                    [CartOperation._meta.db_table],
                )
                row = cursor.fetchone()
            if row:
                result.update(
                    zip(
                        (
                            "estimated_receipts",
                            "estimated_dead_rows",
                            "total_bytes",
                            "index_bytes",
                        ),
                        row,
                    )
                )
        if options["exact"] or connection.vendor != "postgresql":
            metrics = CartOperation.objects.aggregate(
                count=Count("pk"), oldest=Min("created_at"), newest=Max("created_at")
            )
            result["exact"] = {
                key: str(value) if key != "count" and value else value
                for key, value in metrics.items()
            }
        self.stdout.write(json.dumps(result, sort_keys=True))
