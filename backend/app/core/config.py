import os
from dotenv import load_dotenv

# Load .env file
# We assume the .env file is in the root of the project (parent of backend)
# current file is in backend/app/core/config.py
# .env is in ../../../.env relative to this file? 
# or just use load_dotenv which searches?
# The user's .env is at /Users/beiti/prog/logion2/.env
# If we run the app from /Users/beiti/prog/logion2/backend or /Users/beiti/prog/logion2/
# load_dotenv() usually looks for .env in current dir or parents.

load_dotenv() 

class Settings:
    PROJECT_NAME: str = "Logion 2"
    PROJECT_VERSION: str = "1.0.0"

    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "5432")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASS: str = os.getenv("DB_PASS", "")
    DB_NAME: str = "logion2" # override to use the new db

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

settings = Settings()
