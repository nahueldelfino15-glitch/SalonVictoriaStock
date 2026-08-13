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
| Zona horaria | `UTC` (⚠️ ver Deuda técnica) |
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
  models.py        # 11 modelos, toda la lógica de negocio vive acá
  views.py         # CBV para CRUD + FBV (home, compras, merma, calendario, consumo)
  urls.py          # namespace 'stock'
  admin.py         # registra Producto, Evento, Empleado, MovimientoStock, Plato, Puesto
  context_processors.py # resuelve `base_template`: página completa o fragmento de modal
  templates/stock/ # 41 templates
    base.html      # tokens Tailwind + sidebar + helpers JS (tabs, modales, modal remoto)
    _base_modal.html  # base "vacía": sirve cualquier pantalla como fragmento (RN-22)
    _tabla_*.html  # 4 parciales de tabla (productos, compras, consumo, merma)
    _chip_estado.html # chip de estado del evento, compartido por 7 pantallas
  static/stock/img/LogoVictoria.png
  migrations/      # 0001 → 0010
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
Unidad de stock. `sector` ∈ `barra | cocina | extras`.
Campos: `nombre`, `sector`, `precio_unitario` (Decimal 10,2), `stock_actual` (**PositiveInteger**), `unidad_medida` (texto libre, default `'unidad'`).

### `Paquete` / `Menu`
Catálogos planos que se asocian a un evento. `Paquete` tiene `precio`, `Menu` no.
Ambos con `on_delete=SET_NULL` desde `Evento`.

### `Evento`
Núcleo del sistema. `estado` ∈ `pendiente | confirmado | finalizado`.
Campos: `nombre`, `fecha` (DateField, sin hora), `asistentes`, `estado`, `paquete` (FK opcional), `menu` (FK opcional), `telefono_contacto`, `notas`.
Propiedades calculadas: `gasto_stock`, `gasto_personal`, `gasto_total`.

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
Libro mayor del stock. `tipo` ∈ `entrada | salida`.
`producto` (CASCADE), `evento` (SET_NULL, **opcional**), `tipo`, `cantidad`, `fecha` (auto).

---

## 4. REGLAS DE NEGOCIO

### RN-1 · El stock se mueve SOLO por `MovimientoStock`
`Producto.stock_actual` es un valor derivado que `MovimientoStock` mantiene en sus
`save()` y `delete()`. Nunca se toca a mano desde una vista.

- `entrada` → suma a `stock_actual`
- `salida` → resta de `stock_actual`

Excepción real: el campo `stock_actual` está editable en el form de Producto
(alta y edición), así que un alta con "stock inicial" lo escribe directo sin
generar movimiento. Es intencional para la carga inicial.

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

### RN-8 · Los productos viven en 3 sectores, siempre
`barra`, `cocina`, `extras` están hardcodeados en `SECTOR_CHOICES` y se repiten
como tres pestañas en **Productos**, Compras, Merma y Consumo. Agregar un sector
implica tocar el modelo **y** las cuatro pantallas.

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

---

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

### RN-17 · Rentabilidad: ingreso − costo = margen
El sistema dejó de medir solo costos.

```
ingreso_base   = precio_cerrado  (si está cargado)
                 si no: precio_por_persona × asistentes
                 si no hay ninguno: 0
ingreso_cargos = Σ CargoEvento.monto
ingreso_total  = ingreso_base + ingreso_cargos
margen         = ingreso_total − gasto_total
```

`CargoEvento` son los adicionales facturables (barra libre, DJ, hora extra).
**Se llama CARGO y no "extra" a propósito**: `extras` ya es un sector de stock
(RN-8), que es un COSTO. Este es un INGRESO. Mismo nombre para conceptos opuestos
es garantía de que alguien los sume mal.

Hay dos formas de precio porque las dos existen en la realidad del salón: hay
eventos que se cierran por un monto total y otros que se cobran por cubierto. El
cerrado manda si están los dos.

⚠️ **`ingreso_base` NO se deduce de `Paquete.precio`, a propósito.** Ese campo es
ambiguo: el paquete "Premium" está cargado en `129013`, que es el precio TOTAL. Si
se lo tomara como por-persona, el evento de 15 (123 asistentes) mostraría
$15.868.599 facturados con 100% de margen. Un número inventado que parece real es
peor que no tener número: por eso, sin precio cargado, la pantalla dice
"sin precio" y no "$0".

`Evento.tiene_precio_cargado` distingue esos dos casos, y `margen_porcentaje`
devuelve `None` cuando no hay ingreso en vez de dividir por cero.

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

3. **`Paquete.precio` sigue sin usarse.** Con RN-17 el precio se carga en el evento
   (`precio_cerrado` / `precio_por_persona`), no se hereda del paquete, porque el
   dato cargado es ambiguo. Los 3 eventos existentes quedaron **sin precio**: hay
   que cargárselo a mano para que muestren margen.

4. **`Menu` sigue sin precio de venta.** Ya tiene composición y
   `costo_por_persona` (RN-18), así que se sabe cuánto CUESTA el cubierto, pero no
   a cuánto se vende: el precio se carga a mano en cada evento (RN-17). Falta
   decidir si el menú debe proponerlo.

### 🟡 Medios

5. **`MovimientoStock.fecha` es `auto_now_add`**, no editable: si cargás el lunes
   lo del sábado, la fecha miente.

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
