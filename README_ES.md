[English](README.md) · [Español](README_ES.md) · [Technical README](TECHNICAL_README.md) · [Referencia técnica en español](TECHNICAL_README_ES.md) · [Roadmap](ROADMAP.md) · [Hoja de ruta en español](ROADMAP_ES.md)

# CUARTEL

> Registro MCP para la flota de herramientas forenses de Anna — un solo
> registro, renderizado para Claude Code, Codex CLI, y OpenCode.

🚧 **Todavía en desarrollo activo — no es un producto terminado.** El
registro, los renderers y el servidor de autointrospección funcionan y
están verificados contra la flota real (ver [ROADMAP_ES.md](ROADMAP_ES.md)
para lo construido y lo que falta a propósito), pero las interfaces, los
nombres de las tools, y el esquema del registro todavía pueden cambiar.

Anna mantiene una flota de herramientas forenses y de seguridad independientes
— VIGÍA, CRONOS, MNEME, raven-memory, ZAYNOR, VELO, annaconda,
PANCITO-RED-TEAM, SIBERIAN, STIGMERGY, FORGE, CORVUS — cada una en su propio
repositorio, con
sus propios tests, su propio ritmo de releases. Varias ya hablan MCP.
Conectar todas a un runtime de agente (Claude Code hoy; Codex CLI u OpenCode
si alguna vez hace falta un respaldo) significaba editar a mano un formato de
config distinto por cada cliente, cada vez que se agregaba, movía o arreglaba
un servidor.

CUARTEL es el único lugar que sabe cómo arrancar cada uno y en qué formato
espera escucharlo cada runtime.

## Qué no es

CUARTEL **no** es un servidor MCP, y no agrega las tools de nadie en un único
catálogo combinado. Cada proyecto de la flota sigue corriendo su propio
servidor MCP, bajo su propia frontera de autoridad. Mezclar un bridge de
evidencia de solo lectura, uno de mutación de memoria, y uno de acción
ofensiva gateada en un único proceso colapsaría justo las distinciones que
hacen que cada uno sea seguro de exponer. Es la misma decisión que el propio
[ADR-0001](https://github.com/annatchijova/zaynor/blob/main/docs/adr/0001-separate-mcp-capability-planes.md)
de ZAYNOR ya tomó a menor escala.

## Qué es

Un registro de metadata (`registry.yaml`) más un renderer (`render.py`) que
lo traduce al `.mcp.json` de Claude Code, al `config.toml` de Codex CLI, y al
`opencode.json` de OpenCode — así que cambiar dónde vive un servidor, o
agregar uno nuevo, es una edición de una línea seguida de un comando, no tres.

```bash
python3 render.py claude --out ~/.claude.json-mcp-snippet
python3 render.py codex
python3 render.py opencode
python3 render.py doctor      # valida que cada comando registrado exista
python3 render.py doctor --deep   # handshake real + drift de tool_count + diagnóstico (ROADMAP_ES.md N1)
python3 render.py digest          # chequeo profundo, pero solo reporta lo que cambió desde la última corrida (ROADMAP_ES.md N4)
```

CUARTEL también se expone a sí mismo como servidor MCP (`mcp_server.py`)
para que cualquier sesión de agente le pregunte directo en vez de leer
archivos — `cuartel_list_servers`, `cuartel_describe_server`,
`cuartel_run_doctor`, `cuartel_find_capability` (ROADMAP_ES.md Nivel 2).

## Flota actual

| Servidor | Estado |
|---|---|
| CUARTEL mismo, VIGÍA, CRONOS, MNEME, raven-memory, ZAYNOR, VELO, annaconda, PANCITO-RED-TEAM, FORGE, CORVUS | ready |
| SIBERIAN | construido, deshabilitado a propósito — su propio README dice que no está listo para uso operacional |
| mneme_memory_mcp | superado por MNEME, no registrado |
| STIGMERGY | no construido — ver [Technical README](TECHNICAL_README.md) para la razón |

El detalle completo, la decisión de arquitectura detrás, y el esquema del
registro están en la [referencia técnica](TECHNICAL_README_ES.md).

## Requisitos

`pip install pyyaml` (o el paquete de tu sistema) — stdlib para el resto.
