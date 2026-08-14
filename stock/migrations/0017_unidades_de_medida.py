"""La unidad de medida pasa de texto libre a catalogo administrable (RN-26).

Django resolveria el cambio de CharField a FK con un AlterField que se lleva
puestos los datos. Por eso va a mano: se renombra la columna vieja, se crea la
nueva, se mapea, y recien ahi se borra la vieja.
"""

from django.db import migrations, models
import django.db.models.deletion


# Las cuatro que pidio el dueno. De aca en adelante las administra el desde
# /unidades/, igual que los puestos (RN-21).
SEMILLA = ['Cajas', 'Kilogramos', 'Litros', 'Unidad']

# Los datos venian de un campo de texto libre, asi que hay de todo. La clave va
# en minuscula y sin espacios: 'Litros', 'litros' y 'LITROS' son la misma unidad.
ALIAS = {
    'unidad': 'Unidad', 'unidades': 'Unidad', 'u': 'Unidad', 'un': 'Unidad',
    'kg': 'Kilogramos', 'kilo': 'Kilogramos', 'kilos': 'Kilogramos',
    'kilogramo': 'Kilogramos', 'kilogramos': 'Kilogramos',
    'l': 'Litros', 'lt': 'Litros', 'litro': 'Litros', 'litros': 'Litros',
    'caja': 'Cajas', 'cajas': 'Cajas',
}


def sembrar_y_mapear(apps, schema_editor):
    UnidadMedida = apps.get_model('stock', 'UnidadMedida')
    Producto = apps.get_model('stock', 'Producto')

    for nombre in SEMILLA:
        UnidadMedida.objects.get_or_create(nombre=nombre)

    for producto in Producto.objects.all():
        texto = (producto.unidad_medida_texto or '').strip()
        if not texto:
            producto.unidad_medida = UnidadMedida.objects.get(nombre='Unidad')
            producto.save(update_fields=['unidad_medida'])
            continue

        # Lo que no esta en la tabla de alias se crea tal cual: perder un dato
        # cargado por no reconocerlo seria peor que una unidad de mas. Mismo
        # criterio que la 0010 con los puestos.
        nombre = ALIAS.get(texto.lower(), texto)
        producto.unidad_medida = UnidadMedida.objects.get_or_create(nombre=nombre)[0]
        producto.save(update_fields=['unidad_medida'])


def volver_a_texto(apps, schema_editor):
    Producto = apps.get_model('stock', 'Producto')
    for producto in Producto.objects.select_related('unidad_medida'):
        producto.unidad_medida_texto = (
            producto.unidad_medida.nombre if producto.unidad_medida_id else 'unidad'
        )
        producto.save(update_fields=['unidad_medida_texto'])


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0016_quitar_precio_del_evento'),
    ]

    operations = [
        migrations.CreateModel(
            name='UnidadMedida',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=30, unique=True)),
            ],
            options={
                'verbose_name': 'unidad de medida',
                'verbose_name_plural': 'unidades de medida',
                'ordering': ['nombre'],
            },
        ),
        migrations.RenameField(
            model_name='producto',
            old_name='unidad_medida',
            new_name='unidad_medida_texto',
        ),
        migrations.AddField(
            model_name='producto',
            name='unidad_medida',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='productos',
                to='stock.unidadmedida',
                verbose_name='Unidad de medida',
            ),
        ),
        migrations.RunPython(sembrar_y_mapear, volver_a_texto),
        migrations.RemoveField(model_name='producto', name='unidad_medida_texto'),
    ]
