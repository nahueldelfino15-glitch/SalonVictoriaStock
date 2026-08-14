"""Smoke de render: recorre TODAS las pantallas, entera y como fragmento de modal.

Un 200 no alcanza como prueba de que un template esta bien: Django resuelve una
variable inexistente a '' y sigue como si nada, asi que un typo o un atributo que
se renombro pasan sin ruido. Aca se pisa `string_if_invalid` con una marca y se
falla si aparece en el HTML.

El modo modal ademas verifica que el fragmento NO traiga la pagina entera (RN-22).

Al agregar una pantalla, sumala a urls(): es la red que atrapa las URLs muertas
despues de un renombre.
"""
import re
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    CargoEvento, Empleado, Evento, LineaReceta, Menu, MovimientoStock,
    Paquete, PersonalEvento, Plato, Producto, Puesto, TarjetaEvento,
)

MARCA = '<<<INVALIDO:%s>>>'

TEMPLATES_MARCADAS = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'string_if_invalid': MARCA,
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'stock.context_processors.modal',
            ],
        },
    },
]


@override_settings(TEMPLATES=TEMPLATES_MARCADAS)
class RenderSmoke(TestCase):
    maxDiff = None

    def setUp(self):
        # Administrador (is_staff): sin eso las pantallas de usuarios redirigen
        # en vez de renderizar, y el smoke las contaria como rotas (RN-25).
        self.usuario = User.objects.create_user('tester', password='x-1234', is_staff=True)
        self.otro_usuario = User.objects.create_user('mozo', password='x-1234')
        self.client.force_login(self.usuario)

        self.puesto = Puesto.objects.get_or_create(nombre='Mozo')[0]
        self.empleado = Empleado.objects.create(nombre='Juan', puesto_habitual=self.puesto)

        self.p_barra = Producto.objects.create(nombre='Fernet', sector='barra',
                                               precio_unitario=Decimal('100'), stock_actual=Decimal('50'))
        self.p_cocina = Producto.objects.create(nombre='Carne', sector='cocina',
                                                precio_unitario=Decimal('200'), stock_actual=Decimal('80'))
        self.p_extras = Producto.objects.create(nombre='Servilletas', sector='extras',
                                                precio_unitario=Decimal('5'), stock_actual=Decimal('300'))
        self.p_baja = Producto.objects.create(nombre='Vino viejo', sector='barra',
                                              precio_unitario=Decimal('50'), stock_actual=Decimal('0'),
                                              activo=False)

        self.paquete = Paquete.objects.create(nombre='Premium', precio=Decimal('1000'))
        self.menu = Menu.objects.create(nombre='Menu Clasico', descripcion='Rico')
        self.plato_menu = Plato.objects.create(menu=self.menu, paso='principal', nombre='Bife')
        self.linea_menu = LineaReceta.objects.create(plato=self.plato_menu, producto=self.p_cocina,
                                                     cantidad_por_persona=Decimal('0.200'))

        self.evento = Evento.objects.create(nombre='Casamiento', fecha=date(2026, 9, 1),
                                            asistentes=100, estado='confirmado',
                                            paquete=self.paquete, menu=self.menu,
                                            precio_por_persona=Decimal('500'))
        self.p_limpieza = Producto.objects.create(nombre='Lavandina', sector='limpieza',
                                                  precio_unitario=Decimal('50'), stock_actual=Decimal('20'))
        self.p_mobiliario = Producto.objects.create(nombre='Mantel', sector='mobiliario',
                                                    precio_unitario=Decimal('0'), stock_actual=Decimal('40'))

        self.menu_infantil = Menu.objects.create(nombre='Infantil')
        plato_infantil = Plato.objects.create(menu=self.menu_infantil, paso='principal', nombre='Nuggets')
        LineaReceta.objects.create(plato=plato_infantil, producto=self.p_cocina,
                                   cantidad_por_persona=Decimal('0.150'))

        self.cargo = CargoEvento.objects.create(evento=self.evento, concepto='DJ', monto=Decimal('300'))
        self.pe = PersonalEvento.objects.create(evento=self.evento, empleado=self.empleado,
                                                puesto=self.puesto, horas_trabajadas=Decimal('8'),
                                                pago=Decimal('1000'))
        self.mov_salida = MovimientoStock.objects.create(producto=self.p_barra, evento=self.evento,
                                                         tipo='salida', cantidad=Decimal('5'))
        self.mov_entrada = MovimientoStock.objects.create(producto=self.p_barra, tipo='entrada',
                                                          cantidad=Decimal('10'))
        self.mov_merma = MovimientoStock.objects.create(producto=self.p_barra, tipo='merma',
                                                        motivo='rotura', cantidad=Decimal('1'))

        self.tarjeta = TarjetaEvento.objects.create(evento=self.evento, concepto='Adultos',
                                                    cantidad=80, valor_unitario=Decimal('500'),
                                                    menu=self.menu)
        TarjetaEvento.objects.create(evento=self.evento, concepto='Menú infantil',
                                     cantidad=20, valor_unitario=Decimal('300'),
                                     menu=self.menu_infantil)
        self.evento.brindis_asistentes = 60
        self.evento.brindis_valor = Decimal('80')
        self.evento.save()

        # Los platos del evento se leen DESPUES de las tarjetas: cargar una
        # recopia la receta (borra y recrea), asi que los pk de antes ya no valen.
        self.plato_evento = self.evento.platos.first()
        self.linea_evento = LineaReceta.objects.filter(plato__evento=self.evento).first()

        self.evento_cerrado = Evento.objects.create(nombre='Cumple viejo', fecha=date(2025, 1, 1),
                                                    asistentes=50, estado='finalizado')

    # ---------------------------------------------------------------

    def urls(self):
        e = self.evento.pk
        return [
            ('home', reverse('stock:home')),
            ('calendario', reverse('stock:calendario')),
            ('producto_list', reverse('stock:producto_list')),
            ('producto_list_bajas', reverse('stock:producto_list') + '?bajas=1'),
            ('producto_detail', reverse('stock:producto_detail', args=[self.p_barra.pk])),
            ('producto_create', reverse('stock:producto_create')),
            ('producto_update', reverse('stock:producto_update', args=[self.p_barra.pk])),
            ('producto_delete', reverse('stock:producto_delete', args=[self.p_barra.pk])),
            ('evento_list', reverse('stock:evento_list')),
            ('evento_historial', reverse('stock:evento_historial')),
            ('evento_detail', reverse('stock:evento_detail', args=[e])),
            ('evento_detail_cerrado', reverse('stock:evento_detail', args=[self.evento_cerrado.pk])),
            ('evento_create', reverse('stock:evento_create')),
            ('evento_update', reverse('stock:evento_update', args=[e])),
            ('evento_delete', reverse('stock:evento_delete', args=[e])),
            ('cargoevento_create', reverse('stock:cargoevento_create', args=[e])),
            ('cargoevento_update', reverse('stock:cargoevento_update', args=[self.cargo.pk])),
            ('cargoevento_delete', reverse('stock:cargoevento_delete', args=[self.cargo.pk])),
            ('plato_create', reverse('stock:plato_create', args=[self.menu.pk])),
            ('plato_create_paso', reverse('stock:plato_create', args=[self.menu.pk]) + '?paso=postre'),
            ('plato_detail', reverse('stock:plato_detail', args=[self.plato_menu.pk])),
            ('plato_update', reverse('stock:plato_update', args=[self.plato_menu.pk])),
            ('plato_delete', reverse('stock:plato_delete', args=[self.plato_menu.pk])),
            ('plato_detail_evento', reverse('stock:plato_detail', args=[self.plato_evento.pk])),
            ('plato_update_evento', reverse('stock:plato_update', args=[self.plato_evento.pk])),
            ('plato_delete_evento', reverse('stock:plato_delete', args=[self.plato_evento.pk])),
            ('lineareceta_create', reverse('stock:lineareceta_create', args=[self.plato_menu.pk])),
            ('lineareceta_update', reverse('stock:lineareceta_update', args=[self.linea_menu.pk])),
            ('lineareceta_delete', reverse('stock:lineareceta_delete', args=[self.linea_menu.pk])),
            ('lineareceta_update_evento', reverse('stock:lineareceta_update', args=[self.linea_evento.pk])),
            ('lineareceta_delete_evento', reverse('stock:lineareceta_delete', args=[self.linea_evento.pk])),
            ('empleado_list', reverse('stock:empleado_list')),
            ('empleado_detail', reverse('stock:empleado_detail', args=[self.empleado.pk])),
            ('empleado_create', reverse('stock:empleado_create')),
            ('empleado_update', reverse('stock:empleado_update', args=[self.empleado.pk])),
            ('empleado_delete', reverse('stock:empleado_delete', args=[self.empleado.pk])),
            ('puesto_list', reverse('stock:puesto_list')),
            ('puesto_create', reverse('stock:puesto_create')),
            ('puesto_update', reverse('stock:puesto_update', args=[self.puesto.pk])),
            ('puesto_delete', reverse('stock:puesto_delete', args=[self.puesto.pk])),
            ('personalevento_create', reverse('stock:personalevento_create', args=[e])),
            ('personalevento_update', reverse('stock:personalevento_update', args=[self.pe.pk])),
            ('personalevento_delete', reverse('stock:personalevento_delete', args=[self.pe.pk])),
            ('movimientostock_create', reverse('stock:movimientostock_create', args=[e])),
            ('movimientostock_update', reverse('stock:movimientostock_update', args=[self.mov_salida.pk])),
            ('movimientostock_update_merma', reverse('stock:movimientostock_update', args=[self.mov_merma.pk])),
            ('movimientostock_delete', reverse('stock:movimientostock_delete', args=[self.mov_salida.pk])),
            ('movimientostock_delete_merma', reverse('stock:movimientostock_delete', args=[self.mov_merma.pk])),
            ('compras', reverse('stock:compras')),
            ('merma', reverse('stock:merma')),
            ('paquete_list', reverse('stock:paquete_list')),
            ('paquete_detail', reverse('stock:paquete_detail', args=[self.paquete.pk])),
            ('paquete_create', reverse('stock:paquete_create')),
            ('paquete_update', reverse('stock:paquete_update', args=[self.paquete.pk])),
            ('paquete_delete', reverse('stock:paquete_delete', args=[self.paquete.pk])),
            ('menu_list', reverse('stock:menu_list')),
            ('menu_detail', reverse('stock:menu_detail', args=[self.menu.pk])),
            ('menu_create', reverse('stock:menu_create')),
            ('menu_update', reverse('stock:menu_update', args=[self.menu.pk])),
            ('menu_delete', reverse('stock:menu_delete', args=[self.menu.pk])),
            ('consumo_selector', reverse('stock:consumo_selector')),
            ('consumo_evento', reverse('stock:consumo_evento', args=[e])),
            ('movimiento_list', reverse('stock:movimiento_list')),
            ('movimiento_list_filtrado', reverse('stock:movimiento_list')
                + '?tipo=salida&sector=barra&q=fer&evento=%s&desde=2020-01-01&hasta=2030-12-31' % e),
            ('movimiento_list_basura', reverse('stock:movimiento_list')
                + '?desde=no-es-fecha&evento=abc'),
            ('movimiento_list_vacio', reverse('stock:movimiento_list') + '?q=zzzznoexiste'),
            ('tarjetaevento_create', reverse('stock:tarjetaevento_create', args=[e])),
            ('tarjetaevento_update', reverse('stock:tarjetaevento_update', args=[self.tarjeta.pk])),
            ('tarjetaevento_delete', reverse('stock:tarjetaevento_delete', args=[self.tarjeta.pk])),
            ('producto_detail_mobiliario', reverse('stock:producto_detail', args=[self.p_mobiliario.pk])),
            ('producto_update_mobiliario', reverse('stock:producto_update', args=[self.p_mobiliario.pk])),
            ('menu_detail_infantil', reverse('stock:menu_detail', args=[self.menu_infantil.pk])),
            ('usuario_list', reverse('stock:usuario_list')),
            ('usuario_list_busqueda', reverse('stock:usuario_list') + '?q=moz'),
            ('usuario_create', reverse('stock:usuario_create')),
            ('usuario_update', reverse('stock:usuario_update', args=[self.otro_usuario.pk])),
            # Editarse a uno mismo deshabilita campos: es otro render, no el mismo.
            ('usuario_update_propio', reverse('stock:usuario_update', args=[self.usuario.pk])),
            ('usuario_password', reverse('stock:usuario_password', args=[self.otro_usuario.pk])),
            ('usuario_delete', reverse('stock:usuario_delete', args=[self.otro_usuario.pk])),
        ]

    def test_render_pagina_entera(self):
        fallas = []
        for nombre, url in self.urls():
            try:
                r = self.client.get(url)
            except Exception as exc:
                fallas.append(f'{nombre} {url} EXCEPCION {type(exc).__name__}: {exc}')
                continue
            if r.status_code != 200:
                fallas.append(f'{nombre} {url} status {r.status_code}')
                continue
            html = r.content.decode()
            invalidos = sorted(set(re.findall(r'<<<INVALIDO:(.*?)>>>', html)))
            if invalidos:
                fallas.append(f'{nombre} {url} vars invalidas: {invalidos}')
        self.assertEqual(fallas, [], '\n'.join(fallas))

    def test_render_modal(self):
        fallas = []
        for nombre, url in self.urls():
            try:
                r = self.client.get(url, headers={'x-requested-with': 'XMLHttpRequest'})
            except Exception as exc:
                fallas.append(f'{nombre} {url} EXCEPCION {type(exc).__name__}: {exc}')
                continue
            if r.status_code != 200:
                fallas.append(f'{nombre} {url} status {r.status_code}')
                continue
            html = r.content.decode()
            invalidos = sorted(set(re.findall(r'<<<INVALIDO:(.*?)>>>', html)))
            if invalidos:
                fallas.append(f'{nombre} {url} vars invalidas: {invalidos}')
            if '<html' in html.lower():
                fallas.append(f'{nombre} {url} devolvio la pagina ENTERA en modo modal')
        self.assertEqual(fallas, [], '\n'.join(fallas))
