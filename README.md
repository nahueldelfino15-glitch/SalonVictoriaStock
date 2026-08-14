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

> ⚠️ **Si ya tenías el repo de antes y hacés `git pull`**: `db.sqlite3` está versionado,
> es binario y **git no lo sabe mergear**. Si le cargaste datos, el pull va a dar
> conflicto. La salida rápida es quedarte con la del repo:
> ```bash
> git checkout --theirs db.sqlite3 && git add db.sqlite3
> ```
> Si querés conservar lo tuyo, copiala antes con otro nombre. No hay migración que
> valga: son dos bases distintas.

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
      El **puesto** es una lista desplegable, no texto libre.

### 4. Historial de movimientos
- [ ] **Movimientos** (en el menú lateral) → tiene que listar todo lo que cargaste
      hasta ahora, con su fecha, lo más nuevo arriba.
- [ ] Filtrá por **tipo** (entrada / salida / merma), por **sector** y por **rango de fechas**.
- [ ] Desde **Consumo** de un evento, el botón **Historial** te lleva ahí ya filtrado
      por ese evento.

### 5. Limpieza y mobiliario
- [ ] **Productos** → pestañas **Limpieza** y **Mobiliario**, además de las tres de siempre.
- [ ] Cargá un producto de limpieza (nombre, stock, precio) y uno de mobiliario.
- [ ] En **Mobiliario** el precio **no aparece**: se cuenta pero no se valoriza.
      Podés dejarlo vacío al cargarlo.
- [ ] Cargá consumo de mobiliario a un evento: **no le tiene que subir el costo**.
      Los manteles son del salón, no un gasto de la fiesta.

### 6. Tarjetas y ganancia
Acá está el cálculo de plata. Es lo más importante de esta tanda.

- [ ] **Eventos** → entrá a uno → sección **Tarjetas** → "Agregar tarjeta".
      Cargá dos: `Adultos, 80, $50.000` y `Menú infantil, 20, $30.000`.
- [ ] Asignale a cada una **su propio menú** (si tenés dos menús cargados).
- [ ] Editá el evento y cargale el **brindis**: cuántos participan y a cuánto.
- [ ] Elegile un **paquete**: el monto se completa solo y se puede corregir.
- [ ] Abajo, en **Resultado del evento**, tiene que aparecer el **desglose abierto**:
      cada tarjeta, el brindis, el paquete, los cargos, y recién ahí los dos gastos
      restándose. Verificá que la suma cierre con el total.
- [ ] **La prueba que importa**: andá a **Paquetes**, cambiale el precio al que usaste,
      y volvé al evento. **El facturado no se tiene que mover.** Probá también
      borrando el paquete: tampoco.

### 7. Puestos
- [ ] **Puestos** → la lista la administrás vos. Vienen cargados Mozo, Barman, Cocina,
      Dj, Limpieza, Seguridad y Otro; agregá uno nuevo (ej. "Valet").
- [ ] Intentá **borrar un puesto que esté usado** en algún evento: te tiene que frenar.
      Es historial de pagos, no se puede dejar sin etiqueta lo ya liquidado.

### 8. Recetas
La receta se carga **solo en el menú**, organizada en platos. El evento la hereda.

- [ ] **Menús** → entrá a un menú → en cada paso (Entrante / Plato principal / Plato
      secundario / Postre) usá **"Agregar plato"** y ponele nombre (ej. "Bife con papas").
- [ ] Dentro del plato, **"Agregar ingrediente"** con la cantidad **por persona**
      (ej. 0,250 kg de carne). Abajo te dice el **costo del cubierto**.
- [ ] Asignale ese menú a un evento (editando el evento, o desde una **tarjeta**).
      **La receta se copia sola**: no hay que traerla a mano.
- [ ] Entrá al **detalle del evento** → sección "Receta del evento": tienen que estar
      las cantidades ya multiplicadas, y cada plato con su chip de **porciones**.
- [ ] Con dos tarjetas de menús distintos (80 adultos / 20 infantil), cada menú
      tiene que pedir **por su propia cantidad**, no por los 100.
- [ ] Andá a **Consumo** de ese evento: en Barra / Cocina / Extras las cantidades
      aparecen **precargadas**. Ojo: solo sugiere, **no descuenta solo**. Tenés que
      corregir con lo que salió de verdad y confirmar.
- [ ] Si un producto está en **dos platos**, tiene que aparecer **una sola vez** en
      consumo, con las cantidades sumadas.

### 9. Modales y menú lateral
- [ ] El menú de la izquierda **colapsa** con el botón ☰ de arriba. Cerrá el navegador,
      volvé a entrar: tiene que **acordarse** de cómo lo dejaste.
- [ ] Cualquier **ver / editar / eliminar** de una tabla abre un **modal**, sin cambiar
      de pantalla.
- [ ] Guardá con un campo obligatorio **vacío**: el error tiene que aparecer **dentro
      del modal**, sin recargar la página.
- [ ] Abrí uno de esos links con **Ctrl+click**: tiene que abrir la pantalla completa
      en otra pestaña. El modal es una comodidad, no un requisito.

### 10. Cierre de evento
- [ ] Editá el evento y ponelo en **Finalizado**.
- [ ] Intentá cargarle consumo: no te tiene que dejar.
- [ ] En el detalle del evento aparece **"Reabrir evento"**. Usalo y probá que ahora sí deja.
- [ ] Fijate que queda la marca de "Reabierto el ...".

### 11. Recordatorios por mail
- [ ] **Avisos** (menú lateral) → agregá uno o más destinatarios. Podés silenciar a
      alguien sin borrarlo (destildá "activo").
- [ ] Probá sin mandar nada:
      ```bash
      python manage.py recordar_eventos --dry-run
      ```
      Te muestra por pantalla exactamente qué mail saldría y a quién.
- [ ] Si un evento cae dentro de los próximos 7 días, el mail tiene que traer la
      fecha, los asistentes, las tarjetas, la comida estimada y **las notas**.
- [ ] Corré el comando **dos veces sin `--dry-run`**: el segundo no manda nada.
      Cada evento se avisa una sola vez.

**Para que los mails salgan de verdad** hace falta un servidor de correo. Con Gmail,
usá una **contraseña de aplicación** (no la tuya personal) y definí estas variables
de entorno antes de correr:

```powershell
$env:EMAIL_HOST="smtp.gmail.com"
$env:EMAIL_HOST_USER="salonvictoria@gmail.com"
$env:EMAIL_HOST_PASSWORD="xxxxxxxxxxxxxxxx"
$env:DEFAULT_FROM_EMAIL="Salon Victoria <salonvictoria@gmail.com>"
```

Sin eso el sistema queda en modo consola: los mails se imprimen en la terminal en
vez de enviarse. Es a propósito, para que nadie mande un mail de prueba a un cliente
real por accidente. La pantalla de Avisos te lo dice.

**Para que corra solo**, Programador de tareas de Windows → Crear tarea básica →
Diariamente 8:00 → Iniciar un programa:

| Campo | Valor |
|-------|-------|
| Programa | `C:\...\SalonVictoriaStock\.venv\Scripts\python.exe` |
| Argumentos | `manage.py recordar_eventos` |
| Iniciar en | `C:\...\SalonVictoriaStock` |

Ojo: solo manda si la PC está prendida a esa hora. Si un día estuvo apagada, el aviso
**no se pierde** — el comando trabaja con una ventana de días, así que sale en la
próxima corrida.

### 12. Que el pasado no se mueva
Esto es lo más importante del sistema, y lo más fácil de romper:

- [ ] Anotá el **costo** de un evento que ya tenga consumo cargado.
- [ ] Andá a Productos y **cambiale el precio** a uno de los productos que consumió.
- [ ] Volvé al evento: **el costo tiene que seguir igual**.
- [ ] Ahora probá **borrar** ese producto: te va a decir que lo da de baja en vez de
      borrarlo, y el costo del evento **tampoco tiene que cambiar**.
- [ ] Ese producto **desaparece del listado** de Productos. No se perdió: abajo de todo
      hay un aviso con **"Ver dados de baja"**, y desde ahí se reactiva.

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

Son **181** y tienen que pasar todos. Cubren la aritmética del stock, la validación
de faltantes, la merma, el congelamiento de costos, el margen, las recetas por plato,
el catálogo de puestos, las tarjetas, los recordatorios por mail y que los
modales no se coman los mensajes.

## Dónde está la documentación técnica

En [CLAUDE.md](CLAUDE.md): modelo de datos, las 24 reglas de negocio, las trampas
conocidas y la deuda técnica pendiente.
