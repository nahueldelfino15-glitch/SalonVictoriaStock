"""Puestos administrables y recetas organizadas por plato.

Tres cambios que van juntos porque tocan las mismas tablas:

1. `Puesto` deja de ser texto libre y pasa a ser un catálogo con FK. Los datos
   cargados venían sucios ("Moso", "moso", "Barra"), así que se normalizan acá:
   la lista de alias de abajo es de una sola vez, no queda en el código.
2. `Plato` agrupa la receta por momento de la comida, con nombre propio.
3. `LineaReceta` pasa a colgar del plato en vez de colgar del menú o del evento.

El punto 3 sería destructivo si hubiera recetas cargadas. No las hay (se
verificó: 0 filas) — de ahí que se pueda mover el dueño sin migrar datos.
"""

from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


# Los que el salón pidió tener desde el arranque. De acá en adelante los
# administra él desde la pantalla de Personal, no el código.
PUESTOS_INICIALES = ['Mozo', 'Barman', 'Cocina', 'Dj', 'Limpieza', 'Seguridad', 'Otro']

# Lo que ya estaba cargado a mano, mapeado a su puesto real.
ALIAS = {
    'moso': 'Mozo',
    'mozo': 'Mozo',
    'moza': 'Mozo',
    'barra': 'Barman',
    'barman': 'Barman',
    'cocina': 'Cocina',
    'cocinero': 'Cocina',
    'limpieza': 'Limpieza',
    'seguridad': 'Seguridad',
    'dj': 'Dj',
}


def cargar_puestos(apps, schema_editor):
    """Crea el catálogo y engancha lo que ya estaba escrito a mano."""
    Puesto = apps.get_model('stock', 'Puesto')
    Empleado = apps.get_model('stock', 'Empleado')
    PersonalEvento = apps.get_model('stock', 'PersonalEvento')

    for nombre in PUESTOS_INICIALES:
        Puesto.objects.get_or_create(nombre=nombre)

    def resolver(texto):
        """El texto viejo -> el Puesto que le corresponde.

        Si no está en la lista de alias se crea con el nombre tal cual: perder
        un dato cargado por no reconocerlo sería peor que tener un puesto de más.
        """
        limpio = (texto or '').strip()
        if not limpio:
            return None
        nombre = ALIAS.get(limpio.lower(), limpio.capitalize())
        return Puesto.objects.get_or_create(nombre=nombre)[0]

    for empleado in Empleado.objects.all():
        puesto = resolver(empleado.puesto_habitual)
        if puesto:
            Empleado.objects.filter(pk=empleado.pk).update(puesto_nuevo=puesto)

    for asignacion in PersonalEvento.objects.all():
        puesto = resolver(asignacion.puesto)
        if puesto:
            PersonalEvento.objects.filter(pk=asignacion.pk).update(puesto_nuevo=puesto)


def devolver_puestos_a_texto(apps, schema_editor):
    """Marcha atrás: el nombre del puesto vuelve al campo de texto."""
    Empleado = apps.get_model('stock', 'Empleado')
    PersonalEvento = apps.get_model('stock', 'PersonalEvento')

    for modelo, campo in [(Empleado, 'puesto_habitual'), (PersonalEvento, 'puesto')]:
        for fila in modelo.objects.select_related('puesto_nuevo'):
            modelo.objects.filter(pk=fila.pk).update(
                **{campo: fila.puesto_nuevo.nombre if fila.puesto_nuevo_id else ''}
            )


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0009_producto_activo_alter_movimientostock_producto'),
    ]

    operations = [
        # ---------- 1. Catálogo de puestos ----------
        migrations.CreateModel(
            name='Puesto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=60, unique=True)),
            ],
            options={
                'verbose_name': 'Puesto',
                'verbose_name_plural': 'Puestos',
                'ordering': ['nombre'],
            },
        ),
        migrations.AddField(
            model_name='empleado',
            name='puesto_nuevo',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='empleados', to='stock.puesto',
            ),
        ),
        migrations.AddField(
            model_name='personalevento',
            name='puesto_nuevo',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='asignaciones', to='stock.puesto',
            ),
        ),
        migrations.RunPython(cargar_puestos, devolver_puestos_a_texto),
        migrations.RemoveField(model_name='empleado', name='puesto_habitual'),
        migrations.RemoveField(model_name='personalevento', name='puesto'),
        migrations.RenameField(
            model_name='empleado', old_name='puesto_nuevo', new_name='puesto_habitual',
        ),
        migrations.RenameField(
            model_name='personalevento', old_name='puesto_nuevo', new_name='puesto',
        ),
        migrations.AlterField(
            model_name='empleado',
            name='puesto_habitual',
            field=models.ForeignKey(
                blank=True,
                help_text='El que hace normalmente. En cada evento se puede pisar por otro.',
                null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='empleados', to='stock.puesto', verbose_name='Puesto habitual',
            ),
        ),

        # ---------- 2. Platos ----------
        migrations.CreateModel(
            name='Plato',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('paso', models.CharField(choices=[
                    ('entrante', 'Entrante'),
                    ('principal', 'Plato principal'),
                    ('secundario', 'Plato secundario'),
                    ('postre', 'Postre'),
                ], max_length=12)),
                ('nombre', models.CharField(help_text='Ej. Tabla de fiambres, Bife con papas.', max_length=120)),
                ('evento', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name='platos', to='stock.evento',
                )),
                ('menu', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name='platos', to='stock.menu',
                )),
            ],
            options={
                'verbose_name': 'Plato',
                'verbose_name_plural': 'Platos',
                'ordering': [
                    models.Case(
                        models.When(paso='entrante', then=0),
                        models.When(paso='principal', then=1),
                        models.When(paso='secundario', then=2),
                        models.When(paso='postre', then=3),
                        default=4,
                    ),
                    'nombre',
                ],
            },
        ),
        migrations.AddConstraint(
            model_name='plato',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(('evento__isnull', True), ('menu__isnull', False)),
                    models.Q(('evento__isnull', False), ('menu__isnull', True)),
                    _connector='OR',
                ),
                name='plato_tiene_un_solo_dueno',
                violation_error_message='Un plato pertenece a un menú o a un evento, no a los dos.',
            ),
        ),

        # ---------- 3. La receta pasa a colgar del plato ----------
        migrations.RemoveConstraint(
            model_name='lineareceta', name='linea_receta_tiene_un_solo_dueno',
        ),
        migrations.RemoveField(model_name='lineareceta', name='menu'),
        migrations.RemoveField(model_name='lineareceta', name='evento'),
        migrations.AddField(
            model_name='lineareceta',
            name='plato',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='lineas', to='stock.plato',
            ),
        ),
        # En dos pasos porque el campo es obligatorio: si alguna receta hubiera
        # sobrevivido sin plato, esto falla acá en vez de dejarla huérfana.
        migrations.AlterField(
            model_name='lineareceta',
            name='plato',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='lineas', to='stock.plato',
            ),
        ),
        migrations.AlterField(
            model_name='lineareceta',
            name='cantidad_por_persona',
            field=models.DecimalField(
                decimal_places=3,
                help_text='Ej. 0,200 para 200 g de carne por cubierto.',
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name='Cantidad por persona',
            ),
        ),
        migrations.AlterModelOptions(
            name='lineareceta',
            options={
                'ordering': ['producto__nombre'],
                'verbose_name': 'Ingrediente',
                'verbose_name_plural': 'Ingredientes',
            },
        ),
    ]
