from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

SECTOR_CHOICES = [
    ('barra', 'Barra'),
    ('cocina', 'Cocina'),
    ('extras', 'Extras'),
]


class Producto(models.Model):
    nombre = models.CharField(max_length=100)
    sector = models.CharField(max_length=10, choices=SECTOR_CHOICES)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Decimal y no entero: hay productos que se miden en kilos o litros (2,5 kg).
    stock_actual = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    unidad_medida = models.CharField(max_length=20, default='unidad')
    activo = models.BooleanField(
        default=True,
        help_text='Los productos dados de baja no aparecen en Compras, Consumo ni Merma, '
                  'pero conservan su historial.',
    )

    def __str__(self):
        return f"{self.nombre} ({self.get_sector_display()})"

    def dar_de_baja(self):
        """Saca el producto de circulación sin tocar su historial (RN-20)."""
        self.activo = False
        self.save(update_fields=['activo'])


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

    @property
    def costo_por_persona(self):
        """Lo que cuesta un cubierto de este menú, a precios de hoy.

        Sirve para poner precio, así que acá SÍ va el precio actual del catálogo:
        es una proyección hacia adelante, no un histórico (eso es RN-15).
        """
        return sum(linea.costo_por_persona for linea in self.lineas.all())

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
    precio_por_persona = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name='Precio por persona',
        help_text='Lo que se cobra por cubierto. Se multiplica por los asistentes.',
    )
    precio_cerrado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name='Precio cerrado',
        help_text='Monto total acordado. Si lo cargás, manda sobre el precio por persona.',
    )
    reabierto_el = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Reabierto el',
        help_text='Queda marcado si el evento se reabrió después de haberse cerrado.',
    )

    def __str__(self):
        return f"{self.nombre} - {self.fecha}"

    @property
    def cerrado(self):
        """Un evento finalizado no acepta más carga: sus números están cerrados."""
        return self.estado == 'finalizado'

    # ----- Receta (RN-18) -----

    def copiar_receta_del_menu(self):
        """Trae la receta del menú asignado como punto de partida del evento.

        Reemplaza lo que hubiera: es "volver a la base", no "sumar de nuevo".
        Devuelve cuántas líneas copió.
        """
        if not self.menu_id:
            return 0
        with transaction.atomic():
            self.receta.all().delete()
            LineaReceta.objects.bulk_create([
                LineaReceta(
                    evento=self,
                    producto_id=linea.producto_id,
                    cantidad_por_persona=linea.cantidad_por_persona,
                )
                for linea in self.menu.lineas.all()
            ])
        return self.receta.count()

    @property
    def consumo_sugerido(self):
        """Lo que la receta calcula para esta cantidad de gente.

        Es una SUGERENCIA: no descuenta nada (RN-19). Precarga el formulario de
        consumo y el usuario corrige con lo que realmente salió.
        """
        return [
            {
                'producto': linea.producto,
                'cantidad': linea.cantidad_para(self.asistentes),
                'por_persona': linea.cantidad_por_persona,
            }
            for linea in self.receta.select_related('producto')
        ]

    @property
    def costo_receta_estimado(self):
        """Cuánto costaría el consumo si saliera exactamente como dice la receta."""
        return sum(
            item['cantidad'] * item['producto'].precio_unitario
            for item in self.consumo_sugerido
        )

    def reabrir(self):
        """Descongela un evento cerrado para poder corregirlo, dejando el rastro.

        Los olvidos existen: el mozo avisa el lunes lo que salió el sábado. Pero
        que el histórico se pueda tocar sin que quede constancia, no.
        """
        if not self.cerrado:
            return False
        self.estado = 'confirmado'
        self.reabierto_el = timezone.now()
        self.save(update_fields=['estado', 'reabierto_el'])
        return True

    @property
    def gasto_stock(self):
        # Solo las salidas: las entradas son reposición de depósito (RN-4) y la
        # merma es pérdida del salón (RN-12), no consumo del evento.
        #
        # Usa el costo SELLADO en el movimiento, no el precio de hoy del producto
        # (RN-15): si no, un evento del año pasado cambiaría de costo cada vez que
        # se actualiza una lista de precios.
        total = 0
        for m in self.movimientos.filter(tipo='salida'):
            total += m.cantidad * m.costo_unitario
        return total

    @property
    def gasto_personal(self):
        return sum(p.pago for p in self.personal.all())

    @property
    def gasto_total(self):
        return self.gasto_stock + self.gasto_personal

    # ----- Ingresos (RN-17) -----

    @property
    def ingreso_base(self):
        """Lo acordado por el evento en sí, sin los adicionales.

        El precio cerrado manda: hay eventos que se negocian por un monto total
        y otros que se cobran por cubierto. Si no hay ninguno de los dos, es 0 —
        NO se deduce del paquete, porque `Paquete.precio` es ambiguo (puede estar
        cargado como total o como por-persona) y adivinarlo inventa facturación.
        """
        if self.precio_cerrado is not None:
            return self.precio_cerrado
        if self.precio_por_persona is not None:
            return self.precio_por_persona * (self.asistentes or 0)
        return 0

    @property
    def ingreso_cargos(self):
        """Los adicionales facturados aparte: barra libre, DJ, horas extra."""
        return sum(c.monto for c in self.cargos.all())

    @property
    def ingreso_total(self):
        return self.ingreso_base + self.ingreso_cargos

    @property
    def tiene_precio_cargado(self):
        """Sin precio no hay margen: lo que se muestra es 'sin cargar', no '$0'."""
        return self.precio_cerrado is not None or self.precio_por_persona is not None

    @property
    def margen(self):
        return self.ingreso_total - self.gasto_total

    @property
    def margen_porcentaje(self):
        """Qué porcentaje de lo facturado te quedó. None si no hay ingreso."""
        if not self.ingreso_total:
            return None
        return (self.margen / self.ingreso_total) * 100

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

    def clean(self):
        super().clean()
        # RN-16: mismo criterio que el consumo. Un evento cerrado no suma más pagos.
        if self.evento_id and self.evento.cerrado:
            raise ValidationError(
                f'"{self.evento.nombre}" ya está finalizado. Si necesitás corregirlo, '
                'reabrilo primero desde el detalle del evento.'
            )


class LineaReceta(models.Model):
    """Cuánto de un producto se calcula por persona.

    Una sola tabla para dos usos con la misma forma:
    - colgada de un MENÚ: la receta base, sirve para costear el menú.
    - colgada de un EVENTO: la copia ajustada de ESE evento ("estos van sin cerdo").

    Son copias y no referencias a propósito (RN-18): si el evento apuntara al menú,
    cambiar la receta base en marzo cambiaría lo que se calculó para un evento de
    enero. El menú evoluciona; lo ya cargado no.
    """

    menu = models.ForeignKey(
        Menu, on_delete=models.CASCADE, null=True, blank=True, related_name='lineas'
    )
    evento = models.ForeignKey(
        Evento, on_delete=models.CASCADE, null=True, blank=True, related_name='receta'
    )
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name='en_recetas')
    cantidad_por_persona = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        validators=[MinValueValidator(0)],
        verbose_name='Cantidad por persona',
        help_text='Ej. 0,200 para 200 g de carne por cubierto.',
    )

    class Meta:
        verbose_name = 'Línea de receta'
        verbose_name_plural = 'Líneas de receta'
        constraints = [
            # Una línea es de un menú o de un evento, nunca de los dos ni de ninguno.
            models.CheckConstraint(
                condition=(
                    models.Q(menu__isnull=False, evento__isnull=True)
                    | models.Q(menu__isnull=True, evento__isnull=False)
                ),
                name='linea_receta_tiene_un_solo_dueno',
                violation_error_message='Una línea de receta pertenece a un menú o a un evento, no a los dos.',
            ),
        ]

    def __str__(self):
        dueno = self.menu or self.evento
        return f"{self.producto.nombre} x{self.cantidad_por_persona} por persona ({dueno})"

    @property
    def costo_por_persona(self):
        return self.cantidad_por_persona * self.producto.precio_unitario

    def cantidad_para(self, asistentes):
        """Lo que haría falta para esa cantidad de gente, redondeado a 2 decimales.

        `cantidad` en MovimientoStock tiene 2 decimales; la receta tiene 3 para
        poder expresar 0,125 L. Si no se redondea acá, el form sugiere un número
        que después no entra en el campo.
        """
        total = self.cantidad_por_persona * (asistentes or 0)
        return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class CargoEvento(models.Model):
    """Un adicional que se le factura al cliente aparte del precio base.

    Se llama CARGO y no "extra" a propósito: `extras` ya es un sector de stock
    (RN-8), que es un COSTO. Esto es lo contrario, un ingreso. Dos conceptos
    opuestos con el mismo nombre es garantía de que alguien los sume mal.
    """

    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='cargos')
    concepto = models.CharField(max_length=120, help_text='Ej. Barra libre, DJ, hora extra.')
    monto = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        verbose_name = 'Cargo al cliente'
        verbose_name_plural = 'Cargos al cliente'

    def __str__(self):
        return f"{self.concepto} - {self.evento.nombre}"

    def clean(self):
        super().clean()
        # RN-16: mismo criterio que el consumo y el personal.
        if self.evento_id and self.evento.cerrado:
            raise ValidationError(
                f'"{self.evento.nombre}" ya está finalizado. Si necesitás corregirlo, '
                'reabrilo primero desde el detalle del evento.'
            )


class MovimientoStock(models.Model):
    TIPO_CHOICES = [
        ('entrada', 'Entrada'),
        ('salida', 'Salida'),
        ('merma', 'Merma'),
    ]

    MOTIVO_CHOICES = [
        ('rotura', 'Rotura'),
        ('vencimiento', 'Vencimiento'),
        ('consumo_interno', 'Consumo interno'),
        ('otro', 'Otro'),
    ]

    # Las dos formas de que el stock baje. La entrada es la única que sube.
    TIPOS_QUE_DESCUENTAN = ('salida', 'merma')

    # PROTECT y no CASCADE (RN-20): el costo congelado de RN-15 vive ACÁ, así que
    # borrar un producto se llevaba puesto el historial de los eventos cerrados y
    # les cambiaba el margen. Un producto que ya no se usa se da de baja, no se borra.
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name='movimientos')
    evento = models.ForeignKey(Evento, on_delete=models.SET_NULL, null=True, blank=True, related_name='movimientos')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    motivo = models.CharField(
        max_length=20,
        choices=MOTIVO_CHOICES,
        blank=True,
        default='',
        help_text='Solo para las mermas: por qué se perdió la mercadería.',
    )
    cantidad = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    costo_unitario = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Costo unitario',
        help_text='Lo que valía el producto cuando se registró el movimiento. Se sella solo.',
    )
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tipo} - {self.producto.nombre} x{self.cantidad}"

    def clean(self):
        super().clean()
        # Se juntan todos los errores en vez de cortar en el primero, así el
        # usuario ve de una sola vez todo lo que tiene que corregir.
        errores = {}

        if self.tipo == 'merma':
            if not self.motivo:
                errores['motivo'] = 'Elegí por qué se perdió la mercadería.'
            if self.evento_id:
                errores['evento'] = 'La merma no se carga contra un evento: es una pérdida del depósito.'
        elif self.motivo:
            errores['motivo'] = 'El motivo es solo para las mermas.'

        # RN-16: los números de un evento cerrado no se tocan más.
        # El error va sin campo a propósito: 'evento' no lo declara ningún form,
        # y apuntarle un error a un campo inexistente es un 500, no un aviso.
        if self.evento_id and self.evento.cerrado:
            errores['__all__'] = (
                f'"{self.evento.nombre}" ya está finalizado. Si necesitás corregirlo, '
                'reabrilo primero desde el detalle del evento.'
            )

        # RN-2: ni una salida ni una merma pueden llevarse más de lo que hay.
        if self.tipo in self.TIPOS_QUE_DESCUENTAN and self.producto_id and self.cantidad:
            stock_disponible = self._stock_disponible()
            if self.cantidad > stock_disponible:
                errores['cantidad'] = (
                    f'No hay suficiente stock de "{self.producto.nombre}". '
                    f'Disponible: {stock_disponible} {self.producto.unidad_medida}.'
                )

        if errores:
            raise ValidationError(errores)

    def _stock_disponible(self):
        """Stock contra el que se valida, sin contar este mismo movimiento.

        Si es una edición, primero revierte el efecto de la versión guardada:
        cambiar una salida de 10 a 12 sobre un stock de 5 tiene 15 disponibles,
        no 5. Solo si el movimiento sigue apuntando al mismo producto — si le
        cambiaste el producto, el anterior no afecta al stock del nuevo.
        """
        disponible = self.producto.stock_actual
        if self.pk:
            anterior = MovimientoStock.objects.get(pk=self.pk)
            if anterior.producto_id == self.producto_id:
                disponible -= self._delta(anterior)
        return disponible

    @transaction.atomic
    def save(self, *args, **kwargs):
        # El anterior se lee ANTES de guardar: después ya está pisado en la base.
        anterior = None if self._state.adding else MovimientoStock.objects.get(pk=self.pk)

        # RN-15: el costo se sella al nacer y no se vuelve a tocar, salvo que el
        # movimiento pase a apuntar a otro producto. Corregirle la cantidad a un
        # consumo viejo NO tiene que revaluarlo al precio de hoy.
        if anterior is None or anterior.producto_id != self.producto_id:
            self.costo_unitario = self.producto.precio_unitario

        super().save(*args, **kwargs)
        if anterior is not None:
            self._mover_stock(anterior, revertir=True)
        self._mover_stock(self)
        self._sincronizar_producto()

    @transaction.atomic
    def delete(self, *args, **kwargs):
        self._mover_stock(self, revertir=True)
        resultado = super().delete(*args, **kwargs)
        self._sincronizar_producto()
        return resultado

    @staticmethod
    def _delta(movimiento):
        """Cuánto mueve el stock este movimiento, con signo.

        Las entradas suman; las salidas descuentan.
        """
        if movimiento.tipo == 'entrada':
            return movimiento.cantidad
        return -movimiento.cantidad

    @staticmethod
    def _mover_stock(movimiento, revertir=False):
        """Aplica (o revierte) el efecto de un movimiento sobre el stock.

        La cuenta la hace la base con F(), no Python: si editás un movimiento
        sin cambiarle el producto, revertir y aplicar tocan la MISMA fila, y
        con instancias en memoria la segunda escritura pisaba a la primera.
        Como son dos UPDATE ... SET x = x + n, se acumulan en vez de competir,
        y da igual el orden en que se ejecuten.
        """
        delta = MovimientoStock._delta(movimiento)
        if revertir:
            delta = -delta
        Producto.objects.filter(pk=movimiento.producto_id).update(
            stock_actual=F('stock_actual') + delta
        )

    def _sincronizar_producto(self):
        """Baja a memoria el stock que acaba de calcular la base.

        F() arregla la escritura pero deja la instancia mintiendo, y clean()
        lee justo self.producto.stock_actual para validar RN-2.
        """
        if self.producto_id:
            self.producto.refresh_from_db(fields=['stock_actual'])
