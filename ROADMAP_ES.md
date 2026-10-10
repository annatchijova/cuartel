[English](README.md) · [Español](README_ES.md) · [Technical README](TECHNICAL_README.md) · [Referencia técnica en español](TECHNICAL_README_ES.md) · [Roadmap](ROADMAP.md) · [Hoja de ruta en español](ROADMAP_ES.md)

# CUARTEL — hoja de ruta hacia una flota autoconsciente

## Destino

Hoy CUARTEL es un registro estático: un humano (o un agente en su nombre)
edita `registry.yaml` y corre `render.py`. El destino es un plano de
control que **conoce su propio estado, se explica a cualquier agente que
le pregunte, nota cuando algo se desvía, y cierra el loop entre "algo
cambió" y "el registro lo dice"** — sin convertirse nunca en una segunda
autoridad de decisión sobre los veredictos propios de ningún proyecto de
la flota.

Sin calendario puesto a propósito. Cada nivel de abajo es completo y útil
por sí mismo; el siguiente se construye sobre el anterior cuando haya
lugar — una tarde libre, una semana, o de acá a seis meses. Parar después
del Nivel 2 deja algo genuinamente terminado, no una promesa a medio
construir.

## Invariantes que hereda cada nivel (no se agregan después)

Esto es cierto desde el Nivel 1, igual que ya era cierto desde la primera
versión de `registry.yaml`:

1. **CUARTEL nunca se convierte en autoridad de decisión.** Puede
   detectar, loguear, sugerir y redactar borradores — nunca reescribe en
   silencio el código de un proyecto de la flota, nunca expone por su
   cuenta una tool que no verificó que sea de solo lectura, y nunca aplica
   un cambio de registro a una config de cliente en vivo sin mostrarlo
   primero.
2. **"Automatizado" nunca significa "sin verificar".** Cada capacidad
   nueva mantiene la misma disciplina ya establecida: un handshake stdio
   real, una llamada real a una tool, antes de confiar en algo — sea que
   ese chequeo lo corra un humano o un cron.
3. **La autoridad de curación sigue en cada proyecto.** CUARTEL puede
   notar que un proyecto de la flota le creció una tool nueva; no puede
   decidir por su cuenta que esa tool es segura de exponer. Esa decisión
   siempre se muestra para que un humano (o un agente actuando
   explícitamente en su nombre) la tome.

## Nivel 1 — El doctor diagnostica de verdad, no solo pinguea — CONSTRUIDO 2026-10-09

Hoy, `render.py doctor` solo chequea que el archivo de un comando exista.
Se perdió por completo el modo de falla real: 5 de 6 entradas nuevas
fallaron con `CONNECTION_CLOSED` en la primera reconexión real, por una
razón que `doctor` nunca chequeó (la rareza de `cwd` en el scope global).

**Qué construye este nivel:** `doctor --deep` hace un handshake stdio
real contra cada entrada `status: ready` — `initialize()` +
`list_tools()` — y compara el conteo de tools devuelto contra el
`tool_count` del registro. Tres resultados por entrada: `OK` (el
handshake funcionó, el conteo coincide), `DRIFT` (el handshake funcionó,
pero el conteo cambió — exactamente lo que pasó con VELO pasando de 13 a
19 tools sin que nadie lo notara), o `FAIL` (el handshake falló — y acá
la herramienta carga una pequeña biblioteca de firmas de falla
*conocidas* de la propia historia de este proyecto: "no module named
trio" → falta el venv; "No such file or directory" en un arg relativo →
el patrón de cwd-no-respetado; `ModuleNotFoundError` en una invocación
`-m` → falta `PYTHONPATH`. Cada coincidencia imprime el diagnóstico Y el
fix que funcionó la última vez, no solo el error crudo).

Útil por sí solo: esto solo ya habría agarrado el incidente de hoy antes
de que Anna lo notara, con la causa raíz real ya puesta en nombre, el
mismo día que pasó.

**Construido como `render.py doctor --deep`.** La primera corrida real
contra toda la flota encontró una desviación genuina de inmediato: el
registro decía que VIGÍA tenía 33 tools, el handshake en vivo dijo 32 —
corregido en el momento, que es exactamente el loop que este nivel existe
para cerrar. La propia biblioteca de diagnóstico necesitó un fix real
antes de funcionar: la primera regex para la firma de cwd-no-respetado no
coincidía con la redacción real del error de Python (`can't open file
'...'` viene antes de "No such file or directory", no después) —
encontrado disparando deliberadamente el camino de falla con una entrada
falsa rota y leyendo la salida real, no asumido al escribir la regex.

## Nivel 2 — CUARTEL puede explicarse a quien le pregunte — CONSTRUIDO 2026-10-09

Hoy, "saber usar CUARTEL" significa leer `registry.yaml` y dos archivos
Markdown. Una sesión nueva de Claude Code sin memoria de esta
conversación — o la propia Anna en seis meses — tiene que redescubrir
toda la flota leyendo archivos.

**Qué construye este nivel:** `cuartel/mcp_server.py` — CUARTEL consigue
su propio servidor MCP (se suma a la flota que administra), exponiendo
introspección de solo lectura:

- `cuartel_list_servers()` — la flota, con estado y propósito en una línea.
- `cuartel_describe_server(name)` — plano, nota de autoridad, lista de
  tools, y la verificación exacta que se hizo, directo del registro.
- `cuartel_find_capability(query)` — "¿qué servidor puede leer un caso
  sellado?" → una lista ordenada de tools de toda la flota, leída de los
  docstrings propios de cada tool, no una segunda copia que se desactualiza.
- `cuartel_run_doctor()` — dispara el chequeo profundo del Nivel 1 y
  devuelve el reporte como dato estructurado sobre el que un agente puede
  actuar, no solo texto que lee un humano.

Útil por sí solo: cualquier sesión de agente, incluso una que nunca vio
esta conversación, ahora puede preguntar "qué tengo para X" y recibir una
respuesta correcta en vez de adivinar o re-derivarla de cero.

**Construido como `mcp_server.py`, registrado en la flota que
administra.** Se encontraron dos bugs reales solo al llamar las dos tools
de handshake en vivo de punta a punta, no leyendo el código: tanto
`cuartel_run_doctor(deep=True)` como `cuartel_find_capability` llamaban
originalmente a `asyncio.run()` desde adentro del loop de eventos ya
corriendo de FastMCP, y crasheaban en la primera llamada real con
"asyncio.run() cannot be called from a running event loop" — arreglado
convirtiéndolas en tools `async def` que hacen `await` directo.
Reverificado después con las mismas dos llamadas: una corrida completa de
doctor profundo contra las 11 entradas `ready` en ~5 segundos, y
`find_capability("custody chain")` encontrando correctamente tools
relevantes en 8 servidores distintos a partir de sus descripciones en
vivo.

## Nivel 3 — El uso se convierte en señal, no solo en evento — CONSTRUIDO 2026-10-09

Hoy, una llamada a una tool en cualquier parte de la flota no deja
rastro en ningún lado que CUARTEL pueda ver. No hay forma de saber qué
tools se usan realmente, cuáles fallan siempre en silencio, o qué bridge
de qué proyecto quedó obsoleto porque nadie lo llamó en meses.

**Qué construye este nivel:** el propio servidor MCP de CUARTEL (del
Nivel 2) loguea cada llamada que media — qué tool, qué servidor, éxito o
falla, timestamp — en un almacén local de solo-agregar. CRONOS ya existe
exactamente para esto (trazas de razonamiento y auditoría, selladas con
cadena de hashes) — lo natural es una traza de CRONOS dedicada en vez de
un formato de log nuevo hecho a medida, así esto reusa la flota en vez de
hacerla crecer.

Este es el loop de retroalimentación real: el `doctor --deep` del Nivel 1
ahora también puede preguntar "¿qué entradas `ready` tienen cero llamadas
reales en N meses?" — haciendo visible el peso muerto en vez de
invisible. Una tool que siempre falla al llamarla aparece como un patrón,
no como frustración dispersa y puntual.

Útil por sí solo: incluso antes de que algo "actúe" sobre este dato,
tenerlo registrado ya es estrictamente mejor que no tenerlo — el mismo
principio detrás de cada cadena de auditoría de esta flota (VIGÍA, MNEME,
CRONOS, raven-memory ya creen todos esto).

**Construido — con una corrección de alcance que vale la pena decir con
honestidad.** CUARTEL no media *invocaciones* reales a tools de la flota
(nunca llama a una tool de la flota, solo hace `list_tools()` sobre ella
— esa frontera es a propósito, ver los invariantes al principio de este
documento). Así que lo que se loguea es que se llamaron las cuatro tools
propias de CUARTEL, cada una como una traza de CRONOS bajo
`agent_id="cuartel"` (`cronos_open_trace` → `cronos_record_tool_call` →
`cronos_close_trace`, `post_to_slack=False`). Es más angosto que "cada
llamada en toda la flota", pero es la versión honesta: las llamadas a
`cuartel_run_doctor` y `cuartel_find_capability` ahora son un historial
consultable (`cronos_list_traces(agent_id="cuartel")`), incluyendo qué
servidores de la flota tocó cada una y qué encontró. Verificado: corrí
las cuatro tools una vez cada una, confirmé las 4 trazas en CRONOS con
`chain_ok: 1`. También verifiqué el camino de degradación directamente —
apunté el comando de cronos a un path que no existe y confirmé que la
llamada real a la tool igual funcionó con datos correctos; una falla de
telemetría nunca aparece como una falla de la tool.

## Nivel 4 — Los chequeos se corren solos, en un ritmo que tenga sentido

Hoy, `doctor` solo corre cuando alguien se acuerda de correrlo — así fue
como VELO le creció 6 tools en silencio y 5 entradas se rompieron en
silencio sin que nadie lo notara hasta que una sesión real las encontró.

**Qué construye este nivel:** una corrida programada de `doctor --deep`
(diaria es un default razonable, pero el ritmo real es decisión de Anna,
no un plazo que alguien más le pone) que compara contra el último estado
sano conocido y produce un resumen corto — no ruido: "las N servidores
siguen coincidiendo", o "VELO: 19 → 22 tools, DRIFT" — escrito a un
archivo o mostrado la próxima vez que arranca una sesión, nunca una
interrupción por el solo hecho de interrumpir.

Útil por sí solo: esta es la diferencia entre enterarse de la desviación
cuando muerde, versus enterarse en un ritmo que Anna controla.

## Nivel 5 — La desviación se vuelve un borrador, no una sorpresa

Hoy, cuando algo en la flota cambia — aparece un servidor MCP nuevo en un
proyecto, el conteo de tools se mueve, el estado de madurez de un
proyecto cambia (que a SIBERIAN le sacarían el cartel de "NOT READY",
por ejemplo) — nada lo nota hasta que un humano mira por casualidad.

**Qué construye este nivel:** cuando el chequeo programado del Nivel 4
encuentra algo nuevo (un `mcp_server*.py` que aparece en un repo conocido
de la flota y no está en `registry.yaml` todavía; un cambio digno de
estado en el propio README de un proyecto), redacta la edición de
`registry.yaml` que *haría* — como un diff, nunca un cambio aplicado —
más los pasos de verificación que el Nivel 1 ya sabe correr antes de que
pueda volverse `ready`. Anna (o un agente actuando por instrucción
explícita suya) revisa y decide; CUARTEL nunca promueve su propio
borrador a `ready` con su propia autoridad.

Útil por sí solo: la brecha entre "esta flota creció" y "el registro sabe
que creció" se achica de lo que tarde alguien en notarlo, a lo que tarde
revisar un borrador.

## Cómo se ve "terminado" si el tiempo se acaba en cualquier nivel

Cada nivel de arriba se sostiene solo si no se construye nada más. El
Nivel 1 solo ya es una mejora real sobre hoy. Nivel 1 + 2 es una flota que
se explica a sí misma. Agregar el 3 la vuelve responsable ante su propia
historia. Agregar el 4 y el 5 la vuelve proactiva. No hay ningún nivel
acá que sea andamiaje para uno posterior — cada uno es algo en lo que
Anna podría parar y haber ganado algo real, de la misma forma que el
propio CUARTEL no esperó a que las seis herramientas de la flota
estuvieran listas para ser útil con solo dos.
