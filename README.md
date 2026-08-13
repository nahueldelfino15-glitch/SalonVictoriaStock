# Salón Victoria · Control de Stock

Sistema interno de gestión para un salón de eventos: stock por sector, eventos,
personal, compras, consumo y rentabilidad.

Django 6.1 + SQLite + Tailwind por CDN. Sin Node, sin build step, sin API.

---

## Arrancarlo (5 minutos)

Necesitás **Python 3.12 o superior**. Nada más.

```bash
# 1. Entorno virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # Windows PowerShell
# source .venv/bin/activate      # Linux / Mac

# 2. Dependencias (es una sola: Django)
pip install -r requirements.txt

# 3. Base de datos
python manage.py migrate

# 4. Levantarlo
python manage.py runserver
```

Y entrá a **http://127.0.0.1:8000/**

La base (`db.sqlite3`) viene versionada con datos de prueba adentro, así que no
hace falta cargar nada para empezar a mirar.

### Para entrar

El sistema **pide usuario**: todas las pantallas están detrás del login.

Hay un usuario `Admin` cargado. Si no sabés la contraseña, creá el tuyo:

```bash
python manage.py createsuperuser
```

---

## Qué probar

Un recorrido que toca todo lo importante, en orden. Si algo de esto falla, es un bug.

### 1. Stock y compras
- [ ] **Productos** → "Nuevo producto" con un **stock inicial** (ej. 10). Guardalo y fijate
      que el producto quede con ese stock.
- [ ] Entrá a **editar** ese producto: el campo de stock **no se puede tocar**. Es a propósito.
- [ ] **Compras** → cargale cantidad a un producto. Probá con **decimales** (2,5).
- [ ] Volvé a Productos y verificá que el stock subió.

### 2. Merma
- [ ] **Merma** → elegí un producto, un motivo (rotura / vencimiento / consumo interno)
      y una cantidad. El stock tiene que bajar.
- [ ] Probá mermar **más de lo que hay**: te tiene que frenar con un aviso.

### 3. Eventos y consumo
- [ ] **Eventos** → "Nuevo evento" con fecha, asistentes y un **precio** (por persona o cerrado).
- [ ] **Consumo** → elegí el evento → cargá consumo de algún producto.
- [ ] Entrá al **detalle del evento**: tiene que mostrar Facturado / Costo / **Ganancia**.
- [ ] Agregale un **cargo al cliente** (ej. "DJ", $50.000) y mirá cómo cambia la ganancia.
- [ ] Asignale **personal** desde la pestaña Personal de la pantalla de consumo.

### 4. Recetas (lo nuevo)
- [ ] **Menús** → entrá a un menú → "Agregar producto" a la receta, con la cantidad
      **por persona** (ej. 0,250 kg de carne). Abajo te dice el **costo del cubierto**.
- [ ] Asignale ese menú a un evento (editando el evento).
- [ ] En **Consumo** del evento → pestaña **Receta** → "Traer de <menú>".
- [ ] Volvé a las pestañas Barra / Cocina / Extras: las cantidades tienen que aparecer
      **precargadas** (receta × asistentes). Ojo: solo sugiere, **no descuenta solo**.

### 5. Cierre de evento
- [ ] Editá el evento y ponelo en **Finalizado**.
- [ ] Intentá cargarle consumo: no te tiene que dejar.
- [ ] En el detalle del evento aparece **"Reabrir evento"**. Usalo y probá que ahora sí deja.
- [ ] Fijate que queda la marca de "Reabierto el ...".

### 6. Que el pasado no se mueva
Esto es lo más importante del sistema, y lo más fácil de romper:

- [ ] Anotá el **costo** de un evento que ya tenga consumo cargado.
- [ ] Andá a Productos y **cambiale el precio** a uno de los productos que consumió.
- [ ] Volvé al evento: **el costo tiene que seguir igual**.
- [ ] Ahora probá **borrar** ese producto: te va a decir que lo da de baja en vez de
      borrarlo, y el costo del evento **tampoco tiene que cambiar**.

---

## Qué NO está hecho todavía

Para que no lo reportes como bug:

- **No hay ficha de cliente.** El evento tiene nombre y teléfono sueltos, nada más.
- **No hay control de agenda.** Podés cargar varios eventos el mismo día sin aviso. Es a propósito.
- **No hay aviso de stock mínimo.** No te dice qué hay que reponer.
- **No hay conversión de unidades.** Si comprás por cajón y consumís por botella, la
  cuenta la hacés vos.
- **El pago del personal se carga a mano.** Las horas trabajadas son informativas, no calculan nada.
- **El mismo empleado se puede cargar dos veces en el mismo evento** y se duplica el pago.
- **La fecha de un movimiento no se puede editar** (queda la de cuando lo cargaste).
- Los 3 eventos de prueba **no tienen precio cargado**, así que muestran "sin precio"
  en vez de ganancia. Cargáselo para ver los números.

## Un tema pendiente de la base de prueba

El stock declarado **no coincide** con la suma de movimientos: hay 36 unidades de
diferencia, heredadas de cuando el stock se podía editar a mano. Para verlo:

```bash
python manage.py reconciliar_stock              # solo muestra el diagnóstico
python manage.py reconciliar_stock --confirmar  # crea los asientos que faltan
```

No está corrido a propósito. En una base real conviene contar el depósito antes.

---

## Correr los tests

```bash
python manage.py test stock
```

Son **80** y tienen que pasar todos. Cubren la aritmética del stock, la validación
de faltantes, la merma, el congelamiento de costos, el margen y las recetas.

## Dónde está la documentación técnica

En [CLAUDE.md](CLAUDE.md): modelo de datos, las 20 reglas de negocio, las trampas
conocidas y la deuda técnica pendiente.
