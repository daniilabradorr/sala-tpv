from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalog", "0003_alter_product_options_and_more")]
    operations = [
        migrations.AddField(
            model_name="category",
            name="image",
            field=models.ImageField(blank=True, editable=False, upload_to=""),
        ),
        migrations.AddField(
            model_name="product",
            name="image",
            field=models.ImageField(blank=True, editable=False, upload_to=""),
        ),
    ]
