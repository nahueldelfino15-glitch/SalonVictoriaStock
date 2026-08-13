from django.urls import reverse_lazy, reverse
from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from .models import Producto, Evento, Empleado, PersonalEvento, MovimientoStock
from django.shortcuts import render, get_object_or_404, redirect
from .models import Producto, Evento, Empleado, PersonalEvento, MovimientoStock, SECTOR_CHOICES
import calendar
from datetime import date
from .models import Producto, Evento, Empleado, PersonalEvento, MovimientoStock, Paquete, Menu
from django.db.models.functions import Lower
from django.contrib import messages


MESES_ES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
            'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

def home(request):
    year = request.GET.get('year')
    month = request.GET.get('month')
    year = int(year) if year else None
    month = int(month) if month else None
    context = obtener_datos_calendario(year, month)
    return render(request, 'stock/home.html', context)

# ---------- Producto ----------
class ProductoListView(ListView):
    model = Producto
    template_name = 'stock/producto_list.html'
    context_object_name = 'productos'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        q = self.request.GET.get('q', '')
        context['productos_barra'] = Producto.objects.filter(sector='barra', nombre__icontains=q).order_by(Lower('nombre'))
        context['productos_cocina'] = Producto.objects.filter(sector='cocina', nombre__icontains=q).order_by(Lower('nombre'))
        context['productos_extras'] = Producto.objects.filter(sector='extras', nombre__icontains=q).order_by(Lower('nombre'))
        context['q'] = q
        return context


class ProductoDetailView(DetailView):
    model = Producto
    template_name = 'stock/producto_detail.html'


class ProductoCreateView(CreateView):
    model = Producto
    fields = ['nombre', 'sector', 'precio_unitario', 'stock_actual', 'unidad_medida']
    template_name = 'stock/producto_form.html'
    success_url = reverse_lazy('stock:producto_list')


class ProductoUpdateView(UpdateView):
    model = Producto
    fields = ['nombre', 'sector', 'precio_unitario', 'stock_actual', 'unidad_medida']
    template_name = 'stock/producto_form.html'
    success_url = reverse_lazy('stock:producto_list')


class ProductoDeleteView(DeleteView):
    model = Producto
    template_name = 'stock/producto_confirm_delete.html'
    success_url = reverse_lazy('stock:producto_list')


# ---------- Evento ----------
class EventoListView(ListView):
    model = Evento
    template_name = 'stock/evento_list.html'
    context_object_name = 'eventos'
    ordering = ['fecha']

    def get_queryset(self):
        queryset = super().get_queryset().exclude(estado='finalizado')
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(nombre__icontains=q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '')
        return context
    
class EventoHistorialListView(ListView):
    model = Evento
    template_name = 'stock/evento_historial.html'
    context_object_name = 'eventos'

    def get_queryset(self):
        queryset = Evento.objects.filter(estado='finalizado').order_by('-fecha')
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(nombre__icontains=q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '')
        return context

class EventoDetailView(DetailView):
    model = Evento
    template_name = 'stock/evento_detail.html'


class EventoCreateView(CreateView):
    model = Evento
    fields = ['nombre', 'fecha', 'asistentes', 'estado', 'paquete', 'menu', 'telefono_contacto', 'notas']
    template_name = 'stock/evento_form.html'
    success_url = reverse_lazy('stock:evento_list')


class EventoUpdateView(UpdateView):
    model = Evento
    fields = ['nombre', 'fecha', 'asistentes', 'estado', 'paquete', 'menu', 'telefono_contacto', 'notas']
    template_name = 'stock/evento_form.html'
    success_url = reverse_lazy('stock:evento_list')


class EventoDeleteView(DeleteView):
    model = Evento
    template_name = 'stock/evento_confirm_delete.html'
    success_url = reverse_lazy('stock:evento_list')


# ---------- Empleado ----------
class EmpleadoListView(ListView):
    model = Empleado
    template_name = 'stock/empleado_list.html'
    context_object_name = 'empleados'

    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(nombre__icontains=q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '')
        return context


class EmpleadoDetailView(DetailView):
    model = Empleado
    template_name = 'stock/empleado_detail.html'


class EmpleadoCreateView(CreateView):
    model = Empleado
    fields = ['nombre', 'telefono', 'puesto_habitual']
    template_name = 'stock/empleado_form.html'
    success_url = reverse_lazy('stock:empleado_list')


class EmpleadoUpdateView(UpdateView):
    model = Empleado
    fields = ['nombre', 'telefono', 'puesto_habitual']
    template_name = 'stock/empleado_form.html'
    success_url = reverse_lazy('stock:empleado_list')


class EmpleadoDeleteView(DeleteView):
    model = Empleado
    template_name = 'stock/empleado_confirm_delete.html'
    success_url = reverse_lazy('stock:empleado_list')


# ---------- Personal asignado a un Evento ----------
class PersonalEventoCreateView(CreateView):
    model = PersonalEvento
    fields = ['empleado', 'puesto', 'horas_trabajadas', 'pago']
    template_name = 'stock/personalevento_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.evento = get_object_or_404(Evento, pk=self.kwargs['evento_pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.evento = self.evento
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['evento'] = self.evento
        return context

    def get_success_url(self):
        next_url = self.request.POST.get('next')
        if next_url:
            return next_url
        return reverse_lazy('stock:evento_detail', kwargs={'pk': self.evento.pk})


class PersonalEventoUpdateView(UpdateView):
    model = PersonalEvento
    fields = ['nombre', 'fecha', 'asistentes', 'notas']
    template_name = 'stock/personalevento_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['evento'] = self.object.evento
        return context

    def get_success_url(self):
        return reverse_lazy('stock:evento_detail', kwargs={'pk': self.object.evento.pk})


class PersonalEventoDeleteView(DeleteView):
    model = PersonalEvento
    template_name = 'stock/personalevento_confirm_delete.html'

    def get_success_url(self):
        return reverse_lazy('stock:evento_detail', kwargs={'pk': self.object.evento.pk})


# ---------- Consumo (MovimientoStock) de un Evento ----------
class MovimientoStockCreateView(CreateView):
    model = MovimientoStock
    fields = ['producto', 'tipo', 'cantidad']
    template_name = 'stock/movimientostock_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.evento = get_object_or_404(Evento, pk=self.kwargs['evento_pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.evento = self.evento
        return super().form_valid(form)

    def form_invalid(self, form):
        next_url = self.request.POST.get('next') or reverse('stock:evento_detail', kwargs={'pk': self.evento.pk})
        for errores_del_campo in form.errors.values():
            for error in errores_del_campo:
                messages.error(self.request, error)
        return redirect(next_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['evento'] = self.evento
        return context

    def get_success_url(self):
        next_url = self.request.POST.get('next')
        if next_url:
            return next_url
        return reverse_lazy('stock:evento_detail', kwargs={'pk': self.evento.pk})


class MovimientoStockUpdateView(UpdateView):
    model = MovimientoStock
    fields = ['producto', 'tipo', 'cantidad']
    template_name = 'stock/movimientostock_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['evento'] = self.object.evento
        return context

    def get_success_url(self):
        return reverse_lazy('stock:evento_detail', kwargs={'pk': self.object.evento.pk})


class MovimientoStockDeleteView(DeleteView):
    model = MovimientoStock
    template_name = 'stock/movimientostock_confirm_delete.html'

    def get_success_url(self):
        return reverse_lazy('stock:evento_detail', kwargs={'pk': self.object.evento.pk})
    
# ---------- Paquete ----------
class PaqueteListView(ListView):
    model = Paquete
    template_name = 'stock/paquete_list.html'
    context_object_name = 'paquetes'


class PaqueteDetailView(DetailView):
    model = Paquete
    template_name = 'stock/paquete_detail.html'


class PaqueteCreateView(CreateView):
    model = Paquete
    fields = ['nombre', 'descripcion', 'precio']
    template_name = 'stock/paquete_form.html'
    success_url = reverse_lazy('stock:paquete_list')


class PaqueteUpdateView(UpdateView):
    model = Paquete
    fields = ['nombre', 'descripcion', 'precio']
    template_name = 'stock/paquete_form.html'
    success_url = reverse_lazy('stock:paquete_list')


class PaqueteDeleteView(DeleteView):
    model = Paquete
    template_name = 'stock/paquete_confirm_delete.html'
    success_url = reverse_lazy('stock:paquete_list')


# ---------- Menu ----------
class MenuListView(ListView):
    model = Menu
    template_name = 'stock/menu_list.html'
    context_object_name = 'menus'


class MenuDetailView(DetailView):
    model = Menu
    template_name = 'stock/menu_detail.html'


class MenuCreateView(CreateView):
    model = Menu
    fields = ['nombre', 'descripcion']
    template_name = 'stock/menu_form.html'
    success_url = reverse_lazy('stock:menu_list')


class MenuUpdateView(UpdateView):
    model = Menu
    fields = ['nombre', 'descripcion']
    template_name = 'stock/menu_form.html'
    success_url = reverse_lazy('stock:menu_list')


class MenuDeleteView(DeleteView):
    model = Menu
    template_name = 'stock/menu_confirm_delete.html'
    success_url = reverse_lazy('stock:menu_list')

# ---------- Compras (carga de stock por sector, en pestañas) ----------

def compras(request):
    if request.method == 'POST':
        producto_id = request.POST.get('producto_id')
        cantidad = request.POST.get('cantidad')
        tab = request.POST.get('tab', 'barra-pane')
        producto = get_object_or_404(Producto, pk=producto_id)
        if cantidad and int(cantidad) > 0:
            MovimientoStock.objects.create(
                producto=producto,
                tipo='entrada',
                cantidad=int(cantidad),
            )
        return redirect(f"{reverse('stock:compras')}#{tab}")

    context = {
        'productos_barra': Producto.objects.filter(sector='barra').order_by(Lower('nombre')),
        'productos_cocina': Producto.objects.filter(sector='cocina').order_by(Lower('nombre')),
        'productos_extras': Producto.objects.filter(sector='extras').order_by(Lower('nombre')),
    }
    return render(request, 'stock/compras.html', context)

    context = {
        'productos_barra': Producto.objects.filter(sector='barra').order_by(Lower('nombre')),
        'productos_cocina': Producto.objects.filter(sector='cocina').order_by(Lower('nombre')),
        'productos_extras': Producto.objects.filter(sector='extras').order_by(Lower('nombre')),
    }
    return render(request, 'stock/compras.html', context)

# ---------- Calendario de eventos ----------
def obtener_datos_calendario(year=None, month=None):
    hoy = date.today()
    year = year or hoy.year
    month = month or hoy.month

    cal = calendar.Calendar(firstweekday=0)
    semanas_raw = cal.monthdayscalendar(year, month)

    eventos_mes = Evento.objects.filter(fecha__year=year, fecha__month=month)
    eventos_por_dia = {}
    for evento in eventos_mes:
        eventos_por_dia.setdefault(evento.fecha.day, []).append(evento)

    semanas = []
    for semana in semanas_raw:
        fila = []
        for dia in semana:
            if dia == 0:
                fila.append(None)
            else:
                fila.append({
                    'numero': dia,
                    'eventos': eventos_por_dia.get(dia, []),
                    'es_hoy': (year == hoy.year and month == hoy.month and dia == hoy.day),
                })
        semanas.append(fila)

    if month == 1:
        mes_anterior = {'year': year - 1, 'month': 12}
    else:
        mes_anterior = {'year': year, 'month': month - 1}

    if month == 12:
        mes_siguiente = {'year': year + 1, 'month': 1}
    else:
        mes_siguiente = {'year': year, 'month': month + 1}

    proximos = Evento.objects.filter(fecha__gte=hoy).order_by('fecha')[:10]

    return {
        'semanas': semanas,
        'year': year,
        'month': month,
        'nombre_mes': MESES_ES[month],
        'mes_anterior': mes_anterior,
        'mes_siguiente': mes_siguiente,
        'proximos': proximos,
    }


def calendario_eventos(request):
    year = int(request.GET.get('year', date.today().year))
    month = int(request.GET.get('month', date.today().month))
    context = obtener_datos_calendario(year, month)
    return render(request, 'stock/calendario.html', context)

# ---------- Consumo (pantalla dedicada por evento) ----------
def consumo_selector(request):
    eventos = Evento.objects.order_by('-fecha')
    return render(request, 'stock/consumo_selector.html', {'eventos': eventos})


def consumo_evento(request, evento_pk):
    evento = get_object_or_404(Evento, pk=evento_pk)
    context = {
        'evento': evento,
        'productos_barra': Producto.objects.filter(sector='barra').order_by(Lower('nombre')),
        'productos_cocina': Producto.objects.filter(sector='cocina').order_by(Lower('nombre')),
        'productos_extras': Producto.objects.filter(sector='extras').order_by(Lower('nombre')),
        'empleados': Empleado.objects.all().order_by('nombre'),
    }
    return render(request, 'stock/consumo_evento.html', context)