from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("stores", "0002_alter_stores_options_stores_business_stores_code_and_more"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="Stores",
            new_name="Store",
        ),
        migrations.AlterField(
            model_name="store",
            name="business",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="stores",
                to="core.business",
            ),
        ),
        migrations.AlterField(
            model_name="store",
            name="code",
            field=models.CharField(
                "Código de tienda",
                max_length=20,
            ),
        ),
    ]