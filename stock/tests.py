"""Tests de caracterizacion del comportamiento actual del stock.

Escritos ANTES del rediseno para tener red de seguridad: documentan como
deberia comportarse el sistema. Los que estan marcados como bug fallan hoy
a proposito y tienen que pasar cuando se apliquen los arreglos.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import (
    CargoEvento,
    Empleado,
    Evento,
    LineaReceta,
    Menu,
    MovimientoStock,
    PersonalEvento,
    Plato,
    Producto,
    Puesto,
)


def un_puesto(nombre='Mozo'):
    """El puesto ya no es texto libre: es una fila del catalogo (Puesto)."""
    return Puesto.objects.get_or_create(nombre=nombre)[0]


def una_receta(dueno, producto, cantidad, paso='principal', nombre='Plato'):
    """Un plato de un solo ingrediente, que es lo que la mayoria de los tests necesita."""
    plato = Plato.objects.create(paso=paso, nombre=nombre, **dueno)
    LineaReceta.objects.create(plato=plato, producto=producto, cantidad_por_persona=cantidad)
    return plato


class ClienteLogueadoTests(TestCase):
    """Base para los tests que navegan: el sistema entero pide sesión."""

    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_user('tester', password='tester-1234'))


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
            stock_actual=Decimal('10.50'), unidad_medida='kg',
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

    def test_precio_por_persona_se_multiplica_por_los_asistentes(self):
        self.evento.precio_por_persona = 5000
        self.assertEqual(self.evento.ingreso_base, 500000)

    def test_precio_cerrado_manda_sobre_el_precio_por_persona(self):
        self.evento.precio_por_persona = 5000
        self.evento.precio_cerrado = 400000
        self.assertEqual(self.evento.ingreso_base, 400000)

    def test_un_evento_sin_asistentes_con_precio_por_persona_da_cero(self):
        """'Casamiento Nascar' existe y tiene 0 asistentes: para eso está el cerrado."""
        self.evento.asistentes = 0
        self.evento.precio_por_persona = 5000
        self.assertEqual(self.evento.ingreso_base, 0)

    def test_los_cargos_suman_al_ingreso(self):
        self.evento.precio_cerrado = 400000
        self.evento.save()
        CargoEvento.objects.create(evento=self.evento, concepto='Barra libre', monto=80000)
        CargoEvento.objects.create(evento=self.evento, concepto='DJ', monto=50000)

        self.assertEqual(self.evento.ingreso_cargos, 130000)
        self.assertEqual(self.evento.ingreso_total, 530000)

    def test_el_margen_es_lo_facturado_menos_lo_gastado(self):
        self.evento.precio_cerrado = 500000
        self.evento.save()
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
        self.evento.precio_cerrado = 100000
        self.evento.save()
        PersonalEvento.objects.create(
            evento=self.evento, empleado=self.empleado, puesto=un_puesto('Mozo'), pago=150000
        )
        self.assertEqual(self.evento.margen, -50000)

    def test_el_porcentaje_de_margen(self):
        self.evento.precio_cerrado = 200000
        self.evento.save()
        PersonalEvento.objects.create(
            evento=self.evento, empleado=self.empleado, puesto=un_puesto('Mozo'), pago=50000
        )
        self.assertEqual(self.evento.margen_porcentaje, 75)

    def test_la_merma_no_le_come_el_margen_al_evento(self):
        """El choque que abrió toda la auditoría, ahora medido."""
        self.evento.precio_cerrado = 500000
        self.evento.save()
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


class RecetaTests(TestCase):
    """RN-18 y RN-19: la receta se carga en el menu, costea y sugiere.

    La receta vive organizada por platos (entrante, principal, postre...) y cada
    plato lleva sus ingredientes medidos por persona.
    """

    def setUp(self):
        self.carne = Producto.objects.create(
            nombre='Carne', sector='cocina', precio_unitario=8000,
            stock_actual=500, unidad_medida='kg'
        )
        self.vino = Producto.objects.create(
            nombre='Vino', sector='barra', precio_unitario=3000,
            stock_actual=500, unidad_medida='botella'
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
            nombre='Casamiento', fecha=date(2025, 6, 1), precio_cerrado=900000
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
             'unidad_medida': 'unidad'},
            **self.CABECERA,
        )
        self.assertEqual(respuesta.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.nombre, 'Fernet 1L')

    def test_un_form_con_errores_vuelve_como_fragmento_y_no_redirige(self):
        respuesta = self.client.post(
            reverse('stock:producto_update', kwargs={'pk': self.producto.pk}),
            {'nombre': '', 'sector': 'barra', 'precio_unitario': '5000', 'unidad_medida': 'unidad'},
            **self.CABECERA,
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn('<html', respuesta.content.decode())


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
        self.client.force_login(User.objects.create_user('tester', password='tester-1234'))
        self.assertEqual(self.client.get(reverse('stock:home')).status_code, 200)

    def test_se_puede_cerrar_sesion(self):
        self.client.force_login(User.objects.create_user('tester', password='tester-1234'))
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
            'stock_actual': '12', 'unidad_medida': 'unidad',
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
            'stock_actual': '999', 'unidad_medida': 'unidad',
        })
        producto.refresh_from_db()
        self.assertEqual(producto.stock_actual, 7, 'el stock no se toca desde el form')

    def test_el_libro_mayor_cierra_con_el_stock(self):
        """Lo que separa un inventario confiable de una planilla suelta."""
        self.client.post(reverse('stock:producto_create'), {
            'nombre': 'Tonica', 'sector': 'barra', 'precio_unitario': '900',
            'stock_actual': '20', 'unidad_medida': 'unidad',
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
