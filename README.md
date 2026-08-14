# Salón Victoria · Control de Stock

Sistema interno de gestión para un salón de eventos: stock por sector, eventos,
personal, compras, consumo y rentabilidad.

Django 6.1 + **Supabase (Postgres)** + Tailwind por CDN. Sin Node, sin build step, sin API.

---

## Arrancarlo

Necesitás **Python 3.12 o superior** y una cuenta de Supabase (gratis).

**Los datos viven en Supabase, no en tu máquina.** Lo que cargás vos lo ve el
otro al instante: no hay archivo de base que copiar ni que mergear.

### 1. Crear el proyecto en Supabase (una sola vez, 3 minutos)

1. Entrá a **[supabase.com](https://supabase.com)** → *New project*.
2. Ponele nombre (`salon-victoria`), elegí una contraseña para la base y la
   región **South America (São Paulo)** — es la más cerca, y cada milisegundo
   de latencia se paga en cada pantalla.
3. Esperá el minuto y medio que tarda en levantar.
4. Andá a **Project Settings → Database → Connection string** y copiá la del
   **Session pooler**.

> ⚠️ **Copiá la del Session pooler, NO la "Direct connection".**
> La directa (`db.<algo>.supabase.co`) es **IPv6**, y la mayoría de las
> conexiones hogareñas argentinas no tienen IPv6: falla con
> `network is unreachable` y parece que erraste la contraseña. La del pooler
> (`aws-0-....pooler.supabase.com`) anda por IPv4.

> ⚠️ Si la contraseña tiene `@`, `/`, `:` o `?`, hay que escaparla en la URL.
> Lo más simple es generar una sin símbolos raros desde el panel.

### 2. Levantar la app

```bash
# Entorno virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # Windows PowerShell
# source .venv/bin/activate      # Linux / Mac

# Dependencias (Django y el driver de Postgres)
pip install -r requirements.txt

# Configuración: copiá el ejemplo y pegá tu connection string
cp .env.example .env             # en Windows: copy .env.example .env
#   ...y editá .env con la string del paso 1

# Crear las tablas en Supabase
python manage.py migrate

# Tu usuario administrador
python manage.py createsuperuser

# Levantarlo
python manage.py runserver
```

Y entrá a **http://127.0.0.1:8000/**

El `migrate` deja los catálogos ya cargados: los siete puestos (Mozo, Barman,
Cocina, Dj, Limpieza, Seguridad, Otro) y las cuatro unidades de medida (Cajas,
Kilogramos, Litros, Unidad). El resto lo cargás vos desde las pantallas.

> El `.env` **no se versiona**: tiene la contraseña de la base. Cada uno tiene
> el suyo apuntando al mismo proyecto de Supabase.

---

## Publicarlo en Vercel (deploys automáticos desde GitHub)

Cada `git push` a `main` republica el sistema solo. Los deploys tardan ~1 minuto.

### 1. Subir el repo a GitHub

Si ya está en GitHub (este lo está), saltealo. Si no:

```bash
git remote add origin https://github.com/TU-USUARIO/SalonVictoriaStock.git
git push -u origin main
```

### 2. Conectar Vercel

1. Entrá a **[vercel.com](https://vercel.com)** e ingresá **con tu cuenta de GitHub**.
2. **Add New → Project** → elegí el repo `SalonVictoriaStock` → **Import**.
3. Framework Preset: dejá **Other**. No toques Build Command ni Output Directory:
   `vercel.json` ya dice todo lo que hace falta.
4. **Antes de darle Deploy**, abrí *Environment Variables* y cargá estas cuatro:

| Name | Value |
|------|-------|
| `DATABASE_URL` | La misma string de Supabase que tenés en tu `.env` |
| `DJANGO_SECRET_KEY` | Una clave larga y random (abajo dice cómo generarla) |
| `CRON_SECRET` | Cualquier texto largo inventado, para el aviso diario |
| `TZ` | `America/Argentina/Buenos_Aires` |

Para la `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

5. **Deploy**. En un minuto te da la URL: `salon-victoria-stock.vercel.app`.

> No hace falta setear `DJANGO_DEBUG` ni `DJANGO_ALLOWED_HOSTS`: en Vercel se
> resuelven solos. `DEBUG` arranca en `False` **por diseño**, no por variable —
> con `DEBUG=True` una página de error le muestra a cualquiera el settings
> completo, con la contraseña de la base adentro.

### 3. Los deploys automáticos ya están andando

Desde acá, cada push a `main` publica solo. Y cada rama o Pull Request estrena su
propia URL de preview, que apunta **a la misma base de Supabase** — ojo con eso:
probar en una preview toca los datos de verdad.

### 4. El recordatorio diario

`vercel.json` ya declara el cron: todos los días a las 11 UTC (8 de la mañana en
Argentina) Vercel llama a `/avisos/cron/`, que dispara `recordar_eventos` (RN-24).

No hace falta configurar nada más, pero verificá que **`CRON_SECRET` esté cargada**:
sin ella la URL devuelve 503 y no manda nada. Es a propósito — una URL que le
manda mails a los clientes no puede quedar abierta porque faltó una variable.

Para probarlo a mano:

```bash
curl -H "Authorization: Bearer TU_CRON_SECRET" https://tu-app.vercel.app/avisos/cron/
```

### Lo que tenés que saber de correr en Vercel

- **Cold start.** Si nadie entró en un rato, la primera pantalla tarda 1–3 segundos.
  Las siguientes van normales. Es así en todo lo serverless.
- **Timeout de 10 segundos** en el plan gratis. Ninguna pantalla del sistema se
  acerca, pero si algún día una tarda, el síntoma es un 504.
- **No hay disco.** Nada que el sistema escriba en un archivo sobrevive al request.
  Por eso los datos van a Supabase y no a SQLite.
- **Los logs** están en Vercel → tu proyecto → *Logs*. Ahí aparece cualquier error
  de producción, porque con `DEBUG=False` el navegador solo muestra "Server Error".

### Si algo falla en el primer deploy

| Síntoma | Qué es |
|---------|--------|
| `DisallowedHost` | Falta que Vercel setee `VERCEL=1` (lo hace solo). Revisá que `vercel.json` esté en la raíz |
| Formularios rebotan con **CSRF** | `CSRF_TRUSTED_ORIGINS` — se arma solo en Vercel; si usás dominio propio, agregalo |
| `too many clients` en Supabase | Conexiones colgadas. `CONN_MAX_AGE` va en 0 en Vercel, ya está resuelto |
| El logo no carga | WhiteNoise. Verificá que esté en `requirements.txt` |
| `ImproperlyConfigured: Falta DATABASE_URL` | No cargaste la variable de entorno en Vercel |

---

### Si querés ver el sistema con datos antes de cargar los reales

```bash
python manage.py poblar_demo              # muestra qué haría
python manage.py poblar_demo --confirmar  # BORRA TODO y genera 2 meses de uso
```

Genera 60 productos, 22 eventos, 4 menús con receta, 16 empleados y 663
movimientos, todo coherente entre sí (el libro mayor cierra). Usa semilla fija:
dos corridas dan exactamente lo mismo.

⚠️ **`--confirmar` borra todos los datos de la base a la que estés apuntando.**
Si ya tenés `.env` con Supabase, borra los de Supabase. Una vez que el salón
empiece a cargar datos de verdad, ese comando no se toca más.

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
- [ ] **Eventos** → "Nuevo evento" con fecha y asistentes. **No pide precio**: lo que
      se cobra por cubierto se carga en las tarjetas (sección 6).
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

### 7. Unidades de medida y PDF
- [ ] **Unidades** (menú lateral) → vienen Cajas, Kilogramos, Litros y Unidad;
      agregá una nueva (ej. "Botellas").
- [ ] Cargá un producto: **Unidad de medida es un desplegable**, ya no texto libre.
- [ ] Intentá **borrar una unidad que esté en uso**: te tiene que frenar.
- [ ] En **Productos**, editá o borrá algo de la pestaña *Extras*: al guardar tenés
      que **volver a Extras**, no a Barra.
- [ ] Botón **Descargar PDF** en el detalle de un evento, en Productos y en Eventos.
      Abre el diálogo de impresión: elegí **"Guardar como PDF"** como destino.
      En el papel no salen ni el menú ni los botones, y va en negro sobre blanco.

### 8. Cierre de stock por conteo
Así se cuenta de verdad: al terminar la fiesta contás lo que sobró, no lo que salió.

- [ ] **Consumo** → elegí el evento → botón **"Cerrar por conteo"**.
- [ ] Tenés 20 Cocas y te quedaron 15: poné **15**. Dale a "Calcular consumo".
- [ ] Te muestra **"se consumió 5"** antes de tocar nada. Ahí confirmás.
- [ ] Verificá que el stock bajó a 15 y que las 5 aparecen en el consumo del evento.
- [ ] **Lo que dejás vacío no se toca.** Vacío es "no lo conté"; **0** es "no quedó nada".
- [ ] Probá poner **más de lo que hay** (25 sobre 20): te avisa y no registra nada.
      Eso no es consumo, es que falta cargar una compra.

### 9. Menús del evento
- [ ] En el **detalle del evento**, después de Personal asignado, está **Menús del evento**
      con cuánta gente come de cada uno.
- [ ] Con dos tarjetas de menús distintos, tiene que decir 80 y 20, no 100 y 100.
- [ ] Botón **"Qué hace falta"** → los productos y cantidades para esas porciones.
      Lo que no alcanza en stock sale en rojo.
- [ ] Cambiale los asistentes al evento (sin tarjetas): las porciones se recalculan solas.

### 10. Puestos
- [ ] **Puestos** → la lista la administrás vos. Vienen cargados Mozo, Barman, Cocina,
      Dj, Limpieza, Seguridad y Otro; agregá uno nuevo (ej. "Valet").
- [ ] Intentá **borrar un puesto que esté usado** en algún evento: te tiene que frenar.
      Es historial de pagos, no se puede dejar sin etiqueta lo ya liquidado.

### 11. Recetas
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

### 12. Modales y menú lateral
- [ ] El menú de la izquierda **colapsa** con el botón ☰ de arriba. Cerrá el navegador,
      volvé a entrar: tiene que **acordarse** de cómo lo dejaste.
- [ ] Cualquier **ver / editar / eliminar** de una tabla abre un **modal**, sin cambiar
      de pantalla.
- [ ] Guardá con un campo obligatorio **vacío**: el error tiene que aparecer **dentro
      del modal**, sin recargar la página.
- [ ] Abrí uno de esos links con **Ctrl+click**: tiene que abrir la pantalla completa
      en otra pestaña. El modal es una comodidad, no un requisito.

### 13. Cierre de evento
- [ ] Editá el evento y ponelo en **Finalizado**.
- [ ] Intentá cargarle consumo: no te tiene que dejar.
- [ ] En el detalle del evento aparece **"Reabrir evento"**. Usalo y probá que ahora sí deja.
- [ ] Fijate que queda la marca de "Reabierto el ...".

### 14. Recordatorios por mail
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

### 15. Que el pasado no se mueva
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
- Los datos de la base son **inventados**: los clientes no existen y los precios son
  aproximados. Sirven para ver el sistema con volumen, no para sacar conclusiones
  de negocio.

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

Son **237** y tienen que pasar todos. Cubren la aritmética del stock, la validación
de faltantes, la merma, el congelamiento de costos, el margen, las recetas por plato,
el catálogo de puestos, las tarjetas, el cierre por conteo, los recordatorios por
mail y que los modales no se coman los mensajes.

**Los tests corren en SQLite en memoria, no contra Supabase** — tardan 2 minutos
en vez de 20, y no necesitan internet. Los datos del sistema viven solo en
Supabase; esto es la suite, que arma y tira su propia base en cada corrida.
Está en `config/settings.py`, en el `if CORRIENDO_TESTS`.

## Dónde está la documentación técnica

En [CLAUDE.md](CLAUDE.md): modelo de datos, las 31 reglas de negocio, las trampas
conocidas y la deuda técnica pendiente.
