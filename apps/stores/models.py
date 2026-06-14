from django.db import models


# Create your models here.
class Stores(models.Model):
    # demomento lo dejo asi para us relaciones lo cambiaré a un CharField
    name = models.CharField(max_length=100, unique=True)
    pass
