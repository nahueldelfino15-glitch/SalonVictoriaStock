"""Hace que el libro mayor cierre con el stock declarado.

Durante mucho tiempo `Producto.stock_actual` fue editable a mano, así que la
carga inicial se escribió sin generar el movimiento que la respalda. Resultado:
la suma de movimientos no da el stock real, y en varios productos da NEGATIVO
(salió mercadería que nunca entró).

Este comando NO toca el stock: toma `stock_actual` como la verdad física (es lo
que alguien contó mirando el depósito) y agrega los asientos que faltaban para
que el libro llegue a ese número.

    python manage.py reconciliar_stock              # solo muestra qué haría
    python manage.py reconciliar_stock --confirmar  # escribe los ajustes
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from stock.models import MovimientoStock, Producto


class Command(BaseCommand):
    help = 'Compara el stock declarado con la suma de movimientos y crea los asientos faltantes.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirmar',
            action='store_true',
            help='Escribe los ajustes. Sin esto solo muestra el diagnóstico.',
        )

    def handle(self, *args, **options):
        confirmar = options['confirmar']
        ajustes = []

        for producto in Producto.objects.order_by('nombre'):
            libro = Decimal('0')
            for movimiento in producto.movimientos.all():
                libro += MovimientoStock._delta(movimiento)

            diferencia = producto.stock_actual - libro
            if diferencia:
                ajustes.append((producto, libro, diferencia))

        if not ajustes:
            self.stdout.write(self.style.SUCCESS('El libro mayor ya cierra con el stock. No hay nada que ajustar.'))
            return

        self.stdout.write('')
        self.stdout.write(f'{"PRODUCTO":<22}{"DECLARADO":>12}{"LIBRO":>12}{"AJUSTE":>12}')
        self.stdout.write('-' * 58)
        for producto, libro, diferencia in ajustes:
            self.stdout.write(
                f'{producto.nombre[:21]:<22}{producto.stock_actual:>12}{libro:>12}{diferencia:>+12}'
            )
        self.stdout.write('-' * 58)
        total = sum(abs(d) for _, _, d in ajustes)
        self.stdout.write(f'{len(ajustes)} producto(s) descuadrado(s), {total} unidades en total.')
        self.stdout.write('')

        if not confirmar:
            self.stdout.write(self.style.WARNING(
                'Esto fue solo el diagnóstico. Corré con --confirmar para escribir los ajustes.'
            ))
            return

        with transaction.atomic():
            # bulk_create a propósito: NO tiene que pasar por save(), porque save()
            # movería el stock y volvería a descuadrar. El stock ya está bien; lo
            # que falta es el asiento que lo explique.
            MovimientoStock.objects.bulk_create([
                MovimientoStock(
                    producto=producto,
                    tipo='entrada' if diferencia > 0 else 'merma',
                    motivo='' if diferencia > 0 else 'otro',
                    cantidad=abs(diferencia),
                    costo_unitario=producto.precio_unitario,
                )
                for producto, _, diferencia in ajustes
            ])

        self.stdout.write(self.style.SUCCESS(
            f'Listo: {len(ajustes)} ajuste(s) registrado(s). El libro mayor ahora cierra.'
        ))
        self.stdout.write(
            'Las diferencias negativas quedaron como merma con motivo "otro": '
            'era mercadería que ya no estaba y no tenía asiento.'
        )
