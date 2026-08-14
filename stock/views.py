import calendar
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .models import (
    SECTOR_CHOICES,
    sector_valoriza,
    CargoEvento,
    DestinatarioAviso,
    Empleado,
    Evento,
    LineaReceta,
    Menu,
    MovimientoStock,
    Paquete,
    PersonalEvento,
    Plato,
    Producto,
    Puesto,
    TarjetaEvento,
    UnidadMedida,
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


def parsear_fecha(valor):
    """'2026-08-13' -> date, o None si no es una fecha.

    Los filtros vienen de la querystring, que la escribe cualquiera: pasarle
    texto suelto a un lookup __date es un 500, no una lista vacía. Mismo motivo
    que parsear_cantidad().
    """
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        return None


def parsear_entero(valor):
    """Lo que llegó por la URL -> int, o None si no es un número."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None

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
        """Un sector por pestaña, y solo lo que está en circulación (RN-20).

        Los dados de baja no se listan: existen para sostener el historial, no
        para llenar la pantalla de cosas que ya no se compran. Se ven con
        ?bajas=1, que es también la única forma de reactivarlos.
        """
        context = super().get_context_data(**kwargs)
        q = self.request.GET.get('q', '')
        ver_bajas = bool(self.request.GET.get('bajas'))

        productos = Producto.objects.filter(nombre__icontains=q, activo=not ver_bajas)
        context['sectores'] = []
        for clave, etiqueta in SECTOR_CHOICES:
            del_sector = productos.filter(sector=clave).order_by(Lower('nombre'))
            context[f'productos_{clave}'] = del_sector
            context['sectores'].append({
                'clave': clave,
                'etiqueta': etiqueta,
                'productos': del_sector,
                'sin_precio': not sector_valoriza(clave),
            })

        context['q'] = q
        context['ver_bajas'] = ver_bajas
        context['cantidad_bajas'] = Producto.objects.filter(activo=False).count()
        return context


def volver_al_sector(producto):
    """El listado de productos, abierto en la pestaña del sector que se tocó.

    Sin el fragmento el listado abre siempre en Barra: tocás un producto de
    Extras y al guardar aparecés en otra pestaña, buscando de nuevo dónde
    estabas. Es el mismo patrón que ya usaban Compras y Merma (RN-4); lo que
    faltaba era acá.

    Los `<sector>-pane` son contrato con el helper de pestañas de base.html.
    """
    return f"{reverse('stock:producto_list')}#{producto.sector}-pane"


class ProductoDetailView(DetailView):
    model = Producto
    template_name = 'stock/producto_detail.html'


class ProductoCreateView(CreateView):
    model = Producto
    fields = ['nombre', 'sector', 'precio_unitario', 'stock_actual', 'unidad_medida']
    template_name = 'stock/producto_form.html'

    def get_success_url(self):
        return volver_al_sector(self.object)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Opcional: en blanco queda en 0.
        form.fields['stock_actual'].required = False
        form.fields['stock_actual'].label = 'Stock inicial'
        preparar_precio(form)
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

    def get_success_url(self):
        return volver_al_sector(self.object)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        preparar_precio(form)
        return form


def preparar_precio(form):
    """El precio es opcional: el mobiliario se cuenta pero no se valoriza (RN-8).

    No se esconde el campo según el sector porque eso pide JS, y los <script> que
    entran por innerHTML no se ejecutan dentro de un modal (RN-22): sería un campo
    que desaparece en la pantalla suelta y queda a la vista en el modal. Un campo
    opcional bien explicado es más honesto que uno que a veces está.
    """
    campo = form.fields['precio_unitario']
    campo.required = False
    campo.help_text = 'Dejalo vacío para lo que solo se cuenta (mobiliario: vajilla, manteles, vasos).'


class ProductoDeleteView(DeleteView):
    model = Producto
    template_name = 'stock/producto_confirm_delete.html'

    def get_success_url(self):
        return volver_al_sector(self.object)

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
            return redirect(self.get_success_url())

        messages.success(self.request, f'Borramos "{producto.nombre}".')
        return respuesta


def reactivar_producto(request, pk):
    """Vuelve a poner en circulación un producto dado de baja (RN-20)."""
    producto = get_object_or_404(Producto, pk=pk)
    if request.method == 'POST' and not producto.activo:
        producto.activo = True
        producto.save(update_fields=['activo'])
        messages.success(request, f'"{producto.nombre}" volvió a estar disponible.')
    return redirect(volver_al_sector(producto))


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


# El evento no pide precio por cubierto: eso se carga tarjeta por tarjeta, que es
# donde se distingue cuántos son de cada menú (RN-17).
CAMPOS_EVENTO = [
    'nombre', 'fecha', 'asistentes', 'estado', 'paquete', 'menu',
    'precio_paquete', 'brindis_asistentes', 'brindis_valor',
    'telefono_contacto', 'notas',
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
        queryset = super().get_queryset().select_related('puesto_habitual')
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


# ---------- Puestos (catálogo administrable) ----------
class PuestoListView(ListView):
    model = Puesto
    template_name = 'stock/puesto_list.html'
    context_object_name = 'puestos'


class PuestoCreateView(CreateView):
    model = Puesto
    fields = ['nombre']
    template_name = 'stock/puesto_form.html'
    success_url = reverse_lazy('stock:puesto_list')


class PuestoUpdateView(UpdateView):
    model = Puesto
    fields = ['nombre']
    template_name = 'stock/puesto_form.html'
    success_url = reverse_lazy('stock:puesto_list')


class PuestoDeleteView(DeleteView):
    model = Puesto
    template_name = 'stock/puesto_confirm_delete.html'
    success_url = reverse_lazy('stock:puesto_list')

    def form_valid(self, form):
        """Un puesto usado en un evento no se borra: es histórico de pagos."""
        puesto = self.object
        try:
            with transaction.atomic():
                return super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                f'"{puesto.nombre}" está usado en {puesto.asignaciones.count()} asignación'
                f'{"es" if puesto.asignaciones.count() != 1 else ""} de personal, así que no se '
                'puede borrar. Cambiales el puesto primero si querés sacarlo.',
            )
            return redirect(self.success_url)


# ---------- Unidades de medida (RN-26) ----------
class UnidadMedidaListView(ListView):
    model = UnidadMedida
    template_name = 'stock/unidad_list.html'
    context_object_name = 'unidades'


class UnidadMedidaCreateView(CreateView):
    model = UnidadMedida
    fields = ['nombre']
    template_name = 'stock/unidad_form.html'
    success_url = reverse_lazy('stock:unidad_list')


class UnidadMedidaUpdateView(UpdateView):
    model = UnidadMedida
    fields = ['nombre']
    template_name = 'stock/unidad_form.html'
    success_url = reverse_lazy('stock:unidad_list')


class UnidadMedidaDeleteView(DeleteView):
    model = UnidadMedida
    template_name = 'stock/unidad_confirm_delete.html'
    success_url = reverse_lazy('stock:unidad_list')

    def form_valid(self, form):
        """Una unidad en uso no se borra: es lo que le da sentido al stock.

        Sin ella el fernet queda en "50" a secas, que no es un dato. Mismo
        criterio que con los puestos (RN-21).
        """
        unidad = self.object
        try:
            with transaction.atomic():
                return super().form_valid(form)
        except ProtectedError:
            usados = unidad.productos.count()
            messages.error(
                self.request,
                f'"{unidad.nombre}" la usan {usados} producto{"s" if usados != 1 else ""}, '
                'así que no se puede borrar. Cambiales la unidad primero si querés sacarla.',
            )
            return redirect(self.success_url)


# ---------- Destinatarios de los avisos por mail ----------
class DestinatarioAvisoListView(ListView):
    model = DestinatarioAviso
    template_name = 'stock/destinatario_list.html'
    context_object_name = 'destinatarios'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['dias_aviso'] = getattr(settings, 'DIAS_AVISO_EVENTO', 7)
        # Sin SMTP configurado los mails salen por la terminal y nadie los recibe:
        # más vale decirlo en la pantalla que dejar que se descubra solo.
        context['manda_de_verdad'] = 'smtp' in getattr(settings, 'EMAIL_BACKEND', '').lower()
        return context


class DestinatarioAvisoCreateView(CreateView):
    model = DestinatarioAviso
    fields = ['email', 'nombre', 'activo']
    template_name = 'stock/destinatario_form.html'
    success_url = reverse_lazy('stock:destinatario_list')


class DestinatarioAvisoUpdateView(UpdateView):
    model = DestinatarioAviso
    fields = ['email', 'nombre', 'activo']
    template_name = 'stock/destinatario_form.html'
    success_url = reverse_lazy('stock:destinatario_list')


class DestinatarioAvisoDeleteView(DeleteView):
    model = DestinatarioAviso
    template_name = 'stock/destinatario_confirm_delete.html'
    success_url = reverse_lazy('stock:destinatario_list')


# ---------- Recetas: platos y sus ingredientes ----------
class PlatoCreateView(CreateView):
    """Un paso de la comida dentro de un menú (entrante, principal, postre…)."""

    model = Plato
    fields = ['paso', 'nombre']
    template_name = 'stock/plato_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.menu = get_object_or_404(Menu, pk=self.kwargs['menu_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        paso = self.request.GET.get('paso')
        if paso:
            form.initial['paso'] = paso
        return form

    def form_valid(self, form):
        form.instance.menu = self.menu
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['menu'] = self.menu
        return context

    def get_success_url(self):
        return reverse('stock:menu_detail', kwargs={'pk': self.menu.pk})


class PlatoUpdateView(UpdateView):
    model = Plato
    fields = ['paso', 'nombre']
    template_name = 'stock/plato_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['menu'] = self.object.menu
        return context

    def get_success_url(self):
        return volver_del_plato(self.object)


class PlatoDetailView(DetailView):
    model = Plato
    template_name = 'stock/plato_detail.html'


class PlatoDeleteView(DeleteView):
    model = Plato
    template_name = 'stock/plato_confirm_delete.html'

    def get_success_url(self):
        return volver_del_plato(self.object)


def volver_del_plato(plato):
    """El plato es del menú o de un evento (RN-18): cada uno vuelve a su pantalla."""
    if plato.menu_id:
        return reverse('stock:menu_detail', kwargs={'pk': plato.menu_id})
    return reverse('stock:evento_detail', kwargs={'pk': plato.evento_id})


class LineaRecetaCreateView(CreateView):
    """Un ingrediente del plato, medido por persona."""

    model = LineaReceta
    fields = ['producto', 'cantidad_por_persona']
    template_name = 'stock/lineareceta_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.plato = get_object_or_404(Plato, pk=self.kwargs['plato_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Un producto dado de baja no se puede seguir usando en recetas nuevas (RN-20).
        form.fields['producto'].queryset = Producto.objects.filter(activo=True).order_by(Lower('nombre'))
        return form

    def form_valid(self, form):
        form.instance.plato = self.plato
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['plato'] = self.plato
        return context

    def get_success_url(self):
        return reverse('stock:plato_detail', kwargs={'pk': self.plato.pk})


class LineaRecetaUpdateView(UpdateView):
    model = LineaReceta
    fields = ['producto', 'cantidad_por_persona']
    template_name = 'stock/lineareceta_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['plato'] = self.object.plato
        return context

    def get_success_url(self):
        return reverse('stock:plato_detail', kwargs={'pk': self.object.plato_id})


class LineaRecetaDeleteView(DeleteView):
    model = LineaReceta
    template_name = 'stock/lineareceta_confirm_delete.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['plato'] = self.object.plato
        return context

    def get_success_url(self):
        return reverse('stock:plato_detail', kwargs={'pk': self.object.plato_id})


def copiar_receta(request, pk):
    """Vuelve a traer la receta del menú, por si el menú cambió después (RN-18).

    El evento ya la hereda solo al asignársele el menú: esto es para cuando la
    receta base se corrigió con el evento ya cargado.
    """
    evento = get_object_or_404(Evento, pk=pk)
    destino = reverse('stock:evento_detail', kwargs={'pk': evento.pk})

    if request.method != 'POST':
        return redirect(destino)

    if evento.cerrado:
        messages.error(request, f'"{evento.nombre}" está cerrado. Reabrilo si necesitás corregirlo.')
    elif not evento.menu_id:
        messages.error(request, 'Este evento no tiene un menú asignado, así que no hay receta que traer.')
    else:
        copiados = evento.copiar_receta_del_menu()
        if copiados:
            messages.success(
                request,
                f'Trajimos {copiados} plato{"s" if copiados != 1 else ""} de "{evento.menu.nombre}".',
            )
        else:
            messages.error(request, f'"{evento.menu.nombre}" todavía no tiene platos cargados.')

    return redirect(destino)


# ---------- Tarjetas (lo que paga cada tipo de invitado) ----------
class TarjetaEventoCreateView(CreateView):
    model = TarjetaEvento
    fields = ['concepto', 'cantidad', 'valor_unitario', 'menu']
    template_name = 'stock/tarjetaevento_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.evento = get_object_or_404(Evento, pk=self.kwargs['evento_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # El evento antes de validar, para que clean() pueda bloquear si está cerrado (RN-16).
        kwargs['instance'] = TarjetaEvento(evento=self.evento)
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


class TarjetaEventoUpdateView(UpdateView):
    model = TarjetaEvento
    fields = ['concepto', 'cantidad', 'valor_unitario', 'menu']
    template_name = 'stock/tarjetaevento_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['evento'] = self.object.evento
        return context

    def get_success_url(self):
        return reverse('stock:evento_detail', kwargs={'pk': self.object.evento_id})


class TarjetaEventoDeleteView(DeleteView):
    model = TarjetaEvento
    template_name = 'stock/tarjetaevento_confirm_delete.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['evento'] = self.object.evento
        return context

    def get_success_url(self):
        return reverse('stock:evento_detail', kwargs={'pk': self.object.evento_id})


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


class MovimientoStockListView(ListView):
    """El libro mayor completo: qué se movió, cuándo, cuánto y por qué.

    Hasta ahora los movimientos solo se veían colgados de su evento o de la
    pantalla donde se cargaron, así que no había forma de responder "¿qué entró
    la semana pasada?" sin entrar al admin.
    """

    model = MovimientoStock
    template_name = 'stock/movimiento_list.html'
    context_object_name = 'movimientos'
    paginate_by = 50

    def get_queryset(self):
        queryset = (
            MovimientoStock.objects
            .select_related('producto', 'evento')
            .order_by('-fecha', '-pk')
        )

        # Todo lo que entra por la URL se sanea antes de tocar la base: un
        # ?desde=cualquiercosa o un ?evento=abc son un 500, no una lista vacía.
        filtros = self.request.GET

        if filtros.get('tipo'):
            queryset = queryset.filter(tipo=filtros['tipo'])
        if filtros.get('sector'):
            queryset = queryset.filter(producto__sector=filtros['sector'])
        if filtros.get('q'):
            queryset = queryset.filter(producto__nombre__icontains=filtros['q'])

        evento = parsear_entero(filtros.get('evento'))
        if evento is not None:
            queryset = queryset.filter(evento_id=evento)

        # Las fechas se filtran por día: `fecha` es un DateTimeField, así que un
        # `desde=hoy` sin __date dejaría afuera todo lo cargado hoy después de las 00:00.
        desde = parsear_fecha(filtros.get('desde'))
        if desde is not None:
            queryset = queryset.filter(fecha__date__gte=desde)
        hasta = parsear_fecha(filtros.get('hasta'))
        if hasta is not None:
            queryset = queryset.filter(fecha__date__lte=hasta)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sectores'] = SECTOR_CHOICES
        context['tipos'] = MovimientoStock.TIPO_CHOICES
        context['eventos'] = Evento.objects.order_by('-fecha')
        context['filtros'] = self.request.GET
        context['hay_filtros'] = any(
            self.request.GET.get(campo)
            for campo in ('tipo', 'sector', 'q', 'evento', 'desde', 'hasta')
        )
        # Sobre el queryset filtrado entero, no sobre la página: el total de una
        # página suelta no le dice nada a nadie.
        context['total_movimientos'] = self.get_queryset().count()
        return context


def volver_del_movimiento(movimiento, usuario=None):
    """A dónde se vuelve después de editar o borrar un movimiento.

    Las compras y las mermas NO tienen evento: mandarlas a evento_detail era un
    AttributeError. Cada una vuelve a la pantalla de donde salió.
    """
    if movimiento.evento_id:
        # El empleado no puede abrir el detalle del evento (RN-25): mandarlo ahí
        # sería rebotarlo al calendario con un cartel de error justo después de
        # corregir bien. Vuelve a la pantalla desde la que cargó.
        if usuario is not None and not usuario.is_staff:
            return reverse('stock:consumo_evento', kwargs={'evento_pk': movimiento.evento_id})
        return reverse('stock:evento_detail', kwargs={'pk': movimiento.evento_id})
    if movimiento.tipo == 'merma':
        return reverse('stock:merma')
    return reverse('stock:compras')


class MovimientoDelEmpleadoMixin:
    """El empleado corrige lo que carga él: consumos y mermas. Las compras no.

    Sin este filtro, abrirle editar/borrar (RN-25) le abría TODO el libro mayor
    por URL directa: podía borrar una reposición de depósito de medio millón de
    pesos, y el stock se movía de verdad. Va en el queryset y no en el template
    porque el botón se esconde, la URL no: lo que queda afuera da 404.
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_staff:
            return queryset
        return queryset.exclude(tipo='entrada')


class MovimientoStockUpdateView(MovimientoDelEmpleadoMixin, UpdateView):
    model = MovimientoStock
    # 'motivo' va en el form aunque solo lo use la merma: si clean() apunta un
    # error a un campo que el form no declara, Django tira 500 en vez de
    # mostrarlo. Acá se editan los tres tipos, así que van los cuatro campos.
    fields = ['producto', 'tipo', 'cantidad', 'motivo']
    template_name = 'stock/movimientostock_form.html'

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if not self.request.user.is_staff:
            # El empleado corrige la cantidad, no convierte una salida en
            # entrada: eso sería inventar mercadería que nunca llegó. `disabled`
            # además ignora lo que venga por POST, no solo lo pinta gris.
            form.fields['tipo'].disabled = True
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['evento'] = self.object.evento
        return context

    def get_success_url(self):
        return volver_del_movimiento(self.object, self.request.user)


class MovimientoStockDeleteView(MovimientoDelEmpleadoMixin, DeleteView):
    model = MovimientoStock
    template_name = 'stock/movimientostock_confirm_delete.html'

    def get_success_url(self):
        return volver_del_movimiento(self.object, self.request.user)
    
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
    """Los sectores de RN-8, que comparten Productos, Compras, Consumo y Merma.

    Devuelve la lista `sectores` para que los templates la recorran: agregar un
    sector no puede obligar a tocar cuatro pantallas a mano. Las claves sueltas
    (`productos_barra`, …) quedan porque varias pantallas las usan por nombre.

    Solo los activos: un producto dado de baja conserva su historial pero no se
    puede seguir moviendo (RN-20).
    """
    contexto = {'sectores': []}
    for clave, etiqueta in SECTOR_CHOICES:
        productos = Producto.objects.filter(sector=clave, activo=True).order_by(Lower('nombre'))
        contexto[f'productos_{clave}'] = productos
        contexto['sectores'].append({
            'clave': clave,
            'etiqueta': etiqueta,
            'productos': productos,
            'sin_precio': not sector_valoriza(clave),
        })
    return contexto


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
    context['empleados'] = Empleado.objects.select_related('puesto_habitual').order_by('nombre')
    context['puestos'] = Puesto.objects.all()
    # Lo ya cargado, para poder corregirlo (RN-25). El empleado no tiene ninguna
    # otra pantalla donde verlo: el historial y el detalle del evento son del
    # administrador, así que sin esta tabla "puede editar" era letra muerta.
    context['cargado'] = (
        evento.movimientos
        .exclude(tipo='entrada')
        .select_related('producto')
        .order_by('-fecha', '-pk')
    )
    return render(request, 'stock/consumo_evento.html', context)


# ---------- Usuarios del sistema (solo el administrador) ----------
class UsuarioCreationForm(UserCreationForm):
    """El alta de Django, más el rol.

    Es la excepción a "no hay forms.py": las dos contraseñas repetidas y los
    validadores ya están resueltos acá adentro, y rehacerlos a mano para no
    escribir cuatro líneas sería el peor negocio del proyecto.
    """

    class Meta(UserCreationForm.Meta):
        fields = ['username', 'is_staff']


def preparar_rol(form):
    """`is_staff` ES el rol. Tildado, administrador; sin tildar, empleado.

    Mismo criterio que preparar_precio(): el campo ya existe y lo único que le
    falta es decir en castellano qué significa.
    """
    campo = form.fields['is_staff']
    campo.label = 'Administrador'
    campo.help_text = (
        'Ve todo el sistema y puede dar de alta usuarios. Sin tildar, la persona '
        'entra como empleado.'
    )


class UsuarioListView(ListView):
    model = User
    template_name = 'stock/usuario_list.html'
    context_object_name = 'usuarios'
    ordering = ['username']

    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(username__icontains=q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '')
        return context


class UsuarioCreateView(CreateView):
    model = User
    form_class = UsuarioCreationForm
    template_name = 'stock/usuario_form.html'
    success_url = reverse_lazy('stock:usuario_list')
    extra_context = {
        'titulo': 'Nuevo usuario',
        'subtitulo': 'Con estos datos la persona va a poder ingresar al sistema.',
    }

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        preparar_rol(form)
        return form

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        messages.success(self.request, f'Creamos a "{self.object.username}". Ya puede ingresar.')
        return respuesta


class UsuarioUpdateView(UpdateView):
    model = User
    # La contraseña no se toca acá: tiene pantalla propia, con la repetición y
    # los validadores. Mezclarla con el resto obligaría a reescribirla cada vez
    # que se corrige un nombre.
    fields = ['username', 'is_staff', 'is_active']
    template_name = 'stock/usuario_form.html'
    success_url = reverse_lazy('stock:usuario_list')
    extra_context = {
        'titulo': 'Editar usuario',
        'subtitulo': 'El nombre con el que ingresa, su rol, y si sigue teniendo acceso.',
    }

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        preparar_rol(form)
        form.fields['is_active'].label = 'Puede ingresar'
        form.fields['is_active'].help_text = (
            'Destildalo para dejar a alguien afuera sin borrarle el usuario.'
        )
        if self.object == self.request.user:
            # Nadie se saca a sí mismo el acceso: quedaría afuera del módulo con
            # la sesión abierta y sin forma de volver a entrar. `disabled` además
            # ignora lo que venga por POST, así que tampoco se hace a mano.
            form.fields['is_staff'].disabled = True
            form.fields['is_active'].disabled = True
        return form

    def form_valid(self, form):
        # Bajar a empleado tiene que bajar de verdad: a un superusuario le queda
        # is_superuser y con eso pasa cualquier chequeo de permisos de Django.
        if not form.instance.is_staff:
            form.instance.is_superuser = False
        return super().form_valid(form)


class UsuarioPasswordView(UpdateView):
    """Cambiarle la contraseña a otro: el olvido es el soporte real de esto."""

    model = User
    form_class = SetPasswordForm
    template_name = 'stock/usuario_form.html'
    success_url = reverse_lazy('stock:usuario_list')
    extra_context = {
        'titulo': 'Cambiar contraseña',
        'subtitulo': 'La anterior deja de servir apenas guardes.',
    }

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # SetPasswordForm no es un ModelForm: recibe al usuario como `user` y no
        # sabe qué hacer con un `instance`.
        kwargs.pop('instance', None)
        kwargs['user'] = self.object
        return kwargs

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        messages.success(self.request, f'Le cambiamos la contraseña a "{self.object.username}".')
        return respuesta


class UsuarioDeleteView(DeleteView):
    model = User
    template_name = 'stock/usuario_confirm_delete.html'
    success_url = reverse_lazy('stock:usuario_list')

    def get_queryset(self):
        # Borrarse a sí mismo es cerrar la puerta con la llave adentro. Va en el
        # queryset y no en el template: el botón se esconde, la URL no.
        return super().get_queryset().exclude(pk=self.request.user.pk)

    def form_valid(self, form):
        messages.success(self.request, f'Borramos el usuario "{self.object.username}".')
        return super().form_valid(form)