# Comandos y protocolo de la Deebot OZMO 930 (XMPP / XML)

Fuente: [ecovacs-deebot.js](https://github.com/mrbungle64/ecovacs-deebot.js)
(`library/non950type/*`, `library/models.js`, `library/errorCodes.json`) y la documentación de
[Deebot Universe](https://deebot.readthedocs.io/home/models/), que clasifica la OZMO 930 como
**XMPP + XML** (el modelo `115` "DEEBOT OZMO/PRO 930 Series", tipo `legacy`, `950type: false`).
`deebot-client` solo implementa REST/MQTT + JSON, por eso la integración oficial no la soporta de forma fiable.

Capacidades del modelo: cepillo principal, cepillo lateral, filtro, limpieza por zonas (`spot_area`),
área personalizada (`custom_area`), sistema de fregado (`mopping_system`), informe de voz y mapa.

## Transporte

| Elemento | Valor |
| --- | --- |
| Login REST | API de Ecovacs (la reutiliza `deebot-client`): `user_id` + `token` |
| Servidor | `msg-<continente>.ecouser.net:5223` (TLS directo; continente `ww`, `eu`, `na`, `as`) |
| Dominio XMPP | `ecouser.net` |
| JID cliente | `<user_id>@ecouser.net/<resource>` con `resource` = 8 primeros caracteres del *device id* |
| Autenticación | SASL `PLAIN`; usuario `<user_id>`, contraseña `0/<resource>/<token>` |
| JID del robot | `<did>@<class>.ecorobot.net/atom` (`class` viene de la lista de dispositivos, p. ej. `115`) |
| Keep-alive | `iq type="get"` con `<query xmlns="urn:xmpp:ping"/>` cada 30 s |

## Envío de comandos

```xml
<iq id="1" from="<user>@ecouser.net/<resource>" to="<did>@<class>.ecorobot.net/atom" type="set">
  <query xmlns="com:ctl">
    <ctl td="NombreComando" id="12345678" atributo="valor"> <hijo atributo="valor"/> </ctl>
  </query>
</iq>
```

La respuesta llega como `iq type="result"` (o `set`) con `<ctl id="12345678" ret="ok" ...>`; el robot
también emite mensajes espontáneos con `<ctl td="OnXxx">`/`td="CleanReport"`, etc.

## Comandos (`td`)

| Comando | Atributos / hijos | Descripción |
| --- | --- | --- |
| `Clean` | `<clean type="auto\|border\|spot\|SpotArea\|singleroom\|stop" speed="standard\|strong" act="s\|p\|r\|h"/>` | Iniciar (`s`), pausar (`p`), reanudar (`r`) y parar (`h`) |
| `Clean` (zonas) | `clean` + `mid="0,1"` (ids de zona) | Limpieza por zonas (`type="SpotArea"`) |
| `Clean` (área libre) | `clean` + `p="x1,y1,x2,y2"` `deep="1..2"` | Área personalizada |
| `Charge` | `<charge type="go"/>` | Volver a la base |
| `GetCleanState` | – | Estado de limpieza (`clean`) |
| `GetChargeState` | – | `<charge type="Going\|SlotCharging\|WireCharging\|Idle"/>` |
| `GetBatteryInfo` | – | `<battery power="0-100"/>` |
| `GetCleanSpeed` / `SetCleanSpeed` | `speed="standard\|strong"` | Potencia de succión |
| `GetWaterPermeability` / `SetWaterPermeability` | `v="1..4"` | Caudal de agua (fregado) |
| `GetWaterBoxInfo` | – | `on="0\|1"` depósito instalado |
| `GetLifeSpan` | `type="Brush\|SideBrush\|DustCaseHeap"` | Vida útil: `val`/`total` |
| `GetCleanSum` | – | Totales: `a` (m²), `l` (s), `c` (nº) |
| `GetCleanLogs` / `GetLogs` / `GetLogApiCleanLogs` | `count="20"` | Historial |
| `GetPos` / `GetChargerPos` | – | `p="x,y"`, `a="ángulo"` |
| `GetNetInfo` | – | `wi` (IP), `s` (SSID) |
| `GetSleepStatus` | – | `st` |
| `GetOnOff` / `SetOnOff` | `t="b\|g\|s"` (+`on`) | `b` no molestar, `g` limpieza continua, `s` silenciar voz |
| `PlaySound` | `sid="0"` | Localizar al robot |
| `Move` | `<move action="forward\|backward\|SpinLeft\|SpinRight\|trunAround\|stop"/>` | Control manual |
| `GetMapM`, `PullMP` (`pid`), `PullM` (`tp`,`msid`,`mid`), `GetMapSet` (`tp="sa\|vw"`) | – | Mapa, zonas y muros virtuales |
| `GetSched` | – | Programaciones |

Mensajes recibidos relevantes: `CleanSt`, `ChargeState`, `BatteryInfo`, `CleanReport`, `CleanSpeed`,
`LifeSpan`, `Pos`, `ChargerPos`, `WaterPermeability`, `WaterBoxInfo`, `NetInfo`, `SleepStatus`,
`Error`, `CleanSum`, `CleanLogs`, `OnOff`, `Sched`, `MapSet`, `MapM`.

## Mapeos

- Acción: `s`=start, `p`=pause, `r`=resume, `h`=stop.
- Modo: `auto`, `border`=edge, `spot`, `SpotArea`=spot_area, `singleroom`=single_room, `stop`, `going`=returning.
- Succión: `standard` (normal), `strong` (alta).
- Carga: `Going`/`going`=volviendo; `SlotCharging`/`slot_charging`/`WireCharging`=cargando; `Idle`/`idle`=reposo.
- Componentes: `Brush`=cepillo principal, `SideBrush`=lateral, `DustCaseHeap`=filtro.
- Motivos de parada (`STOP_REASON`): `s` completada, `r` batería baja, `a` app, `i` mando, `b` botón,
  `w` aviso, `f` no molestar, `m` clearmap, `n` sin ruta, `u` fuera de mapa, `v` muro virtual.
- Errores: `100`/`0` sin error, `101` batería baja, `102` robot levantado, `103` rueda, `104` sensores de caída,
  `105` atascado, `106` cepillo lateral caducado, `107` filtro caducado, `108` cepillo lateral enredado,
  `109` cepillo principal enredado, `110` sin depósito de polvo, `111` parachoques, `112` LDS,
  `113` cepillo principal caducado, `114` depósito lleno, `120` error depósito de agua, `404` destinatario no disponible.
  Lista completa en `protocol.py` (`ERROR_CODES`).

## Nota

Los nombres exactos de atributos de algunas respuestas se han portado de ecovacs-deebot.js sin poder
probarlos con un robot real en este repositorio. Usa `scripts/xmpp_probe.py` para ver las tramas reales
de tu OZMO 930 y abre una incidencia si alguna difiere.
