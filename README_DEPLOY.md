# VANTA - Como subir la pagina a internet

## Archivos importantes

- `app.py`: backend de Flask.
- `templates/index.html`: tienda.
- `templates/admin.html`: panel de pedidos.
- `requirements.txt`: librerias necesarias.
- `Procfile`: comando que usa Render para arrancar la web.
- `vanta.db`: base de datos local. En Render se crea sola.

## Como correrlo en tu PC

```powershell
cd "C:\Users\Marcelo\OneDrive\Escritorio\Vantra Ropa"
py -m pip install -r requirements.txt
py app.py
```

Despues abrir:

```text
http://127.0.0.1:5000/
```

Panel de pedidos:

```text
http://127.0.0.1:5000/admin
```

## Como subirlo a Render

1. Crear una cuenta en Render:
   https://render.com

2. Subir la carpeta del proyecto a GitHub.

3. En Render tocar `New +`.

4. Elegir `Web Service`.

5. Conectar el repositorio de GitHub donde subiste VANTA.

6. Configurar:

```text
Runtime: Python
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app
```

7. Tocar `Deploy Web Service`.

Cuando termine, Render te da un link publico para compartir.
