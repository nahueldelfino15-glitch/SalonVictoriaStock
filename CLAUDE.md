# CLAUDE.md — Salón Victoria · Control de Stock

Sistema interno de gestión para un salón de eventos: stock por sector, eventos,
personal, compras y consumo. Django monolítico, sin API, sin JS de framework.

---

## 1. Stack y entorno

| Item | Valor |
|------|-------|
| Framework | Django 6.1 |
| Base de datos | SQLite (`db.sqlite3` versionado en el repo) |
| Frontend | Templates Django + **Tailwind CSS (CDN)** + JS vanilla en `base.html` |
| Diseño | **Noir Luxury** — dark mode, negro en capas + dorado |
| Fuentes | Hanken Grotesk + Material Symbols Outlined, Google Fonts |
| Idioma | `es-ar` |
| Zona horaria | `America/Argentina/Buenos_Aires` |
| Auth | `LoginRequiredMiddleware` — **todo pide sesión** salvo `/ingresar/` |

### Comandos

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows PowerShell
pip install -r requirements.txt

python manage.py runserver
python manage.py makemigrations stock
python manage.py migrate
python manage.py createsuperuser
```

`requirements.txt` declara solo la dependencia directa (`Django==6.1`); las
transitivas las resuelve pip. Requiere **Python 3.12+**. El entorno virtual no se
versiona: `.gitignore` contempla `venv/`, `.venv/`, `__pycache__/`, `*.pyc`, `.env`.

---

## 2. Estructura

```
config/            # settings, urls raíz, wsgi/asgi
  settings.py      # SECRET_KEY hardcodeada, DEBUG=True
  urls.py          # /admin/ + include('stock.urls')
stock/
  models.py        # 13 modelos, toda la lógica de negocio vive acá
  views.py         # CBV para CRUD + FBV (home, compras, merma, calendario, consumo)
  urls.py          # namespace 'stock'
  admin.py         # registra los 13 modelos
  management/commands/
    reconciliar_stock.py  # cierra el libro mayor con el stock declarado
    recordar_eventos.py   # el job que avisa por mail (RN-24)
  context_processors.py # resuelve `base_template`: página completa o fragmento de modal
  templates/stock/ # 50 templates
    base.html      # tokens Tailwind + sidebar + helpers JS (tabs, modales, modal remoto)
    _base_modal.html  # base "vacía": sirve cualquier pantalla como fragmento (RN-22)
    _tabla_*.html  # 4 parciales de tabla (productos, compras, consumo, merma)
    _chip_estado.html # chip de estado del evento, compartido por 7 pantallas
  static/stock/img/LogoVictoria.png
  migrations/      # 0001 → 0015
db.sqlite3
manage.py
```

**Convención de nombres de URL**: `stock:<modelo>_<accion>` →
`producto_list`, `producto_detail`, `producto_create`, `producto_update`, `producto_delete`.
Las FBV rompen el patrón: `home`, `compras`, `calendario`, `consumo_selector`, `consumo_evento`, `evento_historial`.

---

## 3. Modelo de datos

```
Paquete ──┐
Menu ─────┼──> Evento <── PersonalEvento ──> Empleado ──> Puesto
  │       │       ^                              ^           │
  │       │       │                              └───────────┘
  │       └───────┴── MovimientoStock ──> Producto
  │                                          ^
  └──> Plato ──> LineaReceta ────────────────┘
         ^
         └── (o de un Evento: la copia heredada)
```

### `Producto`
Unidad de stock. `sector` ∈ `barra | cocina | extras | limpieza | mobiliario` (RN-8).
Campos: `nombre`, `sector`, `precio_unitario` (Decimal 10,2, **opcional**), `stock_actual`
(Decimal 10,2), `unidad_medida` (texto libre, default `'unidad'`), `activo` (baja lógica, RN-20).

### `DestinatarioAviso`
A quién le llegan los recordatorios por mail. `email` (único), `nombre`, `activo`.
Ver RN-24.

### `Paquete` / `Menu`
Catálogos planos que se asocian a un evento. `Paquete` tiene `precio`, `Menu` no.
Ambos con `on_delete=SET_NULL` desde `Evento`.

### `Evento`
Núcleo del sistema. `estado` ∈ `pendiente | confirmado | finalizado`.
Campos: `nombre`, `fecha` (DateField, sin hora), `asistentes`, `estado`, `paquete` (FK opcional), `menu` (FK opcional), `telefono_contacto`, `notas`.
Plata: `precio_cerrado`, `precio_por_persona`, `precio_paquete` (sellado, RN-17),
`brindis_asistentes`, `brindis_valor`.
Propiedades calculadas: `ingreso_*`, `desglose_ingresos`, `margen`, `gasto_stock`,
`gasto_personal`, `gasto_total`.

### `TarjetaEvento`
Lo que paga cada tipo de invitado, y qué come. Ver RN-23.
`evento` (CASCADE), `concepto`, `cantidad` (personas), `valor_unitario`,
`menu` (FK opcional, **SET_NULL**: si se borra el menú la tarjeta sigue valiendo plata).

### `Puesto`
Catálogo de puestos, administrable desde `/puestos/`. Solo `nombre` (único).
Ver RN-21.

### `Empleado`
Catálogo maestro de personal, **independiente de los eventos**.
`nombre`, `telefono`, `puesto_habitual` (FK a `Puesto`, SET_NULL).

### `PersonalEvento`
Tabla de asignación: un empleado trabajando en un evento puntual.
`evento` (CASCADE), `empleado` (**PROTECT**), `puesto` (FK a `Puesto`, **PROTECT**),
`horas_trabajadas`, `pago`.
El `puesto` acá pisa al `puesto_habitual` del empleado — es el puesto de ESE evento.

### `Plato` / `LineaReceta`
La receta de un menú, en dos niveles. Ver RN-18.
`Plato`: `paso` ∈ `entrante | principal | secundario | postre`, `nombre`, y un dueño
(`menu` **o** `evento`, nunca los dos).
`LineaReceta`: `plato` (CASCADE), `producto` (**PROTECT**), `cantidad_por_persona`
(Decimal 10,**3**).

### `MovimientoStock`
Libro mayor del stock. `tipo` ∈ `entrada | salida | merma` (RN-12).
`producto` (**PROTECT**, RN-20), `evento` (SET_NULL, **opcional**), `tipo`, `motivo`,
`cantidad`, `costo_unitario` (sellado, RN-15), `fecha` (auto).
Se ve entero en `/movimientos/`, con filtros por tipo, sector, producto, evento y fechas.

---

## 4. REGLAS DE NEGOCIO

### RN-1 · El stock se mueve SOLO por `MovimientoStock`
`Producto.stock_actual` es un valor derivado que `MovimientoStock` mantiene en sus
`save()` y `delete()`. Nunca se toca a mano desde una vista.

- `entrada` → suma a `stock_actual`
- `salida` → resta de `stock_actual`

⚠️ Ya NO hay excepción: `stock_actual` salió del form de edición y el "stock
inicial" del alta se escribe como un movimiento de entrada (RN-14).

### RN-2 · No se puede consumir más stock del que hay
`MovimientoStock.clean()` bloquea cualquier `salida` mayor al stock disponible y
devuelve el mensaje con el disponible y la unidad de medida.

Al **editar** un movimiento existente, el cálculo del disponible primero revierte
el efecto del movimiento anterior:
- si el anterior era `salida` → suma su cantidad al disponible
- si el anterior era `entrada` → la resta

⚠️ Esta validación corre solo por ModelForm (`full_clean()`). Las creaciones
directas vía `Model.objects.create()` la **saltean** — ver RN-4.

### RN-3 · Editar un movimiento revierte y reaplica
`save()` sobre un movimiento existente:
1. lee el movimiento anterior de la DB,
2. revierte su efecto sobre el stock,
3. guarda el nuevo,
4. aplica el nuevo efecto.

`delete()` revierte el efecto antes de borrar.

### RN-4 · Las compras son entradas sin evento
La pantalla **Compras** (`views.compras`) crea `MovimientoStock` con
`tipo='entrada'` y **sin `evento`** — es reposición de depósito, no consumo.
Usa `objects.create()` directo (sin `full_clean()`), lo cual es seguro porque las
entradas nunca pueden dejar stock negativo.

Solo procesa cantidades `> 0`. Tras guardar, redirige de vuelta a la misma
pestaña de sector vía fragmento (`#barra-pane`).

### RN-5 · El consumo siempre es una salida atada a un evento
La pantalla **Consumo** (`consumo_evento`) fuerza `tipo='salida'` por campo oculto
y ata el movimiento al evento por URL (`evento_pk`). El usuario solo elige cantidad.

Si la validación de stock falla, la vista **no re-renderiza el form**: manda cada
error a `django.contrib.messages` y redirige al `next`. Los mensajes se muestran
en un modal de Bootstrap que dispara solo (ver `base.html`).

### RN-6 · Gastos de un evento
```
gasto_stock    = Σ (movimiento.cantidad × producto.precio_unitario)  para tipo='salida'
gasto_personal = Σ (personalevento.pago)
gasto_total    = gasto_stock + gasto_personal
```

⚠️ **El precio NO es histórico**: usa el `precio_unitario` actual del producto. Si
cambiás el precio de un producto, el gasto de eventos ya finalizados cambia
retroactivamente. Decisión aceptada por ahora, no un descuido.

⚠️ `horas_trabajadas` es informativo: **el pago no se calcula a partir de las
horas**, se carga a mano.

### RN-7 · Eventos activos vs. historial
El estado `finalizado` es el que separa las dos listas:

| Vista | Filtro | Orden |
|-------|--------|-------|
| `evento_list` | `.exclude(estado='finalizado')` | `fecha` ascendente |
| `evento_historial` | `.filter(estado='finalizado')` | `-fecha` descendente |

No hay transición automática de estado — pasar a `finalizado` es manual desde el
form de evento.

### RN-8 · Los productos viven en sectores, y no todos se valorizan
`SECTOR_CHOICES` tiene cinco: `barra`, `cocina`, `extras`, `limpieza`, `mobiliario`.
Aparecen como pestañas en **Productos**, Compras, Merma y Consumo.

**Agregar un sector es una línea**: las cuatro pantallas iteran sobre `sectores`
(que arma `views.productos_por_sector()`) en vez de tener las pestañas escritas a
mano. Antes eran ocho bloques duplicados y se olvidaba siempre alguno.

`SECTORES_SIN_PRECIO` = `('mobiliario',)`. La vajilla, los manteles y los vasos se
**cuentan pero no se valorizan**: son del salón, no mercadería que se consuma. Sin
precio no suman a `gasto_stock`, que es justo lo que se quiere — si no, cada mantel
usado le inflaría el costo a la fiesta. El flag viaja a los templates como
`sin_precio` (en negativo a propósito: si un `include` se lo olvida, la columna
aparece en vez de desaparecer en silencio).

⚠️ El precio quedó **opcional en el form** y `Producto.save()` convierte `None` en 0.
No se esconde el campo según el sector porque eso pide JS, y los `<script>` que
entran por `innerHTML` no se ejecutan dentro de un modal (RN-22): sería un campo
que desaparece en la pantalla suelta y queda a la vista en el modal.

Orden de listado: `Lower('nombre')` — alfabético case-insensitive.

### RN-9 · Búsquedas
Siempre por parámetro GET `q`, con `nombre__icontains`, y el valor se devuelve al
contexto para repoblar el input. Aplica en Productos, Eventos, Historial y Personal.

### RN-10 · Un empleado con historial no se borra
`PersonalEvento.empleado` usa `on_delete=PROTECT`. Borrar un empleado que trabajó
en algún evento lanza `ProtectedError`. Borrar un **evento**, en cambio, arrastra
sus `PersonalEvento` (CASCADE) pero deja los `MovimientoStock` huérfanos
(SET_NULL) — el stock consumido no se devuelve.

### RN-11 · Calendario
Semana arranca **lunes** (`firstweekday=0`). Nombres de mes en español desde la
constante `MESES_ES` (no usa `locale`). El día de hoy se marca con `es_hoy`.
El panel principal (`home`) y `/calendario/` comparten la misma función
`obtener_datos_calendario()`; ambos aceptan `?year=&month=`.

"Próximos eventos" = `fecha >= hoy`, ordenados por fecha, **máximo 10**.

### RN-12 · La merma sale del stock pero no es gasto de nadie
Tercer tipo de `MovimientoStock`: `merma`. Descuenta stock igual que una `salida`,
pero **nunca lleva evento** y exige `motivo` (rotura / vencimiento / consumo interno
/ otro). `clean()` valida las dos cosas.

Existe porque antes la única salida posible era "consumo de un evento": una botella
rota había que cargársela a algún evento (inflándole el costo) o descontarla editando
`stock_actual` a mano (rompiendo el libro mayor). Las dos opciones eran malas.

`Evento.gasto_stock` filtra `tipo='salida'`, así que la merma queda afuera del costo
aunque alguien la cuelgue de un evento por la fuerza. Pantalla propia en `/merma/`.

### RN-13 · El stock se mide con decimales
`Producto.stock_actual` y `MovimientoStock.cantidad` son `DecimalField(10,2)`: hay
productos que se miden en kilos y litros. **No hay conversión de unidades**
(cajón → botella → medida): se descartó a propósito por costo.

Los formularios usan `step="0.01" min="0.01"`, y las FBV parsean con
`views.parsear_cantidad()`, que devuelve `None` ante texto, `nan`, `infinity` o
números que no entran en el campo.

### RN-14 · El stock inicial de un producto también genera movimiento
`stock_actual` **ya no es editable**: salió de `ProductoUpdateView.fields`. En el alta
se puede cargar un "stock inicial", pero `ProductoCreateView.form_valid()` lo escribe
como un `MovimientoStock` de entrada en vez de asignarlo directo. Así la suma de
movimientos siempre cierra con `stock_actual` — que es justo lo que hoy NO pasa con
los datos viejos (ver deuda técnica #1).

### RN-15 · El costo se sella en el movimiento, no se lee del catálogo
`MovimientoStock.costo_unitario` guarda lo que valía el producto **en el momento**
de registrar el movimiento. `Evento.gasto_stock` usa ese valor, no
`producto.precio_unitario`.

Sin esto, actualizar una lista de precios reescribía el costo de todos los eventos
pasados — en Argentina eso convierte el histórico en ruido.

El sello se pone en `save()` **solo al crear**, o si el movimiento pasa a apuntar a
otro producto. Corregirle la cantidad a un consumo viejo NO lo revalúa.

⚠️ Los 20 movimientos anteriores a la migración `0006` quedaron sellados con el
precio que tenía el producto ese día: el costo real de su momento nunca se guardó
y no hay forma de reconstruirlo.

### RN-16 · Un evento finalizado está cerrado
`Evento.cerrado` (= `estado == 'finalizado'`) bloquea la carga de consumo y de
personal: lo validan `MovimientoStock.clean()` y `PersonalEvento.clean()`.
`consumo_selector` tampoco lo lista.

La puerta de salida es `Evento.reabrir()`, expuesta en `/eventos/<pk>/reabrir/` (POST):
pasa el estado a `confirmado` y sella `reabierto_el`. Los olvidos existen; que el
histórico se toque sin dejar rastro, no.

⚠️ El error de bloqueo va como **non-field** (`'__all__'`) a propósito: ningún form
declara el campo `evento`, y apuntarle un error de `clean()` a un campo que el form
no tiene es un **500**, no un mensaje de validación. Misma trampa que con `motivo`.

⚠️ `MovimientoStockCreateView` y `PersonalEventoCreateView` pasan el evento por
`get_form_kwargs()` (`instance=Modelo(evento=...)`) y no solo en `form_valid()`:
la validación corre **antes** que `form_valid()`, así que sin eso `clean()` no vería
el evento y el bloqueo no se dispararía nunca en el alta.

### RN-17 · Rentabilidad: TODO lo facturado − los dos gastos
El sistema dejó de medir solo costos.

```
ingreso_tarjetas = Σ (tarjeta.cantidad × tarjeta.valor_unitario)     ← RN-23
ingreso_brindis  = brindis_asistentes × brindis_valor
ingreso_paquete  = precio_paquete            (monto TOTAL, sellado)
ingreso_base     = precio_cerrado + precio_por_persona × asistentes
ingreso_cargos   = Σ CargoEvento.monto

ingreso_total    = tarjetas + brindis + paquete + base + cargos
margen           = ingreso_total − gasto_stock − gasto_personal
```

**Todo suma; nada pisa a nada.** Antes el `precio_cerrado` mandaba sobre el
`precio_por_persona`; el dueño pidió que se sumen. La contra es real: cargar las
tarjetas Y el precio por persona factura la misma plata dos veces. Por eso existe
`Evento.desglose_ingresos` y la pantalla muestra **cada renglón abierto** — con un
total pelado eso no se ve nunca; con el detalle a la vista, sí. El desglose es
parte de la regla, no decoración.

`CargoEvento` son los adicionales facturables (barra libre, DJ, hora extra).
**Se llama CARGO y no "extra" a propósito**: `extras` ya es un sector de stock
(RN-8), que es un COSTO. Este es un INGRESO. Mismo nombre para conceptos opuestos
es garantía de que alguien los sume mal.

#### El monto del paquete se sella, no se lee del catálogo
`Evento.precio_paquete` guarda lo que salía el paquete **cuando se lo eligió**, y
`Evento.save()` lo completa solo. `ingreso_paquete` lee ese campo y **nunca**
`paquete.precio`.

Es RN-15 del lado del ingreso, y cierra dos agujeros medidos:
- editarle el precio a "Premium" cambiaba la facturación de todos los eventos ya
  cerrados que lo usaran;
- borrar "Premium" del catálogo (`Evento.paquete` es `SET_NULL`) bajaba un evento
  cerrado de $129.013 a **$0** de un click, y mostraba el número nuevo con total
  confianza. Exactamente el bug de RN-20, pero con la plata que entra.

El campo es editable: un evento se puede haber cerrado por otro número que el de
la lista, y corregirlo a mano no lo pisa el catálogo.

⚠️ El paquete es un **monto total**, no un precio por cubierto. Multiplicarlo por
los asistentes inventaría facturación: el evento de 15 (123 asistentes) mostraría
$15.868.599 en vez de $129.013.

`Evento.tiene_precio_cargado` es `bool(ingreso_total)`: sin nada cargado la
pantalla dice "sin precio" y no "$0". `margen_porcentaje` devuelve `None` cuando no
hay ingreso, en vez de dividir por cero.

### RN-18 · La receta se carga en el MENÚ, organizada por platos
La receta es un árbol de tres niveles:

```
Menu ──> Plato (paso + nombre) ──> LineaReceta (producto + cantidad_por_persona)
```

`Plato.paso` ∈ `entrante | principal | secundario | postre`, y tiene **nombre
propio** ("Bife con papas"), porque un menú real no es una bolsa de ingredientes:
es una sucesión de platos. `Meta.ordering` usa un `Case/When` (`ORDEN_DE_SERVICIO`)
para que el entrante vaya antes que el principal — alfabéticamente sería al revés.

`Plato` tiene **dos dueños posibles** y nunca los dos a la vez (`CheckConstraint`):

- colgado de un **`Menu`**: la receta base. `Menu.costo_por_persona` la recorre
  entera para costear el cubierto y poder ponerle precio.
- colgado de un **`Evento`**: la copia heredada de ese menú.

**El evento hereda la receta solo**: `Evento.save()` detecta que el menú cambió y
llama a `copiar_receta_del_menu()`, que **reemplaza** lo que hubiera. Guardar el
evento por cualquier otro motivo NO recopia — si no, corregir un teléfono pisaría
la receta. `/eventos/<pk>/receta/copiar/` (POST) la vuelve a traer a mano, para
cuando el menú se corrigió con el evento ya cargado.

Son copias a propósito: si el evento apuntara al menú, cambiar la receta base en
marzo cambiaría lo que se calculó para un evento de enero. El menú evoluciona; lo
ya cargado, no.

`cantidad_por_persona` tiene **3 decimales** (0,125 L de una copa) mientras que
`MovimientoStock.cantidad` tiene 2, así que `LineaReceta.cantidad_para()` redondea
al sugerir. Sin eso, el form propone un número que después no entra en el campo.

`Producto` en una receta usa `on_delete=PROTECT`: no se puede borrar un producto que
alguna receta esté usando.

### RN-19 · La receta sugiere, no descuenta
`Evento.consumo_sugerido` calcula `cantidad_por_persona × asistentes` y esas
cantidades aparecen **precargadas** en los inputs de la pantalla de consumo. El
usuario corrige con lo que realmente salió y confirma.

Un mismo producto puede estar en varios platos (la papa va en el principal y en la
guarnición): se **suman las porciones antes de redondear**, y sale UNA sola línea
de consumo. Dos redondeos por separado dan otro número.

`Evento.receta_calculada` es lo mismo pero agrupado por plato, y es lo que queda
asentado en el detalle del evento. Cuelga los ingredientes de cada plato como
atributo (`plato.ingredientes`) porque los templates de Django no pueden llamar a
un método con argumentos: `plato.para(asistentes)` no se puede escribir en el HTML.

**Ningún camino descuenta stock automáticamente.** Es la decisión 8 del dueño: el
consumo se registra después del evento y siempre es un acto humano. Si se
descontara solo, el stock del sistema divergiría del real cada vez que sobre o
falte algo — que es exactamente el problema que veníamos a resolver.

⚠️ La receta **no se carga desde Consumo**. Esa pantalla se quedó solo con lo suyo
(barra / cocina / extras / personal). Tener dos lugares para cargar lo mismo
garantiza que se contradigan.

### RN-20 · Un producto con historial no se borra: se da de baja
`MovimientoStock.producto` usa **`PROTECT`**, no `CASCADE`.

El motivo es directo: con RN-15 el costo congelado vive DENTRO del movimiento, así
que borrar un producto se llevaba puestos sus movimientos y **cambiaba el margen de
eventos ya cerrados**. Medido: un evento cerrado pasaba de $800.000 de ganancia a
$900.000 con un solo click, y mostraba el número nuevo con total confianza.

`Producto.activo` es la baja lógica. Un producto dado de baja:
- **no aparece** en Compras, Consumo ni Merma (los filtra `views.productos_por_sector()`),
- **sí aparece** en el listado de Productos, con un chip y un botón para reactivarlo,
- **conserva** todo su historial y los costos congelados que dependen de él.

`ProductoDeleteView` atrapa el `ProtectedError` y da de baja en vez de explotar, con
un mensaje que explica qué pasó. Si el producto no tiene movimientos, se borra normal.

⚠️ Un producto dado de baja **tampoco se lista en Productos**. Existe para sostener
el historial, no para llenar la pantalla de cosas que ya no se compran. Se ven con
`?bajas=1`, que es además la única forma de reactivarlos; la pantalla avisa cuántos
hay para que nadie crea que se perdieron.

### RN-21 · Los puestos son un catálogo, no una constante
`Puesto` es una tabla con CRUD propio en `/puestos/`. `Empleado.puesto_habitual` y
`PersonalEvento.puesto` son FK a esa tabla, y los selects se llenan desde ahí.

No son `choices` en el código porque el salón cambia de servicios: tiene que poder
agregar "Valet" o "Fotógrafo" sin esperar un deploy. La migración `0010` los siembra
con los siete que pidió el dueño (Mozo, Barman, Cocina, Dj, Limpieza, Seguridad,
Otro) y de ahí en adelante los administra él.

Los `on_delete` van distinto a propósito:
- `Empleado.puesto_habitual` → **SET_NULL**: es solo el puesto que suele ocupar.
- `PersonalEvento.puesto` → **PROTECT**: es historial de pagos. Borrar "Barman" del
  catálogo dejaría sin etiqueta lo que ya se liquidó. `PuestoDeleteView` atrapa el
  `ProtectedError` y avisa en cuántas asignaciones está usado.

⚠️ Los datos viejos venían sucios (`Moso`, `moso`, `Barra`): la migración los
normaliza con una tabla de alias. Un texto que no reconoce lo crea como puesto tal
cual — perder un dato cargado por no reconocerlo sería peor que un puesto de más.

### RN-22 · Todo el CRUD se abre en un modal, con el MISMO template
No hay templates duplicados para la versión modal. Lo único que cambia es de qué
hereda el template:

```django
{% extends base_template|default:'stock/base.html' %}
```

`stock/context_processors.modal` resuelve `base_template` a `_base_modal.html`
cuando la request trae `X-Requested-With: XMLHttpRequest`, y a `base.html` si no.
Va como **context processor y no como mixin** para no tocar las 30 CBV y para que
cualquier pantalla nueva lo tenga gratis.

En el HTML basta con marcar el enlace:

```html
<a href="{% url 'stock:producto_update' p.pk %}" data-modal-link>Editar</a>
```

El JS de `base.html` hace el fetch, mete el fragmento en `#modalRemoto` y manda los
forms sin recargar. **Distingue "guardó" de "hay errores" por el redirect**: si la
respuesta viene redirigida, navega ahí; si viene HTML, lo repinta con los errores.

⚠️ `_base_modal.html` **no imprime los mensajes de Django** a propósito. Si los
imprimiera quedarían consumidos y la pantalla a la que se redirige después de
guardar no mostraría nada.

⚠️ Tampoco incluye `extra_js`: los `<script>` insertados por `innerHTML` no se
ejecutan, así que ofrecerlo sería prometer algo que no pasa.

⚠️ El `href` siempre apunta a una pantalla completa que funciona sola. El modal es
una mejora, no un requisito: sin JS, con Ctrl+click o si el fetch falla, la URL
suelta sigue andando. Los botones "Cancelar" llevan
`{% if es_modal %}data-modal-close{% endif %}` — condicional, porque el atributo
suelto haría `preventDefault()` en la página normal y el link no navegaría.

### RN-23 · Las tarjetas: quién paga cuánto, y quién come qué
`TarjetaEvento` es un tipo de invitado dentro del evento: `concepto`, `cantidad`,
`valor_unitario` y un `menu` opcional. Una misma fiesta de 100 puede ser 80
tarjetas de adulto a un precio y 20 de menú infantil a otro — por eso son filas y
no un precio único en el evento.

⚠️ En este modelo `cantidad` son **personas** (no unidades de stock, como en
`MovimientoStock.cantidad`) y `valor_unitario` es un **ingreso** (no el costo de
`Producto.precio_unitario`). Los nombres se repiten en el proyecto con sentidos
opuestos: mirar de qué modelo es antes de sumar.

**La comida se calcula por tarjeta.** `Evento.raciones_por_menu()` arma
`{menu_id: porciones}` desde las tarjetas, y `copiar_receta_del_menu()` copia los
platos de cada menú dejándoles las porciones que les tocan en `Plato.porciones`.
Después `consumo_sugerido` multiplica por **las porciones del plato**, no por los
asistentes del evento: 80 raciones de un menú y 20 de otro no son 100 de cada uno.

- Dos tarjetas del mismo menú se **suman en un solo bloque** (80 adultos + 10
  músicos del mismo menú = 90 raciones, no dos recetas iguales una abajo de la otra).
- Una tarjeta **sin menú** factura pero no pide comida.
- Un producto que está en los dos menús sale en **una sola línea** de consumo, con
  el total sumado antes de redondear (RN-19).
- Guardar o borrar una tarjeta **recopia la receta** del evento. Sin eso, agregar
  "20 menús infantiles" sumaría la plata pero la comida seguiría calculando 80
  raciones de adulto, y nadie lo notaría hasta que falte.

⚠️ Si hay tarjetas con menú, **ellas mandan**: un plato del evento sin `porciones`
(cargado a mano desde el admin) se ignora. Sin esa guarda se sumaba en paralelo,
100 raciones arriba de las 80 + 20, sin ningún aviso.

⚠️ Recopiar **borra y recrea** los platos del evento, así que sus `pk` cambian cada
vez que se toca una tarjeta. Es coherente con RN-18 ("copiar reemplaza"), pero pasa
mucho más seguido que antes: no guardes referencias a un plato de evento.

Retrocompatibilidad: un evento **sin tarjetas** cae a `Evento.menu × asistentes`,
que es como funcionaba antes y lo que siguen usando los eventos ya cargados.

⚠️ En ese caso los platos se copian con `porciones = None`, NO con el número de
asistentes del momento. Sellarlo ahí congelaba la cuenta: corregir los asistentes de
100 a 150 dejaba la receta pidiendo para 100, y un evento cargado con 0 asistentes
(hay uno real: "Casamiento Nascar") quedaba sugiriendo 0 de todo para siempre. Con
`None`, `consumo_sugerido` y `Plato.para()` multiplican **en vivo**.

`Evento.tarjetas_vs_asistentes` avisa si las tarjetas no cuadran con los asistentes,
pero **no bloquea**: en un salón los números bailan hasta último momento y trabar la
carga sería peor que el aviso.

⚠️ La recopia se dispara por **señal** (`post_save`/`post_delete` de `TarjetaEvento`),
no sobrescribiendo `save()`/`delete()`. Es la misma trampa que ya se comió este
proyecto con `MovimientoStock`: `queryset.delete()` NO pasa por `Model.delete()`, así
que borrar tarjetas en masa desde el admin dejaba la receta con los platos de un
grupo que ya no existía. Las señales sí se emiten en todos esos caminos.

### RN-24 · Los recordatorios los manda un job, no la app
`python manage.py recordar_eventos` avisa por mail los eventos que se vienen. Se
corre **una vez por día desde afuera** (Programador de tareas de Windows, cron, o un
HTTP call): el comando no sabe ni le importa quién lo dispara, y por eso sirve igual
si algún día la app se muda a un servidor.

```bash
python manage.py recordar_eventos --dry-run    # muestra qué mandaría, sin mandar
python manage.py recordar_eventos --dias 15    # otra anticipación, por esta vez
python manage.py recordar_eventos --reenviar   # ignora que ya se avisó
```

`DestinatarioAviso` es una tabla con CRUD en `/destinatarios/`, no un setting: mismo
criterio que los puestos (RN-21). `activo` corta el aviso sin perder la dirección.

**Es una VENTANA (de hoy a hoy+N), no un día exacto.** Con la fecha justa, si la
máquina estuvo apagada el día que le tocaba a un evento, ese aviso se perdía para
siempre y nadie se enteraba. `Evento.aviso_enviado_el` es lo que evita repetir; se
puede vaciar para que vuelva a salir.

⚠️ El evento se marca como avisado **solo si el mail salió**. Marcarlo antes sería
peor que fallar: no se reintenta nunca y el aviso se pierde en silencio.

El backend de mail **se elige solo**: si hay `EMAIL_HOST` en el entorno usa SMTP, y
si no imprime por la terminal. Así una máquina recién clonada arranca sin configurar
nada y nadie le manda un mail de prueba a un cliente real por accidente. La pantalla
de `/destinatarios/` avisa cuando está en modo consola.

⚠️ El cuerpo del mail se imprime con `_mostrar()` y no con `stdout.write()` directo:
la consola de Windows es cp1252 y levanta `UnicodeEncodeError` con lo que no entra.
Las notas del evento son texto libre — un emoji alcanzaba para tirar abajo el
`--dry-run` y dejarte sin poder revisar qué se iba a mandar.

⚠️ El día de la semana sale con `django.utils.formats.date_format`, no con
`strftime('%A')`: el segundo usa el idioma del **sistema operativo** y mandaba
"Sunday" en un mail que lee gente del salón.

### RN-25 · Dos roles, y el rol es un booleano que Django ya trae
Hay **administrador** y **empleado**. Nada más, y por eso el rol NO es un modelo
nuevo ni un `Group`: es `User.is_staff`.

| `is_staff` | Rol | Qué puede |
|-----------|-----|-----------|
| `True` | Administrador | Todo el sistema, `/usuarios/` y `/admin/` |
| `False` | Empleado | Todo menos `/usuarios/` (el recorte fino está por definirse) |

Dos roles son un booleano. Una tabla `Rol` con su FK, su migración y su CRUD para
guardar un bit sería el clásico caso de construir el edificio antes de saber si
hay inquilinos. Y `is_staff` de yapa **cierra `/admin/` solo**: el empleado queda
afuera de las dos puertas con una sola marca, sin código de por medio.

El gating es `SoloAdminMixin` (en `views.py`): `test_func` mira `is_staff` y
`handle_no_permission` redirige a la home con un mensaje en vez de tirar un 403
pelado — la sesión ya existe (la exige `LoginRequiredMiddleware`), así que lo
único que cae ahí es un empleado tocando una URL que no le toca. **Para restringir
otra pantalla al administrador, alcanza con colgarle el mixin.**

El grupo "Sistema" del sidebar va dentro de `{% if user.is_staff %}`. Esconder el
link es prolijidad; lo que frena de verdad es el mixin.

**El módulo de usuarios**: alta con `UserCreationForm` (la subclase solo agrega
`is_staff` a `Meta.fields` — las dos contraseñas y sus validadores ya están
resueltos), edición de nombre/rol/acceso, contraseña con `SetPasswordForm`, y
baja. Las tres pantallas de form comparten `usuario_form.html`, que recibe
`titulo` y `subtitulo` por `extra_context`.

⚠️ **Nadie se saca a sí mismo el acceso ni se borra.** El último administrador
degradándose deja el sistema sin nadie que pueda entrar a arreglarlo. Al editarse
a uno mismo, `is_staff` e `is_active` van con `disabled=True` (que además ignora
lo que venga por POST, no solo lo esconde), y `UsuarioDeleteView.get_queryset()`
se excluye a sí mismo → 404. Va en la vista, no en el template: el botón se
esconde, la URL no.

⚠️ **Degradar a empleado también apaga `is_superuser`.** Sin eso, un superusuario
bajado de rango sale del módulo pero conserva TODOS los permisos de Django y pasa
cualquier `has_perm` que se agregue después.

⚠️ Un administrador que no sea superusuario entra a `/admin/` y ve la pantalla
**vacía**: `is_staff` abre la puerta, los permisos son otra cosa. Es correcto —
el sistema se opera desde las pantallas propias, no desde el admin.

⚠️ Los usuarios son la única tabla del sistema **sin FK que la proteja**: borrar
uno no arrastra nada (ningún modelo apunta a `User`). Para alguien que se fue pero
podría volver, la opción buena es destildar "Puede ingresar", no borrar.

---

## 5. Flujos de usuario

**Reponer stock** → `/compras/` → pestaña de sector → cantidad → `+ Agregar`
→ genera `entrada` sin evento.

**Registrar consumo** → `/consumo/` → elegir evento → pestaña de sector →
cantidad → `+ Agregar` → genera `salida` atada al evento.
La cuarta pestaña ("Personal") de esa misma pantalla asigna empleados al evento.

**Alta / edición / baja / detalle de cualquier cosa** → **modal** sobre el listado
(RN-22). No hay forms duplicados: el modal carga por fetch el mismo template de la
pantalla suelta.

**Cargar la receta de un menú** → `/menus/<pk>/` → por cada paso (entrante,
principal, secundario, postre) → `+ Agregar plato` → dentro del plato,
`+ Agregar ingrediente` con la cantidad **por persona**. El pie muestra el costo
del cubierto.

**Ver cuánto hace falta para un evento** → asignarle el menú al evento (la receta
se copia sola) → `/eventos/<pk>/` → sección "Receta del evento", con las cantidades
ya multiplicadas por los asistentes.

**Ver rentabilidad de un evento** → `/eventos/<pk>/` → receta estimada + tabla de
consumo + tabla de personal + cargos + margen.

**Dar de alta a alguien que va a usar el sistema** → `/usuarios/` (solo el
administrador lo ve) → `Nuevo usuario` → nombre + contraseña, y tildar
"Administrador" solo si va a manejar todo. La persona ya puede entrar por
`/ingresar/`. Si se olvida la clave, el icono 🔑 de la fila se la cambia (RN-25).

---

## 6. Convenciones de código

- **Toda la lógica de negocio va en `models.py`**, no en las vistas. `MovimientoStock`
  es el ejemplo: valida en `clean()`, mantiene el stock en `save()`/`delete()`.
- CRUD estándar → CBV genéricas con `fields = [...]` inline. **No hay `forms.py`** y
  no hace falta crearlo salvo que se necesite validación cruzada de campos.
- Pantallas operativas (compras, consumo, calendario) → FBV, porque el flujo es
  "postear un dato y volver a la misma pestaña", no un CRUD.
- **Patrón `next`**: los forms embebidos mandan un campo oculto `next` y
  `get_success_url()` lo respeta. Así se vuelve a la pestaña correcta.
- **Errores al usuario**: `messages.error()` + modal automático en `base.html`.
- Los parciales `_tabla_*.html` reciben `productos` y `tab_id` por `{% include ... with %}`.

### Estilos: Tailwind por CDN, sin build

Todo el sistema vive en el `<head>` de `base.html`: el `tailwind.config` inline
(colores, tipografía, radios, spacing) y un `<style>` con utilitarias custom.
**No hay build step, no hay Node, no hay `package.json`.**

Paleta (tokens de Tailwind, no variables CSS):

| Token | Hex | Uso |
|-------|-----|-----|
| `surface-base` | `#0a0a0a` | fondo de la app |
| `surface-raised` | `#161616` | tarjetas, inputs |
| `surface-overlay` | `#242424` | hover, divisores |
| `primary` | `#f2ca50` | todo lo interactivo |
| `primary-container` | `#d4af37` | labels de tabla, acentos |
| `on-surface-high` | `#ffffff` | títulos |
| `on-surface` | `#eae1d4` | cuerpo |
| `on-surface-med` | `#a1a1a1` | secundario |
| `outline-variant` | `#4d4635` | bordes |
| `error` | `#ffb4ab` | errores |

La profundidad se hace **por capas de tono, no por sombras** — sobre negro una
sombra se ve barro.

Clases custom en el `<style>` (con valores hex literales, porque el CDN de Tailwind
no procesa `theme()` dentro de un `<style>` plano):
`.luxury-button-primary`, `.luxury-button-secondary`, los overrides de
`input`/`select`/`textarea` y `.material-symbols-outlined`.

⚠️ Los selectores de formulario van prefijados con `html` a propósito, para ganarle
por especificidad al reset del plugin `forms`. Para pisarlos desde una pantalla hay
que usar el modificador important de Tailwind: `!bg-surface-base`, `!border-solid`.

### Helpers JS: vanilla, por atributos `data-*`

Bootstrap se fue completo. `base.html` trae tres helpers propios, sin dependencias:

**Pestañas** — el `#hash` de la URL abre la pestaña correcta al cargar (crítico:
`compras` y `consumo_evento` redirigen a `#barra-pane`).
```html
<div data-tabs>
  <button type="button" data-tab-target="#barra-pane">Barra</button>
</div>
<div id="barra-pane" data-tab-panel>…</div>
```

**Modales** — disparador `data-modal-open="#id"`, contenedor `data-modal` (oculto
con `hidden`), cierre por `data-modal-close`, Escape o click en el overlay.
`data-modal-autoopen` lo abre solo al cargar (lo usa el modal de mensajes).

**Modal remoto** — `data-modal-link` en un `<a>` con `href` real (RN-22).

**Panel lateral** — reemplazó al nav horizontal. Colapsa a solo iconos en
escritorio y entra/sale completo en mobile. El ancho y el margen del contenido se
manejan con **CSS sobre `html[data-sidebar="colapsado"]`**, no con clases de
Tailwind toggleadas por JS: así un script inline en el `<head>` aplica el estado
guardado en `localStorage` **antes del primer pintado**. Con JS al final, cada
carga mostraría el panel abierto y lo cerraría de golpe a la vista del usuario.

API pública por si una pantalla la necesita: `window.Victoria.abrirModal()`,
`.cerrarModal()`, `.activarTab()`.

⚠️ **Los `id` de pestaña son contrato con las vistas**: `barra-pane`, `cocina-pane`,
`extras-pane`, `personal-pane`. Cambiarlos rompe el redirect post-carga.

### Trampas de template de Django que ya nos mordieron

Un `QueryDict` o un atributo inexistente **usado como argumento de filtro**
(`|add:request.resolver_match.url_name`, `|default:request.GET.next`) propaga
`VariableDoesNotExist` y **revienta el render entero** — Django no lo atrapa ahí.

- Para el `next` opcional: `{% firstof request.POST.next request.GET.next '' %}`.
- Para lookups que pueden no existir: sacalos a su propio `{% with %}` con
  `|default:"…"`, donde el fallo sí cae en `string_if_invalid`.

---

## 7. Bugs conocidos / deuda técnica

### 🔴 Abiertos / importantes

1. **El libro mayor no cierra con `stock_actual`** — divergencia medida de **36
   unidades** sobre los 5 productos, y en 3 de ellos la suma de movimientos da
   **negativo** (hay salidas de mercadería que nunca entró). Causa: durante meses
   `stock_actual` fue editable a mano, así que la carga inicial nunca generó el
   movimiento que la respalda. Desde la Fase 1 ese agujero está cerrado.

   La herramienta ya está hecha y probada, **falta ejecutarla**:
   ```bash
   python manage.py reconciliar_stock              # diagnóstico, no escribe
   python manage.py reconciliar_stock --confirmar  # escribe los asientos
   ```
   Toma `stock_actual` como la verdad física (es lo que alguien contó en el
   depósito) y agrega los asientos que faltaban. **No mueve el stock**: usa
   `bulk_create` justamente para saltear `save()`, que lo movería y volvería a
   descuadrar. Conviene contar el depósito antes de correrlo.

2. **El costo de los eventos no es histórico** — `Evento.gasto_stock` valúa con el
   `precio_unitario` **de hoy**, así que un evento del año pasado cambia de costo
   con la inflación. Se resuelve en la Fase 2 (congelar el costo unitario en cada
   movimiento).

3. ~~`Paquete.precio` sin usar~~ — **resuelto**: se sella en `Evento.precio_paquete`
   al elegir el paquete (RN-17), como monto total. El evento de 15 pasó de mostrar
   $0 a $129.013. Los otros dos siguen sin precio: hay que cargarles las tarjetas.

4. **`Menu` sigue sin precio de venta.** Ya tiene composición y
   `costo_por_persona` (RN-18), así que se sabe cuánto CUESTA el cubierto, pero no
   a cuánto se vende: el precio se carga a mano en cada evento (RN-17). Falta
   decidir si el menú debe proponerlo.

### 🟡 Medios

5. **`MovimientoStock.fecha` es `auto_now_add`**, no editable: si cargás el lunes
   lo del sábado, la fecha miente. Ahora se nota más, porque el **historial de
   movimientos** (`/movimientos/`) la muestra y se puede filtrar por rango.

6. **`horas_trabajadas` no calcula el pago** y ni `Empleado` ni `Puesto` tienen
   tarifa. El pago se carga a mano en cada evento, y el mismo empleado puede
   cargarse dos veces en el mismo evento, duplicando el pago sin aviso.
   ⚠️ El `unique_together` NO se puede agregar sin más: los datos actuales YA tienen
   duplicados (3 filas de `PersonalEvento` con mismo evento/empleado/puesto), así que
   la migración fallaría. Hay que fusionarlos primero.

7. **Sin aviso de stock mínimo** — la pantalla de Compras no marca qué falta reponer.
   Se evaluó y se descartó por ahora: nadie lo pidió explícitamente.

### 🟢 Menores

8. `db.sqlite3` está versionado en git, **a propósito**: hoy es el método de
   sincronización del proyecto. Sacarlo es una decisión aparte, no un descuido.
   El backup `db.sqlite3.backup-*` sí está ignorado.
9. La migración `0002` eliminó `Evento.hora_inicio`: los eventos manejan fecha, no hora.
10. **El modal remoto gasta un request de más al guardar.** El fetch sigue el
    redirect para saber a dónde ir, y después el browser navega ahí de nuevo. Se
    podría evitar con `redirect: 'manual'`, pero entonces no se sabe el destino y
    habría que recargar la pantalla actual — que no siempre es la correcta (borrar
    un evento desde su detalle). Es una app interna de un solo salón: se paga.

### ✅ Resueltos en la auditoría del 2026-08-12

- ~~`PersonalEventoUpdateView` rota (`FieldError`)~~ — `fields` corregidos.
- ~~Editar un movimiento corrompía el stock (86 en vez de 96)~~ — la aritmética la
  hace la base con `F()`, no instancias en memoria, dentro de `transaction.atomic`.
  Esto se llevó puesta también la falta de atomicidad.
- ~~Sin autenticación~~ — `LoginRequiredMiddleware` + `LoginView`/`LogoutView` con
  template propio. Las 40 vistas piden sesión; solo `/ingresar/` es pública.
- ~~`get_success_url()` explotaba con movimientos sin evento~~ — `volver_del_movimiento()`
  manda cada uno a la pantalla de la que salió.
- ~~`int(cantidad)` sin protección (500)~~ — `parsear_cantidad()` devuelve `None` y avisa.
- ~~Borrado masivo en el admin no revertía el stock~~ — `queryset.delete()` no pasa por
  `Model.delete()`; se sobrescribió `delete_queryset()`. **No estaba documentado.**
- ~~`views.compras` con código muerto / imports triplicados~~.
- ~~`Paquete` y `Menu` sin registrar en el admin~~.
- ~~`SECRET_KEY`, `DEBUG` y `ALLOWED_HOSTS` hardcodeados~~ — por variable de entorno.
- ~~`TIME_ZONE = 'UTC'`~~ — `America/Argentina/Buenos_Aires`.
- ~~El setting de mail se llamaba `MAILERS`~~, que Django ignora. Es `EMAIL_BACKEND`.
- ~~Sin tests~~ — 39 tests en `stock/tests.py`.
- ~~`_tabla_compras.html` con `<form>` anidado~~ — corregido en la migración a Tailwind.
- ~~Sin `requirements.txt`~~ — creado con `Django==6.1`.

---

## 8. Al trabajar en este proyecto

- **No agregues dependencias.** Tailwind por CDN y Django puro alcanzan. En especial:
  **no metas Node, ni un build step, ni `django-tailwind`, ni `django-compressor`**.
  El CDN tiene un costo real (no purga clases sin usar), y es un costo que este
  proyecto puede pagar: es una app interna de un solo salón.
- **No crees `forms.py`** salvo que la validación no entre en `Model.clean()`.
- Si tocás un template, verificá que los `{% url %}`, los `name=` de inputs y los
  `id` de pestaña queden intactos. Son contrato con las vistas, no decoración.
- Si tocás el stock, verificá los tres caminos: form de consumo, pantalla de
  compras y el admin. Los tres escriben `MovimientoStock` de forma distinta.
- Los mensajes al usuario van en español rioplatense, sin tecnicismos.
- Antes de agregar un sector, un estado o un tipo de movimiento: son constantes
  con `choices` y aparecen replicadas en templates.
