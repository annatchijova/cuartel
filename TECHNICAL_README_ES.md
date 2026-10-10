[English overview](README.md) · [Resumen en español](README_ES.md) · [Technical README](TECHNICAL_README.md) · [Referencia técnica en español](TECHNICAL_README_ES.md) · [Roadmap](ROADMAP.md) · [Hoja de ruta en español](ROADMAP_ES.md)

# CUARTEL — referencia técnica

Este documento es la superficie de auditoría y extensión de CUARTEL: el
esquema que lee, qué emite cada renderer, y el razonamiento detrás de cada
estado en la tabla de la flota. El [README](README_ES.md) es la presentación;
esto es lo que se lee antes de tocar `registry.yaml`.

## Decisión de arquitectura

CUARTEL es un **registro**, no un servidor. `registry.yaml` es metadata pura
— sin lógica forense, sin autoridad de decisión — que describe cómo arrancar
el servidor MCP propio e independiente de cada proyecto, y bajo qué plano de
capacidad y frontera de autoridad opera ese servidor. `render.py` es un
templater tonto sobre esa metadata.

Cada entrada es un plano de capacidad MCP separado. Las entradas nunca se
fusionan en un único servidor combinado. El propio
[`docs/adr/0001-separate-mcp-capability-planes.md`](https://github.com/annatchijova/zaynor/blob/main/docs/adr/0001-separate-mcp-capability-planes.md)
de ZAYNOR rechazó fusionar VIGÍA + CRONOS + MNEME en un único servidor,
porque eso colapsa niveles de confianza distintos — el acceso de solo lectura
a evidencia no es lo mismo que la memoria de un caso, y ninguno de los dos es
lo mismo que una acción ofensiva gateada. CUARTEL generaliza esa misma
decisión a toda la flota en vez de re-decidirla por proyecto.

Si algún día un runtime objetivo no puede cargar más de un servidor MCP, el
fallback documentado es un multiplexor tipado que preserva estas mismas
fronteras de plano de capacidad — no un proxy plano. Ese multiplexor no
existe todavía, y nada acá implica que haya que construirlo.

### Invariantes, desde la primera entrada

1. El registro es solo metadata — ningún renderer ejecuta lógica forense ni
   toma una decisión sobre la salida de ningún proyecto.
2. Cada entrada declara explícitamente su plano de capacidad y su nota de
   autoridad — nunca se infiere del comando solo.
3. Nunca se aplana todo en un único servidor combinado (ver arriba).
4. Un proyecto bloqueado o no-listo se registra como tal — nunca se cablea
   en silencio solo porque su servidor existe y funciona.

## Esquema de `registry.yaml`

```yaml
servers:
  <nombre>:
    display_name: string
    repo: path absoluto al proyecto
    command: path absoluto al ejecutable, o null si status != ready
    args: lista de argumentos de CLI
    cwd: directorio de trabajo donde arrancar
    env: {ENV_VAR: valor}             # solo lo que esta entrada necesita fijar
    plane: etiqueta corta de plano de capacidad (ej. read-only-evidence-and-analysis)
    authority: >-
      una o dos frases sobre qué puede y qué no puede decidir este servidor
    status: ready | blocked | planned
    tool_count: entero, de un handshake real, nunca adivinado
    notes: >-
      qué se verificó, cuándo, cómo, y cualquier salvedad que valga saber
      antes de confiar en esta entrada
```

`status: ready` es el único estado que un renderer emite alguna vez en una
config de runtime. `blocked` (existe, tiene un problema conocido abierto) y
`planned` (no existe todavía, o existe pero deliberadamente no está
habilitado) aparecen en la salida de `doctor`, así que el hueco queda
visible en vez de silencioso.

## Renderers

`render.py <target>` lee el registro y emite exactamente uno de estos:

| Target | Formato | Forma |
|---|---|---|
| `claude` | `.mcp.json` de Claude Code | `{"mcpServers": {nombre: {command, args, env?, cwd?}}}` |
| `codex` | `config.toml` de Codex CLI | bloques `[mcp_servers.<nombre>]` con `command`, `args`, `cwd`, `env.*`, `enabled` |
| `opencode` | `opencode.json` de OpenCode | `{"mcp": {nombre: {type: "local", command: [...], environment?, enabled}}}` |
| `doctor` | — | una línea por entrada: `OK`/`MISSING` para `ready`, o el estado + los primeros 100 caracteres de `notes` para el resto |
| `doctor --deep` | — | un handshake stdio real por entrada `ready` (deliberadamente sin `cwd`, igual que el comportamiento real del scope global): `OK` (el conteo coincide), `DRIFT` (el handshake funcionó, pero el conteo de tools cambió respecto al registro), o `FAIL` con un diagnóstico de una pequeña biblioteca de firmas de falla ya vividas por este proyecto, cuando alguna coincide (ROADMAP_ES.md Nivel 1) |
| `digest` | — | el mismo chequeo profundo, comparado contra `.doctor_state.json` (en `.gitignore`) de la última corrida — imprime solo las transiciones (fallo nuevo, fallo resuelto, cambio de tool_count) o "sin cambios", la forma que debería tener una corrida programada (ROADMAP_ES.md Nivel 4; el ritmo en sí no lo decide este repo) |
| `scan` | — | redacta cambios de `registry.yaml` para la desviación que encuentra — un archivo de servidor MCP nuevo en un repo conocido al que ninguna entrada apunta, o el README de SIBERIAN perdiendo su banner "NOT READY" — y los imprime para revisión. Nunca escribe `registry.yaml` (ROADMAP_ES.md Nivel 5) |

Los tres formatos se confirmaron contra la documentación propia y actual de
cada herramienta al momento de construir esto (octubre 2026), no se
asumieron de memoria. `--out <path>` escribe a un archivo en vez de stdout.

## Metodología de verificación usada en cada entrada `ready`

Todo servidor de este registro llegó a `status: ready` de la misma manera,
sin importar quién lo construyó o cuándo:

1. Un handshake MCP stdio real (`ClientSession.initialize()` +
   `list_tools()`) contra el comando de arranque real — nunca asumido
   leyendo el código fuente del servidor.
2. Al menos una llamada real a una tool, con input real o realista, chequeada
   contra los fixtures de test del propio proyecto (cuando existen) o un
   equivalente armado a mano, inspeccionando la respuesta por corrección —
   no solo "no crasheó".
3. Un chequeo deliberado del camino de error: un argumento inválido o una
   dependencia inalcanzable debería degradar a un error estructurado, no a
   un stack trace llegando al cliente MCP.

`tool_count` en el registro es siempre el número que `list_tools()`
devolvió realmente durante ese handshake.

## La flota, en detalle

### CUARTEL mismo — ready
`mcp_server.py`, 4 tools: `cuartel_list_servers`, `cuartel_describe_server`
(ambas rápidas, solo leen registry.yaml), `cuartel_run_doctor` (shallow o
`deep=True`, reusando el propio `doctor_deep_data()` de `render.py` — una
sola implementación, no dos que puedan desviarse entre sí),
`cuartel_find_capability` (un handshake real en paralelo a cada servidor
`ready`, buscando en los nombres/descripciones de tools en vivo — nunca
una segunda copia desactualizada de ellos). ROADMAP_ES.md Nivel 2. Dos
bugs reales salieron a la luz solo al llamar las tools profundas de
punta a punta: las dos llamaban originalmente a `asyncio.run()` desde
adentro del loop de eventos ya corriendo de FastMCP y crasheaban en la
primera llamada real; arreglado convirtiéndolas en tools `async def` que
hacen `await` directo. CUARTEL se registra a sí mismo acá a propósito —
la flota que administra se incluye a sí misma.

Las 4 tools también loguean su propia llamada como una traza de CRONOS
(ROADMAP_ES.md Nivel 3: `agent_id="cuartel"`, `post_to_slack=False`) —
best-effort, nunca bloqueando el resultado real por eso. CUARTEL no media
*invocaciones* a tools de la flota (solo `list_tools()`), así que lo que
se loguea es el uso propio de CUARTEL, no el de toda la flota —
`cronos_list_traces(agent_id="cuartel")` es el historial consultable de
llamadas de CUARTEL. Verificado: las 4 tools llamadas una vez cada una,
confirmadas en CRONOS con `chain_ok: 1`; la degradación se verificó
directamente apuntando el comando de CRONOS a un path que no existe y
confirmando que el resultado real de la tool no se vio afectado.

### VIGÍA — ready
`vigia/vigia_sift_bridge.py`, FastMCP, 33 tools, solo stdio por construcción
(`_verify_transport_security()` aborta duro ante cualquier otro transporte).
Se arranca vía `launch_vigia_mcp.sh`, que ya exporta cada variable de entorno
que este servidor necesita — CUARTEL no las redeclara, para evitar una
segunda fuente de verdad sobre el confinamiento de los directorios de
evidencia/trabajo.

### CRONOS — ready (arregló una falla real)
`mcp_server.py`, 10 tools. La conexión MCP de CRONOS de esta misma sesión
había fallado de verdad (`CONNECTION_CLOSED`) antes de que este registro
existiera. Causa raíz, encontrada reproduciéndola directamente en vez de
adivinar: el servidor fuerza el backend `trio` de anyio
(`anyio.run(mcp.run_stdio_async, backend="trio")`), y `trio` — declarado en
`pyproject.toml` — nunca se instaló para el `python3` desnudo al que
apuntaba la config vieja. No existía ningún venv, y `pip install --user`
está bloqueado acá por PEP 668. Se arregló creando `cronos/.venv` y
corriendo `pip install -e .` ahí, y reapuntando tanto este registro como la
propia entrada `mcpServers.cronos` de `~/.claude.json` a `.venv/bin/python3`.

### MNEME — ready (curado)
El propio `mcp_server.py` de MNEME expone 26 tools, la mayoría mutantes
(guardar, suceder, otorgar, cuarentena, propagar taint...). Ese servidor
completo es correcto para un agente que usa MNEME como su capa de memoria;
es incorrecto para un registro de flota de solo lectura. `mcp_server_readonly.py`
(construido para este registro, viviendo en el propio repo de MNEME) expone
exactamente las tres tools que ZAYNOR ya había vetado y puesto en su
allowlist para este mismo propósito
(`zaynor/docs/adr/0001-separate-mcp-capability-planes.md`): `mneme_info`,
`mneme_verify_bundle`, `mneme_custody_chain`. Las implementaciones son
copiadas textualmente del servidor principal, no reimplementadas. Usa
`mcp.run()` (asyncio por defecto) en vez del backend `trio` forzado del
servidor principal, ya que `trio` no está instalado ahí y ninguna de estas
tres tools lo necesita.

### mneme_memory_mcp — planned (superado)
Un repositorio de GitHub separado (`annatchijova/mneme_memory_mcp`), un
snapshot anterior y más chico del mismo linaje que MNEME — 9 tools contra
las 26 de MNEME, sin los módulos `authority`/`causality`/`claims`/
`counterfactual`. MNEME es un superset funcional. No se construyó ni
registró por separado: sería una segunda fuente de verdad, más vieja, para
lo mismo.

### raven-memory — ready (curado)
El propio `mcp_server.py` de raven-memory expone 12 tools. Cinco son
escrituras obvias (`store`, `reinforce`, `forget`, `create_link`,
`consolidate`). Una sexta, `raven_recall`, parece de solo lectura pero no lo
es: el `recall()` de `memory_engine.py` llama a
`self._db.store_audit(...)` y `self._db.update_activations(...)` en cada
llamada, y — solo con `RAVEN_STYLO_ENFORCE=1` — puede cambiar el estado de
una memoria a `FORGOTTEN`. Ninguna de esas seis está en el bridge curado.
`mcp_server_readonly.py` conserva exactamente: `raven_stats`,
`raven_get_memory`, `raven_audit_trail`, `raven_export_graph`,
`raven_verify_chain`, `raven_info`. Como ninguna de esas seis genera
embeddings de texto, el archivo curado evita construir el proveedor de
embeddings Qwen/sentence-transformers por completo — una dependencia pesada
menos en un bridge que nunca la necesita.

El propio README de MNEME documenta que fusiona la mecánica de campo de
STIGMERGY y de raven-memory, así que hay una superposición conceptual real
entre MNEME y raven-memory. Ambos quedan registrados igual, como dos
sistemas de memoria independientes con sus propios motores y cadenas de
auditoría — no como una vista duplicada del mismo dato.

### ZAYNOR — ready
Console script `zaynor-mcp`, 6 tools: `zaynor_info`,
`zaynor_verify_audit`, `zaynor_verify_memory`, `zaynor_list_memory`,
`zaynor_add_hypothesis`, `zaynor_note_question`. Ninguna crea, modifica o
recalcula `result.json` ni `result.seal.json` (ADR-0001). ZAYNOR es en sí
mismo un cliente MCP de VIGÍA/CRONOS/MNEME — ese cableado es interno a
ZAYNOR y no se duplica acá; CUARTEL solo registra el servidor propio de
ZAYNOR.

### VELO — ready (desbloqueó un hallazgo obsoleto)
`dist/src/mcp/server.js`, 13 tools. Un informe de red-team en español
(`velo/docs/informe-red-team-VELO.md`) había marcado un path-traversal
crítico (F1) en el manejo de `caseId` como sin resolver. Se chequeó contra
el código vivo primero, por disciplina de auditar-antes-de-parchear: el fix
ya estaba ahí — validación por regex en la frontera del esquema
(`server.ts`) más `resolve()`/contención de prefijo en el store
(`store.ts`), ambos comentados "Red team F1" — mergeado en el commit
`ef0caa4` ("Red team round 1"). Ese informe en español es anterior a seis
rondas de red-team posteriores en inglés (`docs/RED_TEAM_ROUND_1..6.md`).
Verificado en vivo corriendo el propio `tests/caseid.test.ts` de VELO — 4/4
en verde, incluyendo "the store refuses to read or write outside its
directory". Los items abiertos que quedan en la ronda 6 (F20-F25) son de
severidad Media/Baja y no tocan el manejo de `caseId`/MCP — fuera de alcance
para este registro.

### annaconda — ready (construido desde cero)
No tenía ninguna superficie MCP antes de que este registro existiera.
`service/mcp_server.py` es un wrapper stdio delgado (solo `urllib` de
stdlib — sin dependencia nueva de runtime salvo `mcp` mismo) sobre un
subconjunto curado y GET-only de las rutas HTTP ya existentes de
`service/app.py`: `health`, `registry`, `catalog`, `hunts`, `list_cases`,
`get_case`, `get_case_stix`, `get_case_cacao`. Excluye por construcción toda
ruta que crea un caso, arranca una investigación en vivo, o empuja a un
sistema externo (`POST /cases`, `/investigate`, `/cases/{id}/investigate`,
`/fleet-investigate`, `/cases/{id}/push-to-secops`, `/injection-demo`,
`/tasks/sweep`). Hace proxy del servicio en vivo de annaconda por HTTP en
vez de reimplementar su lógica, porque el estado en vivo de annaconda
(contadores de sweep, elección de backend Firestore-vs-memoria) vive
genuinamente en ese proceso corriendo — un segundo proceso que importara
`build_case_store()` de forma independiente divergiría en silencio bajo el
fallback a memoria. **Requiere que el servicio de annaconda ya esté
corriendo** (`uvicorn service.app:app --port 8080`).

### PANCITO-RED-TEAM — ready (gateado por construcción)
No tenía ninguna superficie MCP antes de que este registro existiera.
`offensive/mcp_server.py` expone exactamente dos tools:
`pancito_openapi_triage` y `pancito_purple_evaluate`, envolviendo
`offensive.openapi_cli` y `offensive.purple_cli` como subprocesos — las
únicas dos de aproximadamente veinte `offensive.*_cli` que son análisis
pasivo de archivos locales sin acción de red. Cualquier otro CLI
(`bola_cli`, `cors_misconfiguration_cli`, `ssrf_outbound_fetch_cli`, ...)
ejecuta activamente acciones de red reales contra un target loopback
declarado en un manifiesto. Ampliar esta lista de tools requiere un diseño
de autorización/enforcement de loopback revisado por separado a nivel
MCP — no una edición de este archivo. Verificado con una llamada real de
punta a punta contra fixtures armados a mano que coinciden byte a byte con
los valores esperados del propio
`pancito-red-team/tests/test_openapi_cli.py`.

### SIBERIAN — planned a propósito, no por falta de trabajo
`siberian/mcp_server.py` existe y está verificado: 6 subcomandos de solo
lectura (`validate`, `analyze`, `explain`, `seal`, `verify`, `rivals`),
ninguno de los cuales escribe, muta o crea un archivo. Excluye
deliberadamente `import-plaso` y los adaptadores de Nivel 6
(`import-mft`/`prefetch`/`amcache`/`shimcache`/`shellbags`, `batch`) — esos
escriben archivos de salida y/o necesitan extras opcionales no instalados
acá, y la propia tabla de Build Levels de SIBERIAN todavía marca el Nivel 6
como "Partial". Que el servidor funcione no es el gate: el propio README de
SIBERIAN todavía dice "UNDER CONSTRUCTION — NOT READY FOR OPERATIONAL USE".
Pasar esto a `ready` cuando SIBERIAN mismo lo diga, no cuando lo diga su
bridge.

### FORGE — ready (primero consolidó dos directorios divergentes)
`forge/mcp_server.py`, 22 tools. Había dos directorios locales del mismo
proyecto: `/home/labestiadevigia/forge` (remote `forge.git`) y
`/home/labestiadevigia/forge-nuevo` (remote `forge-improved.git`),
divergentes desde el commit `6bee0de`. La creencia de Anna de que
forge-nuevo "tiene más lenguajes" resultó correcta, solo que todavía no
estaba traída localmente: el `origin/main` de `forge-improved.git` tenía
11 commits sin traer que agregaban soporte real para C/C++, Java, C#,
Ruby y PHP vía un PR ya mergeado, encima de 6 commits locales de fixes de
determinismo/honestidad y un exportador SARIF 2.1.0 — nada de lo cual
tiene el directorio `forge` más viejo. `forge` solo recibió 2 commits de
limpieza de docs después del punto de bifurcación.

Consolidación realizada: se mergeó `feat/sarif-output` al `main` de
forge-nuevo (fast-forward), se cherry-pickeó el commit de limpieza de
docs de forge (`3a4f361`) sobre él, se trajo y mergeó el linaje de 11
commits de paquetes de lenguaje del `origin/main` — un conflicto real en
`forge/detector/stack.py` (dos agregados independientes y no superpuestos
a la misma lista de limitaciones, ambos conservados) — y se corrió la
suite completa (482 passed, 5 skipped) antes de empujar. El `main` de
forge-nuevo es ahora el estado canónico verificado. El directorio
`forge` original y su remote `forge.git` **no** se borraron — quedan
como están, pendientes de la decisión de Anna sobre qué hacer con ese
remote y el nombre del directorio local.

Registrado tal cual (las 22 tools), igual que ya estaba configurado en el
propio `~/.claude.json` de Anna antes de que este registro existiera — un
`PYTHONPATH` apuntando a `forge-nuevo` bajo el nombre de servidor
`"forge"`. No se curó de nuevo acá, misma postura que CORVUS abajo.

### CORVUS — ready
`mcp_server.py`, 7 tools: `analyze_message`, `get_user_baseline`,
`get_user_history`, `get_channel_stats`, `verify_audit_chain`,
`export_audit_chain`, `corvus_info`. Seis son de lectura pura;
`analyze_message` tiene `persist=False` por defecto y solo escribe en
memoria/baseline/cadena de auditoría si el llamador pasa explícitamente
`persist=True` — una escritura opt-in, no un efecto secundario escondido
como el `raven_recall` de raven-memory, así que no necesitó el mismo
tratamiento de exclusión. Sin dependencia externa: SQLite local
(`~/.corvus/memory.db`, se crea sola), sin venv necesario. Standalone —
sin conexión funcional con el resto de la flota más allá de un comentario
que menciona haber tomado prestado un patrón de sanitización de inputs de
vigia-repo. Ya estaba configurado en el propio `~/.claude.json` de Anna
antes de que este registro existiera; registrado tal cual, las 7 tools,
por pedido explícito.

### STIGMERGY — no construido
No existe ningún servidor MCP. CockroachDB no es una dependencia secundaria
u opcional acá — es el único canal de coordinación entre agentes y el
almacén principal: una columna `VECTOR` nativa con un `VECTOR INDEX` para
`recall()` (una feature de CockroachDB v25.2+, requerida por el hackathon
para el que se construyó STIGMERGY), un modelo de autoridad atado al propio
`current_user`/RBAC de CockroachDB (`ops/authority.py`), changefeeds que
empujan a Lambda, y lógica de reintento atada al propio `SQLSTATE 40001` de
CockroachDB. No hay ninguna capa de ORM o repositorio en ningún lado del
código — SQL crudo esparcido en doce archivos (`ops/*.py`, `audit/*.py`,
`lambdas/*.py`). Peor aún, específicamente para un bridge de solo lectura:
`recall()` en sí mismo escribe — actualiza metadata de acceso y puede
disparar una transición de estado a `REDISCOVERED` en la misma transacción.
No es una lectura a pesar del nombre.

Desacoplar una vía de solo lectura con esfuerzo moderado no es realista
acá. Si más adelante se quiere una vista de solo lectura, el camino honesto
es un exportador/snapshot periódico (ETL a SQLite o JSON) construido
**afuera** del propio código de STIGMERGY, con un bridge MCP sobre ese
snapshot — no un bridge en vivo contra CockroachDB, y no una edición de
`ops/` o `audit/`.

## Una trampa real: el scope global de Claude Code ignora `cwd`

Encontrado el 2026-10-09 de la peor manera: después de fusionar un render
en el `~/.claude.json` real, 5 de 6 entradas nuevas fallaron con
`CONNECTION_CLOSED` al reconectar. Se reprodujo directamente: el scope
global **"User MCPs"** de Claude Code (el `mcpServers` de nivel superior
en `~/.claude.json`, a diferencia de un `.mcp.json` de proyecto) no
aplica el campo `cwd`. Cualquier entrada cuyo `args` contenga un path
relativo, o cuyo comando necesite el directorio de trabajo en `sys.path`
para una invocación `-m modulo`, falla inmediatamente en ese scope —
aunque la misma entrada idéntica funcione en una config de proyecto.

`cwd` sigue declarado en `registry.yaml` (inofensivo si otro cliente lo
respeta, ej. una config de proyecto de Claude, Codex, u OpenCode), pero
el `command`/`args`/`env` de cada entrada también tiene que ser
autosuficiente sin él:

- Cualquier path de script en `args` tiene que ser absoluto, no relativo.
- Cualquier invocación `-m <paquete>` necesita `PYTHONPATH` fijado en
  `env` hacia la raíz de ese paquete (el mismo patrón que la entrada de
  FORGE ya usaba, por lo cual nunca se vio afectada).

Antes de confiar en una entrada nueva, reproducí las dos direcciones vos
misma, de la misma forma en que se encontró esto: corré el comando
configurado exacto desde un directorio sin relación, sin fijar `cwd`,
confirmá que falla igual que fallaría `CONNECTION_CLOSED`, y después
confirmá que el fix (path absoluto/`PYTHONPATH`) funciona con un
handshake stdio real. No lo infieras leyendo la entrada — el modo de
falla es silencioso hasta que algo realmente intenta conectarse.

## Agregar un servidor

1. El proyecto construye y verifica su **propio** servidor MCP primero — un
   handshake real, una llamada real a una tool, un camino de error
   chequeado. CUARTEL nunca contiene lógica forense o de seguridad propia.
2. Agregar una entrada a `registry.yaml` con `status: ready`, siguiendo el
   esquema de arriba, incluyendo en `notes` la verificación que realmente se
   hizo.
3. Correr `render.py doctor` para confirmar que el comando resuelve, y
   después `render.py <target>` (o `--out` directo al path de config del
   runtime) para que lo tome.

Si el servidor MCP completo de un proyecto mezcla tools de lectura y
escritura, y solo el lado de lectura pertenece a un registro compartido como
este, escribí un archivo curado chico en el propio repositorio de ese
proyecto (ver `mcp_server_readonly.py` de MNEME y raven-memory) en vez de
intentar filtrar tools desde el lado de CUARTEL — la curación pertenece al
proyecto que es dueño de la frontera de autoridad.
