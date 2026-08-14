"""Llena la base con dos meses de uso, como si el salon la viniera usando.

    python manage.py poblar_demo              # muestra que haria, sin tocar nada
    python manage.py poblar_demo --confirmar  # BORRA todo y lo genera

Sirve para ver las pantallas con volumen real: el calendario lleno, el historial
de movimientos con cientos de renglones, eventos con su rentabilidad calculada.
Con cinco productos y tres eventos no se ve nada de eso.

Los datos salen de un `random` con semilla fija, asi que dos corridas dan
exactamente lo mismo. Sin eso no se puede reproducir un bug que aparezca ac�.

OJO: --confirmar BORRA todos los datos del sistema (menos los usuarios). Hace
falta backup si hay algo que valga la pena.
"""

import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from stock.models import (
    CargoEvento, DestinatarioAviso, Empleado, Evento, LineaReceta, Menu,
    MovimientoStock, Paquete, PersonalEvento, Plato, Producto, Puesto,
    TarjetaEvento, UnidadMedida,
)

SEMILLA = 1975

# (nombre, sector, unidad, precio, stock que conviene tener en deposito)
PRODUCTOS = [
    # --- Barra -----------------------------------------------------------
    ('Fernet Branca 750ml', 'barra', 'Unidad', 14500, 40),
    ('Coca-Cola 1.5L', 'barra', 'Unidad', 2800, 120),
    ('Sprite 1.5L', 'barra', 'Unidad', 2700, 60),
    ('Agua mineral 1.5L', 'barra', 'Unidad', 1900, 100),
    ('Soda 2L', 'barra', 'Unidad', 1600, 80),
    ('Vino tinto Malbec', 'barra', 'Unidad', 8900, 90),
    ('Vino blanco Chardonnay', 'barra', 'Unidad', 8200, 50),
    ('Champagne extra brut', 'barra', 'Unidad', 16800, 70),
    ('Cerveza rubia litro', 'barra', 'Unidad', 3400, 100),
    ('Gin London Dry', 'barra', 'Unidad', 19500, 20),
    ('Vodka', 'barra', 'Unidad', 15200, 18),
    ('Whisky 8 anios', 'barra', 'Unidad', 28000, 12),
    ('Agua tonica', 'barra', 'Unidad', 2100, 60),
    ('Jugo de naranja 1L', 'barra', 'Litros', 3200, 40),
    ('Hielo', 'barra', 'Kilogramos', 900, 200),
    ('Energizante 500ml', 'barra', 'Unidad', 3600, 48),
    # --- Cocina ----------------------------------------------------------
    ('Bife de chorizo', 'cocina', 'Kilogramos', 18500, 120),
    ('Lomo', 'cocina', 'Kilogramos', 24000, 60),
    ('Pechuga de pollo', 'cocina', 'Kilogramos', 8900, 90),
    ('Bondiola de cerdo', 'cocina', 'Kilogramos', 12500, 40),
    ('Papa', 'cocina', 'Kilogramos', 1400, 250),
    ('Cebolla', 'cocina', 'Kilogramos', 1600, 80),
    ('Tomate', 'cocina', 'Kilogramos', 2900, 60),
    ('Lechuga', 'cocina', 'Kilogramos', 2400, 40),
    ('Zanahoria', 'cocina', 'Kilogramos', 1500, 50),
    ('Queso cremoso', 'cocina', 'Kilogramos', 11800, 45),
    ('Jamon cocido', 'cocina', 'Kilogramos', 13200, 35),
    ('Arroz', 'cocina', 'Kilogramos', 2200, 60),
    ('Fideos', 'cocina', 'Kilogramos', 2600, 40),
    ('Crema de leche', 'cocina', 'Litros', 4800, 50),
    ('Manteca', 'cocina', 'Kilogramos', 9500, 25),
    ('Huevos', 'cocina', 'Unidad', 280, 360),
    ('Harina 000', 'cocina', 'Kilogramos', 1300, 80),
    ('Azucar', 'cocina', 'Kilogramos', 1700, 50),
    ('Aceite de girasol', 'cocina', 'Litros', 3900, 60),
    ('Helado', 'cocina', 'Kilogramos', 8600, 70),
    ('Frutillas', 'cocina', 'Kilogramos', 6800, 30),
    ('Chocolate cobertura', 'cocina', 'Kilogramos', 15400, 20),
    ('Langostinos', 'cocina', 'Kilogramos', 28000, 25),
    ('Pan de mesa', 'cocina', 'Unidad', 950, 200),
    # --- Extras ----------------------------------------------------------
    ('Servilletas de papel', 'extras', 'Cajas', 4200, 30),
    ('Velas de torta', 'extras', 'Unidad', 850, 60),
    ('Sorbetes', 'extras', 'Cajas', 2600, 25),
    ('Bengalas frias', 'extras', 'Unidad', 1800, 80),
    ('Vasos descartables', 'extras', 'Cajas', 5400, 20),
    ('Globos', 'extras', 'Cajas', 3100, 15),
    # --- Limpieza --------------------------------------------------------
    ('Lavandina 5L', 'limpieza', 'Litros', 3800, 30),
    ('Detergente 5L', 'limpieza', 'Litros', 6200, 20),
    ('Bolsas de residuo 60x90', 'limpieza', 'Cajas', 4900, 25),
    ('Papel higienico', 'limpieza', 'Cajas', 7200, 18),
    ('Desodorante de ambiente', 'limpieza', 'Unidad', 2900, 24),
    ('Trapos de piso', 'limpieza', 'Unidad', 1800, 20),
    # --- Mobiliario (se cuenta, no se valoriza: RN-8) ---------------------
    ('Mantel redondo blanco', 'mobiliario', 'Unidad', None, 60),
    ('Servilleta de tela', 'mobiliario', 'Unidad', None, 400),
    ('Plato playo', 'mobiliario', 'Unidad', None, 350),
    ('Plato postre', 'mobiliario', 'Unidad', None, 350),
    ('Copa de agua', 'mobiliario', 'Unidad', None, 400),
    ('Copa de vino', 'mobiliario', 'Unidad', None, 400),
    ('Cubiertos (juego)', 'mobiliario', 'Unidad', None, 350),
    ('Silla Tiffany', 'mobiliario', 'Unidad', None, 300),
]

EMPLEADOS = [
    ('Rosa Gimenez', 'Mozo'), ('Carlos Peralta', 'Mozo'),
    ('Marina Lopez', 'Mozo'), ('Diego Sosa', 'Mozo'),
    ('Julieta Ferrari', 'Mozo'), ('Nicolas Aguirre', 'Mozo'),
    ('Martin Quiroga', 'Barman'), ('Sofia Cabrera', 'Barman'),
    ('Hector Villalba', 'Cocina'), ('Ana Maria Rios', 'Cocina'),
    ('Lucas Benitez', 'Cocina'), ('Ramiro Ledesma', 'Dj'),
    ('Gabriela Ponce', 'Limpieza'), ('Silvia Ocampo', 'Limpieza'),
    ('Oscar Maidana', 'Seguridad'), ('Walter Ibarra', 'Seguridad'),
]

# menu -> [(paso, plato, [(producto, cantidad por persona)])]
MENUS = {
    'Clasico Adulto': [
        ('entrante', 'Tabla de fiambres', [
            ('Jamon cocido', '0.060'), ('Queso cremoso', '0.060'), ('Pan de mesa', '0.500'),
        ]),
        ('principal', 'Bife de chorizo con papas', [
            ('Bife de chorizo', '0.280'), ('Papa', '0.250'), ('Aceite de girasol', '0.020'),
        ]),
        ('secundario', 'Ensalada mixta', [
            ('Lechuga', '0.060'), ('Tomate', '0.070'), ('Cebolla', '0.030'),
        ]),
        ('postre', 'Helado con frutillas', [
            ('Helado', '0.150'), ('Frutillas', '0.050'),
        ]),
    ],
    'Premium': [
        ('entrante', 'Langostinos al ajillo', [
            ('Langostinos', '0.120'), ('Manteca', '0.020'), ('Pan de mesa', '0.500'),
        ]),
        ('principal', 'Lomo al malbec', [
            ('Lomo', '0.300'), ('Vino tinto Malbec', '0.080'), ('Papa', '0.200'),
        ]),
        ('secundario', 'Papas gratinadas', [
            ('Papa', '0.150'), ('Crema de leche', '0.050'), ('Queso cremoso', '0.040'),
        ]),
        ('postre', 'Volcan de chocolate', [
            ('Chocolate cobertura', '0.080'), ('Huevos', '1'), ('Harina 000', '0.040'),
            ('Manteca', '0.030'),
        ]),
    ],
    'Infantil': [
        ('principal', 'Nuggets con papas fritas', [
            ('Pechuga de pollo', '0.150'), ('Papa', '0.200'), ('Aceite de girasol', '0.030'),
        ]),
        ('postre', 'Helado', [('Helado', '0.120')]),
    ],
    'Vegetariano': [
        ('entrante', 'Bruschettas', [
            ('Pan de mesa', '0.400'), ('Tomate', '0.080'), ('Queso cremoso', '0.050'),
        ]),
        ('principal', 'Risotto de hongos', [
            ('Arroz', '0.120'), ('Crema de leche', '0.060'), ('Queso cremoso', '0.050'),
            ('Cebolla', '0.040'),
        ]),
        ('postre', 'Ensalada de frutas', [('Frutillas', '0.120'), ('Azucar', '0.020')]),
    ],
}

PAQUETES = [
    ('Basico', 'Salon, mesas, sillas y sonido.', 850000),
    ('Completo', 'Salon, ambientacion, DJ y barra basica.', 1450000),
    ('Premium', 'Todo incluido, con barra libre y pantalla LED.', 2350000),
]

# (tipo de fiesta, min invitados, max invitados, menu principal, lleva infantil)
TIPOS_DE_EVENTO = [
    ('Casamiento', 120, 220, 'Clasico Adulto', True),
    ('Casamiento', 100, 180, 'Premium', True),
    ('Fiesta de 15', 100, 190, 'Clasico Adulto', True),
    ('Cumpleanios', 45, 90, 'Clasico Adulto', False),
    ('Bautismo', 40, 80, 'Clasico Adulto', True),
    ('Aniversario', 50, 100, 'Premium', False),
    ('Evento corporativo', 35, 70, 'Premium', False),
    ('Despedida', 40, 75, 'Clasico Adulto', False),
]

APELLIDOS = [
    'Fernandez', 'Rodriguez', 'Gomez', 'Lopez', 'Martinez', 'Perez', 'Sanchez',
    'Romero', 'Sosa', 'Torres', 'Ruiz', 'Ramirez', 'Flores', 'Acosta', 'Benitez',
    'Medina', 'Suarez', 'Herrera', 'Aguirre', 'Pereyra', 'Gutierrez', 'Molina',
    'Silva', 'Castro', 'Ortiz', 'Nunez', 'Luna', 'Juarez', 'Cabrera', 'Rios',
]

NOTAS = [
    'Llegan a las 21. La entrada por el porton de atras.',
    'La torta la trae la familia, hay que dejar lugar en la heladera.',
    'Piden que el DJ arranque despues del brindis.',
    'Dos invitados celiacos: avisar a cocina.',
    'Van a poner alfombra roja en la entrada, llegan a las 18 a armar.',
    'El padre de la novia pidio que las mesas queden numeradas.',
    'Sacan fotos antes, el salon tiene que estar listo 19:30.',
    'Traen su propio fotografo y drone.',
    'Barra libre hasta las 3. Despues solo agua y gaseosa.',
    'Pidieron mantel negro en la mesa principal.',
    '',
    '',
]

CARGOS = [
    ('Barra libre', 180000, 420000),
    ('DJ', 150000, 300000),
    ('Hora extra', 90000, 200000),
    ('Pantalla LED', 120000, 250000),
    ('Servicio de fotografia', 200000, 380000),
    ('Ambientacion especial', 100000, 260000),
]


class Command(BaseCommand):
    help = 'Llena la base con dos meses de uso realista (BORRA lo que haya).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirmar', action='store_true',
            help='Borra TODOS los datos del sistema y los genera de nuevo.',
        )
        parser.add_argument(
            '--semilla', type=int, default=SEMILLA,
            help='Cambiala para obtener otro juego de datos igual de coherente.',
        )

    def handle(self, *args, **opciones):
        if not opciones['confirmar']:
            self.stdout.write(self.style.WARNING(
                'Esto BORRA todos los datos del sistema (menos los usuarios) y los\n'
                'reemplaza por dos meses de uso inventado.\n\n'
                'Hace backup primero:\n'
                '    cp db.sqlite3 db.sqlite3.backup-antes-demo\n\n'
                'Y despues corrre:\n'
                '    python manage.py poblar_demo --confirmar'
            ))
            return

        self.azar = random.Random(opciones['semilla'])
        hoy = timezone.localdate()

        with transaction.atomic():
            self._limpiar()
            unidades = self._unidades()
            puestos = self._puestos()
            productos = self._productos(unidades)
            empleados = self._empleados(puestos)
            paquetes = self._paquetes()
            menus = self._menus(productos)
            self._destinatarios()
            eventos = self._eventos(hoy, paquetes, menus)
            self._historia(hoy, productos, eventos, empleados, puestos)
            self._normalizar_ceros()

        self._resumen(hoy)

    # -- catalogos ---------------------------------------------------------

    def _limpiar(self):
        """Los usuarios NO se tocan: si no, te quedas afuera del sistema."""
        for modelo in [MovimientoStock, PersonalEvento, CargoEvento, TarjetaEvento,
                       LineaReceta, Plato, Evento, Empleado, Menu, Paquete,
                       Producto, Puesto, UnidadMedida, DestinatarioAviso]:
            modelo.objects.all().delete()

    def _unidades(self):
        nombres = ['Cajas', 'Kilogramos', 'Litros', 'Unidad']
        return {n: UnidadMedida.objects.create(nombre=n) for n in nombres}

    def _puestos(self):
        nombres = ['Mozo', 'Barman', 'Cocina', 'Dj', 'Limpieza', 'Seguridad', 'Otro']
        return {n: Puesto.objects.create(nombre=n) for n in nombres}

    def _productos(self, unidades):
        productos = {}
        for nombre, sector, unidad, precio, _ in PRODUCTOS:
            productos[nombre] = Producto.objects.create(
                nombre=nombre,
                sector=sector,
                precio_unitario=Decimal(precio) if precio is not None else None,
                stock_actual=0,          # lo va a levantar la primera compra
                unidad_medida=unidades[unidad],
            )
        return productos

    def _empleados(self, puestos):
        return [
            Empleado.objects.create(
                nombre=nombre,
                telefono=f'351 {self.azar.randint(200, 799)}-{self.azar.randint(1000, 9999)}',
                puesto_habitual=puestos[puesto],
            )
            for nombre, puesto in EMPLEADOS
        ]

    def _paquetes(self):
        return [
            Paquete.objects.create(nombre=n, descripcion=d, precio=Decimal(p))
            for n, d, p in PAQUETES
        ]

    def _menus(self, productos):
        menus = {}
        for nombre, platos in MENUS.items():
            menu = Menu.objects.create(
                nombre=nombre,
                descripcion=f'{len(platos)} pasos. Se cobra por cubierto.',
            )
            for paso, plato_nombre, ingredientes in platos:
                plato = Plato.objects.create(menu=menu, paso=paso, nombre=plato_nombre)
                LineaReceta.objects.bulk_create([
                    LineaReceta(
                        plato=plato,
                        producto=productos[prod],
                        cantidad_por_persona=Decimal(cant),
                    )
                    for prod, cant in ingredientes
                ])
            menus[nombre] = menu
        return menus

    def _destinatarios(self):
        DestinatarioAviso.objects.create(nombre='Duenio', email='duenio@salonvictoria.com.ar')
        DestinatarioAviso.objects.create(nombre='Coordinadora', email='eventos@salonvictoria.com.ar')
        DestinatarioAviso.objects.create(
            nombre='Cocina', email='cocina@salonvictoria.com.ar', activo=False,
        )

    # -- eventos -----------------------------------------------------------

    def _eventos(self, hoy, paquetes, menus):
        """Dos meses para atras y tres semanas para adelante.

        Un salon trabaja los fines de semana: los eventos caen viernes, sabado y
        domingo. Los que ya pasaron van finalizados; los que vienen, confirmados
        o pendientes segun cuanto falte.
        """
        eventos = []
        dia = hoy - timedelta(days=60)
        fin = hoy + timedelta(days=21)

        while dia <= fin:
            if dia.weekday() not in (4, 5, 6):          # viernes, sabado, domingo
                dia += timedelta(days=1)
                continue
            # El sabado casi siempre hay fiesta; viernes y domingo, a veces.
            probabilidad = 0.9 if dia.weekday() == 5 else 0.45
            if self.azar.random() > probabilidad:
                dia += timedelta(days=1)
                continue

            tipo, minimo, maximo, menu_nombre, lleva_infantil = self.azar.choice(TIPOS_DE_EVENTO)
            asistentes = self.azar.randint(minimo, maximo)
            apellido = self.azar.choice(APELLIDOS)

            if dia < hoy:
                estado = 'finalizado'
            elif (dia - hoy).days <= 10:
                estado = 'confirmado'
            else:
                estado = self.azar.choice(['confirmado', 'pendiente'])

            paquete = self.azar.choice(paquetes + [None])
            evento = Evento.objects.create(
                nombre=f'{tipo} {apellido}',
                fecha=dia,
                asistentes=asistentes,
                estado='confirmado',       # se cierra al final, para poder cargarle cosas
                paquete=paquete,
                telefono_contacto=f'351 {self.azar.randint(200, 799)}-{self.azar.randint(1000, 9999)}',
                notas=self.azar.choice(NOTAS),
            )

            self._tarjetas(evento, asistentes, menus, menu_nombre, lleva_infantil)

            # El brindis no siempre es para todos.
            if self.azar.random() < 0.7:
                evento.brindis_asistentes = int(asistentes * self.azar.uniform(0.6, 1.0))
                evento.brindis_valor = Decimal(self.azar.randrange(4000, 9000, 500))
                evento.save()

            for _ in range(self.azar.randint(0, 3)):
                concepto, minimo_cargo, maximo_cargo = self.azar.choice(CARGOS)
                if not evento.cargos.filter(concepto=concepto).exists():
                    CargoEvento.objects.create(
                        evento=evento,
                        concepto=concepto,
                        monto=Decimal(self.azar.randrange(minimo_cargo, maximo_cargo, 10000)),
                    )

            eventos.append((evento, estado))
            dia += timedelta(days=1)

        return eventos

    def _tarjetas(self, evento, asistentes, menus, menu_nombre, lleva_infantil):
        """Lo que paga cada tipo de invitado (RN-23).

        Las cantidades tienen que cerrar con los asistentes: si no, el aviso de
        `tarjetas_vs_asistentes` salta en todos los eventos y deja de significar
        algo. Se reparte adultos / infantil / vegetariano sobre el mismo total.
        """
        valor_adulto = Decimal(self.azar.randrange(38000, 75000, 1000))
        restantes = asistentes

        if lleva_infantil and asistentes >= 60 and self.azar.random() < 0.75:
            chicos = self.azar.randint(8, max(9, int(asistentes * 0.18)))
            chicos = min(chicos, restantes - 10)
            TarjetaEvento.objects.create(
                evento=evento, concepto='Menu infantil', cantidad=chicos,
                valor_unitario=(valor_adulto * Decimal('0.55')).quantize(Decimal('1')),
                menu=menus['Infantil'],
            )
            restantes -= chicos

        if self.azar.random() < 0.35 and restantes > 20:
            veggies = self.azar.randint(3, 12)
            TarjetaEvento.objects.create(
                evento=evento, concepto='Vegetariano', cantidad=veggies,
                valor_unitario=valor_adulto, menu=menus['Vegetariano'],
            )
            restantes -= veggies

        # El personal del cliente (fotografo, DJ, banda) come pero no paga entrada.
        if self.azar.random() < 0.4 and restantes > 30:
            servicio = self.azar.randint(2, 6)
            TarjetaEvento.objects.create(
                evento=evento, concepto='Personal del cliente', cantidad=servicio,
                valor_unitario=(valor_adulto * Decimal('0.4')).quantize(Decimal('1')),
                menu=menus[menu_nombre],
            )
            restantes -= servicio

        TarjetaEvento.objects.create(
            evento=evento, concepto='Adultos', cantidad=restantes,
            valor_unitario=valor_adulto, menu=menus[menu_nombre],
        )

    # -- el libro mayor ----------------------------------------------------

    def _historia(self, hoy, productos, eventos, empleados, puestos):
        """Compras semanales, consumo por evento, mermas y personal.

        El orden importa: primero la carga inicial del deposito, despues cada
        semana su reposicion, y el consumo de cada evento el dia que se hizo. Al
        final se le pone la fecha real a cada movimiento, porque `fecha` es
        auto_now_add y no se puede pasar en create().
        """
        arranque = hoy - timedelta(days=62)

        # Carga inicial: el deposito el dia que arrancaron a usar el sistema.
        for nombre, _, _, _, stock in PRODUCTOS:
            self._movimiento(productos[nombre], 'entrada', Decimal(stock), arranque)

        # Reposicion: todos los martes se compra lo que falta para el finde.
        dia = arranque + timedelta(days=(1 - arranque.weekday()) % 7)
        while dia < hoy:
            for nombre, _, _, precio, stock in PRODUCTOS:
                if precio is None and self.azar.random() < 0.7:
                    continue                      # el mobiliario casi no se repone
                if self.azar.random() < 0.35:
                    continue                      # no se compra todo todas las semanas
                # Se repone por arriba del stock objetivo: la barra de un salon
                # se compra de más, no de menos. Con el rango pegado al objetivo,
                # el vino y el champagne (que ademas van en las recetas) se
                # consumian mas rapido de lo que entraban y quedaban en cero.
                cantidad = Decimal(self.azar.randint(int(stock * 0.6) or 1, int(stock * 1.6) or 2))
                self._movimiento(productos[nombre], 'entrada', cantidad, dia)
            dia += timedelta(days=7)

        # Lo que salio en cada fiesta.
        for evento, estado_final in eventos:
            if evento.fecha >= hoy:
                continue                          # todavia no paso: no consumio nada

            for item in evento.consumo_sugerido:
                producto = item['producto']
                # Nunca sale exactamente lo que dice la receta.
                real = (item['cantidad'] * Decimal(str(self.azar.uniform(0.85, 1.12)))
                        ).quantize(Decimal('0.01'))
                if real <= 0:
                    continue
                self._movimiento(producto, 'salida', real, evento.fecha, evento=evento)

            # Barra y descartables, que no estan en ninguna receta.
            for nombre in ['Coca-Cola 1.5L', 'Agua mineral 1.5L', 'Cerveza rubia litro',
                           'Vino tinto Malbec', 'Champagne extra brut', 'Hielo',
                           'Servilletas de papel', 'Mantel redondo blanco', 'Copa de vino']:
                producto = productos[nombre]
                por_persona = Decimal(str(self.azar.uniform(0.15, 0.85)))
                cantidad = (por_persona * evento.asistentes).quantize(Decimal('0.01'))
                if cantidad > 0:
                    self._movimiento(producto, 'salida', cantidad, evento.fecha, evento=evento)

            # Personal de esa noche: escala con el tamanio de la fiesta.
            mozos = max(2, evento.asistentes // 25)
            plantel = [('Mozo', mozos), ('Barman', 1 if evento.asistentes < 120 else 2),
                       ('Cocina', 2 if evento.asistentes < 120 else 3),
                       ('Limpieza', 1), ('Seguridad', 1 if evento.asistentes > 90 else 0)]
            usados = set()
            for puesto_nombre, cuantos in plantel:
                candidatos = [e for e in empleados
                              if e.puesto_habitual and e.puesto_habitual.nombre == puesto_nombre]
                otros = [e for e in empleados if e not in candidatos]
                for _ in range(cuantos):
                    disponibles = [e for e in candidatos + otros if e.pk not in usados]
                    if not disponibles:
                        break
                    empleado = self.azar.choice(disponibles)
                    usados.add(empleado.pk)
                    horas = Decimal(self.azar.choice([6, 7, 8, 8, 9, 10]))
                    PersonalEvento.objects.create(
                        evento=evento, empleado=empleado, puesto=puestos[puesto_nombre],
                        horas_trabajadas=horas,
                        pago=Decimal(self.azar.randrange(35000, 75000, 2500)),
                    )

        # Roturas y vencimientos, repartidos en los dos meses.
        rompibles = [n for n, s, _, _, _ in PRODUCTOS if s in ('barra', 'mobiliario', 'cocina')]
        for _ in range(28):
            nombre = self.azar.choice(rompibles)
            cuando = arranque + timedelta(days=self.azar.randint(1, 60))
            self._movimiento(
                productos[nombre], 'merma',
                Decimal(self.azar.randint(1, 6)), cuando,
                motivo=self.azar.choice(['rotura', 'vencimiento', 'consumo_interno', 'otro']),
            )

        # Recien ahora se cierran: con el estado puesto antes, RN-16 habria
        # bloqueado toda la carga de consumo y de personal.
        for evento, estado_final in eventos:
            if estado_final != evento.estado:
                evento.estado = estado_final
                evento.save(update_fields=['estado'])

    def _normalizar_ceros(self):
        """Un producto que se consumio entero queda en `-0.00`, no en `0.00`.

        Sale de restar con F() dos decimales iguales: matematicamente es cero,
        pero SQLite se guarda el signo y la pantalla muestra "-0.00", que parece
        stock negativo. Es cosmetico, pero justo en la columna donde uno mira si
        falta algo.
        """
        for producto in Producto.objects.filter(stock_actual__lte=0):
            Producto.objects.filter(pk=producto.pk).update(stock_actual=Decimal('0'))

    def _movimiento(self, producto, tipo, cantidad, cuando, evento=None, motivo=''):
        """Un asiento del libro mayor, con su fecha de verdad.

        `MovimientoStock.fecha` es auto_now_add, asi que create() la pisa con
        ahora: se corrige con un update() despues, que no vuelve a pasar por
        save() y por lo tanto no toca el stock de nuevo (RN-1).

        Una salida mayor al stock disponible se recorta en vez de romper: es
        exactamente lo que clean() impide, y aca no hay formulario que avise.

        El refresh va ANTES de comparar y no solo despues de crear: los productos
        llegan por distintos caminos (el dict de catalogo, y `consumo_sugerido`,
        que arma instancias nuevas), asi que el `stock_actual` que trae el objeto
        puede ser de varios movimientos atras. Comparar contra eso dejaba stock
        negativo, que es justo lo que RN-2 no permite.
        """
        producto.refresh_from_db()
        if tipo in ('salida', 'merma') and cantidad > producto.stock_actual:
            cantidad = producto.stock_actual
        if cantidad <= 0:
            return None

        movimiento = MovimientoStock.objects.create(
            producto=producto, evento=evento, tipo=tipo,
            cantidad=cantidad, motivo=motivo,
        )
        MovimientoStock.objects.filter(pk=movimiento.pk).update(
            fecha=timezone.make_aware(datetime.combine(
                cuando, time(self.azar.randint(9, 23), self.azar.randint(0, 59))
            ))
        )
        producto.refresh_from_db()
        return movimiento

    # -- salida por pantalla -----------------------------------------------

    def _resumen(self, hoy):
        finalizados = Evento.objects.filter(estado='finalizado')
        margen = sum(e.margen for e in finalizados)
        facturado = sum(e.ingreso_total for e in finalizados)

        self.stdout.write(self.style.SUCCESS('\nListo. Dos meses de uso cargados.\n'))
        filas = [
            ('Productos', Producto.objects.count()),
            ('Unidades de medida', UnidadMedida.objects.count()),
            ('Puestos', Puesto.objects.count()),
            ('Empleados', Empleado.objects.count()),
            ('Menus (con receta)', Menu.objects.count()),
            ('Platos', Plato.objects.count()),
            ('Lineas de receta', LineaReceta.objects.count()),
            ('Paquetes', Paquete.objects.count()),
            ('Eventos', Evento.objects.count()),
            ('  finalizados', finalizados.count()),
            ('  por venir', Evento.objects.filter(fecha__gte=hoy).count()),
            ('Tarjetas', TarjetaEvento.objects.count()),
            ('Cargos', CargoEvento.objects.count()),
            ('Personal asignado', PersonalEvento.objects.count()),
            ('Movimientos de stock', MovimientoStock.objects.count()),
            ('  entradas', MovimientoStock.objects.filter(tipo='entrada').count()),
            ('  salidas', MovimientoStock.objects.filter(tipo='salida').count()),
            ('  mermas', MovimientoStock.objects.filter(tipo='merma').count()),
        ]
        for etiqueta, valor in filas:
            self.stdout.write(f'  {etiqueta:<24} {valor:>7}')

        self.stdout.write('')
        self.stdout.write(f'  Facturado (finalizados)  $ {facturado:>14,.2f}')
        self.stdout.write(f'  Ganancia                 $ {margen:>14,.2f}')
