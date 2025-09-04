"""
Main FastAPI application for NCR Upload API
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routes import router


def create_app() -> FastAPI:
    """Create and configure FastAPI application"""
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description="API for processing NCR upload jobs with validation and SFTP upload"
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure this properly for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routes
    app.include_router(router)
    
    return app


# Create the app instance
app = create_app()


if __name__ == "__main__":
    print("Starting NCR Upload API...")
    print("Make sure Redis is running on localhost:6379")
    print(f"API will be available at http://{settings.api_host}:{settings.api_port}")
    print(f"API docs at http://{settings.api_host}:{settings.api_port}/docs")
    print(f"Using timezone: {settings.timezone}")
    
    uvicorn.run(
        app, 
        host=settings.api_host, 
        port=settings.api_port,
        reload=True  # Enable auto-reload for development
    )
