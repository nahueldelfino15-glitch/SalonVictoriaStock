from collections import defaultdict
from decimal import Decimal

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import (
    CargoEvento,
    Empleado,
    Evento,
    LineaReceta,
    Menu,
    MovimientoStock,
    Paquete,
    PersonalEvento,
    Producto,
)


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = (
        'nombre',
        'sector',
        'stock_actual',
        'precio_unitario',
        'unidad_medida',
    )
    list_filter = ('sector',)
    search_fields = ('nombre',)
    ordering = ('nombre',)


@admin.register(Paquete)
class PaqueteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'precio')
    search_fields = ('nombre',)
    ordering = ('nombre',)


class LineaRecetaMenuInline(admin.TabularInline):
    model = LineaReceta
    extra = 1
    fields = ('producto', 'cantidad_por_persona')
    fk_name = 'menu'


@admin.register(Menu)
class MenuAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'costo_por_persona')
    search_fields = ('nombre',)
    ordering = ('nombre',)
    inlines = [LineaRecetaMenuInline]

    @admin.display(description='Costo por cubierto')
    def costo_por_persona(self, obj):
        return obj.costo_por_persona


@admin.register(Empleado)
class EmpleadoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'puesto_habitual', 'telefono')
    search_fields = ('nombre',)
    ordering = ('nombre',)


class CargoEventoInline(admin.TabularInline):
    model = CargoEvento
    extra = 1
    fields = ('concepto', 'monto')


class PersonalEventoInline(admin.TabularInline):
    model = PersonalEvento
    extra = 1
    fields = ('empleado', 'puesto', 'horas_trabajadas', 'pago')


def _efecto(tipo, cantidad):
    """Cuánto suma (o resta) un movimiento al stock del producto."""
    if tipo in MovimientoStock.TIPOS_QUE_DESCUENTAN:
        return -cantidad
    return cantidad


class MovimientoStockInlineFormSet(BaseInlineFormSet):
    """Valida el stock mirando TODAS las filas juntas.

    `MovimientoStock.clean()` valida cada movimiento contra el stock que hay en
    la base (RN-2), pero dentro de un formset cada fila se valida por separado y
    ninguna ve lo que sacan las otras: con 50 botellas, dos filas de 45 pasaban
    las dos y el stock terminaba en -40. Acá sumamos el efecto neto por producto
    antes de guardar nada.
    """

    def clean(self):
        super().clean()
        if any(self.errors):
            return

        neto = defaultdict(Decimal)
        for form in self.forms:
            datos = getattr(form, 'cleaned_data', None)
            if not datos:
                continue
            if form.instance.pk:
                # Editar o borrar primero devuelve al stock lo que el movimiento
                # guardado había movido (RN-3).
                previo = MovimientoStock.objects.filter(pk=form.instance.pk).values(
                    'producto_id', 'tipo', 'cantidad'
                ).first()
                if previo:
                    neto[previo['producto_id']] -= _efecto(previo['tipo'], previo['cantidad'])
            if datos.get('DELETE'):
                continue
            producto, tipo, cantidad = datos.get('producto'), datos.get('tipo'), datos.get('cantidad')
            if producto and tipo and cantidad is not None:
                neto[producto.pk] += _efecto(tipo, cantidad)

        faltantes = [
            producto
            for producto in Producto.objects.filter(
                pk__in=[pk for pk, delta in neto.items() if delta < 0]
            )
            if producto.stock_actual + neto[producto.pk] < 0
        ]
        if faltantes:
            raise ValidationError([
                f'No hay suficiente stock de "{p.nombre}" para todos los movimientos '
                f'juntos. Disponible: {p.stock_actual} {p.unidad_medida}.'
                for p in faltantes
            ])


class MovimientoStockInline(admin.TabularInline):
    """Ojo: cada fila de acá mueve stock de verdad, porque pasa por
    `MovimientoStock.save()` (RN-1) y valida el disponible (RN-2)."""

    model = MovimientoStock
    formset = MovimientoStockInlineFormSet
    extra = 1
    # Sin 'motivo': acá los movimientos cuelgan de un evento y una merma nunca
    # lleva evento (RN-12), así que desde este inline no se puede cargar una.
    fields = ('producto', 'tipo', 'cantidad')

    def delete_queryset(self, request, queryset):  # pragma: no cover - defensivo
        """Los inlines borran fila por fila, pero si algún día no lo hicieran
        el stock quedaría sin revertir. Ver MovimientoStockAdmin."""
        for movimiento in queryset:
            movimiento.delete()


@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    list_display = (
        'nombre',
        'fecha',
        'estado',
        'asistentes',
        'gasto_stock',
        'gasto_personal',
        'gasto_total',
    )
    list_filter = ('estado',)
    search_fields = ('nombre',)
    date_hierarchy = 'fecha'
    ordering = ('-fecha',)
    inlines = [CargoEventoInline, PersonalEventoInline, MovimientoStockInline]

    # Los tres gastos son properties del modelo (RN-6). Se envuelven acá solo
    # para que la columna tenga un título en castellano.
    @admin.display(description='Gasto de stock')
    def gasto_stock(self, obj):
        return obj.gasto_stock

    @admin.display(description='Gasto de personal')
    def gasto_personal(self, obj):
        return obj.gasto_personal

    @admin.display(description='Gasto total')
    def gasto_total(self, obj):
        return obj.gasto_total


@admin.register(MovimientoStock)
class MovimientoStockAdmin(admin.ModelAdmin):
    list_display = ('producto', 'tipo', 'motivo', 'cantidad', 'evento', 'fecha')
    list_filter = ('tipo', 'motivo', 'producto__sector')
    search_fields = ('producto__nombre', 'evento__nombre')
    date_hierarchy = 'fecha'
    list_select_related = ('producto', 'evento')
    ordering = ('-fecha',)

    def delete_queryset(self, request, queryset):
        """La acción masiva de Django usa queryset.delete(), que NO pasa por
        MovimientoStock.delete() y dejaría el stock sin revertir (RN-1/RN-3).
        Borramos uno por uno para que cada movimiento devuelva su efecto."""
        for movimiento in queryset:
            movimiento.delete()
