from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Business
from apps.onboarding.demo_seed import DemoBusinessSeeder, DemoSeedError


class Command(BaseCommand):
    help = "Carga datos demo idempotentes en un Business ya provisionado."

    def add_arguments(self, parser):
        parser.add_argument("--business-slug", required=True)

    def handle(self, *args, **options):
        slug = options["business_slug"]
        try:
            business = Business.objects.get(slug=slug)
        except Business.DoesNotExist as exc:
            raise CommandError(f"No existe un Business con slug '{slug}'.") from exc
        if not business.is_active:
            raise CommandError(f"El Business '{slug}' está inactivo.")
        try:
            result = DemoBusinessSeeder.seed(business=business)
        except DemoSeedError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "\n".join(
                    (
                        "Demo cargada correctamente.",
                        "",
                        "Business:",
                        f"  {result.business.name}",
                        f"  {result.business.slug}",
                        "",
                        "Store:",
                        f"  {result.store.name}",
                        f"  {result.store.code}",
                        "",
                        "Categorías:",
                        f"  creadas: {result.category_counts.created}",
                        f"  reutilizadas: {result.category_counts.reused}",
                        "",
                        "Productos:",
                        f"  creados: {result.product_counts.created}",
                        f"  reutilizados: {result.product_counts.reused}",
                        "",
                        "Inventario:",
                        f"  fichas creadas: {result.inventory_counts.created}",
                        f"  reutilizadas: {result.inventory_counts.reused}",
                        f"  stocks iniciales creados: {result.initial_stocks_created}",
                        "",
                        "Clientes:",
                        f"  creados: {result.customer_counts.created}",
                        f"  reutilizados: {result.customer_counts.reused}",
                    )
                )
            )
        )
