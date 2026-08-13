from django.urls import path 
from . import views

app_name = 'stock'

urlpatterns = [
    path('', views.home, name='home'),

    path('productos/', views.ProductoListView.as_view(), name='producto_list'),
    path('productos/<int:pk>/', views.ProductoDetailView.as_view(), name='producto_detail'),
    path('productos/nuevo/', views.ProductoCreateView.as_view(), name='producto_create'),
    path('productos/<int:pk>/editar/', views.ProductoUpdateView.as_view(), name='producto_update'),
    path('productos/<int:pk>/eliminar/', views.ProductoDeleteView.as_view(), name='producto_delete'),

    path('eventos/', views.EventoListView.as_view(), name='evento_list'),
    path('eventos/<int:pk>/', views.EventoDetailView.as_view(), name='evento_detail'),
    path('eventos/nuevo/', views.EventoCreateView.as_view(), name='evento_create'),
    path('eventos/<int:pk>/editar/', views.EventoUpdateView.as_view(), name='evento_update'),
    path('eventos/<int:pk>/eliminar/', views.EventoDeleteView.as_view(), name='evento_delete'),

    path('empleados/', views.EmpleadoListView.as_view(), name='empleado_list'),
    path('empleados/<int:pk>/', views.EmpleadoDetailView.as_view(), name='empleado_detail'),
    path('empleados/nuevo/', views.EmpleadoCreateView.as_view(), name='empleado_create'),
    path('empleados/<int:pk>/editar/', views.EmpleadoUpdateView.as_view(), name='empleado_update'),
    path('empleados/<int:pk>/eliminar/', views.EmpleadoDeleteView.as_view(), name='empleado_delete'),

    path('eventos/<int:evento_pk>/personal/nuevo/', views.PersonalEventoCreateView.as_view(), name='personalevento_create'),
    path('personal-evento/<int:pk>/editar/', views.PersonalEventoUpdateView.as_view(), name='personalevento_update'),
    path('personal-evento/<int:pk>/eliminar/', views.PersonalEventoDeleteView.as_view(), name='personalevento_delete'),

    path('eventos/historial/', views.EventoHistorialListView.as_view(), name='evento_historial'),
    path('eventos/<int:evento_pk>/consumo/nuevo/', views.MovimientoStockCreateView.as_view(), name='movimientostock_create'),
    path('consumo/<int:pk>/editar/', views.MovimientoStockUpdateView.as_view(), name='movimientostock_update'),
    path('consumo/<int:pk>/eliminar/', views.MovimientoStockDeleteView.as_view(), name='movimientostock_delete'),

    path('compras/', views.compras, name='compras'),
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