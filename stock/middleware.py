"""Qué puede tocar un empleado (RN-25).

Es una lista BLANCA, y esa es toda la decisión: lo que no está acá, no se ve.

Con lista negra habría que acordarse de bloquear cada pantalla nueva, y el
olvido se descubriría el día que un mozo abra la rentabilidad de un evento. Con
lista blanca, la pantalla que nadie nombró nace cerrada — que es el default que
uno quiere cuando se equivoca. Mismo criterio que `LoginRequiredMiddleware`, que
ya cubre las 50 vistas con una línea en vez de un mixin por vista.
"""

from django.contrib import messages
from django.shortcuts import redirect

# El empleado carga consumos, carga merma y mira el calendario. Nada más.
PANTALLAS_DEL_EMPLEADO = frozenset({
    'calendario',
    'consumo_selector',
    'consumo_evento',
    # El POST de cada renglón de la tabla de consumo: sin esto la pantalla se
    # ve pero el botón "Agregar" rebota, que es peor que no tenerla.
    'movimientostock_create',
    # Corregir lo que él mismo cargó mal. Un mozo que se equivoca en una cantidad
    # un sábado a las 3 de la mañana no puede quedar esperando al dueño.
    # ⚠️ Estas dos vistas filtran por su cuenta QUÉ movimiento puede tocar: las
    # entradas (compras del salón) quedan afuera. Ver MovimientoDelEmpleadoMixin.
    'movimientostock_update',
    'movimientostock_delete',
    'merma',
    'login',
    'logout',
})

# La casa del empleado. No es `home`: ese panel son accesos rápidos a pantallas
# que no puede abrir, así que lo mandamos derecho a lo suyo.
INICIO_DEL_EMPLEADO = 'stock:calendario'


class RolEmpleadoMiddleware:
    """Deja pasar al administrador, y al empleado solo por su lista."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Va en process_view y no en __call__ porque acá la URL ya está
        resuelta: `resolver_match` todavía es None cuando entra el request."""
        usuario = getattr(request, 'user', None)
        if usuario is None or not usuario.is_authenticated or usuario.is_staff:
            return None

        match = request.resolver_match
        permitida = (
            match is not None
            and match.app_name == 'stock'
            and match.url_name in PANTALLAS_DEL_EMPLEADO
        )
        if permitida:
            return None

        # `home` es la landing de todo el sistema (LOGIN_REDIRECT_URL): el
        # empleado cae ahí en cada ingreso sin haber tocado nada, así que ahí no
        # va reto, va la redirección y listo. El resto sí avisa.
        if match is None or match.url_name != 'home':
            messages.error(request, 'Esa pantalla es solo para administradores.')
        return redirect(INICIO_DEL_EMPLEADO)
