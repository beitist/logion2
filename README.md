# Logion 2

A professional AI-powered Computer-Assisted Translation (CAT) tool built with FastAPI and React. Logion 2 combines Translation Memory, Glossary Management, and RAG-based context retrieval with LLM-powered translation workflows.

## Features

- **Multi-file project management** — DOCX, XLIFF, TMX, RTF, PDF support
- **AI Translation Workflows** — Pre-analysis, batch translation, sequential translation, optimization
- **Translation Memory (TM)** — Automatic TM with semantic search via Voyage AI embeddings
- **Glossary Management** — Manual and AI-extracted glossaries with auto-enforcement
- **RAG Context** — Legal, background, and reference documents enrich translations
- **Track Changes** — DOCX revision tracking preserved through translation
- **Inline Editing** — Tiptap-based rich text editor with XML tag preservation
- **Backup System** — Automatic project backups with configurable intervals

---

## Prerequisites

| Dependency | Version | Notes |
|------------|---------|-------|
| Python | 3.13+ | Backend runtime |
| Node.js | 18+ | Frontend build (22+ recommended) |
| PostgreSQL | 15+ | Primary database |
| pip | latest | Python package manager |

### Installing Prerequisites

**macOS** (using Homebrew):
```bash
brew install python@3.13 node postgresql@15
brew services start postgresql@15
```

**Windows**:
1. **Python**: Download from [python.org](https://www.python.org/downloads/). During installation, check "Add Python to PATH".
2. **Node.js**: Download LTS from [nodejs.org](https://nodejs.org/).
3. **PostgreSQL**: Download from [postgresql.org](https://www.postgresql.org/download/windows/). The installer includes pgAdmin. Remember the password you set for the `postgres` user.

**Linux (Ubuntu/Debian)**:
```bash
sudo apt update
sudo apt install python3.13 python3.13-venv nodejs npm postgresql postgresql-contrib
sudo systemctl start postgresql
```

---

## Database Setup

Create the database. Logion 2 will auto-create all tables on first startup.

**macOS / Linux**:
```bash
createdb logion2
```

**Windows** (in pgAdmin or psql):
```sql
CREATE DATABASE logion2;
```

If your PostgreSQL uses a different user/password than the defaults (`postgres`/`postgres`), note them for the `.env` file below.

---

## Backend Setup

### 1. Create and activate a virtual environment

**macOS / Linux**:
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
```

**Windows** (Command Prompt):
```cmd
cd backend
python -m venv venv
venv\Scripts\activate
```

**Windows** (PowerShell):
```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

This installs FastAPI, SQLAlchemy, LangChain, Voyage AI, Google Generative AI, spaCy, sentence-transformers, and all other dependencies. The installation may take a few minutes due to PyTorch and transformer models.

### 3. Configure environment variables

Copy the example file and fill in your values:

```bash
# From the project root (not backend/)
cp .env.example .env
```

Edit `.env` with your settings:

```ini
# --- Database (PostgreSQL) ---
DB_HOST=localhost
DB_PORT=5432
DB_NAME=logion2
DB_USER=postgres
DB_PASS=postgres

# --- File Storage ---
# Local filesystem path for project files (source docs, TM, references).
# Default: ./projectdata (relative to backend/ directory)
# STORAGE_ROOT=./projectdata

# --- AI API Keys ---

# Google Gemini (translation, optimization, chat)
# Get yours at: https://aistudio.google.com/apikey
GOOGLE_API_KEY=your-google-api-key-here

# Anthropic Claude (translation, chat — optional, needed for Claude models)
# Get yours at: https://console.anthropic.com/
ANTHROPIC_API_KEY=your-anthropic-api-key-here

# Voyage AI (semantic embeddings & reranking — required for RAG)
# Get yours at: https://www.voyageai.com/
VOYAGE_API_KEY=your-voyage-api-key-here
VOYAGE_MODEL=voyage-3-large
```

**Required keys:**
- `GOOGLE_API_KEY` — needed for Gemini models (default translation engine)
- `VOYAGE_API_KEY` — needed for semantic search (TM, glossary, context retrieval)

**Optional keys:**
- `ANTHROPIC_API_KEY` — only needed if you want to use Claude models for translation/chat

### 4. Configure AI Models

The available AI models are defined in `backend/ai_models.json`. The default configuration includes:

| Model | Provider | Purpose |
|-------|----------|---------|
| Gemini 3.1 Pro Preview | Google | Translation (default) |
| Gemini 3 Pro Preview | Google | Translation |
| Gemini 3 Flash Preview | Google | Translation (fast) |
| Gemini 2.5 Pro | Google | Translation (stable) |
| Gemini 2.5 Flash | Google | Translation (fast) |
| Claude Opus 4.6 | Anthropic | Translation (premium) |
| Claude Sonnet 4.6 | Anthropic | Translation |
| Voyage 3 Large | Voyage | Embeddings |
| Rerank 2.5 | Voyage | Reranking |

To add or remove models, edit `backend/ai_models.json`:

```json
{
    "models": [
        {
            "id": "gemini-2.5-flash",
            "name": "Gemini 2.5 Flash",
            "provider": "google",
            "usage": "mt",
            "context_window": 1000000,
            "input_cost_per_m": 0.3,
            "output_cost_per_m": 2.5
        }
    ]
}
```

Fields:
- `id` — API model identifier (must match the provider's model ID)
- `name` — Display name in the UI
- `provider` — `"google"`, `"anthropic"`, or `"voyage"`
- `usage` — `"mt"` (machine translation / chat) or `"bg"` (background / embeddings)
- `context_window` — Max tokens
- `input_cost_per_m` / `output_cost_per_m` — Cost per million tokens (for usage tracking)

The first model in the list is used as the default if no model is selected in project settings.

### 5. Start the backend

```bash
cd backend
source venv/bin/activate   # macOS/Linux
# venv\Scripts\activate    # Windows

uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://127.0.0.1:8000`. Tables are created automatically on first startup.

---

## Frontend Setup

### 1. Install Node dependencies

```bash
cd frontend
npm install
```

### 2. Start the development server

```bash
npm run dev
```

The UI will be available at `http://localhost:5173`.

---

## Running the Application

You need **two terminal windows** running simultaneously:

**Terminal 1 — Backend:**
```bash
cd backend
source venv/bin/activate   # macOS/Linux (or venv\Scripts\activate on Windows)
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```

Then open `http://localhost:5173` in your browser.

---

## Project Structure

```
logion2/
├── .env                          # Environment variables (not in git)
├── .env.example                  # Template for .env
├── backend/
│   ├── ai_models.json            # AI model definitions
│   ├── requirements.txt          # Python dependencies (pip-compiled)
│   ├── requirements.in           # Top-level Python dependencies
│   ├── app/
│   │   ├── main.py               # FastAPI app, CORS, startup events
│   │   ├── config.py             # AI model config loader
│   │   ├── database.py           # PostgreSQL connection (SQLAlchemy)
│   │   ├── storage.py            # Local file storage
│   │   ├── models.py             # SQLAlchemy models
│   │   ├── routers/              # API endpoints
│   │   │   ├── project.py        # Project CRUD, workflows
│   │   │   ├── segment.py        # Segment updates, propagation
│   │   │   ├── translate.py      # AI draft generation
│   │   │   ├── glossary.py       # Glossary CRUD
│   │   │   ├── chat.py           # Segment AI chat
│   │   │   └── settings.py       # Global app settings, backups
│   │   ├── services/             # Business logic
│   │   ├── workflows/            # Background workflows (translate, optimize, reingest)
│   │   ├── rag/                  # RAG pipeline (embeddings, retrieval, assembly)
│   │   └── parsers/              # Document parsers (DOCX, XLIFF, TMX, etc.)
│   └── projectdata/              # File storage (created at runtime)
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── App.jsx               # Root component, routing
│   │   ├── api/client.js         # API client functions
│   │   ├── components/           # React components
│   │   │   ├── SplitView.jsx     # Main translation editor
│   │   │   ├── TiptapEditor.jsx  # Rich text editor with tag support
│   │   │   ├── ProjectList.jsx   # Project dashboard
│   │   │   └── settings/         # Settings tabs (AI, RAG, Glossary, Workflows)
│   │   ├── hooks/                # Custom React hooks
│   │   └── utils/                # Utilities (tag transforms, etc.)
│   └── public/
└── backups/                      # Auto-backup directory (configurable)
```

---

## Troubleshooting

### PostgreSQL connection refused
- **macOS**: `brew services start postgresql@15`
- **Linux**: `sudo systemctl start postgresql`
- **Windows**: Check that the PostgreSQL service is running in Services (`services.msc`)

### `pip install` fails on macOS (torch / C extensions)
Make sure you have Xcode Command Line Tools:
```bash
xcode-select --install
```

### Port 8000 already in use
```bash
# Find and kill the process
lsof -i :8000  # macOS/Linux
# or
netstat -ano | findstr :8000  # Windows
```

### CORS errors in browser
The backend allows requests from `localhost:5173`, `5174`, `5175`, and `3000`. If your frontend runs on a different port, add it to the `allow_origins` list in `backend/app/main.py`.

### Empty translations / API errors
- Check that your API keys are set correctly in `.env`
- Verify the keys work by checking the provider's console (Google AI Studio, Anthropic Console, Voyage dashboard)
- Check the backend terminal for error messages
