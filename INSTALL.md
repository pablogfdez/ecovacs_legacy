# Instalación de Ecovacs Legacy (XMPP) para la Deebot OZMO 930

Integración personalizada (`ecovacs_legacy`) que habla XMPP/XML directamente con la OZMO 930.
Convive con la integración oficial `ecovacs`, pero **no deben usar la misma cuenta a la vez**.

## Instalación manual

1. Copia la carpeta `custom_components/ecovacs_legacy` a `<config>/custom_components/` de Home Assistant
   (queda `<config>/custom_components/ecovacs_legacy/manifest.json`).
2. Reinicia Home Assistant.
3. **Desactiva o elimina** la entrada de la integración oficial Ecovacs que use la misma cuenta
   (Ajustes → Dispositivos y servicios → Ecovacs → ⋮ → Deshabilitar). Dos conexiones XMPP con el mismo
   recurso se expulsan mutuamente.
4. Ajustes → Dispositivos y servicios → Añadir integración → **Ecovacs Legacy (XMPP)**.
5. Introduce correo, contraseña, país y, opcionalmente, el `device_id` que usaba la integración oficial
   (evita un nuevo código de verificación). Si Ecovacs pide código, introdúcelo.

## HACS (opcional)

HACS → ⋮ → Repositorios personalizados → URL de tu repositorio con esta carpeta → categoría *Integración*.
Ajusta las URLs de `manifest.json` (actualmente marcadores de posición).

## Uso

Entidades: `vacuum` (iniciar, pausar, parar, volver a base, localizar, velocidad de succión) y sensores
(batería, vida útil de cepillos y filtro, etc.).

Comandos extra con `vacuum.send_command`:

```yaml
service: vacuum.send_command
target: { entity_id: vacuum.deebot }
data: { command: spot_area, params: { areas: "0,1" } }
```

Otros comandos: `custom_area`, `edge`, `set_water_level`, o cualquier comando crudo (ver
[docs/OZMO930_COMMANDS.md](docs/OZMO930_COMMANDS.md)).

## Depuración

```yaml
logger:
  logs:
    custom_components.ecovacs_legacy: debug
```

Censura tokens y JIDs antes de compartir logs. Para ver las tramas XMPP sin Home Assistant:

```powershell
pip install aiohttp deebot-client
$env:ECOVACS_PASSWORD = "tu_contraseña"
python scripts/xmpp_probe.py --help
```

## Problemas frecuentes

- **Entidad no disponible**: comprueba que la oficial está deshabilitada y revisa el log en DEBUG.
- **Fallo de certificado TLS**: el cliente reintenta sin verificar el certificado (los servidores legacy
  tienen certificados débiles) y avisa en el log.
- **Avisos `sleekxmppfs` / `fulljid deprecated`**: provienen de la integración oficial (py-sucks);
  desaparecen al deshabilitarla. Esta integración no usa esa biblioteca.
- Probada solo contra un servidor XMPP simulado; las tramas reales pueden requerir ajustes menores.
