"""Tests de caracterizacion del comportamiento actual del stock.

Escritos ANTES del rediseno para tener red de seguridad: documentan como
deberia comportarse el sistema. Los que estan marcados como bug fallan hoy
a proposito y tienen que pasar cuando se apliquen los arreglos.
"""

from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import (
    CargoEvento,
    DestinatarioAviso,
    Empleado,
    Evento,
    LineaReceta,
    Menu,
    MovimientoStock,
    PersonalEvento,
    Paquete,
    Plato,
    Producto,
    Puesto,
    TarjetaEvento,
    UnidadMedida,
)


def un_puesto(nombre='Mozo'):
    """El puesto ya no es texto libre: es una fila del catalogo (Puesto)."""
    return Puesto.objects.get_or_create(nombre=nombre)[0]


def una_unidad(nombre='Unidad'):
    """Misma historia que un_puesto(): la unidad es catalogo, no texto (RN-26)."""
    return UnidadMedida.objects.get_or_create(nombre=nombre)[0]


def una_receta(dueno, producto, cantidad, paso='principal', nombre='Plato'):
    """Un plato de un solo ingrediente, que es lo que la mayoria de los tests necesita."""
    plato = Plato.objects.create(paso=paso, nombre=nombre, **dueno)
    LineaReceta.objects.create(plato=plato, producto=producto, cantidad_por_persona=cantidad)
    return plato


class ClienteLogueadoTests(TestCase):
    """Base para los tests que navegan: el sistema entero pide sesión.

    El tester es ADMINISTRADOR (`is_staff`) porque estos tests recorren todo el
    sistema, que es justo lo que el empleado no puede hacer (RN-25). Lo que ve y
    lo que no ve un empleado se prueba aparte, en RolEmpleadoTests.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_user('tester', password='tester-1234', is_staff=True))


class StockAritmeticaTests(TestCase):
    """La aritmetica del stock: lo unico que no puede fallar nunca."""

    def setUp(self):
        self.producto = Producto.objects.create(
            nombre='Fernet', sector='barra', precio_unitario=10, stock_actual=100
        )
        self.evento = Evento.objects.create(nombre='Casamiento', fecha=date(2026, 8, 15))

    def test_salida_descuenta_del_stock(self):
        MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=10
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 90)

    def test_entrada_suma_al_stock(self):
        MovimientoStock.objects.create(producto=self.producto, tipo='entrada', cantidad=25)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 125)

    def test_borrar_un_movimiento_revierte_su_efecto(self):
        movimiento = MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=10
        )
        movimiento.delete()
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 100)

    def test_editar_la_cantidad_de_una_salida_recalcula_bien_el_stock(self):
        """BUG CONOCIDO (models.py save): hoy da 86 en vez de 96.

        save() revierte usando anterior.producto (instancia fresca de la DB) y
        despues aplica usando self.producto (instancia cargada ANTES de esa
        reversion). La segunda escritura pisa a la primera.
        """
        movimiento = MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=10
        )
        movimiento.cantidad = 4
        movimiento.save()
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 96)

    def test_editar_cambiando_de_producto_mueve_el_stock_correcto(self):
        """El movimiento cambia de producto: cada uno tiene que quedar bien."""
        otro = Producto.objects.create(
            nombre='Gancia', sector='barra', precio_unitario=8, stock_actual=50
        )
        movimiento = MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=10
        )
        movimiento.producto = otro
        movimiento.save()

        self.producto.refresh_from_db()
        otro.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 100, 'el producto original tiene que recuperar su stock')
        self.assertEqual(otro.stock_actual, 40, 'el producto nuevo tiene que absorber la salida')


class StockValidacionTests(TestCase):
    """RN-2: no se puede consumir mas stock del que hay."""

    def setUp(self):
        self.producto = Producto.objects.create(
            nombre='Whisky', sector='barra', precio_unitario=100, stock_actual=5
        )
        self.evento = Evento.objects.create(nombre='Cumple 15', fecha=date(2026, 9, 1))

    def test_no_permite_sacar_mas_de_lo_disponible(self):
        movimiento = MovimientoStock(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=6
        )
        with self.assertRaises(ValidationError):
            movimiento.full_clean()

    def test_permite_sacar_exactamente_lo_disponible(self):
        movimiento = MovimientoStock(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=5
        )
        movimiento.full_clean()

    def test_la_entrada_no_tiene_tope(self):
        movimiento = MovimientoStock(producto=self.producto, tipo='entrada', cantidad=9999)
        movimiento.full_clean()


class GastoEventoTests(TestCase):
    """RN-6: como se compone el gasto de un evento."""

    def setUp(self):
        self.producto = Producto.objects.create(
            nombre='Vino', sector='barra', precio_unitario=1000, stock_actual=100
        )
        self.evento = Evento.objects.create(nombre='Aniversario', fecha=date(2026, 10, 5))
        self.empleado = Empleado.objects.create(nombre='Carlos')

    def test_gasto_stock_suma_las_salidas_del_evento(self):
        MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=3
        )
        self.assertEqual(self.evento.gasto_stock, 3000)

    def test_gasto_personal_suma_los_pagos(self):
        PersonalEvento.objects.create(
            evento=self.evento, empleado=self.empleado, puesto=un_puesto('Mozo'), pago=50000
        )
        self.assertEqual(self.evento.gasto_personal, 50000)

    def test_las_entradas_no_cuentan_como_gasto_del_evento(self):
        MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='entrada', cantidad=10
        )
        self.assertEqual(self.evento.gasto_stock, 0)

    def test_gasto_total_es_stock_mas_personal(self):
        MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=2
        )
        PersonalEvento.objects.create(
            evento=self.evento, empleado=self.empleado, puesto=un_puesto('Mozo'), pago=50000
        )
        self.assertEqual(self.evento.gasto_total, 52000)


class MermaTests(TestCase):
    """RN-12: la merma descuenta stock pero no es gasto de nadie."""

    def setUp(self):
        self.producto = Producto.objects.create(
            nombre='Champagne', sector='barra', precio_unitario=5000, stock_actual=20
        )
        self.evento = Evento.objects.create(nombre='Boda', fecha=date(2026, 12, 12))

    def test_la_merma_descuenta_del_stock(self):
        MovimientoStock.objects.create(
            producto=self.producto, tipo='merma', motivo='rotura', cantidad=3
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 17)

    def test_borrar_una_merma_devuelve_el_stock(self):
        merma = MovimientoStock.objects.create(
            producto=self.producto, tipo='merma', motivo='vencimiento', cantidad=3
        )
        merma.delete()
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 20)

    def test_la_merma_no_suma_al_gasto_del_evento(self):
        """Aunque quede colgada de un evento, no es plata que gasto el cliente."""
        MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=2
        )
        merma = MovimientoStock.objects.create(
            producto=self.producto, tipo='merma', motivo='rotura', cantidad=5
        )
        MovimientoStock.objects.filter(pk=merma.pk).update(evento=self.evento)

        self.assertEqual(self.evento.gasto_stock, 10000, 'solo tienen que contar las salidas')

    def test_la_merma_exige_motivo(self):
        merma = MovimientoStock(producto=self.producto, tipo='merma', cantidad=1)
        with self.assertRaises(ValidationError) as ctx:
            merma.full_clean()
        self.assertIn('motivo', ctx.exception.message_dict)

    def test_la_merma_no_puede_ir_atada_a_un_evento(self):
        merma = MovimientoStock(
            producto=self.producto, evento=self.evento, tipo='merma', motivo='rotura', cantidad=1
        )
        with self.assertRaises(ValidationError) as ctx:
            merma.full_clean()
        self.assertIn('evento', ctx.exception.message_dict)

    def test_el_motivo_es_solo_para_las_mermas(self):
        salida = MovimientoStock(
            producto=self.producto, evento=self.evento, tipo='salida', motivo='rotura', cantidad=1
        )
        with self.assertRaises(ValidationError) as ctx:
            salida.full_clean()
        self.assertIn('motivo', ctx.exception.message_dict)

    def test_no_se_puede_mermar_mas_de_lo_que_hay(self):
        merma = MovimientoStock(
            producto=self.producto, tipo='merma', motivo='vencimiento', cantidad=21
        )
        with self.assertRaises(ValidationError) as ctx:
            merma.full_clean()
        self.assertIn('cantidad', ctx.exception.message_dict)


class DecimalesTests(TestCase):
    """RN-13: hay productos que se miden en kilos y litros, no en unidades."""

    def setUp(self):
        self.producto = Producto.objects.create(
            nombre='Lomo', sector='cocina', precio_unitario=20000,
            stock_actual=Decimal('10.50'), unidad_medida=una_unidad('Kilogramos'),
        )
        self.evento = Evento.objects.create(nombre='Corporativo', fecha=date(2026, 7, 1))

    def test_una_salida_decimal_descuenta_decimales(self):
        MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=Decimal('2.25')
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal('8.25'))

    def test_el_gasto_usa_la_cantidad_decimal(self):
        MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=Decimal('0.75')
        )
        self.assertEqual(self.evento.gasto_stock, Decimal('15000.00'))

    def test_editar_una_salida_decimal_recalcula_bien(self):
        movimiento = MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=Decimal('2.50')
        )
        movimiento.cantidad = Decimal('1.25')
        movimiento.save()
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal('9.25'))


class CostoCongeladoTests(TestCase):
    """RN-15: el costo se sella en el movimiento, no se lee del precio de hoy."""

    def setUp(self):
        self.producto = Producto.objects.create(
            nombre='Champagne', sector='barra', precio_unitario=1000, stock_actual=100
        )
        self.evento = Evento.objects.create(nombre='Boda', fecha=date(2026, 3, 1))

    def test_el_movimiento_sella_el_costo_al_nacer(self):
        movimiento = MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=2
        )
        self.assertEqual(movimiento.costo_unitario, 1000)

    def test_cambiar_el_precio_no_mueve_el_gasto_de_un_evento_viejo(self):
        """El corazón de la Fase 2: sin esto, la inflación reescribe el pasado."""
        MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=2
        )
        self.assertEqual(self.evento.gasto_stock, 2000)

        self.producto.precio_unitario = 5000
        self.producto.save()

        self.assertEqual(self.evento.gasto_stock, 2000, 'el gasto histórico no se toca')

    def test_corregir_la_cantidad_no_revalua_al_precio_de_hoy(self):
        movimiento = MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=2
        )
        self.producto.precio_unitario = 5000
        self.producto.save()

        movimiento.cantidad = 3
        movimiento.save()

        movimiento.refresh_from_db()
        self.assertEqual(movimiento.costo_unitario, 1000, 'sigue valuado al costo de su momento')
        self.assertEqual(self.evento.gasto_stock, 3000)

    def test_cambiar_de_producto_si_vuelve_a_sellar(self):
        otro = Producto.objects.create(
            nombre='Sidra', sector='barra', precio_unitario=300, stock_actual=50
        )
        movimiento = MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=2
        )
        movimiento.producto = otro
        movimiento.save()

        movimiento.refresh_from_db()
        self.assertEqual(movimiento.costo_unitario, 300, 'es otro producto: otro costo')


class RentabilidadTests(TestCase):
    """RN-17: ingresos, adicionales y margen. Lo que el sistema no sabía hacer."""

    def setUp(self):
        self.producto = Producto.objects.create(
            nombre='Vino', sector='barra', precio_unitario=1000, stock_actual=1000
        )
        self.empleado = Empleado.objects.create(nombre='Rosa')
        self.evento = Evento.objects.create(
            nombre='Cumple 15', fecha=date(2026, 9, 1), asistentes=100
        )

    def test_sin_precio_cargado_no_hay_ingreso_ni_se_inventa(self):
        self.assertFalse(self.evento.tiene_precio_cargado)
        self.assertEqual(self.evento.ingreso_total, 0)
        self.assertIsNone(self.evento.margen_porcentaje)

    def test_el_evento_no_tiene_precio_propio(self):
        """El cubierto se cobra en un solo lugar: la tabla de tarjetas.

        `precio_cerrado` y `precio_por_persona` se fueron del modelo. Sumaban EN
        PARALELO a las tarjetas, asi que cargar las dos cosas facturaba la misma
        comida dos veces sin que nada avisara.
        """
        self.assertFalse(hasattr(self.evento, 'precio_cerrado'))
        self.assertFalse(hasattr(self.evento, 'precio_por_persona'))

    def test_lo_que_factura_el_evento_sale_de_las_tarjetas(self):
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=80, valor_unitario=50000
        )
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Infantil', cantidad=20, valor_unitario=30000
        )
        self.assertEqual(self.evento.ingreso_total, 4_600_000)

    def test_un_evento_sin_asistentes_igual_factura_por_sus_tarjetas(self):
        """'Casamiento Nascar' existe y tiene 0 asistentes cargados.

        Antes el ingreso por cubierto se multiplicaba por `asistentes`, asi que ese
        evento facturaba 0 hasta que alguien corrigiera el numero. La tarjeta trae
        su propia cantidad: no depende del campo del evento.
        """
        self.evento.asistentes = 0
        self.evento.save()
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=100, valor_unitario=5000
        )
        self.assertEqual(self.evento.ingreso_total, 500000)

    def test_los_cargos_suman_al_ingreso(self):
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=100, valor_unitario=4000
        )
        CargoEvento.objects.create(evento=self.evento, concepto='Barra libre', monto=80000)
        CargoEvento.objects.create(evento=self.evento, concepto='DJ', monto=50000)

        self.assertEqual(self.evento.ingreso_cargos, 130000)
        self.assertEqual(self.evento.ingreso_total, 530000)

    def test_el_margen_es_lo_facturado_menos_lo_gastado(self):
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=100, valor_unitario=5000
        )
        CargoEvento.objects.create(evento=self.evento, concepto='DJ', monto=50000)
        MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=100
        )
        PersonalEvento.objects.create(
            evento=self.evento, empleado=self.empleado, puesto=un_puesto('Moza'), pago=150000
        )

        self.assertEqual(self.evento.ingreso_total, 550000)
        self.assertEqual(self.evento.gasto_total, 250000)
        self.assertEqual(self.evento.margen, 300000)

    def test_un_evento_que_pierde_plata_da_margen_negativo(self):
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=100, valor_unitario=1000
        )
        PersonalEvento.objects.create(
            evento=self.evento, empleado=self.empleado, puesto=un_puesto('Mozo'), pago=150000
        )
        self.assertEqual(self.evento.margen, -50000)

    def test_el_porcentaje_de_margen(self):
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=100, valor_unitario=2000
        )
        PersonalEvento.objects.create(
            evento=self.evento, empleado=self.empleado, puesto=un_puesto('Mozo'), pago=50000
        )
        self.assertEqual(self.evento.margen_porcentaje, 75)

    def test_la_merma_no_le_come_el_margen_al_evento(self):
        """El choque que abrió toda la auditoría, ahora medido."""
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=100, valor_unitario=5000
        )
        MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=100
        )
        margen_antes = self.evento.margen

        MovimientoStock.objects.create(
            producto=self.producto, tipo='merma', motivo='rotura', cantidad=80
        )
        self.assertEqual(self.evento.margen, margen_antes, 'la rotura no es del cliente')

    def test_no_se_puede_cargar_un_cargo_a_un_evento_cerrado(self):
        self.evento.estado = 'finalizado'
        self.evento.save()
        with self.assertRaises(ValidationError):
            CargoEvento(evento=self.evento, concepto='DJ', monto=1000).full_clean()


class TarjetasTests(ClienteLogueadoTests):
    """RN-23: lo que paga cada tipo de invitado, el brindis y el paquete."""

    def setUp(self):
        super().setUp()
        self.paquete = Paquete.objects.create(nombre='Premium', precio=Decimal('129013'))
        self.evento = Evento.objects.create(
            nombre='Cumple 15', fecha=date(2026, 9, 1), asistentes=100
        )

    def test_una_fiesta_puede_tener_varios_valores_de_tarjeta(self):
        """El caso que pidio el dueno: 80 adultos y 20 menus infantiles."""
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=80, valor_unitario=50000
        )
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Menú infantil', cantidad=20, valor_unitario=30000
        )
        # 80 × 50.000 = 4.000.000   +   20 × 30.000 = 600.000
        self.assertEqual(self.evento.ingreso_tarjetas, 4_600_000)
        self.assertEqual(self.evento.ingreso_total, 4_600_000)

    def test_el_brindis_se_cobra_por_los_que_participan_no_por_todos(self):
        self.evento.brindis_asistentes = 60
        self.evento.brindis_valor = 8000
        self.assertEqual(self.evento.ingreso_brindis, 480000)

    def test_sin_brindis_cargado_no_suma_nada(self):
        self.assertEqual(self.evento.ingreso_brindis, 0)

        self.evento.brindis_asistentes = 60      # cantidad pero sin valor
        self.assertEqual(self.evento.ingreso_brindis, 0, 'con la mitad del dato no se inventa')

    def test_el_paquete_suma_una_vez_no_por_persona(self):
        """129.013 es lo que sale el paquete, no lo que sale por cubierto."""
        self.evento.paquete = self.paquete
        self.evento.save()
        self.assertEqual(self.evento.ingreso_paquete, 129013)
        self.assertEqual(self.evento.ingreso_total, 129013, 'no se multiplica por los 100 asistentes')

    def test_el_monto_del_paquete_se_sella_al_elegirlo(self):
        self.evento.paquete = self.paquete
        self.evento.save()
        self.evento.refresh_from_db()
        self.assertEqual(self.evento.precio_paquete, 129013)

    def test_cambiar_el_precio_del_catalogo_no_mueve_un_evento_ya_cargado(self):
        """RN-15 del lado del ingreso: la lista de precios no reescribe el pasado."""
        self.evento.paquete = self.paquete
        self.evento.estado = 'finalizado'
        self.evento.save()

        self.paquete.precio = 999999
        self.paquete.save()

        self.evento.refresh_from_db()
        self.assertEqual(self.evento.ingreso_paquete, 129013, 'el evento cerrado no se toca')

    def test_borrar_el_paquete_del_catalogo_no_le_borra_la_facturacion_al_evento(self):
        """Evento.paquete es SET_NULL: sin sellar, esto bajaba el ingreso a $0."""
        self.evento.paquete = self.paquete
        self.evento.estado = 'finalizado'
        self.evento.save()
        facturado_antes = self.evento.ingreso_total

        self.paquete.delete()

        self.evento.refresh_from_db()
        self.assertIsNone(self.evento.paquete, 'el catalogo se limpio')
        self.assertEqual(self.evento.ingreso_paquete, 129013, 'pero la plata quedo')
        self.assertEqual(self.evento.ingreso_total, facturado_antes)

    def test_sacarle_el_paquete_al_evento_si_le_saca_el_monto(self):
        """Distinto de borrarlo del catalogo: aca el evento deja de tener paquete."""
        self.evento.paquete = self.paquete
        self.evento.save()
        self.evento.paquete = None
        self.evento.save()

        self.evento.refresh_from_db()
        self.assertIsNone(self.evento.precio_paquete)
        self.assertEqual(self.evento.ingreso_paquete, 0)

    def test_el_monto_sellado_se_puede_corregir_a_mano(self):
        """Un evento se puede haber cerrado por otro numero que el de la lista."""
        self.evento.paquete = self.paquete
        self.evento.save()
        self.evento.precio_paquete = 200000
        self.evento.save()

        self.evento.refresh_from_db()
        self.assertEqual(self.evento.ingreso_paquete, 200000, 'no lo pisa el del catalogo')

    def test_reguardar_el_evento_no_borra_el_sello_del_paquete_borrado(self):
        """El agujero que anulaba el sellado entero.

        Al borrar el paquete del catalogo, SET_NULL deja paquete_id en None. Si
        despues se guardaba el evento por cualquier motivo (corregir un telefono,
        finalizarlo), la rama "sin paquete" limpiaba el monto y la facturacion
        volvia a $0.
        """
        self.evento.paquete = self.paquete
        self.evento.save()
        self.paquete.delete()
        self.evento.refresh_from_db()

        self.evento.telefono_contacto = '351-1234'
        self.evento.save()

        self.evento.refresh_from_db()
        self.assertEqual(self.evento.ingreso_paquete, 129013, 'el sello sobrevive al reguardado')

    def test_se_puede_cargar_un_monto_de_paquete_sin_elegir_paquete(self):
        """Hay eventos que se cierran por un monto sin un paquete del catalogo."""
        self.evento.precio_paquete = 500000
        self.evento.save()

        self.evento.refresh_from_db()
        self.assertEqual(self.evento.ingreso_paquete, 500000)

    def test_cambiar_de_paquete_y_corregir_el_monto_a_la_vez_respeta_el_monto(self):
        """En el mismo formulario: elige otro paquete Y escribe otra cifra."""
        basico = Paquete.objects.create(nombre='Básico', precio=50000)
        self.evento.paquete = basico
        self.evento.save()

        self.evento.paquete = self.paquete        # pasa a Premium ($129.013)
        self.evento.precio_paquete = 100000       # pero se cerró por $100.000
        self.evento.save()

        self.evento.refresh_from_db()
        self.assertEqual(self.evento.ingreso_paquete, 100000, 'manda lo que escribio el usuario')

    def test_cambiar_solo_de_paquete_si_resella_con_el_nuevo(self):
        basico = Paquete.objects.create(nombre='Básico', precio=50000)
        self.evento.paquete = basico
        self.evento.save()
        self.evento.refresh_from_db()

        self.evento.paquete = self.paquete
        self.evento.save()

        self.evento.refresh_from_db()
        self.assertEqual(self.evento.ingreso_paquete, 129013)

    def test_el_desglose_no_explota_si_el_paquete_ya_no_existe(self):
        self.evento.paquete = self.paquete
        self.evento.save()
        self.paquete.delete()
        self.evento.refresh_from_db()

        conceptos = [r['concepto'] for r in self.evento.desglose_ingresos]
        self.assertIn('Paquete', conceptos)

    def test_la_ganancia_es_todo_lo_facturado_menos_los_dos_gastos(self):
        """La formula completa que pidio el dueno, de punta a punta."""
        producto = Producto.objects.create(
            nombre='Vino', sector='barra', precio_unitario=1000, stock_actual=500
        )
        empleado = Empleado.objects.create(nombre='Rosa')

        self.evento.paquete = self.paquete
        self.evento.brindis_asistentes = 60
        self.evento.brindis_valor = 8000
        self.evento.save()

        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=80, valor_unitario=50000
        )
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Menú infantil', cantidad=20, valor_unitario=30000
        )
        CargoEvento.objects.create(evento=self.evento, concepto='DJ', monto=150000)
        MovimientoStock.objects.create(
            producto=producto, evento=self.evento, tipo='salida', cantidad=200
        )
        PersonalEvento.objects.create(
            evento=self.evento, empleado=empleado, puesto=un_puesto(), pago=300000
        )

        # tarjetas 4.600.000 + brindis 480.000 + paquete 129.013 + cargos 150.000
        self.assertEqual(self.evento.ingreso_total, 5_359_013)
        # stock 200 × 1.000 = 200.000  +  personal 300.000
        self.assertEqual(self.evento.gasto_total, 500_000)
        self.assertEqual(self.evento.margen, 4_859_013)

    def test_el_desglose_muestra_de_donde_sale_cada_peso(self):
        """Cada peso facturado tiene que poder rastrearse hasta su renglon."""
        self.evento.paquete = self.paquete
        self.evento.save()
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=80, valor_unitario=50000
        )
        CargoEvento.objects.create(evento=self.evento, concepto='DJ', monto=150000)

        conceptos = [r['concepto'] for r in self.evento.desglose_ingresos]
        self.assertIn('Adultos', conceptos)
        self.assertIn('Paquete Premium', conceptos)
        self.assertIn('DJ', conceptos)

        total = sum(r['monto'] for r in self.evento.desglose_ingresos)
        self.assertEqual(total, self.evento.ingreso_total, 'el desglose tiene que cerrar con el total')

    def test_el_desglose_no_lista_lo_que_esta_vacio(self):
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=80, valor_unitario=50000
        )
        self.assertEqual(len(self.evento.desglose_ingresos), 1, 'sin ceros de relleno')

    def test_avisa_si_las_tarjetas_no_cuadran_con_los_asistentes(self):
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=80, valor_unitario=50000
        )
        self.assertEqual(self.evento.tarjetas_vs_asistentes, -20, '80 tarjetas contra 100 asistentes')

    def test_sin_tarjetas_no_hay_nada_que_avisar(self):
        self.assertIsNone(self.evento.tarjetas_vs_asistentes)

    def test_no_bloquea_la_carga_aunque_no_cuadre(self):
        """En un salon los numeros bailan hasta ultimo momento: se avisa, no se traba."""
        tarjeta = TarjetaEvento(
            evento=self.evento, concepto='Adultos', cantidad=500, valor_unitario=1000
        )
        tarjeta.full_clean()
        tarjeta.save()
        self.assertEqual(self.evento.ingreso_tarjetas, 500000)

    def test_no_se_cargan_tarjetas_a_un_evento_cerrado(self):
        """RN-16: mismo criterio que el consumo, el personal y los cargos."""
        self.evento.estado = 'finalizado'
        self.evento.save()
        with self.assertRaises(ValidationError):
            TarjetaEvento(
                evento=self.evento, concepto='Adultos', cantidad=80, valor_unitario=50000
            ).full_clean()

    def test_sin_nada_cargado_no_se_inventa_facturacion(self):
        self.assertFalse(self.evento.tiene_precio_cargado)
        self.assertEqual(self.evento.ingreso_total, 0)
        self.assertIsNone(self.evento.margen_porcentaje)

    def test_se_carga_una_tarjeta_desde_la_pantalla(self):
        respuesta = self.client.post(
            reverse('stock:tarjetaevento_create', kwargs={'evento_pk': self.evento.pk}),
            {'concepto': 'Adultos', 'cantidad': '80', 'valor_unitario': '50000', 'menu': ''},
        )
        self.assertRedirects(
            respuesta, reverse('stock:evento_detail', kwargs={'pk': self.evento.pk})
        )
        self.assertEqual(self.evento.ingreso_tarjetas, 4_000_000)

    def test_borrar_el_menu_del_catalogo_no_borra_la_tarjeta(self):
        """La tarjeta es plata; el menu es solo la sugerencia de comida."""
        menu = Menu.objects.create(nombre='Infantil')
        tarjeta = TarjetaEvento.objects.create(
            evento=self.evento, concepto='Menú infantil', cantidad=20,
            valor_unitario=30000, menu=menu,
        )
        menu.delete()

        tarjeta.refresh_from_db()
        self.assertIsNone(tarjeta.menu)
        self.assertEqual(self.evento.ingreso_tarjetas, 600000, 'la facturacion no se toca')


class RecetaTests(TestCase):
    """RN-18 y RN-19: la receta se carga en el menu, costea y sugiere.

    La receta vive organizada por platos (entrante, principal, postre...) y cada
    plato lleva sus ingredientes medidos por persona.
    """

    def setUp(self):
        self.carne = Producto.objects.create(
            nombre='Carne', sector='cocina', precio_unitario=8000,
            stock_actual=500, unidad_medida=una_unidad('Kilogramos')
        )
        self.vino = Producto.objects.create(
            nombre='Vino', sector='barra', precio_unitario=3000,
            stock_actual=500, unidad_medida=una_unidad('Botellas')
        )
        self.menu = Menu.objects.create(nombre='Clásico')
        self.principal = una_receta(
            {'menu': self.menu}, self.carne, Decimal('0.250'),
            paso='principal', nombre='Bife con papas',
        )
        una_receta(
            {'menu': self.menu}, self.vino, Decimal('0.500'),
            paso='entrante', nombre='Brindis',
        )
        self.evento = Evento.objects.create(
            nombre='Boda', fecha=date(2026, 11, 1), asistentes=100, menu=self.menu
        )

    def test_el_menu_sabe_cuanto_cuesta_el_cubierto(self):
        # 0,250 kg × $8.000 = $2.000  +  0,5 botella × $3.000 = $1.500
        self.assertEqual(self.menu.costo_por_persona, Decimal('3500.000'))

    def test_los_platos_se_agrupan_en_orden_de_servicio(self):
        """El entrante va antes que el principal, aunque alfabeticamente no."""
        grupos = self.menu.platos_por_paso
        self.assertEqual([g['clave'] for g in grupos],
                         ['entrante', 'principal', 'secundario', 'postre'])
        self.assertEqual(grupos[0]['platos'][0].nombre, 'Brindis')
        self.assertEqual(grupos[1]['platos'][0].nombre, 'Bife con papas')

    def test_asignar_el_menu_le_trae_la_receta_al_evento_solo(self):
        """No hay que copiar nada a mano: el evento hereda al quedar asignado."""
        self.assertEqual(self.evento.platos.count(), 2)

    def test_copiar_la_receta_del_menu_al_evento(self):
        self.assertEqual(self.evento.copiar_receta_del_menu(), 2)
        self.assertEqual(self.evento.platos.count(), 2)

    def test_cambiar_el_menu_base_no_altera_la_receta_ya_copiada(self):
        """RN-18: el menú evoluciona, lo ya cargado no."""
        linea = self.principal.lineas.get(producto=self.carne)
        linea.cantidad_por_persona = Decimal('0.400')
        linea.save()

        copia = LineaReceta.objects.get(plato__evento=self.evento, producto=self.carne)
        self.assertEqual(copia.cantidad_por_persona, Decimal('0.250'), 'la copia es independiente')

    def test_copiar_de_nuevo_reemplaza_no_duplica(self):
        self.evento.copiar_receta_del_menu()
        self.evento.copiar_receta_del_menu()
        self.assertEqual(self.evento.platos.count(), 2)

    def test_guardar_el_evento_sin_cambiar_el_menu_no_recopia(self):
        """Corregir el telefono no puede pisar la receta que ya estaba."""
        self.evento.platos.filter(paso='entrante').delete()
        self.evento.telefono_contacto = '351-1234'
        self.evento.save()
        self.assertEqual(self.evento.platos.count(), 1, 'la receta se quedó como estaba')

    def test_cambiar_de_menu_si_recopia(self):
        otro = Menu.objects.create(nombre='Vegetariano')
        una_receta({'menu': otro}, self.vino, Decimal('0.100'), nombre='Ensalada')

        self.evento.menu = otro
        self.evento.save()

        self.assertEqual(self.evento.platos.count(), 1)
        self.assertEqual(self.evento.platos.first().nombre, 'Ensalada')

    def test_el_consumo_sugerido_multiplica_por_los_asistentes(self):
        sugerido = {item['producto'].nombre: item['cantidad'] for item in self.evento.consumo_sugerido}

        self.assertEqual(sugerido['Carne'], Decimal('25.00'))
        self.assertEqual(sugerido['Vino'], Decimal('50.00'))

    def test_un_producto_en_dos_platos_se_suma_una_sola_vez(self):
        """La papa va en el principal y en la guarnicion: es UN pedido de papa."""
        una_receta(
            {'menu': self.menu}, self.carne, Decimal('0.100'),
            paso='secundario', nombre='Empanadas',
        )
        self.evento.copiar_receta_del_menu()

        sugerido = [i for i in self.evento.consumo_sugerido if i['producto'] == self.carne]
        self.assertEqual(len(sugerido), 1, 'un producto, una linea de consumo')
        self.assertEqual(sugerido[0]['cantidad'], Decimal('35.00'), '(0,250 + 0,100) × 100')

    def test_la_receta_no_descuenta_stock_por_su_cuenta(self):
        """RN-19: el corazón de la decisión 8 del dueño."""
        _ = self.evento.consumo_sugerido

        self.carne.refresh_from_db()
        self.vino.refresh_from_db()
        self.assertEqual(self.carne.stock_actual, 500)
        self.assertEqual(self.vino.stock_actual, 500)
        self.assertFalse(self.evento.movimientos.exists())

    def test_un_evento_sin_menu_no_tiene_nada_que_copiar(self):
        suelto = Evento.objects.create(nombre='Suelto', fecha=date(2026, 12, 1), asistentes=50)
        self.assertEqual(suelto.copiar_receta_del_menu(), 0)

    def test_un_plato_no_puede_ser_de_un_menu_y_de_un_evento_a_la_vez(self):
        plato = Plato(menu=self.menu, evento=self.evento, paso='postre', nombre='Helado')
        with self.assertRaises(Exception):
            plato.save()

    def test_un_plato_tiene_que_tener_algun_dueno(self):
        with self.assertRaises(Exception):
            Plato(paso='postre', nombre='Helado').save()

    def test_no_se_puede_borrar_un_producto_que_esta_en_una_receta(self):
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.carne.delete()


class RecetaPorTarjetaTests(TestCase):
    """RN-23: cada tarjeta come su menu, y la comida se calcula por separado.

    El caso del dueno: 100 personas, 80 con menu de adultos y 20 con infantil.
    """

    def setUp(self):
        self.carne = Producto.objects.create(
            nombre='Carne', sector='cocina', precio_unitario=8000,
            stock_actual=1000, unidad_medida=una_unidad('Kilogramos'),
        )
        self.nuggets = Producto.objects.create(
            nombre='Nuggets', sector='cocina', precio_unitario=4000,
            stock_actual=1000, unidad_medida=una_unidad('Kilogramos'),
        )
        self.papa = Producto.objects.create(
            nombre='Papa', sector='cocina', precio_unitario=1000,
            stock_actual=1000, unidad_medida=una_unidad('Kilogramos'),
        )

        # Menu de adultos: 250 g de carne + 200 g de papa por cubierto.
        self.adultos = Menu.objects.create(nombre='Clásico')
        principal = Plato.objects.create(menu=self.adultos, paso='principal', nombre='Bife con papas')
        LineaReceta.objects.create(plato=principal, producto=self.carne, cantidad_por_persona=Decimal('0.250'))
        LineaReceta.objects.create(plato=principal, producto=self.papa, cantidad_por_persona=Decimal('0.200'))

        # Menu infantil: 150 g de nuggets + 100 g de papa por cubierto.
        self.infantil = Menu.objects.create(nombre='Infantil')
        infantil = Plato.objects.create(menu=self.infantil, paso='principal', nombre='Nuggets con papas')
        LineaReceta.objects.create(plato=infantil, producto=self.nuggets, cantidad_por_persona=Decimal('0.150'))
        LineaReceta.objects.create(plato=infantil, producto=self.papa, cantidad_por_persona=Decimal('0.100'))

        self.evento = Evento.objects.create(
            nombre='Cumple 15', fecha=date(2026, 9, 1), asistentes=100
        )
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=80,
            valor_unitario=50000, menu=self.adultos,
        )
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Menú infantil', cantidad=20,
            valor_unitario=30000, menu=self.infantil,
        )

    def sugerido(self):
        return {i['producto'].nombre: i['cantidad'] for i in self.evento.consumo_sugerido}

    def test_cada_menu_se_calcula_por_su_propia_cantidad(self):
        pedido = self.sugerido()
        self.assertEqual(pedido['Carne'], Decimal('20.00'), '0,250 × 80 adultos')
        self.assertEqual(pedido['Nuggets'], Decimal('3.00'), '0,150 × 20 chicos')

    def test_un_producto_de_los_dos_menus_sale_en_una_sola_linea_sumada(self):
        """La papa esta en los dos menus: es UN pedido de papa, no dos."""
        pedido = self.sugerido()
        # 0,200 × 80 = 16 kg  +  0,100 × 20 = 2 kg
        self.assertEqual(pedido['Papa'], Decimal('18.00'))
        lineas_de_papa = [i for i in self.evento.consumo_sugerido if i['producto'] == self.papa]
        self.assertEqual(len(lineas_de_papa), 1)

    def test_no_multiplica_todo_por_los_asistentes_del_evento(self):
        """El bug que se busca evitar: 100 raciones de cada menu en vez de 80 y 20."""
        pedido = self.sugerido()
        self.assertNotEqual(pedido['Carne'], Decimal('25.00'), 'seria 0,250 × 100')
        self.assertNotEqual(pedido['Nuggets'], Decimal('15.00'), 'seria 0,150 × 100')

    def test_la_receta_se_copia_sola_al_cargar_la_tarjeta(self):
        self.assertEqual(self.evento.platos.count(), 2, 'un plato por menu')
        porciones = sorted(p.porciones for p in self.evento.platos.all())
        self.assertEqual(porciones, [20, 80])

    def test_cambiar_la_cantidad_de_una_tarjeta_recalcula_la_comida(self):
        tarjeta = self.evento.tarjetas.get(concepto='Adultos')
        tarjeta.cantidad = 120
        tarjeta.save()
        self.assertEqual(self.sugerido()['Carne'], Decimal('30.00'), '0,250 × 120')

    def test_borrar_una_tarjeta_saca_su_comida_del_calculo(self):
        self.evento.tarjetas.get(concepto='Menú infantil').delete()
        pedido = self.sugerido()
        self.assertNotIn('Nuggets', pedido)
        self.assertEqual(pedido['Papa'], Decimal('16.00'), 'solo la de los adultos')

    def test_dos_tarjetas_del_mismo_menu_se_suman_en_un_bloque(self):
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Músicos', cantidad=10,
            valor_unitario=0, menu=self.adultos,
        )
        self.assertEqual(self.sugerido()['Carne'], Decimal('22.50'), '0,250 × (80 + 10)')
        del_clasico = self.evento.platos.filter(nombre='Bife con papas')
        self.assertEqual(del_clasico.count(), 1, 'un solo bloque, no dos recetas iguales')

    def test_una_tarjeta_sin_menu_factura_pero_no_pide_comida(self):
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Solo baile', cantidad=30, valor_unitario=10000,
        )
        self.assertEqual(self.sugerido()['Carne'], Decimal('20.00'), 'no cambia la comida')
        self.assertEqual(self.evento.ingreso_tarjetas, 4_900_000, 'pero si la plata')

    def test_el_evento_sin_tarjetas_sigue_usando_su_menu_y_sus_asistentes(self):
        """Retrocompatibilidad: los eventos ya cargados no cambian de comportamiento."""
        viejo = Evento.objects.create(
            nombre='De antes', fecha=date(2026, 1, 1), asistentes=50, menu=self.adultos
        )
        pedido = {i['producto'].nombre: i['cantidad'] for i in viejo.consumo_sugerido}
        self.assertEqual(pedido['Carne'], Decimal('12.50'), '0,250 × 50 asistentes')

    def test_corregir_los_asistentes_recalcula_la_comida(self):
        """Sin tarjetas, la cantidad de gente se multiplica EN VIVO.

        Sellar las porciones al asignar el menu congelaba el numero de ese dia:
        se confirmaban 50 invitados mas y la cocina seguia comprando para 100.
        """
        evento = Evento.objects.create(
            nombre='Boda', fecha=date(2026, 5, 1), asistentes=100, menu=self.adultos
        )
        pedido = {i['producto'].nombre: i['cantidad'] for i in evento.consumo_sugerido}
        self.assertEqual(pedido['Carne'], Decimal('25.00'))

        evento.asistentes = 150
        evento.save()

        pedido = {i['producto'].nombre: i['cantidad'] for i in evento.consumo_sugerido}
        self.assertEqual(pedido['Carne'], Decimal('37.50'), '0,250 × 150')

    def test_un_evento_sin_asistentes_no_queda_pidiendo_cero_para_siempre(self):
        """El caso real de 'Casamiento Nascar', que esta cargado con 0 asistentes."""
        evento = Evento.objects.create(
            nombre='Nascar', fecha=date(2026, 5, 1), asistentes=0, menu=self.adultos
        )
        self.assertEqual(evento.consumo_sugerido[0]['cantidad'], Decimal('0.00'))

        evento.asistentes = 120
        evento.save()

        pedido = {i['producto'].nombre: i['cantidad'] for i in evento.consumo_sugerido}
        self.assertEqual(pedido['Carne'], Decimal('30.00'), '0,250 × 120')

    def test_borrar_la_ultima_tarjeta_se_lleva_la_receta_que_ya_nadie_pide(self):
        self.evento.tarjetas.all().delete()

        self.assertEqual(self.evento.platos.count(), 0)
        self.assertEqual(self.evento.consumo_sugerido, [])
        self.assertEqual(self.evento.costo_receta_estimado, 0)

    def test_el_costo_estimado_usa_las_cantidades_por_tarjeta(self):
        # carne 20 × 8.000 = 160.000 | nuggets 3 × 4.000 = 12.000 | papa 18 × 1.000 = 18.000
        self.assertEqual(self.evento.costo_receta_estimado, Decimal('190000.00'))

    def test_un_plato_suelto_no_se_suma_en_paralelo_a_las_tarjetas(self):
        """Si mandan las tarjetas, un plato sin porciones no puede colarse.

        Un plato cargado a mano desde el admin (con evento pero sin porciones)
        caia al fallback por asistentes y sumaba 100 raciones ARRIBA de las
        80 + 20, sin ningun aviso.
        """
        suelto = Plato.objects.create(evento=self.evento, paso='postre', nombre='Colado')
        LineaReceta.objects.create(
            plato=suelto, producto=self.carne, cantidad_por_persona=Decimal('1.000')
        )
        self.assertEqual(self.sugerido()['Carne'], Decimal('20.00'), 'las tarjetas mandan')

    def test_la_receta_sigue_sin_descontar_stock(self):
        """RN-19 no se negocia, por mas tarjetas que haya."""
        _ = self.evento.consumo_sugerido
        self.carne.refresh_from_db()
        self.assertEqual(self.carne.stock_actual, 1000)
        self.assertFalse(self.evento.movimientos.exists())


class EventoCerradoTests(TestCase):
    """RN-16: un evento finalizado no acepta más carga, salvo que se reabra."""

    def setUp(self):
        self.producto = Producto.objects.create(
            nombre='Vino', sector='barra', precio_unitario=1000, stock_actual=100
        )
        self.empleado = Empleado.objects.create(nombre='Luis')
        self.evento = Evento.objects.create(
            nombre='Casamiento', fecha=date(2026, 1, 10), estado='finalizado'
        )

    def test_no_se_puede_cargar_consumo_a_un_evento_cerrado(self):
        movimiento = MovimientoStock(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=1
        )
        with self.assertRaises(ValidationError):
            movimiento.full_clean()

    def test_no_se_puede_cargar_personal_a_un_evento_cerrado(self):
        asignacion = PersonalEvento(
            evento=self.evento, empleado=self.empleado, puesto=un_puesto('Mozo'), pago=1000
        )
        with self.assertRaises(ValidationError):
            asignacion.full_clean()

    def test_un_evento_abierto_si_acepta_carga(self):
        self.evento.estado = 'confirmado'
        self.evento.save()
        MovimientoStock(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=1
        ).full_clean()

    def test_reabrir_descongela_y_deja_rastro(self):
        self.assertTrue(self.evento.reabrir())
        self.evento.refresh_from_db()

        self.assertEqual(self.evento.estado, 'confirmado')
        self.assertIsNotNone(self.evento.reabierto_el, 'tiene que quedar constancia')
        MovimientoStock(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=1
        ).full_clean()

    def test_reabrir_un_evento_que_no_estaba_cerrado_no_hace_nada(self):
        self.evento.estado = 'pendiente'
        self.evento.save()
        self.assertFalse(self.evento.reabrir())
        self.assertIsNone(self.evento.reabierto_el)


class BajaDeProductoTests(ClienteLogueadoTests):
    """RN-20: un producto con historial no se borra, se da de baja."""

    def setUp(self):
        super().setUp()
        self.producto = Producto.objects.create(
            nombre='Whisky', sector='barra', precio_unitario=10000, stock_actual=50
        )
        self.evento = Evento.objects.create(
            nombre='Casamiento', fecha=date(2025, 6, 1), asistentes=100
        )
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=100, valor_unitario=9000
        )

    def test_borrar_un_producto_con_historial_lo_da_de_baja_y_no_toca_el_pasado(self):
        MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=10
        )
        self.evento.estado = 'finalizado'
        self.evento.save()
        margen_antes = self.evento.margen

        self.client.post(reverse('stock:producto_delete', kwargs={'pk': self.producto.pk}))

        self.producto.refresh_from_db()
        self.assertFalse(self.producto.activo, 'tiene que quedar dado de baja')
        self.assertTrue(Producto.objects.filter(pk=self.producto.pk).exists(), 'no se borra')
        self.assertEqual(self.evento.movimientos.count(), 1, 'el historial queda')
        self.assertEqual(self.evento.margen, margen_antes, 'el margen del evento cerrado no se mueve')

    def test_un_producto_sin_historial_si_se_borra(self):
        self.client.post(reverse('stock:producto_delete', kwargs={'pk': self.producto.pk}))
        self.assertFalse(Producto.objects.filter(pk=self.producto.pk).exists())

    def test_un_producto_dado_de_baja_no_aparece_en_las_pantallas_operativas(self):
        self.producto.dar_de_baja()
        for nombre, kwargs in [
            ('stock:compras', {}),
            ('stock:merma', {}),
            ('stock:consumo_evento', {'evento_pk': self.evento.pk}),
        ]:
            with self.subTest(pantalla=nombre):
                respuesta = self.client.get(reverse(nombre, kwargs=kwargs))
                self.assertNotIn(self.producto, respuesta.context['productos_barra'])

    def test_se_puede_reactivar(self):
        self.producto.dar_de_baja()
        self.client.post(reverse('stock:producto_reactivar', kwargs={'pk': self.producto.pk}))
        self.producto.refresh_from_db()
        self.assertTrue(self.producto.activo)


class ListadoDeProductosTests(ClienteLogueadoTests):
    """Un sector por pestana, y los dados de baja fuera de la lista (RN-20)."""

    def setUp(self):
        super().setUp()
        self.activo = Producto.objects.create(nombre='Fernet', sector='barra', stock_actual=10)
        self.baja = Producto.objects.create(nombre='Gancia', sector='barra', stock_actual=0)
        self.baja.dar_de_baja()
        self.cocina = Producto.objects.create(nombre='Carne', sector='cocina', stock_actual=5)

    def test_cada_sector_va_en_su_propia_lista(self):
        contexto = self.client.get(reverse('stock:producto_list')).context
        self.assertIn(self.activo, contexto['productos_barra'])
        self.assertIn(self.cocina, contexto['productos_cocina'])
        self.assertNotIn(self.cocina, contexto['productos_barra'])
        self.assertEqual(list(contexto['productos_extras']), [])

    def test_los_dados_de_baja_no_se_listan(self):
        contexto = self.client.get(reverse('stock:producto_list')).context
        self.assertNotIn(self.baja, contexto['productos_barra'])
        self.assertEqual(contexto['cantidad_bajas'], 1, 'pero el sistema sabe que estan')

    def test_se_pueden_ver_aparte_para_reactivarlos(self):
        contexto = self.client.get(reverse('stock:producto_list'), {'bajas': '1'}).context
        self.assertIn(self.baja, contexto['productos_barra'])
        self.assertNotIn(self.activo, contexto['productos_barra'])

    def test_la_busqueda_sigue_filtrando_por_nombre(self):
        contexto = self.client.get(reverse('stock:producto_list'), {'q': 'fern'}).context
        self.assertIn(self.activo, contexto['productos_barra'])
        self.assertEqual(list(contexto['productos_cocina']), [])


class HistorialDeMovimientosTests(ClienteLogueadoTests):
    """El libro mayor completo, con sus filtros."""

    def setUp(self):
        super().setUp()
        self.fernet = Producto.objects.create(
            nombre='Fernet', sector='barra', precio_unitario=1000, stock_actual=100
        )
        self.lavandina = Producto.objects.create(
            nombre='Lavandina', sector='limpieza', precio_unitario=500, stock_actual=20
        )
        self.evento = Evento.objects.create(nombre='Boda', fecha=date(2026, 6, 1))

        self.entrada = MovimientoStock.objects.create(
            producto=self.fernet, tipo='entrada', cantidad=10
        )
        self.salida = MovimientoStock.objects.create(
            producto=self.fernet, evento=self.evento, tipo='salida', cantidad=4
        )
        self.merma = MovimientoStock.objects.create(
            producto=self.lavandina, tipo='merma', motivo='rotura', cantidad=1
        )

    def movimientos(self, **filtros):
        respuesta = self.client.get(reverse('stock:movimiento_list'), filtros)
        self.assertEqual(respuesta.status_code, 200)
        return list(respuesta.context['movimientos'])

    def test_lista_todos_los_movimientos_del_mas_nuevo_al_mas_viejo(self):
        listado = self.movimientos()
        self.assertEqual(len(listado), 3)
        self.assertEqual(listado[0], self.merma, 'el ultimo cargado va primero')

    def test_filtra_por_tipo(self):
        self.assertEqual(self.movimientos(tipo='merma'), [self.merma])

    def test_filtra_por_sector(self):
        self.assertEqual(self.movimientos(sector='limpieza'), [self.merma])

    def test_filtra_por_evento(self):
        self.assertEqual(self.movimientos(evento=self.evento.pk), [self.salida])

    def test_filtra_por_nombre_de_producto(self):
        self.assertEqual(len(self.movimientos(q='fern')), 2)

    def test_filtra_por_rango_de_fechas_incluyendo_hoy(self):
        """`fecha` es DateTimeField: sin __date, un 'hasta hoy' se come lo de hoy."""
        hoy = date.today().isoformat()
        self.assertEqual(len(self.movimientos(desde=hoy, hasta=hoy)), 3)

    def test_una_url_con_basura_no_revienta_la_pantalla(self):
        """La querystring la escribe cualquiera: no puede ser un 500 (como parsear_cantidad)."""
        for filtros in [
            {'desde': 'no-es-fecha'},
            {'hasta': '99-99-99'},
            {'evento': 'abc'},
            {'evento': ''},
            {'tipo': 'inventado'},
            {'sector': 'inventado'},
            {'desde': 'x', 'hasta': 'y', 'evento': 'z'},
        ]:
            with self.subTest(filtros=filtros):
                respuesta = self.client.get(reverse('stock:movimiento_list'), filtros)
                self.assertEqual(respuesta.status_code, 200)

    def test_el_total_cuenta_el_filtro_entero_no_la_pagina(self):
        respuesta = self.client.get(reverse('stock:movimiento_list'), {'tipo': 'entrada'})
        self.assertEqual(respuesta.context['total_movimientos'], 1)


class SectoresNuevosTests(ClienteLogueadoTests):
    """RN-8: limpieza se valoriza como cualquier producto; mobiliario solo se cuenta."""

    def setUp(self):
        super().setUp()
        self.lavandina = Producto.objects.create(
            nombre='Lavandina', sector='limpieza', precio_unitario=500, stock_actual=10
        )
        self.mantel = Producto.objects.create(
            nombre='Mantel', sector='mobiliario', stock_actual=40, unidad_medida=una_unidad()
        )

    def test_los_sectores_nuevos_aparecen_en_las_cuatro_pantallas(self):
        evento = Evento.objects.create(nombre='Boda', fecha=date(2026, 6, 1))
        pantallas = [
            ('stock:producto_list', {}),
            ('stock:compras', {}),
            ('stock:merma', {}),
            ('stock:consumo_evento', {'evento_pk': evento.pk}),
        ]
        for nombre, kwargs in pantallas:
            with self.subTest(pantalla=nombre):
                contexto = self.client.get(reverse(nombre, kwargs=kwargs)).context
                claves = [s['clave'] for s in contexto['sectores']]
                self.assertIn('limpieza', claves)
                self.assertIn('mobiliario', claves)

    def test_el_mobiliario_no_se_valoriza_y_el_resto_si(self):
        self.assertFalse(self.mantel.valoriza)
        self.assertTrue(self.lavandina.valoriza)

        contexto = self.client.get(reverse('stock:producto_list')).context
        por_clave = {s['clave']: s for s in contexto['sectores']}
        self.assertTrue(por_clave['mobiliario']['sin_precio'])
        self.assertFalse(por_clave['limpieza']['sin_precio'])

    def test_un_producto_sin_precio_se_guarda_en_cero_en_vez_de_explotar(self):
        """El precio es opcional (mobiliario), y None en una columna NOT NULL es un 500."""
        producto = Producto(nombre='Servilletas', sector='mobiliario', precio_unitario=None)
        producto.save()
        producto.refresh_from_db()
        self.assertEqual(producto.precio_unitario, 0)

    def test_el_mobiliario_consumido_no_le_infla_el_costo_al_evento(self):
        """Los manteles son del salón: usarlos no es un gasto de la fiesta."""
        evento = Evento.objects.create(nombre='Boda', fecha=date(2026, 6, 1))
        MovimientoStock.objects.create(
            producto=self.mantel, evento=evento, tipo='salida', cantidad=30
        )
        self.assertEqual(evento.gasto_stock, 0)

    def test_la_limpieza_si_suma_al_costo(self):
        evento = Evento.objects.create(nombre='Boda', fecha=date(2026, 6, 1))
        MovimientoStock.objects.create(
            producto=self.lavandina, evento=evento, tipo='salida', cantidad=2
        )
        self.assertEqual(evento.gasto_stock, 1000)

    def test_el_alta_por_pantalla_acepta_un_sector_nuevo(self):
        self.client.post(reverse('stock:producto_create'), {
            'nombre': 'Copas', 'sector': 'mobiliario', 'precio_unitario': '',
            'stock_actual': '50', 'unidad_medida': una_unidad().pk,
        })
        copas = Producto.objects.get(nombre='Copas')
        self.assertEqual(copas.sector, 'mobiliario')
        self.assertEqual(copas.precio_unitario, 0)
        self.assertEqual(copas.stock_actual, 50)


class PuestoTests(ClienteLogueadoTests):
    """El catalogo de puestos lo administra el salon, no el codigo."""

    def setUp(self):
        super().setUp()
        self.puesto = Puesto.objects.create(nombre='Valet')
        self.empleado = Empleado.objects.create(nombre='Tito')
        self.evento = Evento.objects.create(nombre='Casamiento', fecha=date(2026, 5, 1))

    def test_se_puede_cargar_un_puesto_nuevo(self):
        self.client.post(reverse('stock:puesto_create'), {'nombre': 'Fotógrafo'})
        self.assertTrue(Puesto.objects.filter(nombre='Fotógrafo').exists())

    def test_un_puesto_sin_uso_se_borra(self):
        self.client.post(reverse('stock:puesto_delete', kwargs={'pk': self.puesto.pk}))
        self.assertFalse(Puesto.objects.filter(pk=self.puesto.pk).exists())

    def test_un_puesto_usado_en_un_evento_no_se_borra(self):
        """Es historial de pagos: borrarlo dejaria sin etiqueta lo ya liquidado."""
        PersonalEvento.objects.create(
            evento=self.evento, empleado=self.empleado, puesto=self.puesto, pago=1000
        )
        respuesta = self.client.post(reverse('stock:puesto_delete', kwargs={'pk': self.puesto.pk}))

        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(Puesto.objects.filter(pk=self.puesto.pk).exists())

    def test_los_puestos_llegan_a_la_pantalla_de_consumo(self):
        contexto = self.client.get(
            reverse('stock:consumo_evento', kwargs={'evento_pk': self.evento.pk})
        ).context
        self.assertIn(self.puesto, contexto['puestos'])

    def test_se_asigna_personal_eligiendo_un_puesto_de_la_lista(self):
        self.client.post(
            reverse('stock:personalevento_create', kwargs={'evento_pk': self.evento.pk}),
            {'empleado': self.empleado.pk, 'puesto': self.puesto.pk,
             'horas_trabajadas': '8', 'pago': '50000'},
        )
        asignacion = PersonalEvento.objects.get(evento=self.evento)
        self.assertEqual(asignacion.puesto, self.puesto)


class ModalTests(ClienteLogueadoTests):
    """Todo el CRUD se abre en un modal, con el MISMO template de la pantalla."""

    CABECERA = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}

    def setUp(self):
        super().setUp()
        self.producto = Producto.objects.create(nombre='Fernet', sector='barra', stock_actual=10)

    def test_por_fetch_devuelve_solo_el_fragmento(self):
        respuesta = self.client.get(
            reverse('stock:producto_update', kwargs={'pk': self.producto.pk}), **self.CABECERA
        )
        cuerpo = respuesta.content.decode()

        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn('<html', cuerpo, 'el fragmento no puede traer la pagina entera')
        self.assertNotIn('id="sidebar"', cuerpo)
        self.assertIn('name="nombre"', cuerpo, 'pero si el formulario')

    def test_sin_fetch_devuelve_la_pantalla_completa(self):
        """El modal es una mejora: la URL suelta tiene que seguir funcionando."""
        cuerpo = self.client.get(
            reverse('stock:producto_update', kwargs={'pk': self.producto.pk})
        ).content.decode()

        self.assertIn('<html', cuerpo)
        self.assertIn('id="sidebar"', cuerpo)

    def test_el_fragmento_no_se_come_los_mensajes(self):
        """Los mensajes los tiene que mostrar la pantalla a la que se redirige.

        Si el fragmento los imprimiera quedarian consumidos y el usuario no se
        enteraria de que su producto se dio de baja en vez de borrarse.
        """
        MovimientoStock.objects.create(producto=self.producto, tipo='entrada', cantidad=5)
        self.client.post(reverse('stock:producto_delete', kwargs={'pk': self.producto.pk}))

        destino = self.client.get(reverse('stock:producto_list'), **self.CABECERA)
        self.assertTrue(destino.context['messages'], 'el aviso sigue disponible')

    def test_guardar_desde_el_modal_redirige(self):
        """El JS distingue 'guardo' de 'hay errores' por el redirect."""
        respuesta = self.client.post(
            reverse('stock:producto_update', kwargs={'pk': self.producto.pk}),
            {'nombre': 'Fernet 1L', 'sector': 'barra', 'precio_unitario': '5000',
             'unidad_medida': una_unidad().pk},
            **self.CABECERA,
        )
        self.assertEqual(respuesta.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.nombre, 'Fernet 1L')

    def test_un_form_con_errores_vuelve_como_fragmento_y_no_redirige(self):
        respuesta = self.client.post(
            reverse('stock:producto_update', kwargs={'pk': self.producto.pk}),
            {'nombre': '', 'sector': 'barra', 'precio_unitario': '5000', 'unidad_medida': una_unidad().pk},
            **self.CABECERA,
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn('<html', respuesta.content.decode())


class RecordatoriosPorMailTests(TestCase):
    """RN-24: el job que avisa los eventos que se vienen.

    Corre solo, sin nadie mirando: si se equivoca, o no avisa (y el salon se
    entera tarde) o avisa de mas (y molesta hasta que lo apagan).
    """

    def setUp(self):
        self.destinatario = DestinatarioAviso.objects.create(email='dueno@victoria.com')
        DestinatarioAviso.objects.create(email='silenciado@victoria.com', activo=False)
        self.evento = Evento.objects.create(
            nombre='Boda', fecha=date.today() + timedelta(days=3),
            asistentes=100, estado='confirmado', notas='Llegan a las 21.',
        )

    def correr(self, *args):
        salida = StringIO()
        call_command('recordar_eventos', *args, stdout=salida, stderr=StringIO())
        return salida.getvalue()

    def test_avisa_un_evento_que_esta_dentro_de_la_ventana(self):
        self.correr()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['dueno@victoria.com'], 'el silenciado no recibe')
        self.assertIn('Boda', mail.outbox[0].subject)

    def test_el_mail_lleva_la_fecha_los_datos_y_las_notas(self):
        self.correr()
        cuerpo = mail.outbox[0].body
        self.assertIn('Llegan a las 21.', cuerpo, 'las notas son el motivo del pedido')
        self.assertIn('100', cuerpo)
        self.assertIn('Confirmado', cuerpo)

    def test_no_avisa_dos_veces_el_mismo_evento(self):
        self.correr()
        self.correr()
        self.assertEqual(len(mail.outbox), 1)

    def test_con_reenviar_vuelve_a_avisar(self):
        self.correr()
        self.correr('--reenviar')
        self.assertEqual(len(mail.outbox), 2)

    def test_no_avisa_lo_que_esta_fuera_de_la_ventana(self):
        self.evento.fecha = date.today() + timedelta(days=30)
        self.evento.save()
        self.correr()
        self.assertEqual(len(mail.outbox), 0)

    def test_la_ventana_se_puede_estirar(self):
        self.evento.fecha = date.today() + timedelta(days=20)
        self.evento.save()
        self.correr('--dias', '30')
        self.assertEqual(len(mail.outbox), 1)

    def test_no_avisa_eventos_que_ya_pasaron(self):
        self.evento.fecha = date.today() - timedelta(days=1)
        self.evento.save()
        self.correr()
        self.assertEqual(len(mail.outbox), 0)

    def test_no_avisa_eventos_finalizados(self):
        self.evento.estado = 'finalizado'
        self.evento.save()
        self.correr()
        self.assertEqual(len(mail.outbox), 0)

    def test_recupera_un_aviso_atrasado_en_vez_de_perderlo(self):
        """Si la maquina estuvo apagada el dia que le tocaba, se avisa igual.

        Por eso es una ventana y no una fecha exacta: con el dia justo, un evento
        que caia un dia sin corrida no se avisaba nunca y nadie se enteraba.
        """
        self.evento.fecha = date.today() + timedelta(days=1)
        self.evento.save()
        self.correr()
        self.assertEqual(len(mail.outbox), 1)

    def test_sin_destinatarios_no_manda_ni_marca(self):
        DestinatarioAviso.objects.all().delete()
        self.correr()
        self.assertEqual(len(mail.outbox), 0)
        self.evento.refresh_from_db()
        self.assertIsNone(self.evento.aviso_enviado_el, 'no puede quedar como avisado')

    def test_el_ensayo_no_manda_ni_marca(self):
        salida = self.correr('--dry-run')
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('Boda', salida)
        self.evento.refresh_from_db()
        self.assertIsNone(self.evento.aviso_enviado_el)

    def test_un_emoji_en_las_notas_no_rompe_el_ensayo(self):
        """La consola de Windows es cp1252 y explota con lo que no entra."""
        self.evento.notas = 'Torta 🎂'
        self.evento.save()
        self.correr('--dry-run')   # no tiene que levantar UnicodeEncodeError

    def test_si_un_mail_falla_el_evento_no_queda_marcado_como_avisado(self):
        """Marcarlo sin haberlo mandado seria peor que fallar: no se reintenta nunca."""
        with patch('stock.management.commands.recordar_eventos.EmailMessage.send',
                   side_effect=OSError('smtp caido')):
            self.correr()
        self.evento.refresh_from_db()
        self.assertIsNone(self.evento.aviso_enviado_el)

    def test_el_mail_incluye_las_tarjetas_y_la_comida_estimada(self):
        producto = Producto.objects.create(
            nombre='Carne', sector='cocina', precio_unitario=8000,
            stock_actual=500, unidad_medida=una_unidad('Kilogramos'),
        )
        menu = Menu.objects.create(nombre='Clásico')
        plato = Plato.objects.create(menu=menu, paso='principal', nombre='Bife')
        LineaReceta.objects.create(plato=plato, producto=producto, cantidad_por_persona=Decimal('0.250'))
        TarjetaEvento.objects.create(
            evento=self.evento, concepto='Adultos', cantidad=80,
            valor_unitario=50000, menu=menu,
        )

        self.correr()
        cuerpo = mail.outbox[0].body
        self.assertIn('80 × Adultos', cuerpo)
        self.assertIn('20.00 Kilogramos de Carne', cuerpo, '0,250 × 80 tarjetas')


class ReconciliacionTests(TestCase):
    """El comando que hace cerrar el libro mayor con el stock declarado."""

    def setUp(self):
        # Un producto descuadrado como los reales: stock escrito a mano sin asiento.
        self.producto = Producto.objects.create(
            nombre='Querosene', sector='extras', precio_unitario=200, stock_actual=0
        )
        MovimientoStock.objects.create(producto=self.producto, tipo='salida', cantidad=5)
        Producto.objects.filter(pk=self.producto.pk).update(stock_actual=3)
        self.producto.refresh_from_db()

    def _libro(self):
        return sum(MovimientoStock._delta(m) for m in self.producto.movimientos.all())

    def test_sin_confirmar_no_toca_nada(self):
        call_command('reconciliar_stock', stdout=StringIO())
        self.assertEqual(self.producto.movimientos.count(), 1)

    def test_con_confirmar_el_libro_cierra_y_el_stock_no_se_mueve(self):
        call_command('reconciliar_stock', '--confirmar', stdout=StringIO())

        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 3, 'el stock físico es la verdad, no se toca')
        self.assertEqual(self._libro(), 3, 'el libro tiene que llegar al mismo número')

    def test_es_idempotente(self):
        call_command('reconciliar_stock', '--confirmar', stdout=StringIO())
        movimientos = self.producto.movimientos.count()

        call_command('reconciliar_stock', '--confirmar', stdout=StringIO())
        self.assertEqual(self.producto.movimientos.count(), movimientos, 'ya cerraba: no agrega más')

    def test_una_diferencia_negativa_queda_como_merma(self):
        otro = Producto.objects.create(
            nombre='Copas', sector='barra', precio_unitario=500, stock_actual=0
        )
        MovimientoStock.objects.create(producto=otro, tipo='entrada', cantidad=10)
        Producto.objects.filter(pk=otro.pk).update(stock_actual=4)

        call_command('reconciliar_stock', '--confirmar', stdout=StringIO())

        ajuste = otro.movimientos.get(tipo='merma')
        self.assertEqual(ajuste.cantidad, 6)
        self.assertEqual(ajuste.motivo, 'otro')
        otro.refresh_from_db()
        self.assertEqual(otro.stock_actual, 4)


class AutenticacionTests(TestCase):
    """BUG CRITICO 3: antes todas las pantallas eran publicas."""

    def test_sin_sesion_no_se_ve_nada(self):
        for nombre in [
            'stock:home', 'stock:producto_list', 'stock:evento_list',
            'stock:empleado_list', 'stock:compras', 'stock:merma',
            'stock:calendario', 'stock:consumo_selector',
        ]:
            with self.subTest(url=nombre):
                respuesta = self.client.get(reverse(nombre))
                self.assertEqual(respuesta.status_code, 302)
                self.assertIn(reverse('stock:login'), respuesta.url)

    def test_la_pantalla_de_ingreso_es_publica(self):
        self.assertEqual(self.client.get(reverse('stock:login')).status_code, 200)

    def test_con_sesion_se_entra(self):
        self.client.force_login(User.objects.create_user('tester', password='tester-1234', is_staff=True))
        self.assertEqual(self.client.get(reverse('stock:home')).status_code, 200)

    def test_se_puede_cerrar_sesion(self):
        self.client.force_login(User.objects.create_user('tester', password='tester-1234', is_staff=True))
        self.client.post(reverse('stock:logout'))
        self.assertEqual(self.client.get(reverse('stock:home')).status_code, 302)


class VistasTests(ClienteLogueadoTests):
    """Las pantallas tienen que abrir. Suena obvio, pero una no abre."""

    def setUp(self):
        super().setUp()
        self.producto = Producto.objects.create(
            nombre='Coca', sector='barra', precio_unitario=500, stock_actual=30
        )
        self.evento = Evento.objects.create(nombre='Egresados', fecha=date(2026, 11, 20))
        self.empleado = Empleado.objects.create(nombre='Ana')
        self.asignacion = PersonalEvento.objects.create(
            evento=self.evento, empleado=self.empleado, puesto=un_puesto('Moza'), pago=40000
        )

    def test_editar_personal_de_un_evento_abre(self):
        """BUG CONOCIDO (views.py PersonalEventoUpdateView): tira FieldError.

        Declara fields = ['nombre', 'fecha', 'asistentes', 'notas'], que son
        campos de Evento y no de PersonalEvento.
        """
        url = reverse('stock:personalevento_update', kwargs={'pk': self.asignacion.pk})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_pantallas_principales_abren(self):
        for nombre, kwargs in [
            ('stock:home', {}),
            ('stock:producto_list', {}),
            ('stock:evento_list', {}),
            ('stock:evento_historial', {}),
            ('stock:empleado_list', {}),
            ('stock:compras', {}),
            ('stock:merma', {}),
            ('stock:calendario', {}),
            ('stock:consumo_selector', {}),
            ('stock:paquete_list', {}),
            ('stock:menu_list', {}),
            ('stock:evento_detail', {'pk': self.evento.pk}),
            ('stock:consumo_evento', {'evento_pk': self.evento.pk}),
            ('stock:cargoevento_create', {'evento_pk': self.evento.pk}),
            ('stock:puesto_list', {}),
            ('stock:puesto_create', {}),
            ('stock:producto_create', {}),
            ('stock:producto_detail', {'pk': self.producto.pk}),
            ('stock:producto_update', {'pk': self.producto.pk}),
            ('stock:producto_delete', {'pk': self.producto.pk}),
        ]:
            with self.subTest(url=nombre):
                self.assertEqual(self.client.get(reverse(nombre, kwargs=kwargs)).status_code, 200)

    def test_compras_no_revienta_con_una_cantidad_que_no_es_numero(self):
        """BUG CONOCIDO (views.compras): int(cantidad) sin proteccion -> ValueError 500."""
        respuesta = self.client.post(reverse('stock:compras'), {
            'producto_id': self.producto.pk,
            'cantidad': 'muchas',
            'tab': 'barra-pane',
        })
        self.assertEqual(respuesta.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 30, 'no tiene que tocar el stock')

    def test_el_selector_de_consumo_no_lista_los_eventos_cerrados(self):
        cerrado = Evento.objects.create(
            nombre='Ya pasó', fecha=date(2026, 1, 1), estado='finalizado'
        )
        respuesta = self.client.get(reverse('stock:consumo_selector'))
        eventos = list(respuesta.context['eventos'])
        self.assertIn(self.evento, eventos)
        self.assertNotIn(cerrado, eventos)

    def test_reabrir_un_evento_desde_la_pantalla(self):
        self.evento.estado = 'finalizado'
        self.evento.save()

        respuesta = self.client.post(reverse('stock:evento_reabrir', kwargs={'pk': self.evento.pk}))
        self.assertRedirects(
            respuesta, reverse('stock:evento_detail', kwargs={'pk': self.evento.pk})
        )
        self.evento.refresh_from_db()
        self.assertEqual(self.evento.estado, 'confirmado')
        self.assertIsNotNone(self.evento.reabierto_el)

    def test_cargar_consumo_a_un_evento_cerrado_avisa_y_no_toca_el_stock(self):
        self.evento.estado = 'finalizado'
        self.evento.save()

        respuesta = self.client.post(
            reverse('stock:movimientostock_create', kwargs={'evento_pk': self.evento.pk}),
            {'producto': self.producto.pk, 'tipo': 'salida', 'cantidad': '1'},
        )
        self.assertEqual(respuesta.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 30, 'no tiene que tocar el stock')
        self.assertFalse(self.evento.movimientos.exists())

    def test_cargar_un_adicional_desde_la_pantalla(self):
        respuesta = self.client.post(
            reverse('stock:cargoevento_create', kwargs={'evento_pk': self.evento.pk}),
            {'concepto': 'Barra libre', 'monto': '75000'},
        )
        self.assertRedirects(
            respuesta, reverse('stock:evento_detail', kwargs={'pk': self.evento.pk})
        )
        self.assertEqual(self.evento.ingreso_cargos, 75000)

    def test_compras_acepta_cantidades_decimales(self):
        self.client.post(reverse('stock:compras'), {
            'producto_id': self.producto.pk, 'cantidad': '2.5', 'tab': 'barra-pane',
        })
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal('32.50'))


class PantallaMermaTests(ClienteLogueadoTests):
    """La merma tiene su propia pantalla: no se carga contra un evento."""

    def setUp(self):
        super().setUp()
        self.producto = Producto.objects.create(
            nombre='Copa', sector='barra', precio_unitario=800, stock_actual=10
        )

    def test_registrar_una_merma_descuenta_el_stock(self):
        respuesta = self.client.post(reverse('stock:merma'), {
            'producto_id': self.producto.pk,
            'cantidad': '2',
            'motivo': 'rotura',
            'tab': 'barra-pane',
        })
        self.assertEqual(respuesta.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 8)

        movimiento = MovimientoStock.objects.get(producto=self.producto, tipo='merma')
        self.assertEqual(movimiento.motivo, 'rotura')
        self.assertIsNone(movimiento.evento, 'la merma nunca lleva evento')

    def test_no_se_puede_mermar_mas_de_lo_que_hay(self):
        self.client.post(reverse('stock:merma'), {
            'producto_id': self.producto.pk,
            'cantidad': '11',
            'motivo': 'rotura',
            'tab': 'barra-pane',
        })
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 10, 'no tiene que tocar el stock')
        self.assertFalse(MovimientoStock.objects.filter(tipo='merma').exists())

    def test_la_merma_exige_motivo_desde_la_pantalla(self):
        self.client.post(reverse('stock:merma'), {
            'producto_id': self.producto.pk, 'cantidad': '1', 'motivo': '', 'tab': 'barra-pane',
        })
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 10)
        self.assertFalse(MovimientoStock.objects.filter(tipo='merma').exists())

    def test_la_merma_no_revienta_con_una_cantidad_que_no_es_numero(self):
        respuesta = self.client.post(reverse('stock:merma'), {
            'producto_id': self.producto.pk, 'cantidad': 'dos', 'motivo': 'rotura', 'tab': 'barra-pane',
        })
        self.assertEqual(respuesta.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 10)


class StockNoSeEditaAManoTests(ClienteLogueadoTests):
    """RN-1: el stock lo escribe el libro mayor, no el formulario."""

    def test_el_alta_con_stock_inicial_genera_la_entrada_que_lo_respalda(self):
        self.client.post(reverse('stock:producto_create'), {
            'nombre': 'Sidra', 'sector': 'barra', 'precio_unitario': '1200',
            'stock_actual': '12', 'unidad_medida': una_unidad().pk,
        })
        producto = Producto.objects.get(nombre='Sidra')
        self.assertEqual(producto.stock_actual, 12)

        movimientos = producto.movimientos.all()
        self.assertEqual(len(movimientos), 1, 'el stock inicial tiene que quedar registrado')
        self.assertEqual(movimientos[0].tipo, 'entrada')
        self.assertEqual(movimientos[0].cantidad, 12)

    def test_editar_un_producto_no_puede_reescribir_el_stock(self):
        producto = Producto.objects.create(
            nombre='Agua', sector='barra', precio_unitario=300, stock_actual=7
        )
        self.client.post(reverse('stock:producto_update', kwargs={'pk': producto.pk}), {
            'nombre': 'Agua', 'sector': 'barra', 'precio_unitario': '300',
            'stock_actual': '999', 'unidad_medida': una_unidad().pk,
        })
        producto.refresh_from_db()
        self.assertEqual(producto.stock_actual, 7, 'el stock no se toca desde el form')

    def test_el_libro_mayor_cierra_con_el_stock(self):
        """Lo que separa un inventario confiable de una planilla suelta."""
        self.client.post(reverse('stock:producto_create'), {
            'nombre': 'Tonica', 'sector': 'barra', 'precio_unitario': '900',
            'stock_actual': '20', 'unidad_medida': una_unidad().pk,
        })
        producto = Producto.objects.get(nombre='Tonica')
        self.client.post(reverse('stock:compras'), {
            'producto_id': producto.pk, 'cantidad': '5.5', 'tab': 'barra-pane',
        })
        self.client.post(reverse('stock:merma'), {
            'producto_id': producto.pk, 'cantidad': '0.5', 'motivo': 'rotura', 'tab': 'barra-pane',
        })

        producto.refresh_from_db()
        libro = sum(
            m.cantidad if m.tipo == 'entrada' else -m.cantidad
            for m in producto.movimientos.all()
        )
        self.assertEqual(producto.stock_actual, libro)
        self.assertEqual(producto.stock_actual, Decimal('25.00'))


class MovimientosSinEventoTests(ClienteLogueadoTests):
    """Las compras y las mermas no tienen evento: no pueden volver a evento_detail."""

    def setUp(self):
        super().setUp()
        self.producto = Producto.objects.create(
            nombre='Papel', sector='extras', precio_unitario=100, stock_actual=50
        )

    def test_editar_una_compra_no_explota_y_vuelve_a_compras(self):
        compra = MovimientoStock.objects.create(
            producto=self.producto, tipo='entrada', cantidad=10
        )
        url = reverse('stock:movimientostock_update', kwargs={'pk': compra.pk})
        self.assertEqual(self.client.get(url).status_code, 200)

        respuesta = self.client.post(url, {
            'producto': self.producto.pk, 'tipo': 'entrada', 'cantidad': '4', 'motivo': '',
        })
        self.assertRedirects(respuesta, reverse('stock:compras'))

    def test_borrar_una_merma_no_explota_y_vuelve_a_merma(self):
        merma = MovimientoStock.objects.create(
            producto=self.producto, tipo='merma', motivo='rotura', cantidad=3
        )
        url = reverse('stock:movimientostock_delete', kwargs={'pk': merma.pk})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertRedirects(self.client.post(url), reverse('stock:merma'))


class UsuariosDelSistemaTests(TestCase):
    """RN-25: dos roles, y el modulo de usuarios lo ve solo el administrador."""

    def setUp(self):
        self.admin = User.objects.create_user('jefe', password='jefe-1234', is_staff=True)
        self.empleado = User.objects.create_user('mozo', password='mozo-1234')

    # --- la puerta ---------------------------------------------------

    def test_el_empleado_no_entra_al_modulo(self):
        self.client.force_login(self.empleado)
        respuesta = self.client.get(reverse('stock:usuario_list'))
        self.assertRedirects(respuesta, reverse('stock:calendario'))

    def test_el_empleado_tampoco_puede_crear_por_POST(self):
        """Esconder el boton no alcanza: la URL tiene que frenar sola."""
        self.client.force_login(self.empleado)
        self.client.post(reverse('stock:usuario_create'), {
            'username': 'colado', 'password1': 'Salon-Victoria-99', 'password2': 'Salon-Victoria-99',
        })
        self.assertFalse(User.objects.filter(username='colado').exists())

    def test_el_administrador_entra(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('stock:usuario_list')).status_code, 200)

    def test_el_empleado_sigue_usando_lo_suyo(self):
        """El rol no lo deja afuera de lo operativo, que es a lo que viene."""
        self.client.force_login(self.empleado)
        self.assertEqual(self.client.get(reverse('stock:consumo_selector')).status_code, 200)
        self.assertEqual(self.client.get(reverse('stock:merma')).status_code, 200)

    # --- alta --------------------------------------------------------

    def test_crear_un_empleado_lo_deja_sin_is_staff(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('stock:usuario_create'), {
            'username': 'barman', 'password1': 'Salon-Victoria-99', 'password2': 'Salon-Victoria-99',
        })
        creado = User.objects.get(username='barman')
        self.assertFalse(creado.is_staff)

    def test_crear_marcando_administrador_lo_deja_con_is_staff(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('stock:usuario_create'), {
            'username': 'socio', 'password1': 'Salon-Victoria-99',
            'password2': 'Salon-Victoria-99', 'is_staff': 'on',
        })
        self.assertTrue(User.objects.get(username='socio').is_staff)

    def test_el_usuario_creado_puede_ingresar(self):
        """Lo unico que importa del modulo: que despues la persona entre."""
        self.client.force_login(self.admin)
        self.client.post(reverse('stock:usuario_create'), {
            'username': 'barman', 'password1': 'Salon-Victoria-99', 'password2': 'Salon-Victoria-99',
        })
        self.client.logout()
        self.assertTrue(self.client.login(username='barman', password='Salon-Victoria-99'))

    # --- edicion -----------------------------------------------------

    def test_degradar_a_empleado_saca_tambien_el_superusuario(self):
        """Sin esto el degradado conserva is_superuser y pasa cualquier permiso."""
        jefazo = User.objects.create_superuser('duenio', password='duenio-1234')
        self.client.force_login(self.admin)
        self.client.post(reverse('stock:usuario_update', kwargs={'pk': jefazo.pk}), {
            'username': 'duenio', 'is_active': 'on',
        })
        jefazo.refresh_from_db()
        self.assertFalse(jefazo.is_staff)
        self.assertFalse(jefazo.is_superuser)

    def test_nadie_se_saca_a_si_mismo_el_rol(self):
        """Quedaria afuera del modulo con la sesion abierta y sin como volver."""
        self.client.force_login(self.admin)
        self.client.post(reverse('stock:usuario_update', kwargs={'pk': self.admin.pk}), {
            'username': 'jefe',
        })
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_staff)
        self.assertTrue(self.admin.is_active)

    def test_desactivar_a_otro_le_saca_el_acceso_sin_borrarlo(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('stock:usuario_update', kwargs={'pk': self.empleado.pk}), {
            'username': 'mozo',
        })
        self.empleado.refresh_from_db()
        self.assertFalse(self.empleado.is_active)
        self.assertFalse(self.client.login(username='mozo', password='mozo-1234'))

    def test_cambiarle_la_contrasena_a_otro(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('stock:usuario_password', kwargs={'pk': self.empleado.pk}), {
            'new_password1': 'Otra-Clave-2026', 'new_password2': 'Otra-Clave-2026',
        })
        self.client.logout()
        self.assertTrue(self.client.login(username='mozo', password='Otra-Clave-2026'))

    # --- baja --------------------------------------------------------

    def test_borrar_a_otro_usuario(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('stock:usuario_delete', kwargs={'pk': self.empleado.pk}))
        self.assertFalse(User.objects.filter(username='mozo').exists())

    def test_nadie_se_borra_a_si_mismo(self):
        """Cerrar la puerta con la llave adentro: el ultimo admin se quedaria sin sistema."""
        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse('stock:usuario_delete', kwargs={'pk': self.admin.pk}))
        self.assertEqual(respuesta.status_code, 404)
        self.assertTrue(User.objects.filter(username='jefe').exists())


class RolEmpleadoTests(TestCase):
    """RN-25: el empleado carga consumos, carga merma y mira el calendario.

    La lista blanca vive en stock/middleware.py. Estos tests son su contrato:
    si alguien agrega una pantalla a PANTALLAS_DEL_EMPLEADO sin querer, o saca
    una que hace falta, se entera aca y no en el salon un sabado a la noche.
    """

    def setUp(self):
        self.empleado = User.objects.create_user('mozo', password='mozo-1234')
        self.admin = User.objects.create_user('jefe', password='jefe-1234', is_staff=True)
        self.producto = Producto.objects.create(
            nombre='Fernet', sector='barra', precio_unitario=100, stock_actual=50
        )
        self.evento = Evento.objects.create(
            nombre='Casamiento', fecha=date(2026, 9, 1), asistentes=100, estado='confirmado'
        )
        self.client.force_login(self.empleado)

    # --- lo que SI puede -------------------------------------------------

    def test_ve_sus_cuatro_pantallas(self):
        permitidas = [
            reverse('stock:calendario'),
            reverse('stock:consumo_selector'),
            reverse('stock:consumo_evento', kwargs={'evento_pk': self.evento.pk}),
            reverse('stock:merma'),
        ]
        for url in permitidas:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_carga_consumo_y_el_stock_baja(self):
        """Lo unico que el empleado TIENE que poder hacer."""
        self.client.post(
            reverse('stock:movimientostock_create', kwargs={'evento_pk': self.evento.pk}),
            {'producto': self.producto.pk, 'tipo': 'salida', 'cantidad': '6'},
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 44)
        self.assertTrue(
            MovimientoStock.objects.filter(evento=self.evento, tipo='salida').exists()
        )

    def test_carga_merma(self):
        self.client.post(reverse('stock:merma'), {
            'producto_id': self.producto.pk, 'cantidad': '2', 'motivo': 'rotura',
        })
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 48)

    # --- corregir lo suyo ------------------------------------------------

    def un_consumo(self, cantidad=6):
        return MovimientoStock.objects.create(
            producto=self.producto, evento=self.evento, tipo='salida', cantidad=cantidad
        )

    def test_ve_en_su_pantalla_lo_que_ya_cargo(self):
        """Sin esta tabla no tiene desde donde llegar al boton de corregir."""
        self.un_consumo()
        respuesta = self.client.get(
            reverse('stock:consumo_evento', kwargs={'evento_pk': self.evento.pk})
        )
        self.assertEqual(len(respuesta.context['cargado']), 1)

    def test_corrige_la_cantidad_de_su_consumo(self):
        movimiento = self.un_consumo(6)          # stock 50 -> 44
        self.client.post(
            reverse('stock:movimientostock_update', kwargs={'pk': movimiento.pk}),
            {'producto': self.producto.pk, 'tipo': 'salida', 'cantidad': '8', 'motivo': ''},
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 42)

    def test_borra_su_consumo_y_el_stock_vuelve(self):
        movimiento = self.un_consumo(6)
        self.client.post(reverse('stock:movimientostock_delete', kwargs={'pk': movimiento.pk}))
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 50)

    def test_al_corregir_vuelve_a_su_pantalla_y_no_al_detalle_del_evento(self):
        """Mandarlo a evento_detail seria rebotarlo con un cartel justo despues
        de corregir bien: esa pantalla la tiene prohibida."""
        movimiento = self.un_consumo()
        respuesta = self.client.post(
            reverse('stock:movimientostock_delete', kwargs={'pk': movimiento.pk})
        )
        self.assertRedirects(
            respuesta, reverse('stock:consumo_evento', kwargs={'evento_pk': self.evento.pk})
        )

    def test_no_toca_las_compras_del_salon(self):
        """Una reposicion de deposito no es suya: borrarla moveria el stock."""
        compra = MovimientoStock.objects.create(
            producto=self.producto, tipo='entrada', cantidad=20
        )
        url = reverse('stock:movimientostock_delete', kwargs={'pk': compra.pk})
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.post(url)
        self.assertTrue(MovimientoStock.objects.filter(pk=compra.pk).exists())

    def test_no_convierte_una_salida_en_entrada(self):
        """Cambiarle el tipo seria inventar mercaderia que nunca llego."""
        movimiento = self.un_consumo(6)          # stock 50 -> 44
        self.client.post(
            reverse('stock:movimientostock_update', kwargs={'pk': movimiento.pk}),
            {'producto': self.producto.pk, 'tipo': 'entrada', 'cantidad': '6', 'motivo': ''},
        )
        movimiento.refresh_from_db()
        self.producto.refresh_from_db()
        self.assertEqual(movimiento.tipo, 'salida')
        self.assertEqual(self.producto.stock_actual, 44)

    # --- lo que NO puede -------------------------------------------------

    def test_no_ve_las_pantallas_del_administrador(self):
        prohibidas = [
            reverse('stock:producto_list'),
            reverse('stock:compras'),
            reverse('stock:movimiento_list'),
            reverse('stock:evento_list'),
            reverse('stock:evento_historial'),
            reverse('stock:evento_detail', kwargs={'pk': self.evento.pk}),
            reverse('stock:empleado_list'),
            reverse('stock:menu_list'),
            reverse('stock:paquete_list'),
            reverse('stock:puesto_list'),
            reverse('stock:usuario_list'),
        ]
        for url in prohibidas:
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), reverse('stock:calendario'))

    def test_no_borra_un_evento_ni_por_POST(self):
        """Esconder el boton no alcanza: la URL suelta tiene que frenar sola."""
        self.client.post(reverse('stock:evento_delete', kwargs={'pk': self.evento.pk}))
        self.assertTrue(Evento.objects.filter(pk=self.evento.pk).exists())

    def test_no_carga_personal_ni_pagos(self):
        empleado = Empleado.objects.create(nombre='Juan')
        self.client.post(
            reverse('stock:personalevento_create', kwargs={'evento_pk': self.evento.pk}),
            {'empleado': empleado.pk, 'puesto': un_puesto().pk,
             'horas_trabajadas': '8', 'pago': '10000'},
        )
        self.assertFalse(PersonalEvento.objects.exists())

    def test_el_calendario_no_le_ofrece_el_detalle_del_evento(self):
        """La pantalla que SI ve no puede tener la puerta a la que no ve."""
        respuesta = self.client.get(reverse('stock:calendario'))
        self.assertNotContains(
            respuesta, reverse('stock:evento_detail', kwargs={'pk': self.evento.pk})
        )

    # --- la casa del empleado -------------------------------------------

    def test_el_panel_lo_manda_al_calendario_sin_retarlo(self):
        """`home` es LOGIN_REDIRECT_URL: cae ahi en cada ingreso sin tocar nada.

        Si eso disparara el mensaje de "solo para administradores", el empleado
        veria un modal de error cada vez que entra al sistema.
        """
        respuesta = self.client.get(reverse('stock:home'), follow=True)
        self.assertRedirects(respuesta, reverse('stock:calendario'))
        self.assertEqual(list(respuesta.context['messages']), [])

    def test_al_administrador_no_le_cambia_nada(self):
        self.client.force_login(self.admin)
        for url in [reverse('stock:home'), reverse('stock:producto_list'),
                    reverse('stock:evento_detail', kwargs={'pk': self.evento.pk}),
                    reverse('stock:usuario_list')]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class UnidadesDeMedidaTests(TestCase):
    """RN-26: la unidad es un catalogo que carga el dueno, no texto libre."""

    def setUp(self):
        self.usuario = User.objects.create_user('admin', password='x-1234', is_staff=True)
        self.client.force_login(self.usuario)

    def test_la_migracion_dejo_las_cuatro_del_dueno(self):
        self.assertEqual(
            sorted(UnidadMedida.objects.values_list('nombre', flat=True)),
            ['Cajas', 'Kilogramos', 'Litros', 'Unidad'],
        )

    def test_se_puede_cargar_una_unidad_nueva(self):
        """El punto de que sea tabla: agregar 'Botellas' no espera un deploy."""
        self.client.post(reverse('stock:unidad_create'), {'nombre': 'Botellas'})
        self.assertTrue(UnidadMedida.objects.filter(nombre='Botellas').exists())

    def test_no_se_repite_una_unidad(self):
        respuesta = self.client.post(reverse('stock:unidad_create'), {'nombre': 'Litros'})
        self.assertEqual(respuesta.status_code, 200, 'tiene que volver con el error')
        self.assertEqual(UnidadMedida.objects.filter(nombre='Litros').count(), 1)

    def test_una_unidad_sin_uso_se_borra(self):
        unidad = UnidadMedida.objects.create(nombre='Bidones')
        self.client.post(reverse('stock:unidad_delete', kwargs={'pk': unidad.pk}))
        self.assertFalse(UnidadMedida.objects.filter(pk=unidad.pk).exists())

    def test_una_unidad_en_uso_no_se_borra_y_avisa(self):
        """Sin unidad el stock queda en un numero suelto: '50' de que."""
        unidad = una_unidad('Kilogramos')
        Producto.objects.create(
            nombre='Carne', sector='cocina', stock_actual=20, unidad_medida=unidad
        )

        respuesta = self.client.post(
            reverse('stock:unidad_delete', kwargs={'pk': unidad.pk}), follow=True
        )

        self.assertTrue(UnidadMedida.objects.filter(pk=unidad.pk).exists())
        self.assertIn('no se puede borrar', str(list(respuesta.context['messages'])[0]))

    def test_el_producto_muestra_el_nombre_de_su_unidad(self):
        """Los 15 templates dicen {{ producto.unidad_medida }} y no se tocaron:
        con FK eso sale por __str__, asi que tiene que leerse igual que antes."""
        producto = Producto.objects.create(
            nombre='Fernet', sector='barra', stock_actual=5,
            unidad_medida=una_unidad('Litros'),
        )
        self.assertEqual(f'{producto.stock_actual:.0f} {producto.unidad_medida}', '5 Litros')


class ImprimirYModalTests(TestCase):
    """RN-28: el PDF lo hace el navegador, y el modal separa sus secciones."""

    def setUp(self):
        self.usuario = User.objects.create_user('admin', password='x-1234', is_staff=True)
        self.client.force_login(self.usuario)
        self.evento = Evento.objects.create(
            nombre='Boda', fecha=date(2026, 9, 1), asistentes=100
        )
        Producto.objects.create(
            nombre='Fernet', sector='barra', stock_actual=10, unidad_medida=una_unidad()
        )

    def test_las_tres_pantallas_tienen_el_boton(self):
        pantallas = [
            reverse('stock:evento_detail', kwargs={'pk': self.evento.pk}),
            reverse('stock:producto_list'),
            reverse('stock:evento_list'),
        ]
        for url in pantallas:
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertIn('window.print()', html)
                self.assertIn('Descargar PDF', html)

    def test_el_boton_no_se_imprime_a_si_mismo(self):
        """Sin `no-print` el PDF sale con el boton de descargar PDF adentro."""
        html = self.client.get(reverse('stock:producto_list')).content.decode()
        boton = html[html.index('window.print()') - 400:html.index('window.print()')]
        self.assertIn('no-print', boton)

    def test_el_modal_separa_las_secciones(self):
        """El <main> de base.html separa con gap; el fragmento no lo tenia.

        Sin esto, el detalle de un evento salia con todas sus secciones pegadas
        una abajo de la otra, y SOLO dentro del modal.
        """
        respuesta = self.client.get(
            reverse('stock:evento_detail', kwargs={'pk': self.evento.pk}),
            headers={'x-requested-with': 'XMLHttpRequest'},
        )
        html = respuesta.content.decode()
        self.assertNotIn('<html', html, 'el fragmento no trae la pagina entera (RN-22)')
        self.assertIn('flex flex-col gap-stack-lg', html)

    def test_la_tira_de_datos_no_usa_breakpoints_de_ventana(self):
        """grid-datos mide el contenedor; lg:grid-cols-6 mide la ventana, y en
        el modal dejaba las seis columnas encimadas."""
        html = self.client.get(
            reverse('stock:evento_detail', kwargs={'pk': self.evento.pk})
        ).content.decode()
        self.assertIn('class="grid-datos"', html)
        # El patron exacto que habia, para que nadie lo reponga sin darse cuenta.
        self.assertNotIn('grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6', html)


class VolverALaPestanaTests(TestCase):
    """Tocar un producto de Extras tiene que devolverte a Extras, no a Barra."""

    def setUp(self):
        self.usuario = User.objects.create_user('admin', password='x-1234', is_staff=True)
        self.client.force_login(self.usuario)
        self.producto = Producto.objects.create(
            nombre='Servilletas', sector='extras', stock_actual=100,
            unidad_medida=una_unidad(),
        )

    def test_al_crear_vuelve_a_la_pestana_del_sector(self):
        respuesta = self.client.post(reverse('stock:producto_create'), {
            'nombre': 'Lavandina', 'sector': 'limpieza', 'precio_unitario': '900',
            'stock_actual': '4', 'unidad_medida': una_unidad('Litros').pk,
        })
        self.assertTrue(respuesta.url.endswith('#limpieza-pane'), respuesta.url)

    def test_al_editar_vuelve_a_la_pestana_del_sector(self):
        respuesta = self.client.post(
            reverse('stock:producto_update', kwargs={'pk': self.producto.pk}),
            {'nombre': 'Servilletas', 'sector': 'extras', 'precio_unitario': '100',
             'unidad_medida': una_unidad().pk},
        )
        self.assertTrue(respuesta.url.endswith('#extras-pane'), respuesta.url)

    def test_al_borrar_vuelve_a_la_pestana_del_sector(self):
        respuesta = self.client.post(
            reverse('stock:producto_delete', kwargs={'pk': self.producto.pk})
        )
        self.assertTrue(respuesta.url.endswith('#extras-pane'), respuesta.url)

    def test_al_dar_de_baja_uno_con_historial_tambien_vuelve_a_su_pestana(self):
        """El camino del ProtectedError es otro `return`: se olvida facil."""
        MovimientoStock.objects.create(producto=self.producto, tipo='entrada', cantidad=5)

        respuesta = self.client.post(
            reverse('stock:producto_delete', kwargs={'pk': self.producto.pk})
        )

        self.producto.refresh_from_db()
        self.assertFalse(self.producto.activo, 'con historial se da de baja, no se borra')
        self.assertTrue(respuesta.url.endswith('#extras-pane'), respuesta.url)

    def test_al_reactivar_tambien(self):
        self.producto.dar_de_baja()
        respuesta = self.client.post(
            reverse('stock:producto_reactivar', kwargs={'pk': self.producto.pk})
        )
        self.assertTrue(respuesta.url.endswith('#extras-pane'), respuesta.url)
