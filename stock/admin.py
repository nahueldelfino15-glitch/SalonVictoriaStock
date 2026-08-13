from django.contrib import admin
from .models import Producto, Evento, Empleado, PersonalEvento, MovimientoStock


class PersonalEventoInline(admin.TabularInline):
    model = PersonalEvento
    extra = 1


class MovimientoStockInline(admin.TabularInline):
    model = MovimientoStock
    extra = 1


class EventoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'fecha', 'gasto_stock', 'gasto_personal', 'gasto_total')
    inlines = [PersonalEventoInline, MovimientoStockInline]


admin.site.register(Producto)
admin.site.register(Evento, EventoAdmin)
admin.site.register(Empleado)
admin.site.register(MovimientoStock)