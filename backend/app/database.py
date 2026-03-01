import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Lädt die .env Datei (wo deine Passwörter stehen)
load_dotenv()

# Wir bauen den Connection-String aus den Env-Variablen
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "password")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "logion2")

# SQLALCHEMY_DATABASE_URL = "sqlite:///./logion.db"
SQLALCHEMY_DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"



# Der Motor der Datenbank
# Increased pool size: background workflows hold long-lived sessions
# while the user + auto-polling need concurrent connections.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=60,
    pool_recycle=1800,
)

# Die Session-Fabrik (jedes Request bekommt eine eigene Session)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Die Basis-Klasse für unsere Models
Base = declarative_base()

# Hilfsfunktion: Session holen und sauber wieder schließen
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()