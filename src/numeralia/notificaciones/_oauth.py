"""
Alcances OAuth2 de token_gmail.json, compartidos por todo lo que lo usa
(Gmail, Drive, y scripts/autorizar_gmail.py).

Viven en un solo lugar a propósito: si cada módulo cargara y renovara las
credenciales pidiendo SOLO su propio alcance (gmail.py con gmail.send,
drive.py con drive), la primera renovación que toque —el token de acceso
vence cada hora— le pide a Google un token nuevo recortado a ESE alcance
nada más. Google lo entrega así aunque el refresh token de fondo siga
cubriendo los dos permisos, y el siguiente módulo que use ese token de
acceso ya recortado truena con 'insufficientPermissions'. Pidiendo siempre
los dos juntos, sin importar cuál renueve primero, el token sigue sirviendo
para ambos.
"""

ALCANCES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/drive',
]
