from django.db import models
from django.core.exceptions import ValidationError

SECTOR_CHOICES = [
    ('barra', 'Barra'),
    ('cocina', 'Cocina'),
    ('extras', 'Extras'),
]


class Producto(models.Model):
    nombre = models.CharField(max_length=100)
    sector = models.CharField(max_length=10, choices=SECTOR_CHOICES)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock_actual = models.PositiveIntegerField(default=0)
    unidad_medida = models.CharField(max_length=20, default='unidad')

    def __str__(self):
        return f"{self.nombre} ({self.get_sector_display()})"
    
class Paquete(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2, default=0, blank=True, null=True)

    def __str__(self):
        return self.nombre


class Menu(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)

    def __str__(self):
        return self.nombre

ESTADO_CHOICES = [
    ('pendiente', 'Pendiente'),
    ('confirmado', 'Confirmado'),
    ('finalizado', 'Finalizado'),
]


class Evento(models.Model):
    nombre = models.CharField(max_length=150)
    fecha = models.DateField()
    asistentes = models.PositiveIntegerField(default=0, blank=True, null=True, verbose_name='Cantidad de asistentes')
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='pendiente')
    paquete = models.ForeignKey(Paquete, on_delete=models.SET_NULL, null=True, blank=True, related_name='eventos')
    menu = models.ForeignKey(Menu, on_delete=models.SET_NULL, null=True, blank=True, related_name='eventos')
    telefono_contacto = models.CharField(max_length=30, blank=True, verbose_name='Teléfono de contacto')
    notas = models.TextField(blank=True)

    def __str__(self):
        return f"{self.nombre} - {self.fecha}"

    @property
    def gasto_stock(self):
        total = 0
        for m in self.movimientos.filter(tipo='salida'):
            total += m.cantidad * m.producto.precio_unitario
        return total

    @property
    def gasto_personal(self):
        return sum(p.pago for p in self.personal.all())

    @property
    def gasto_total(self):
        return self.gasto_stock + self.gasto_personal

class Empleado(models.Model):
    """Catálogo general de personal, independiente de los eventos."""
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=30, blank=True)
    puesto_habitual = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.nombre


class PersonalEvento(models.Model):
    """Asignación de un empleado a un evento puntual."""
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='personal')
    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, related_name='eventos_trabajados')
    puesto = models.CharField(max_length=100, blank=True)
    horas_trabajadas = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    pago = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.empleado.nombre} - {self.evento.nombre}"


class MovimientoStock(models.Model):
    TIPO_CHOICES = [
        ('entrada', 'Entrada'),
        ('salida', 'Salida'),
    ]
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='movimientos')
    evento = models.ForeignKey(Evento, on_delete=models.SET_NULL, null=True, blank=True, related_name='movimientos')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    cantidad = models.PositiveIntegerField()
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tipo} - {self.producto.nombre} x{self.cantidad}"

    def clean(self):
        super().clean()
        if self.tipo == 'salida' and self.producto_id and self.cantidad:
            stock_disponible = self.producto.stock_actual
            if self.pk:
                anterior = MovimientoStock.objects.get(pk=self.pk)
                if anterior.tipo == 'salida':
                    stock_disponible += anterior.cantidad
                elif anterior.tipo == 'entrada':
                    stock_disponible -= anterior.cantidad
            if self.cantidad > stock_disponible:
                raise ValidationError({
                    'cantidad': f'No hay suficiente stock de "{self.producto.nombre}". Disponible: {stock_disponible} {self.producto.unidad_medida}.'
                })

    def save(self, *args, **kwargs):
        es_nuevo = self._state.adding
        if not es_nuevo:
            anterior = MovimientoStock.objects.get(pk=self.pk)
            self._revertir_stock(anterior)
        super().save(*args, **kwargs)
        self._aplicar_stock()

    def delete(self, *args, **kwargs):
        self._revertir_stock(self)
        super().delete(*args, **kwargs)

    def _aplicar_stock(self):
        if self.tipo == 'entrada':
            self.producto.stock_actual += self.cantidad
        else:
            self.producto.stock_actual -= self.cantidad
        self.producto.save()

    def _revertir_stock(self, movimiento):
        producto = movimiento.producto
        if movimiento.tipo == 'entrada':
            producto.stock_actual -= movimiento.cantidad
        else:
            producto.stock_actual += movimiento.cantidad
        producto.save()