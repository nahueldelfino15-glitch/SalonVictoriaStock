from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

SECTOR_CHOICES = [
    ('barra', 'Barra'),
    ('cocina', 'Cocina'),
    ('extras', 'Extras'),
    ('limpieza', 'Limpieza'),
    ('mobiliario', 'Mobiliario'),
]

# El mobiliario (vajilla, manteles, servilletas, vasos) se cuenta pero no se valoriza:
# no es mercadería que se consuma, es lo que el salón pone. Sin precio no suma al costo
# del evento, que es justo lo que se quiere — si no, cada mantel usado le inflaría el
# gasto a la fiesta.
SECTORES_SIN_PRECIO = ('mobiliario',)


def sector_valoriza(sector):
    return sector not in SECTORES_SIN_PRECIO


class UnidadMedida(models.Model):
    """En qué se mide un producto: kilogramos, litros, unidad, cajas (RN-26).

    Es una tabla y no `choices` por el mismo motivo que `Puesto` (RN-21): el salón
    compra en formatos que van cambiando (botellas, docenas, bidones), y agregar
    uno no puede depender de un deploy.
    """

    nombre = models.CharField(max_length=30, unique=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'unidad de medida'
        verbose_name_plural = 'unidades de medida'

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    nombre = models.CharField(max_length=100)
    sector = models.CharField(max_length=20, choices=SECTOR_CHOICES)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Decimal y no entero: hay productos que se miden en kilos o litros (2,5 kg).
    stock_actual = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    # PROTECT (RN-26): la unidad es lo que le da sentido al stock. Borrar "Litros"
    # del catálogo dejaría el fernet en "50" a secas, que no es un dato, es un número.
    # null=True es para la base (los productos viejos migran solos); el form igual
    # la exige, así que ninguno nuevo nace sin unidad.
    unidad_medida = models.ForeignKey(
        UnidadMedida,
        on_delete=models.PROTECT,
        null=True,
        related_name='productos',
        verbose_name='Unidad de medida',
    )
    activo = models.BooleanField(
        default=True,
        help_text='Los productos dados de baja no aparecen en Compras, Consumo ni Merma, '
                  'pero conservan su historial.',
    )

    def __str__(self):
        return f"{self.nombre} ({self.get_sector_display()})"

    def save(self, *args, **kwargs):
        """Sin precio vale 0, no revienta.

        El precio es opcional porque el mobiliario no se valoriza (RN-8), y un
        campo opcional devuelve None, que en una columna NOT NULL es un 500. Va
        acá y no en la vista para que valga también desde el admin y el shell.
        """
        if self.precio_unitario is None:
            self.precio_unitario = 0
        super().save(*args, **kwargs)

    @property
    def valoriza(self):
        """Si este producto lleva precio o solo se cuenta (RN-8)."""
        return sector_valoriza(self.sector)

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
        return sum(
            linea.costo_por_persona
            for plato in self.platos.all()
            for linea in plato.lineas.all()
        )

    @property
    def platos_por_paso(self):
        """Los platos agrupados por momento de la comida, en orden de servicio."""
        return agrupar_por_paso(self.platos.all())

    def necesita_para(self, porciones):
        """Los productos que hacen falta para servir N cubiertos de este menú.

        Un producto que está en dos platos (la papa va en el principal y en la
        guarnición) sale en UNA línea, con las porciones sumadas **antes** de
        redondear: dos redondeos por separado dan otro número (RN-19).
        """
        por_producto = {}
        lineas = (
            LineaReceta.objects
            .filter(plato__menu=self)
            .select_related('producto', 'producto__unidad_medida')
        )
        for linea in lineas:
            item = por_producto.setdefault(
                linea.producto_id,
                {'producto': linea.producto, 'por_persona': Decimal('0')},
            )
            item['por_persona'] += linea.cantidad_por_persona

        for item in por_producto.values():
            item['cantidad'] = (item['por_persona'] * porciones).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )

        return sorted(por_producto.values(), key=lambda i: i['producto'].nombre.lower())

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
    precio_paquete = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name='Monto del paquete',
        help_text='Se completa solo al elegir el paquete. Cambialo si este evento se cerró por otro monto.',
    )
    brindis_asistentes = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Asistentes al brindis',
        help_text='Cuántos participan del brindis. No siempre son todos los invitados.',
    )
    brindis_valor = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name='Valor del brindis',
        help_text='Lo que se cobra por persona por el brindis.',
    )
    reabierto_el = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Reabierto el',
        help_text='Queda marcado si el evento se reabrió después de haberse cerrado.',
    )
    aviso_enviado_el = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Aviso enviado el',
        help_text='Cuándo salió el recordatorio por mail. Vaciálo para que se vuelva a mandar.',
    )

    def __str__(self):
        return f"{self.nombre} - {self.fecha}"

    @property
    def cerrado(self):
        """Un evento finalizado no acepta más carga: sus números están cerrados."""
        return self.estado == 'finalizado'

    # ----- Receta (RN-18) -----

    @transaction.atomic
    def save(self, *args, **kwargs):
        """Asignarle un menú al evento le trae la receta sola (RN-18).

        La receta se carga en UN solo lugar: el menú. El evento la hereda al
        quedar asignado, y esa copia es la que queda asentada en su detalle.
        Solo se recopia cuando el menú CAMBIA: guardar el evento por cualquier
        otro motivo no puede pisar lo que ya está calculado.
        """
        anterior = (
            None if self._state.adding
            else Evento.objects.filter(pk=self.pk)
                               .values('menu_id', 'paquete_id', 'precio_paquete').first()
        )
        menu_anterior = anterior['menu_id'] if anterior else None
        paquete_anterior = anterior['paquete_id'] if anterior else None
        precio_anterior = anterior['precio_paquete'] if anterior else None

        # El monto del paquete se sella al elegirlo, igual que el costo de un
        # movimiento (RN-15). Después vive en el evento y el catálogo no lo toca.
        if self.paquete_id and self.paquete_id != paquete_anterior:
            # Solo se resella si el usuario NO escribió un monto propio. Si en el
            # mismo formulario cambió de paquete y tipeó otra cifra, manda la suya:
            # el evento se cerró por ese número, no por el de la lista.
            if self.precio_paquete in (None, precio_anterior):
                self.precio_paquete = self.paquete.precio
        elif paquete_anterior and not self.paquete_id:
            # Se limpia SOLO si el evento tenía paquete y se lo sacaron. Sin esa
            # condición, cualquier guardado borraba un monto cargado a mano — y
            # también el sello de un evento cuyo paquete se borró del catálogo
            # (SET_NULL deja paquete_id en None), que es justo lo que hay que
            # proteger: la facturación volvía a $0 al reguardar.
            self.precio_paquete = None

        super().save(*args, **kwargs)
        if self.menu_id and self.menu_id != menu_anterior:
            self.copiar_receta_del_menu()

    def raciones_por_menu(self):
        """Cuánta gente come de cada menú: {menu_id: porciones}.

        Manda la tarjeta (RN-23): una fiesta de 100 puede ser 80 del menú adulto
        y 20 del infantil. Dos tarjetas del mismo menú se suman en un solo bloque
        — son 90 raciones del clásico, no dos recetas iguales una abajo de la otra.

        Si no hay tarjetas con menú, se cae al menú del evento por los asistentes,
        que es como funcionaba antes de las tarjetas y lo que siguen usando los
        eventos ya cargados.
        """
        raciones = {}
        for tarjeta in self.tarjetas.all():
            if tarjeta.menu_id and tarjeta.cantidad:
                raciones[tarjeta.menu_id] = raciones.get(tarjeta.menu_id, 0) + tarjeta.cantidad

        if not raciones and self.menu_id:
            # None y NO `self.asistentes`: sin tarjetas la cantidad de gente se
            # multiplica EN VIVO al mostrar. Sellarla acá congelaba el número del
            # día en que se asignó el menú — corregir los asistentes de 100 a 150
            # dejaba la receta pidiendo para 100, y un evento cargado con 0
            # asistentes quedaba sugiriendo 0 de todo para siempre.
            raciones[self.menu_id] = None
        return raciones

    def copiar_receta_del_menu(self):
        """Trae la receta de los menús que come este evento.

        Reemplaza lo que hubiera: es "volver a la base", no "sumar de nuevo".
        Cada plato copiado se queda con las porciones que le corresponden, así el
        cálculo de comida no necesita volver a mirar las tarjetas después.

        Devuelve cuántos platos copió.
        """
        raciones = self.raciones_por_menu()

        with transaction.atomic():
            # Se borra ANTES de chequear si hay algo que copiar: al sacar la
            # última tarjeta no queda ninguna ración, y con el return temprano
            # arriba la receta del grupo que ya no existe seguía en pantalla,
            # sumando al costo estimado.
            self.platos.all().delete()
            if not raciones:
                return 0

            for menu_id, porciones in raciones.items():
                platos_base = Plato.objects.filter(menu_id=menu_id).prefetch_related('lineas')
                for base in platos_base:
                    copia = Plato.objects.create(
                        evento=self, paso=base.paso, nombre=base.nombre, porciones=porciones,
                    )
                    LineaReceta.objects.bulk_create([
                        LineaReceta(
                            plato=copia,
                            producto_id=linea.producto_id,
                            cantidad_por_persona=linea.cantidad_por_persona,
                        )
                        for linea in base.lineas.all()
                    ])
        return self.platos.count()

    @property
    def platos_por_paso(self):
        """La receta de ESTE evento agrupada por momento de la comida."""
        return agrupar_por_paso(self.platos.all())

    @property
    def menus_del_evento(self):
        """Qué menús se sirven y cuánta gente come de cada uno (RN-31).

        Sale de `raciones_por_menu()`, así que respeta lo mismo que la receta: si
        hay tarjetas con menú mandan ellas (80 del adulto + 20 del infantil), y
        si no, el menú del evento por los asistentes.

        `porciones` se resuelve acá y no en la consulta porque sin tarjetas vale
        `None`, que significa "por los asistentes de HOY" (RN-23).
        """
        raciones = self.raciones_por_menu()
        if not raciones:
            return []

        menus = {m.pk: m for m in Menu.objects.filter(pk__in=raciones)}
        salida = []
        for menu_id, porciones in raciones.items():
            menu = menus.get(menu_id)
            if menu is None:
                continue            # el menú se borró del catálogo (SET_NULL)
            salida.append({
                'menu': menu,
                'porciones': self.asistentes or 0 if porciones is None else porciones,
                'por_tarjeta': porciones is not None,
            })
        return sorted(salida, key=lambda i: i['menu'].nombre.lower())

    @property
    def receta_calculada(self):
        """La receta con las cantidades ya resueltas para los asistentes.

        Los ingredientes se cuelgan de cada plato porque los templates de Django
        no pueden llamar a un método con argumentos: `plato.para(asistentes)` no
        se puede escribir en el HTML, `plato.ingredientes` sí.
        """
        grupos = agrupar_por_paso(self.platos.prefetch_related('lineas__producto'))
        for grupo in grupos:
            for plato in grupo['platos']:
                plato.ingredientes = plato.para(self.asistentes)
        return grupos

    @property
    def consumo_sugerido(self):
        """Lo que la receta calcula para esta cantidad de gente.

        Un mismo producto puede aparecer en varios platos, y ahora también en
        menús distintos (la papa está en el menú adulto y en el infantil): se
        acumula el TOTAL de todos y recién ahí se redondea. Redondear cada plato
        por separado y después sumar da otro número.

        Cada plato multiplica por SUS porciones, no por los asistentes del evento:
        80 raciones de un menú y 20 de otro no son 100 de cada uno (RN-23).

        Es una SUGERENCIA: no descuenta nada (RN-19). Precarga el formulario de
        consumo y el usuario corrige con lo que realmente salió.
        """
        # Si hay tarjetas con menú, ELLAS mandan y nada se cuenta por asistentes.
        # Sin esta guarda, un plato suelto sin porciones (cargado a mano desde el
        # admin) se sumaría EN PARALELO a los de las tarjetas: 100 raciones más
        # arriba de las 80 + 20, y sin ningún aviso.
        manda_la_tarjeta = any(t.menu_id and t.cantidad for t in self.tarjetas.all())

        por_producto = {}
        lineas = (
            LineaReceta.objects
            .filter(plato__evento=self)
            .select_related('producto', 'plato')
        )
        for linea in lineas:
            porciones = linea.plato.porciones
            if porciones is None:
                if manda_la_tarjeta:
                    continue
                # Evento anterior a las tarjetas: vale por los asistentes, como
                # se calculaba entonces.
                porciones = self.asistentes or 0

            item = por_producto.setdefault(
                linea.producto_id,
                {'producto': linea.producto, 'total': Decimal('0'), 'porciones': 0},
            )
            item['total'] += linea.cantidad_por_persona * porciones
            item['porciones'] += porciones

        for item in por_producto.values():
            item['cantidad'] = item['total'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            # Lo que se muestra como "por persona" es el promedio real sobre la
            # gente que come ese producto. Con un solo menú da exactamente la
            # cantidad de la receta; con dos, informa sin mentir.
            item['por_persona'] = (
                (item['total'] / item['porciones']).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
                if item['porciones'] else Decimal('0')
            )

        return sorted(por_producto.values(), key=lambda item: item['producto'].nombre.lower())

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
    def ingreso_tarjetas(self):
        """Lo que paga la gente, por tipo de invitado (RN-23).

        Una fiesta de 100 puede tener 80 tarjetas de adulto y 20 de menú infantil,
        a precios distintos. Por eso son filas y no un precio único.
        """
        return sum(t.subtotal for t in self.tarjetas.all())

    @property
    def ingreso_brindis(self):
        """El brindis se cobra aparte y no siempre lo tienen todos los invitados."""
        if not self.brindis_asistentes or not self.brindis_valor:
            return 0
        return self.brindis_asistentes * self.brindis_valor

    @property
    def ingreso_paquete(self):
        """El paquete es un MONTO TOTAL del evento, no un precio por cubierto.

        Decisión del dueño: "Premium: 129.013" es lo que sale el paquete completo.
        Multiplicarlo por los asistentes inventaría una facturación que no existe.

        Sale de `precio_paquete`, sellado en el evento, y NO de `paquete.precio`
        (RN-15 del lado del ingreso). Leerlo en vivo del catálogo tenía dos
        puertas abiertas y las dos cambiaban la plata de un evento ya cerrado:
        editar el precio del paquete, y borrar el paquete — que con SET_NULL
        dejaba la facturación en $0 sin avisar nada.
        """
        return self.precio_paquete or 0

    @property
    def ingreso_cargos(self):
        """Los adicionales facturados aparte: barra libre, DJ, horas extra."""
        return sum(c.monto for c in self.cargos.all())

    @property
    def ingreso_total(self):
        """Lo facturado sale de las tarjetas, el brindis, el paquete y los cargos.

        El evento ya no tiene precio propio: antes había `precio_cerrado` y
        `precio_por_persona`, y sumaban EN PARALELO a las tarjetas. Cargar las dos
        cosas facturaba la misma comida dos veces, sin que nada lo avisara. El
        cubierto se cobra en un solo lugar — la tabla de tarjetas — que además es el
        único que sabe distinguir 80 adultos de 20 menús infantiles (RN-23).
        """
        return (
            self.ingreso_tarjetas
            + self.ingreso_brindis
            + self.ingreso_paquete
            + self.ingreso_cargos
        )

    @property
    def desglose_ingresos(self):
        """Cada renglón de lo facturado, para mostrarlo abierto en la pantalla.

        Solo aparecen los que tienen algo cargado: una tabla llena de ceros no
        informa, esconde.
        """
        renglones = []

        for tarjeta in self.tarjetas.all():
            renglones.append({
                'concepto': tarjeta.concepto,
                'detalle': f'{tarjeta.cantidad} × $ {tarjeta.valor_unitario:,.2f}',
                'monto': tarjeta.subtotal,
            })

        if self.ingreso_brindis:
            renglones.append({
                'concepto': 'Brindis',
                'detalle': f'{self.brindis_asistentes} × $ {self.brindis_valor:,.2f}',
                'monto': self.ingreso_brindis,
            })

        if self.ingreso_paquete:
            renglones.append({
                # El paquete puede haberse borrado del catálogo: el monto sellado
                # sigue siendo válido aunque ya no haya nombre que mostrar.
                'concepto': f'Paquete {self.paquete.nombre}' if self.paquete_id else 'Paquete',
                'detalle': 'monto total',
                'monto': self.ingreso_paquete,
            })

        for cargo in self.cargos.all():
            renglones.append({
                'concepto': cargo.concepto,
                'detalle': 'adicional',
                'monto': cargo.monto,
            })

        return renglones

    @property
    def tarjetas_vs_asistentes(self):
        """La diferencia entre lo que dicen las tarjetas y los asistentes cargados.

        No se valida ni se bloquea: en un salón los números bailan hasta último
        momento y trabar la carga sería peor. Pero se avisa, porque una diferencia
        grande casi siempre es un dato mal cargado, no la realidad.
        Devuelve None si no hay tarjetas.
        """
        if not self.tarjetas.exists():
            return None
        return sum(t.cantidad for t in self.tarjetas.all()) - (self.asistentes or 0)

    @property
    def tiene_precio_cargado(self):
        """Sin precio no hay margen: lo que se muestra es 'sin cargar', no '$0'."""
        return bool(self.ingreso_total)

    @property
    def margen(self):
        return self.ingreso_total - self.gasto_total

    @property
    def margen_porcentaje(self):
        """Qué porcentaje de lo facturado te quedó. None si no hay ingreso."""
        if not self.ingreso_total:
            return None
        return (self.margen / self.ingreso_total) * 100

class DestinatarioAviso(models.Model):
    """A quién le llegan los recordatorios de eventos (RN-24).

    Es una tabla y no un setting para que el salón agregue y saque gente sin
    esperar un deploy — mismo criterio que los puestos (RN-21). El `activo`
    existe para cortarle el aviso a alguien sin perder su dirección: si se borra
    y mañana vuelve, hay que escribirla de nuevo.
    """

    email = models.EmailField(unique=True, verbose_name='Correo')
    nombre = models.CharField(max_length=100, blank=True, help_text='Opcional, para saber quién es.')
    activo = models.BooleanField(default=True, help_text='Destildalo para dejar de avisarle sin borrarlo.')

    class Meta:
        ordering = ['email']
        verbose_name = 'Destinatario de avisos'
        verbose_name_plural = 'Destinatarios de avisos'

    def __str__(self):
        return f'{self.nombre} <{self.email}>' if self.nombre else self.email

    @classmethod
    def direcciones_activas(cls):
        return list(cls.objects.filter(activo=True).values_list('email', flat=True))


class Puesto(models.Model):
    """Catálogo de puestos, administrable desde la pantalla de Personal.

    No son constantes en el código a propósito: el salón cambia de servicios y
    tiene que poder agregar "Valet" o "Fotógrafo" sin esperar un deploy. Los
    selects de personal se llenan desde acá.
    """

    nombre = models.CharField(max_length=60, unique=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Puesto'
        verbose_name_plural = 'Puestos'

    def __str__(self):
        return self.nombre


class Empleado(models.Model):
    """Catálogo general de personal, independiente de los eventos."""
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=30, blank=True)
    puesto_habitual = models.ForeignKey(
        Puesto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='empleados',
        verbose_name='Puesto habitual',
        help_text='El que hace normalmente. En cada evento se puede pisar por otro.',
    )

    def __str__(self):
        return self.nombre


class PersonalEvento(models.Model):
    """Asignación de un empleado a un evento puntual."""
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='personal')
    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, related_name='eventos_trabajados')
    # PROTECT: acá el puesto es histórico de pagos. Borrar "Barman" del catálogo
    # no puede dejar sin etiqueta lo que ya se liquidó.
    puesto = models.ForeignKey(
        Puesto,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='asignaciones',
    )
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


PASO_CHOICES = [
    ('entrante', 'Entrante'),
    ('principal', 'Plato principal'),
    ('secundario', 'Plato secundario'),
    ('postre', 'Postre'),
]

# El orden de servicio no es el alfabético: se ordena por la posición en la lista.
ORDEN_DE_SERVICIO = models.Case(
    *[models.When(paso=clave, then=orden) for orden, (clave, _) in enumerate(PASO_CHOICES)],
    default=len(PASO_CHOICES),
)


def agrupar_por_paso(platos):
    """Los platos repartidos en los cuatro momentos de la comida.

    Devuelve SIEMPRE los cuatro, aunque estén vacíos: en el menú sirven de
    casilleros para cargar. La pantalla que no quiera los vacíos los filtra.
    """
    por_clave = {clave: [] for clave, _ in PASO_CHOICES}
    for plato in platos:
        por_clave.setdefault(plato.paso, []).append(plato)
    return [
        {'clave': clave, 'etiqueta': etiqueta, 'platos': por_clave[clave]}
        for clave, etiqueta in PASO_CHOICES
    ]


class Plato(models.Model):
    """Un paso de la comida con nombre propio y su lista de ingredientes.

    Igual que LineaReceta, tiene dos dueños posibles y nunca los dos a la vez:
    - colgado de un MENÚ: la receta base, la que se costea para poner precio.
    - colgado de un EVENTO: la copia heredada al asignarle ese menú.

    Son copias y no referencias a propósito (RN-18): si el evento apuntara al
    menú, cambiar la receta base en marzo cambiaría lo que se calculó para un
    evento de enero. El menú evoluciona; lo ya cargado no.
    """

    menu = models.ForeignKey(
        Menu, on_delete=models.CASCADE, null=True, blank=True, related_name='platos'
    )
    evento = models.ForeignKey(
        Evento, on_delete=models.CASCADE, null=True, blank=True, related_name='platos'
    )
    paso = models.CharField(max_length=12, choices=PASO_CHOICES)
    nombre = models.CharField(max_length=120, help_text='Ej. Tabla de fiambres, Bife con papas.')
    # Cuántos cubiertos de este plato salen. Solo tiene sentido en la copia del
    # EVENTO: en el menú el plato es una plantilla y no sabe para cuánta gente es.
    # Con esto una fiesta puede tener 80 porciones del menú adulto y 20 del
    # infantil sin que el cálculo de comida se mezcle (RN-23).
    porciones = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Para cuántas personas sale este plato. Lo completa la tarjeta.',
    )

    class Meta:
        ordering = [ORDEN_DE_SERVICIO, 'nombre']
        verbose_name = 'Plato'
        verbose_name_plural = 'Platos'
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(menu__isnull=False, evento__isnull=True)
                    | models.Q(menu__isnull=True, evento__isnull=False)
                ),
                name='plato_tiene_un_solo_dueno',
                violation_error_message='Un plato pertenece a un menú o a un evento, no a los dos.',
            ),
        ]

    def __str__(self):
        return f"{self.get_paso_display()}: {self.nombre}"

    @property
    def costo_por_persona(self):
        return sum(linea.costo_por_persona for linea in self.lineas.all())

    def para(self, asistentes=None):
        """Los ingredientes de este plato, calculados para su cantidad de gente.

        Manda `porciones`, que es lo que dejó la tarjeta al copiar la receta. El
        argumento es el respaldo para los platos que no lo tienen: los del menú
        (que son plantilla) y los de eventos anteriores a las tarjetas.
        """
        cubiertos = self.porciones if self.porciones is not None else (asistentes or 0)
        return [
            {
                'producto': linea.producto,
                'por_persona': linea.cantidad_por_persona,
                'cantidad': linea.cantidad_para(cubiertos),
            }
            for linea in self.lineas.select_related('producto')
        ]


class LineaReceta(models.Model):
    """Cuánto de un producto lleva un plato, por persona.

    El cálculo es siempre por cubierto (200 g de carne por persona) y se
    multiplica por los asistentes al momento de mostrarlo. Nunca al revés: si se
    guardara el total, cambiar la cantidad de gente dejaría la receta mintiendo.
    """

    plato = models.ForeignKey(Plato, on_delete=models.CASCADE, related_name='lineas')
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name='en_recetas')
    cantidad_por_persona = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        validators=[MinValueValidator(0)],
        verbose_name='Cantidad por persona',
        help_text='Ej. 0,200 para 200 g de carne por cubierto.',
    )

    class Meta:
        ordering = ['producto__nombre']
        verbose_name = 'Ingrediente'
        verbose_name_plural = 'Ingredientes'

    def __str__(self):
        return f"{self.producto.nombre} x{self.cantidad_por_persona} por persona ({self.plato})"

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


class TarjetaEvento(models.Model):
    """Lo que paga cada tipo de invitado: cantidad × valor (RN-23).

    No es un precio único por persona porque una misma fiesta tiene tarjetas
    distintas: 80 adultos a un precio y 20 menús infantiles a otro. Cada una puede
    apuntar a su propio menú, y de ahí sale cuánta comida hace falta de cada cosa.
    """

    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='tarjetas')
    concepto = models.CharField(max_length=120, help_text='Ej. Adultos, Menú infantil, Músicos.')
    cantidad = models.PositiveIntegerField(default=0, verbose_name='Cantidad de tarjetas')
    valor_unitario = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Valor de la tarjeta',
    )
    # SET_NULL y no PROTECT: si se borra un menú del catálogo, la tarjeta sigue
    # valiendo plata. Lo que se pierde es la sugerencia de comida, no la facturación.
    menu = models.ForeignKey(
        Menu,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tarjetas',
        help_text='Qué come este grupo. Si lo cargás, la receta se calcula para esta cantidad.',
    )

    class Meta:
        ordering = ['-cantidad', 'concepto']
        verbose_name = 'Tarjeta'
        verbose_name_plural = 'Tarjetas'

    def __str__(self):
        return f"{self.concepto} x{self.cantidad} - {self.evento.nombre}"

    @property
    def subtotal(self):
        return self.cantidad * self.valor_unitario

    def clean(self):
        super().clean()
        # RN-16: mismo criterio que el consumo, el personal y los cargos.
        if self.evento_id and self.evento.cerrado:
            raise ValidationError(
                f'"{self.evento.nombre}" ya está finalizado. Si necesitás corregirlo, '
                'reabrilo primero desde el detalle del evento.'
            )


@receiver(post_save, sender=TarjetaEvento)
@receiver(post_delete, sender=TarjetaEvento)
def recalcular_receta_al_tocar_una_tarjeta(sender, instance, **kwargs):
    """Tocar una tarjeta cambia cuánta comida hace falta, así que se recopia.

    Sin esto, agregar "20 menús infantiles" sumaría la plata pero la receta
    seguiría calculando 80 raciones de adulto, y nadie lo notaría hasta que falte
    la comida.

    Va como señal y no sobrescribiendo `save()`/`delete()` por la trampa que este
    proyecto ya se comió con `MovimientoStock`: `queryset.delete()` NO pasa por
    `Model.delete()`, así que borrar tarjetas en masa (desde el admin o el shell)
    dejaba la receta con los platos de un grupo que ya no existía. Las señales sí
    se emiten en todos esos caminos.
    """
    # Si el evento se está borrando, sus tarjetas caen por cascada: no hay nada
    # que recalcular y `instance.evento` ya no existe.
    if not Evento.objects.filter(pk=instance.evento_id).exists():
        return
    instance.evento.copiar_receta_del_menu()


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
