"""Punto de entrada para Vercel.

Vercel busca en esta carpeta un modulo que exponga una app WSGI, la envuelve en
una funcion serverless y le manda cada request. Django ya trae la suya armada en
config/wsgi.py: aca solo se la pasa con el nombre que Vercel espera.

No hay logica propia a proposito. Si algun dia se corre en un servidor normal
(gunicorn, uwsgi), el entrypoint sigue siendo config/wsgi.py y este archivo
simplemente no se usa.
"""

from config.wsgi import application

app = application
