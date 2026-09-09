from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.core.models import Business
from apps.onboarding.tests.test_demo_seed import provision_business


class SeedDemoBusinessCommandTests(TestCase):
    def test_requires_existing_active_business(self):
        with self.assertRaisesMessage(CommandError, "No existe un Business"):
            call_command("seed_demo_business", business_slug="does-not-exist")
        self.assertEqual(Business.objects.count(), 0)

        onboarding = provision_business()
        onboarding.business.is_active = False
        onboarding.business.save()
        with self.assertRaisesMessage(CommandError, "está inactivo"):
            call_command("seed_demo_business", business_slug=onboarding.business.slug)

    def test_prints_first_and_second_run_summaries(self):
        onboarding = provision_business()
        first_output = StringIO()
        second_output = StringIO()

        call_command(
            "seed_demo_business",
            business_slug=onboarding.business.slug,
            stdout=first_output,
        )
        call_command(
            "seed_demo_business",
            business_slug=onboarding.business.slug,
            stdout=second_output,
        )

        self.assertIn("Demo cargada correctamente.", first_output.getvalue())
        self.assertIn(onboarding.store.name, first_output.getvalue())
        self.assertIn("creadas: 3", first_output.getvalue())
        self.assertIn("fichas creadas: 5", first_output.getvalue())
        self.assertIn("reutilizadas: 3", second_output.getvalue())
        self.assertIn("reutilizados: 6", second_output.getvalue())
        self.assertIn("stocks iniciales creados: 0", second_output.getvalue())
