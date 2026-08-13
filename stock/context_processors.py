"""Lo que necesita el chrome de la app en todas las pantallas."""


def modal(request):
    """De qué base hereda el template: la página entera o el fragmento del modal.

    Todo el CRUD se abre en un modal, pero los templates son LOS MISMOS que los
    de la página suelta: lo único que cambia es de qué heredan. Así el modal
    muestra exactamente lo que muestra la pantalla, sin una segunda copia del
    HTML que se desincroniza a la primera edición.

    Va como context processor y no como mixin en las vistas para no tener que
    tocar las 30 CBV — y para que cualquier pantalla nueva lo tenga gratis.
    """
    es_modal = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    return {
        'es_modal': es_modal,
        'base_template': 'stock/_base_modal.html' if es_modal else 'stock/base.html',
    }
