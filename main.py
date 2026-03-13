import os
import uvicorn
from app import app

if __name__ == "__main__":
    PORT = int(os.getenv("PORT"))  
    uvicorn.run(
        "main:app", # módulo:objeto (main.py contiene app)
        host="0.0.0.0", # escucha en todas las interfaces
        port=PORT,
        reload=True # autoreload en desarrollo
    )