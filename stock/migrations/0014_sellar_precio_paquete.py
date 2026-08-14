"""El monto del paquete se sella en el evento en vez de leerse del catálogo.

Es RN-15 (el costo congelado del movimiento) aplicado del lado del INGRESO. Leer
`paquete.precio` en vivo dejaba dos puertas abiertas, y las dos cambiaban la plata
de un evento ya cerrado sin avisar:

- editarle el precio al paquete desde su pantalla,
- borrar el paquete, que con `SET_NULL` bajaba la facturación del evento a $0.

Los eventos que ya tienen paquete se sellan con el precio de hoy. No es el precio
histórico real (ese nunca se guardó), pero es el que el sistema venía mostrando:
la migración no puede cambiarle los números a nadie.
"""

import django.core.validators
from django.db import migrations, models


def sellar_los_que_ya_tienen_paquete(apps, schema_editor):
    Evento = apps.get_model('stock', 'Evento')
    for evento in Evento.objects.filter(paquete__isnull=False).select_related('paquete'):
        Evento.objects.filter(pk=evento.pk).update(precio_paquete=evento.paquete.precio)


def desellar(apps, schema_editor):
    """Marcha atrás: el dato vuelve a salir del catálogo, así que se descarta."""
    apps.get_model('stock', 'Evento').objects.update(precio_paquete=None)


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0013_porciones_por_plato'),
    ]

    operations = [
        migrations.AddField(
            model_name='evento',
            name='precio_paquete',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Se completa solo al elegir el paquete. Cambialo si este evento se cerró por otro monto.', max_digits=12, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Monto del paquete'),
        ),
        migrations.RunPython(sellar_los_que_ya_tienen_paquete, desellar),
    ]
