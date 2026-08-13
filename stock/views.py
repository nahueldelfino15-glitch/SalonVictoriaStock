import calendar
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .models import (
    SECTOR_CHOICES,
    CargoEvento,
    Empleado,
    Evento,
    LineaReceta,
    Menu,
    MovimientoStock,
    Paquete,
    PersonalEvento,
    Producto,
)


MESES_ES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
            'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

# Lo más grande que entra en cantidad (max_digits=10, decimal_places=2).
CANTIDAD_MAXIMA = Decimal('99999999.99')


def parsear_cantidad(valor):
    """Lo que llegó del formulario -> Decimal, o None si no es un número cargable.

    Las cantidades ahora son decimales (2,5 kg / 0,75 L), así que además de
    ValueError hay que atajar InvalidOperation, que es lo que tira Decimal()
    con texto. 'nan' e 'infinity' son Decimal válidos pero después revientan al
    comparar o al guardar: los sacamos acá.
    """
    try:
        cantidad = Decimal(valor)
    except (TypeError, ValueError, InvalidOperation):
        return None
    if not cantidad.is_finite() or cantidad > CANTIDAD_MAXIMA:
        return None
    return cantidad

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

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Opcional: en blanco queda en 0.
        form.fields['stock_actual'].required = False
        form.fields['stock_actual'].label = 'Stock inicial'
        return form

    @transaction.atomic
    def form_valid(self, form):
        """RN-1: el stock lo escribe el libro mayor, no el formulario.

        El "stock inicial" del alta no se guarda a mano en el producto: se
        guarda como una entrada. Así el producto nace con el movimiento que lo
        respalda y la suma de movimientos siempre cierra con stock_actual.
        """
        stock_inicial = form.cleaned_data.get('stock_actual') or 0
        form.instance.stock_actual = 0
        respuesta = super().form_valid(form)
        if stock_inicial > 0:
            MovimientoStock.objects.create(
                producto=self.object,
                tipo='entrada',
                cantidad=stock_inicial,
            )
        return respuesta


class ProductoUpdateView(UpdateView):
    model = Producto
    # stock_actual NO se edita a mano (RN-1): se mueve con compras y consumo.
    fields = ['nombre', 'sector', 'precio_unitario', 'unidad_medida']
    template_name = 'stock/producto_form.html'
    success_url = reverse_lazy('stock:producto_list')


class ProductoDeleteView(DeleteView):
    model = Producto
    template_name = 'stock/producto_confirm_delete.html'
    success_url = reverse_lazy('stock:producto_list')

    def form_valid(self, form):
        """Si el producto tiene historial no se borra: se da de baja (RN-20).

        Borrarlo se llevaría puestos sus movimientos, y con ellos el costo
        congelado de eventos ya cerrados, que cambiarían de margen solos.
        """
        producto = self.object
        try:
            with transaction.atomic():
                respuesta = super().form_valid(form)
        except ProtectedError:
            producto.dar_de_baja()
            messages.success(
                self.request,
                f'"{producto.nombre}" tiene movimientos cargados, así que lo dimos de baja en vez '
                'de borrarlo. Sale de Compras, Consumo y Merma, pero su historial queda intacto.',
            )
            return redirect(self.success_url)

        messages.success(self.request, f'Borramos "{producto.nombre}".')
        return respuesta


def reactivar_producto(request, pk):
    """Vuelve a poner en circulación un producto dado de baja (RN-20)."""
    producto = get_object_or_404(Producto, pk=pk)
    if request.method == 'POST' and not producto.activo:
        producto.activo = True
        producto.save(update_fields=['activo'])
        messages.success(request, f'"{producto.nombre}" volvió a estar disponible.')
    return redirect('stock:producto_list')


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


CAMPOS_EVENTO = [
    'nombre', 'fecha', 'asistentes', 'estado', 'paquete', 'menu',
    'precio_por_persona', 'precio_cerrado', 'telefono_contacto', 'notas',
]


class EventoCreateView(CreateView):
    model = Evento
    fields = CAMPOS_EVENTO
    template_name = 'stock/evento_form.html'
    success_url = reverse_lazy('stock:evento_list')


class EventoUpdateView(UpdateView):
    model = Evento
    fields = CAMPOS_EVENTO
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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Mismo motivo que en MovimientoStockCreateView: sin el evento puesto de
        # antemano, clean() no puede bloquear la carga sobre un evento cerrado.
        kwargs['instance'] = PersonalEvento(evento=self.evento)
        return kwargs

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


class PersonalEventoUpdateView(UpdateView):
    model = PersonalEvento
    fields = ['empleado', 'puesto', 'horas_trabajadas', 'pago']
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


# ---------- Recetas (líneas de menú o de evento) ----------
class LineaRecetaCreateView(CreateView):
    """Sirve para las dos recetas: la base del menú y la ajustada del evento.

    Cuál es se define por la URL de la que viene (menu_pk o evento_pk).
    """

    model = LineaReceta
    fields = ['producto', 'cantidad_por_persona']
    template_name = 'stock/lineareceta_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.menu = get_object_or_404(Menu, pk=kwargs['menu_pk']) if 'menu_pk' in kwargs else None
        self.evento = get_object_or_404(Evento, pk=kwargs['evento_pk']) if 'evento_pk' in kwargs else None
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['instance'] = LineaReceta(menu=self.menu, evento=self.evento)
        return kwargs

    def form_valid(self, form):
        form.instance.menu = self.menu
        form.instance.evento = self.evento
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['menu'] = self.menu
        context['evento'] = self.evento
        return context

    def get_success_url(self):
        return volver_de_la_receta(self.menu, self.evento)


class LineaRecetaDeleteView(DeleteView):
    model = LineaReceta
    template_name = 'stock/lineareceta_confirm_delete.html'

    def get_success_url(self):
        return volver_de_la_receta(self.object.menu, self.object.evento)


def volver_de_la_receta(menu, evento):
    if menu is not None:
        return reverse('stock:menu_detail', kwargs={'pk': menu.pk})
    return reverse('stock:consumo_evento', kwargs={'evento_pk': evento.pk}) + '#receta-pane'


def copiar_receta(request, pk):
    """Trae la receta del menú del evento como punto de partida (RN-18)."""
    evento = get_object_or_404(Evento, pk=pk)
    destino = reverse('stock:consumo_evento', kwargs={'evento_pk': evento.pk}) + '#receta-pane'

    if request.method != 'POST':
        return redirect(destino)

    if evento.cerrado:
        messages.error(request, f'"{evento.nombre}" está cerrado. Reabrilo si necesitás corregirlo.')
    elif not evento.menu_id:
        messages.error(request, 'Este evento no tiene un menú asignado, así que no hay receta que copiar.')
    else:
        copiadas = evento.copiar_receta_del_menu()
        if copiadas:
            messages.success(
                request,
                f'Copiamos {copiadas} producto{"s" if copiadas != 1 else ""} de "{evento.menu.nombre}". '
                'Ajustá lo que haga falta para este evento.',
            )
        else:
            messages.error(request, f'"{evento.menu.nombre}" todavía no tiene productos cargados en su receta.')

    return redirect(destino)


# ---------- Cargos al cliente (adicionales facturables) ----------
class CargoEventoCreateView(CreateView):
    model = CargoEvento
    fields = ['concepto', 'monto']
    template_name = 'stock/cargoevento_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.evento = get_object_or_404(Evento, pk=self.kwargs['evento_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # El evento antes de validar, para que clean() pueda bloquear si está cerrado.
        kwargs['instance'] = CargoEvento(evento=self.evento)
        return kwargs

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
        return self.request.POST.get('next') or reverse('stock:evento_detail', kwargs={'pk': self.evento.pk})


class CargoEventoUpdateView(UpdateView):
    model = CargoEvento
    fields = ['concepto', 'monto']
    template_name = 'stock/cargoevento_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['evento'] = self.object.evento
        return context

    def get_success_url(self):
        return reverse('stock:evento_detail', kwargs={'pk': self.object.evento_id})


class CargoEventoDeleteView(DeleteView):
    model = CargoEvento
    template_name = 'stock/cargoevento_confirm_delete.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['evento'] = self.object.evento
        return context

    def get_success_url(self):
        return reverse('stock:evento_detail', kwargs={'pk': self.object.evento_id})


# ---------- Consumo (MovimientoStock) de un Evento ----------
class MovimientoStockEnEventoMixin:
    """Lo que se carga contra un evento es entrada o salida, nunca merma.

    La merma no lleva evento (la valida MovimientoStock.clean), así que si el
    form la ofreciera, elegirla sería un 500: Django revienta cuando clean()
    apunta un error a un campo que el form no declara ('motivo').
    """

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['tipo'].choices = [
            (valor, etiqueta)
            for valor, etiqueta in MovimientoStock.TIPO_CHOICES
            if valor != 'merma'
        ]
        return form


class MovimientoStockCreateView(MovimientoStockEnEventoMixin, CreateView):
    model = MovimientoStock
    fields = ['producto', 'tipo', 'cantidad']
    template_name = 'stock/movimientostock_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.evento = get_object_or_404(Evento, pk=self.kwargs['evento_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # El evento tiene que estar puesto ANTES de validar. Si se asigna recién
        # en form_valid(), clean() no lo ve y el bloqueo por evento cerrado
        # (RN-16) nunca se dispararía en el alta.
        kwargs['instance'] = MovimientoStock(evento=self.evento)
        return kwargs

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


def volver_del_movimiento(movimiento):
    """A dónde se vuelve después de editar o borrar un movimiento.

    Las compras y las mermas NO tienen evento: mandarlas a evento_detail era un
    AttributeError. Cada una vuelve a la pantalla de donde salió.
    """
    if movimiento.evento_id:
        return reverse('stock:evento_detail', kwargs={'pk': movimiento.evento_id})
    if movimiento.tipo == 'merma':
        return reverse('stock:merma')
    return reverse('stock:compras')


class MovimientoStockUpdateView(UpdateView):
    model = MovimientoStock
    # 'motivo' va en el form aunque solo lo use la merma: si clean() apunta un
    # error a un campo que el form no declara, Django tira 500 en vez de
    # mostrarlo. Acá se editan los tres tipos, así que van los cuatro campos.
    fields = ['producto', 'tipo', 'cantidad', 'motivo']
    template_name = 'stock/movimientostock_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['evento'] = self.object.evento
        return context

    def get_success_url(self):
        return volver_del_movimiento(self.object)


class MovimientoStockDeleteView(DeleteView):
    model = MovimientoStock
    template_name = 'stock/movimientostock_confirm_delete.html'

    def get_success_url(self):
        return volver_del_movimiento(self.object)
    
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

# ---------- Compras y merma (movimientos de depósito, por sector) ----------

def productos_por_sector():
    """Los tres sectores de RN-8, que comparten Compras, Consumo y Merma.

    Solo los activos: un producto dado de baja conserva su historial pero no se
    puede seguir moviendo (RN-20).
    """
    return {
        f'productos_{sector}': Producto.objects.filter(sector=sector, activo=True).order_by(Lower('nombre'))
        for sector, _ in SECTOR_CHOICES
    }


def compras(request):
    if request.method == 'POST':
        tab = request.POST.get('tab', 'barra-pane')
        destino = f"{reverse('stock:compras')}#{tab}"
        producto = get_object_or_404(Producto, pk=request.POST.get('producto_id'))
        cantidad = parsear_cantidad(request.POST.get('cantidad'))

        if cantidad is None or cantidad <= 0:
            messages.error(request, 'Poné una cantidad en números para cargar el stock.')
            return redirect(destino)

        MovimientoStock.objects.create(producto=producto, tipo='entrada', cantidad=cantidad)
        return redirect(destino)

    return render(request, 'stock/compras.html', productos_por_sector())


def merma(request):
    """Salidas que no son de ningún evento: rotura, vencimiento, consumo interno.

    Antes esto no existía y la única forma de descontar era cargarlo a un evento
    (que le inflaba el costo) o editar el stock a mano (que rompía el libro mayor).
    """
    if request.method == 'POST':
        tab = request.POST.get('tab', 'barra-pane')
        destino = f"{reverse('stock:merma')}#{tab}"
        producto = get_object_or_404(Producto, pk=request.POST.get('producto_id'))
        cantidad = parsear_cantidad(request.POST.get('cantidad'))

        if cantidad is None or cantidad <= 0:
            messages.error(request, 'Poné una cantidad en números para registrar la merma.')
            return redirect(destino)

        movimiento = MovimientoStock(
            producto=producto,
            tipo='merma',
            motivo=request.POST.get('motivo', ''),
            cantidad=cantidad,
        )
        try:
            movimiento.full_clean()
        except ValidationError as error:
            for errores_del_campo in error.message_dict.values():
                for mensaje in errores_del_campo:
                    messages.error(request, mensaje)
            return redirect(destino)

        movimiento.save()
        messages.success(
            request,
            f'Registramos la merma de {cantidad} {producto.unidad_medida} de {producto.nombre}.',
        )
        return redirect(destino)

    context = productos_por_sector()
    context['motivos'] = MovimientoStock.MOTIVO_CHOICES
    return render(request, 'stock/merma.html', context)

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
def reabrir_evento(request, pk):
    """RN-16: la puerta de salida del congelamiento, con rastro."""
    evento = get_object_or_404(Evento, pk=pk)
    if request.method == 'POST':
        if evento.reabrir():
            messages.success(
                request,
                f'Reabrimos "{evento.nombre}". Acordate de volver a finalizarlo cuando termines de corregir.',
            )
        else:
            messages.error(request, f'"{evento.nombre}" no está finalizado, así que no hay nada que reabrir.')
    return redirect('stock:evento_detail', pk=evento.pk)


def consumo_selector(request):
    # Los finalizados quedan afuera: sus números están cerrados (RN-16). Para
    # corregir uno hay que reabrirlo desde su detalle.
    eventos = Evento.objects.exclude(estado='finalizado').order_by('-fecha')
    return render(request, 'stock/consumo_selector.html', {'eventos': eventos})


def consumo_evento(request, evento_pk):
    evento = get_object_or_404(Evento, pk=evento_pk)

    # RN-19: la receta no descuenta nada, solo sugiere. Se le cuelga la cantidad
    # a cada producto para que el input aparezca precargado y el usuario corrija.
    sugerido = {item['producto'].pk: item['cantidad'] for item in evento.consumo_sugerido}

    context = productos_por_sector()
    for sector, _ in SECTOR_CHOICES:
        productos = list(context[f'productos_{sector}'])
        for producto in productos:
            producto.sugerido = sugerido.get(producto.pk)
        context[f'productos_{sector}'] = productos

    context['evento'] = evento
    context['empleados'] = Empleado.objects.all().order_by('nombre')
    return render(request, 'stock/consumo_evento.html', context)