"""Manda por mail el recordatorio de los eventos que se vienen (RN-24).

Se corre una vez por día desde afuera (Programador de tareas de Windows, cron, o
lo que sea): el comando no sabe ni le importa quién lo dispara.

    python manage.py recordar_eventos             # manda de verdad
    python manage.py recordar_eventos --dry-run   # muestra qué mandaría, sin mandar
    python manage.py recordar_eventos --dias 15   # cambia la anticipación por esta vez
    python manage.py recordar_eventos --reenviar  # ignora que ya se avisó
"""

from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.formats import date_format

from stock.models import DestinatarioAviso, Evento


class Command(BaseCommand):
    help = 'Avisa por mail los eventos que están por venir.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dias', type=int, default=None,
            help='Con cuántos días de anticipación avisar. Por defecto, DIAS_AVISO_EVENTO.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Muestra qué mandaría y a quién, sin mandar nada ni marcar nada.',
        )
        parser.add_argument(
            '--reenviar', action='store_true',
            help='Vuelve a avisar aunque el evento ya tenga el aviso marcado.',
        )

    def handle(self, *args, **opciones):
        dias = opciones['dias'] if opciones['dias'] is not None else getattr(
            settings, 'DIAS_AVISO_EVENTO', 7
        )
        ensayo = opciones['dry_run']

        destinatarios = DestinatarioAviso.direcciones_activas()
        if not destinatarios:
            self.stdout.write(self.style.WARNING(
                'No hay destinatarios activos cargados. Cargalos en /destinatarios/ '
                '(o en el admin) y volvé a correrlo.'
            ))
            return

        eventos = self._eventos_a_avisar(dias, opciones['reenviar'])
        if not eventos:
            self.stdout.write(f'No hay eventos sin avisar dentro de los próximos {dias} días.')
            return

        self.stdout.write(
            f'{len(eventos)} evento(s) para avisar a {len(destinatarios)} destinatario(s)'
            f'{" [ENSAYO: no se manda nada]" if ensayo else ""}'
        )

        # Una sola conexión SMTP para todos los mails: abrir una por evento es
        # lento y hay proveedores que lo cortan por abuso.
        conexion = None if ensayo else get_connection()
        enviados = 0

        for evento in eventos:
            asunto, cuerpo = self._armar_mail(evento, dias)

            if ensayo:
                self.stdout.write('')
                self._mostrar(self.style.HTTP_INFO(f'  Para: {", ".join(destinatarios)}'))
                self._mostrar(self.style.HTTP_INFO(f'  Asunto: {asunto}'))
                self._mostrar(cuerpo)
                continue

            try:
                EmailMessage(
                    subject=asunto,
                    body=cuerpo,
                    to=destinatarios,
                    connection=conexion,
                ).send()
            except Exception as error:
                # Un mail que falla no puede tirar abajo los que faltan, y sobre
                # todo no puede marcar como avisado algo que no salió.
                self.stderr.write(self.style.ERROR(
                    f'  No se pudo avisar "{evento.nombre}": {error}'
                ))
                continue

            Evento.objects.filter(pk=evento.pk).update(aviso_enviado_el=timezone.now())
            enviados += 1
            self.stdout.write(self.style.SUCCESS(f'  Avisado: {evento.nombre} ({evento.fecha:%d/%m/%Y})'))

        if not ensayo:
            self.stdout.write(self.style.SUCCESS(f'Listo: {enviados} aviso(s) enviado(s).'))

    def _mostrar(self, texto):
        """Escribe a la terminal sin morir por un carácter raro.

        La consola de Windows es cp1252 y levanta UnicodeEncodeError con lo que
        no entra. Las notas del evento son texto libre: alcanza con que alguien
        pegue un emoji para que `--dry-run` explote y no se pueda ni revisar qué
        se iba a mandar. El mail sale en UTF-8 igual: esto es solo la vista previa.
        """
        codificacion = getattr(self.stdout, 'encoding', None) or 'utf-8'
        self.stdout.write(texto.encode(codificacion, 'replace').decode(codificacion, 'replace'))

    def _eventos_a_avisar(self, dias, reenviar):
        """Los que caen dentro de la ventana y todavía no se avisaron.

        Es una VENTANA (de hoy a hoy+dias) y no un día exacto a propósito: si la
        máquina estuvo apagada el día que le tocaba a un evento, con la fecha
        exacta ese aviso se perdía para siempre y nadie se enteraba. Así se
        recupera en la próxima corrida.

        Los finalizados quedan afuera: ya pasaron, no hay nada que recordar.
        """
        hoy = timezone.localdate()
        eventos = (
            Evento.objects
            .filter(fecha__gte=hoy, fecha__lte=hoy + timedelta(days=dias))
            .exclude(estado='finalizado')
            .order_by('fecha')
        )
        if not reenviar:
            eventos = eventos.filter(aviso_enviado_el__isnull=True)
        return list(eventos)

    def _armar_mail(self, evento, dias):
        """El asunto y el cuerpo, en texto plano.

        Sin HTML a propósito: esto lo lee alguien del salón desde el teléfono
        para saber qué se viene, no es una newsletter.
        """
        faltan = (evento.fecha - timezone.localdate()).days
        if faltan == 0:
            cuando = 'HOY'
        elif faltan == 1:
            cuando = 'MAÑANA'
        else:
            cuando = f'en {faltan} días'

        asunto = f'Salón Victoria · {evento.nombre} · {evento.fecha:%d/%m/%Y} ({cuando})'

        lineas = [
            f'{evento.nombre}',
            '=' * len(evento.nombre),
            '',
            # date_format y no strftime: %A saca el día de la semana en el idioma
            # del SISTEMA operativo ("Sunday"), no en el de Django. Este mail lo
            # lee gente del salón.
            f'Fecha:      {date_format(evento.fecha, "l d/m/Y")}',
            f'Faltan:     {cuando}',
            f'Estado:     {evento.get_estado_display()}',
            f'Asistentes: {evento.asistentes or "sin cargar"}',
        ]

        if evento.telefono_contacto:
            lineas.append(f'Teléfono:   {evento.telefono_contacto}')
        if evento.paquete_id:
            lineas.append(f'Paquete:    {evento.paquete.nombre}')

        tarjetas = list(evento.tarjetas.all())
        if tarjetas:
            lineas += ['', 'TARJETAS']
            for tarjeta in tarjetas:
                menu = f' · {tarjeta.menu.nombre}' if tarjeta.menu_id else ''
                lineas.append(f'  {tarjeta.cantidad} × {tarjeta.concepto}{menu}')

        sugerido = evento.consumo_sugerido
        if sugerido:
            lineas += ['', 'COMIDA ESTIMADA (según la receta, no descuenta stock)']
            for item in sugerido:
                lineas.append(
                    f'  {item["cantidad"]} {item["producto"].unidad_medida} '
                    f'de {item["producto"].nombre}'
                )

        if evento.notas:
            lineas += ['', 'NOTAS', evento.notas]

        if evento.estado == 'pendiente':
            lineas += ['', 'ATENCION: este evento todavía está PENDIENTE de confirmación.']

        return asunto, '\n'.join(lineas)
