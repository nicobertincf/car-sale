# Proyecto Multiagentes (Base de desarrollo)

Estructura minima para iniciar un proyecto multiagente con LangGraph.

## Incluye
- Grafo base con 4 nodos: `router`, `researcher`, `builder`, `supervisor`.
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
pytest -q
langgraph dev
```

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

### 4) Cargar variables (mismo patron del module-0)

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

Flujo:
`START -> router -> (researcher | builder | supervisor)`
`researcher -> builder -> supervisor -> END`
`supervisor -> END`
