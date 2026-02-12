# Proyecto Multiagentes (Base de desarrollo)

Estructura minima para iniciar un proyecto multiagente con LangGraph.

## Incluye
- Grafo base con 4 nodos: `router`, `researcher`, `builder`, `supervisor`.
- Sistema de cotizacion persistente para autos usados con agentes de:
  - cotizacion de inventario (`quote_agent`)
  - solicitud de llamada (`contact_agent`)
- Herramientas (`tools`) para consultar inventario y crear solicitudes de llamada.
- Prompts versionados para router/cotizacion/contacto.
- Dependencias separadas en runtime/dev.
- Prueba smoke con `pytest`.
- Configuracion para `langgraph dev`.

## Arranque rapido

```bash
cd pruebas/proyecto_multiagentes
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python3 scripts/init_sqlite_db.py
pytest -q
langgraph dev
```

## SQLite inventory

Se agrego una base SQLite para una automotora de usados con:
- tablas de referencia (`countries`, `body_types`, `fuel_types`, `transmission_types`, `drivetrains`),
- tabla `vehicles` (inventario de autos con foreign keys a catálogos),
- tabla `contact_requests` (solicitudes de contacto por vehiculo).

### Esquema

Archivo SQL:
`app/db/schema.sql`

Campos principales de `vehicles`:
- `country_id` (FK a `countries`)
- `year`
- `mileage_km`
- `make`
- `model`
- `color`
- `description`
- `body_type_id` (FK a `body_types`)
- `transmission_type_id` (FK a `transmission_types`)
- `fuel_type_id` (FK a `fuel_types`)
- `drivetrain_id` (FK a `drivetrains`)
- `number_of_doors`

Campos de `contact_requests`:
- `customer_name`
- `phone_number`
- `preferred_call_time`
- `vehicle_id` (FK a `vehicles.id`)

### Inicializar DB + seed (60 autos distintos)

```bash
cd pruebas/proyecto_multiagentes
python3 scripts/init_sqlite_db.py
```

DB generada por defecto:
`data/dealership.db`

Opcional (path o cantidad personalizada, minimo 50):

```bash
python3 scripts/init_sqlite_db.py --db-path data/mi_inventario.db --seed-count 75
```

### Migrar DB existente (esquema antiguo -> normalizado)

Si ya tenías `dealership.db` del esquema viejo:

```bash
python3 scripts/migrate_inventory_db.py --db-path data/dealership.db
```

El script crea backup automático:
`data/dealership.db.bak-pre-migration`

Nota:
- Los tools del asistente ahora validan el esquema al primer uso.
- Si detectan esquema legacy, migran automáticamente antes de consultar inventario.
- Si quieres limpiar una DB local y dejar solo el esquema actual (sin tablas legacy), re-inicializa:
```bash
python3 scripts/init_sqlite_db.py --db-path data/dealership.db
```

## Sistema de cotizacion persistente

Nuevo grafo en:
`app/car_sales_graph.py`

Capacidades:
- Conversacion persistente por `thread_id` (mensajes + estado de filtros/contacto).
- Cotizacion por preferencias del usuario.
- La IA construye consultas usando solo parámetros permitidos a través de `tools`.
- SQL final siempre parametrizado y seguro (sin SQL raw del usuario).
- Registro de solicitud de llamada en `contact_requests`.
- Solicitud de llamada idempotente (si llega el mismo payload, reutiliza el `request_id` existente).
- Flujo Tool-Calling con `ToolNode` (estilo módulos del curso).
- Guardrails de ejecución: trimming de contexto, timeout de modelo y límite de iteraciones de tool-calling.
- Nodo final de supervisión de respuesta al cliente:
  - reescribe la salida para tono conversacional en párrafos,
  - elimina exposición de IDs internos (`ID`, `request_id`, `vehicle_id`, etc.),
  - evita formato tipo lista numerada/viñetas o bloques tipo payload.
- Estado conversacional persistente con `MessagesState` + reducers:
  - `conversation_language`
  - `active_search_filters`
  - `last_vehicle_candidates`
  - `known_contact_profile`
  - `search_history` / `contact_history`
  - `state_logs`
  Esto evita perder datos relevantes cuando el contexto al LLM se recorta con `trim_messages`.
  El idioma se infiere por LLM y se guarda en `conversation_language` para mantener consistencia de respuesta por hilo.

### Parametros soportados para cotizar

- `country_id`
- `body_type_id`
- `transmission_type_id`
- `fuel_type_id`
- `drivetrain_id`
- `year_min`, `year_max`
- `mileage_km_min`, `mileage_km_max`
- `make`, `model`, `color`
- `number_of_doors`
- `price_usd_min`, `price_usd_max`
- `limit`

### Prompts y tools

Prompts:
- `app/prompts/car_sales_prompts.py`

Tools:
- `app/tools/car_sales_tools.py`
  - Flujo cotización: `list_available_vehicle_filters`, `search_used_vehicles`
  - Flujo contacto: `get_vehicle_details`, `create_executive_call_request`

Nota:
- `list_available_vehicle_filters` consulta catálogos reales en DB y entrega `id + name`.
- El flujo de cotización es: consultar catálogo, elegir IDs, luego ejecutar `search_used_vehicles` con esos IDs.

### Ejecutar chat persistente

```bash
cd pruebas/proyecto_multiagentes
python3 scripts/run_car_sales_chat.py --thread-id demo-autos
```

Si vuelves a ejecutar con el mismo `thread-id`, la conversacion continua.

Base de persistencia de conversaciones:
`data/conversations.db`

Variables opcionales:
- `DEALERSHIP_DB_PATH` (default `data/dealership.db`)
- `SHOW_SQL_DEBUG=true` para mostrar SQL generado por la IA en cada respuesta
- `MAX_CONTEXT_MESSAGES` (default `18`) para ventana deslizante de mensajes enviados al modelo
- `MAX_AGENT_TOOL_ITERATIONS` (default `8`) para cortar loops de tools
- `MAX_QUOTE_ITERATIONS_PER_TURN` (default `3`) para evitar búsquedas especulativas en cadena en un mismo turno
- `MAX_CONTACT_ITERATIONS_PER_TURN` (default `3`) para evitar loops en captura/confirmación de contacto
- `CONTACT_DEDUP_WINDOW_MINUTES` (default `0`) ventana para deduplicar solicitudes idénticas de contacto (mismo vehículo + nombre + teléfono + horario). Si `0`, no deduplica.
- `DEFAULT_CONVERSATION_LANGUAGE` fallback solo si no hay inferencia disponible (default `es`)
- `FINAL_SUPERVISOR_USE_LLM` (default `true`): si `true`, aplica supervisión final con LLM para limpiar formato y lenguaje customer-facing; si `false`, deja el borrador del agente.
- `OPENAI_TIMEOUT_SECONDS` (default `45`) timeout por llamada al modelo

### Ejemplo de flujo

1. \"Busco un SUV Toyota 2020 o más nuevo, menos de 80.000 km y hasta 26.000 USD\"
2. El asistente devuelve opciones con `ID` de vehículo.
3. \"Quiero que me llame un ejecutivo por el ID 12. Me llamo Ana, +541112345678, mañana 10:00\"
4. Se inserta la fila en `contact_requests` y devuelve confirmación.

### Probar en LangSmith Studio (chat habilitado)

1. Ejecuta:
```bash
cd pruebas/proyecto_multiagentes
langgraph dev
```
2. En Studio, selecciona el grafo `car_sales_assistant`.
3. Crea/usa un `thread` para mantener conversación.
4. Envía mensajes en el panel de chat.

Si no ves chat habilitado:
- verifica que elegiste `car_sales_assistant` (no `multiagente`),
- verifica `OPENAI_API_KEY` en `.env`,
- reinicia `langgraph dev` después de cambios.
- si quedan asistentes viejos en Studio, borra estado local y reinicia: `rm -rf .langgraph_api && langgraph dev`
- si aparece error `module 'langchain' has no attribute 'llm_cache'`, activa el virtualenv del proyecto y reinstala dependencias:
```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
```
- para observabilidad de tools, revisa logs estructurados con `tool_name`, `args`, `duration_ms`, `status` y `artifacts`.

## API keys

Variables recomendadas:
- `OPENAI_API_KEY` para modelos de chat.
- `TAVILY_API_KEY` para busqueda web.
- `LANGSMITH_API_KEY` para tracing y Studio.
- `LANGSMITH_TRACING_V2="true"` para habilitar trazas.
- `LANGSMITH_PROJECT` para nombrar el proyecto de observabilidad.
- `LANGSMITH_ENDPOINT` solo si usas instancia EU.

### 1) OPENAI_API_KEY

1. Crea una cuenta en OpenAI (si aun no tienes).
2. Entra al panel de API keys: `https://platform.openai.com/api-keys`
3. Crea una nueva key y copiala.
4. Pegala en tu `.env`:

```bash
OPENAI_API_KEY="tu_key_aqui"
```

### 2) TAVILY_API_KEY

1. Registra una cuenta en Tavily: `https://tavily.com/`
2. Desde tu dashboard, genera/copiala API key.
3. Pegala en tu `.env`:

```bash
TAVILY_API_KEY="tu_key_aqui"
```

### 3) LANGSMITH_API_KEY

1. Crea cuenta en LangSmith.
2. Sigue la guia oficial para crear API key:
   `https://docs.langchain.com/langsmith/create-account-api-key#create-an-account-and-api-key`
3. Genera/copiala la key desde tu cuenta.
4. Agrega estas variables en `.env`:

```bash
LANGSMITH_API_KEY="tu_key_aqui"
LANGSMITH_TRACING_V2="true"
LANGSMITH_PROJECT="proyecto-multiagentes"
```

Si tu cuenta esta en region EU, agrega tambien:

```bash
LANGSMITH_ENDPOINT="https://eu.api.smith.langchain.com"
```

### 4) Cargar variables

El notebook usa un helper para pedir la variable si no existe:

```python
import os, getpass

def _set_env(var: str):
    if not os.environ.get(var):
        os.environ[var] = getpass.getpass(f"{var}: ")

_set_env("OPENAI_API_KEY")
_set_env("TAVILY_API_KEY")
_set_env("LANGSMITH_API_KEY")
```

En este proyecto, para desarrollo local, puedes cargar desde `.env` con:

```bash
source .venv/bin/activate
set -a
source .env
set +a
```

### 5) Verificacion rapida

```bash
python3 - <<'PY'
import os
for var in (
    "OPENAI_API_KEY",
    "TAVILY_API_KEY",
    "LANGSMITH_API_KEY",
    "LANGSMITH_TRACING_V2",
    "LANGSMITH_PROJECT",
):
    print(var, "OK" if os.getenv(var) else "MISSING")
PY
```

## Grafo actual

Grafo base (`app/graph.py`):
`START -> router -> (researcher | builder | supervisor)`
`researcher -> builder -> supervisor -> END`
`supervisor -> END`

Grafo de ventas (`app/car_sales_graph.py`):
`START -> router -> (quote_agent | contact_agent) -> END`
