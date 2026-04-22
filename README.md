# MVP — Generador de Tests con IA

Stack simplificado: Django + SQLite + ChromaDB + LangChain + Ollama (Mistral) + Next.js

## Requisitos previos
- Python 3.11+
- Node.js 18+
- [Ollama](https://ollama.com) instalado y corriendo

## 1 — Levantar Ollama con Deepseek-coder:6.7b

```bash
ollama run deepseek-coder:6.7b
```

## 2 — Backend

```bash
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt

python manage.py migrate
python manage.py runserver
```

Backend disponible en `http://localhost:8000`

## 3 — Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend disponible en `http://localhost:3000`

## 4 — Proyecto de Prueba (test_project)

Contiene una app web estática simple para probar la generación de tests.

```bash
cd test_project
# Levantar la aplicación localmente en http://localhost:8081
python -m http.server 8081
```

Para probar los scripts generados con Cypress (en otra terminal):
```bash
cd test_project
npm install
npx cypress open
```

## Endpoints de la API

| Método | URL | Descripción |
|--------|-----|-------------|
| GET | `/api/projects/` | Listar proyectos |
| POST | `/api/projects/create/` | Crear proyecto (`name`, `directory_path`) |
| POST | `/api/projects/:id/sync/` | Indexar directorio en ChromaDB |
| POST | `/api/projects/:id/generate/` | Generar test (`instruction`) |
| GET | `/api/projects/:id/tests/` | Historial de tests generados |

## Flujo de uso

1. Agregar un proyecto apuntando a un directorio local.
2. Sincronizar el proyecto (indexa el código fuente en ChromaDB).
3. Escribir una instrucción en lenguaje natural y generar el test Cypress.
4. Copiar el script generado al repositorio del proyecto.
