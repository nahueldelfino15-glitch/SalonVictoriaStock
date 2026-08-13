from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = 'stock'

urlpatterns = [
    path('', views.home, name='home'),

    # Autenticación con las vistas que ya trae Django: el único trabajo propio
    # es el template. LogoutView solo acepta POST desde Django 5.
    path('ingresar/', auth_views.LoginView.as_view(
        template_name='stock/login.html',
        redirect_authenticated_user=True,
    ), name='login'),
    path('salir/', auth_views.LogoutView.as_view(), name='logout'),

    path('productos/', views.ProductoListView.as_view(), name='producto_list'),
    path('productos/<int:pk>/', views.ProductoDetailView.as_view(), name='producto_detail'),
    path('productos/nuevo/', views.ProductoCreateView.as_view(), name='producto_create'),
    path('productos/<int:pk>/editar/', views.ProductoUpdateView.as_view(), name='producto_update'),
    path('productos/<int:pk>/eliminar/', views.ProductoDeleteView.as_view(), name='producto_delete'),
    path('productos/<int:pk>/reactivar/', views.reactivar_producto, name='producto_reactivar'),

    path('eventos/', views.EventoListView.as_view(), name='evento_list'),
    path('eventos/<int:pk>/', views.EventoDetailView.as_view(), name='evento_detail'),
    path('eventos/nuevo/', views.EventoCreateView.as_view(), name='evento_create'),
    path('eventos/<int:pk>/editar/', views.EventoUpdateView.as_view(), name='evento_update'),
    path('eventos/<int:pk>/eliminar/', views.EventoDeleteView.as_view(), name='evento_delete'),
    path('eventos/<int:pk>/reabrir/', views.reabrir_evento, name='evento_reabrir'),

    path('eventos/<int:evento_pk>/cargos/nuevo/', views.CargoEventoCreateView.as_view(), name='cargoevento_create'),
    path('cargos/<int:pk>/editar/', views.CargoEventoUpdateView.as_view(), name='cargoevento_update'),
    path('cargos/<int:pk>/eliminar/', views.CargoEventoDeleteView.as_view(), name='cargoevento_delete'),

    path('menus/<int:menu_pk>/platos/nuevo/', views.PlatoCreateView.as_view(), name='plato_create'),
    path('platos/<int:pk>/', views.PlatoDetailView.as_view(), name='plato_detail'),
    path('platos/<int:pk>/editar/', views.PlatoUpdateView.as_view(), name='plato_update'),
    path('platos/<int:pk>/eliminar/', views.PlatoDeleteView.as_view(), name='plato_delete'),

    path('platos/<int:plato_pk>/ingredientes/nuevo/', views.LineaRecetaCreateView.as_view(), name='lineareceta_create'),
    path('ingredientes/<int:pk>/editar/', views.LineaRecetaUpdateView.as_view(), name='lineareceta_update'),
    path('ingredientes/<int:pk>/eliminar/', views.LineaRecetaDeleteView.as_view(), name='lineareceta_delete'),
    path('eventos/<int:pk>/receta/copiar/', views.copiar_receta, name='evento_copiar_receta'),

    path('empleados/', views.EmpleadoListView.as_view(), name='empleado_list'),
    path('empleados/<int:pk>/', views.EmpleadoDetailView.as_view(), name='empleado_detail'),
    path('empleados/nuevo/', views.EmpleadoCreateView.as_view(), name='empleado_create'),
    path('empleados/<int:pk>/editar/', views.EmpleadoUpdateView.as_view(), name='empleado_update'),
    path('empleados/<int:pk>/eliminar/', views.EmpleadoDeleteView.as_view(), name='empleado_delete'),

    path('puestos/', views.PuestoListView.as_view(), name='puesto_list'),
    path('puestos/nuevo/', views.PuestoCreateView.as_view(), name='puesto_create'),
    path('puestos/<int:pk>/editar/', views.PuestoUpdateView.as_view(), name='puesto_update'),
    path('puestos/<int:pk>/eliminar/', views.PuestoDeleteView.as_view(), name='puesto_delete'),

    path('eventos/<int:evento_pk>/personal/nuevo/', views.PersonalEventoCreateView.as_view(), name='personalevento_create'),
    path('personal-evento/<int:pk>/editar/', views.PersonalEventoUpdateView.as_view(), name='personalevento_update'),
    path('personal-evento/<int:pk>/eliminar/', views.PersonalEventoDeleteView.as_view(), name='personalevento_delete'),

    path('eventos/historial/', views.EventoHistorialListView.as_view(), name='evento_historial'),
    path('eventos/<int:evento_pk>/consumo/nuevo/', views.MovimientoStockCreateView.as_view(), name='movimientostock_create'),
    path('consumo/<int:pk>/editar/', views.MovimientoStockUpdateView.as_view(), name='movimientostock_update'),
    path('consumo/<int:pk>/eliminar/', views.MovimientoStockDeleteView.as_view(), name='movimientostock_delete'),

    path('compras/', views.compras, name='compras'),
    path('merma/', views.merma, name='merma'),
    path('calendario/', views.calendario_eventos, name='calendario'),

    path('paquetes/', views.PaqueteListView.as_view(), name='paquete_list'),
    path('paquetes/<int:pk>/', views.PaqueteDetailView.as_view(), name='paquete_detail'),
    path('paquetes/nuevo/', views.PaqueteCreateView.as_view(), name='paquete_create'),
    path('paquetes/<int:pk>/editar/', views.PaqueteUpdateView.as_view(), name='paquete_update'),
    path('paquetes/<int:pk>/eliminar/', views.PaqueteDeleteView.as_view(), name='paquete_delete'),

    path('menus/', views.MenuListView.as_view(), name='menu_list'),
    path('menus/<int:pk>/', views.MenuDetailView.as_view(), name='menu_detail'),
    path('menus/nuevo/', views.MenuCreateView.as_view(), name='menu_create'),
    path('menus/<int:pk>/editar/', views.MenuUpdateView.as_view(), name='menu_update'),
    path('menus/<int:pk>/eliminar/', views.MenuDeleteView.as_view(), name='menu_delete'),

    path('consumo/', views.consumo_selector, name='consumo_selector'),
    path('consumo/<int:evento_pk>/', views.consumo_evento, name='consumo_evento'),
]