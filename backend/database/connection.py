# -*- coding: utf-8 -*-
# Copyright (c) 2024, LinkSpot Project Contributors
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
LinkSpot Database Connection Management

Provides synchronous and asynchronous database connection management
with connection pooling, session handling, and spatial index creation.
"""

import logging
import random
import time
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Generator, Optional, Any

from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    AsyncEngine,
    async_sessionmaker,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from .models import Base

logger = logging.getLogger(__name__)


class Database:
    """
    Database connection manager for PostgreSQL + PostGIS.
    
    Provides both synchronous and asynchronous database connections
    with proper connection pooling, session management, and spatial
    index creation.
    
    Example:
        >>> db = Database("postgresql://user:pass@localhost/linkspot")
        >>> db.connect()
        >>> db.create_tables()
        >>> db.create_indexes()
        >>> 
        >>> # Synchronous usage
        >>> with db.get_session() as session:
        ...     # perform queries
        ...
        >>> # Asynchronous usage
        >>> async with db.get_async_session() as session:
        ...     # perform async queries
        ...
        >>> db.close()
    
    Attributes:
        connection_string: PostgreSQL connection URI
        async_connection_string: Async PostgreSQL connection URI
        engine: SQLAlchemy synchronous engine
        async_engine: SQLAlchemy asynchronous engine
        SessionLocal: Synchronous session factory
        AsyncSessionLocal: Asynchronous session factory
    """
    
    def __init__(
        self,
        connection_string: str,
        async_connection_string: Optional[str] = None,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
        echo: bool = False,
    ):
        """
        Initialize database connection manager.
        
        Args:
            connection_string: PostgreSQL connection URI (sync)
            async_connection_string: PostgreSQL connection URI (async).
                If None, converts sync URI to async format.
            pool_size: Connection pool size
            max_overflow: Maximum overflow connections
            pool_timeout: Pool connection timeout in seconds
            pool_recycle: Connection recycle time in seconds
            echo: Enable SQL query logging
        """
        self.connection_string = connection_string
        self.async_connection_string = async_connection_string or self._to_async_uri(
            connection_string
        )
        
        self._pool_config = {
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "pool_timeout": pool_timeout,
            "pool_recycle": pool_recycle,
        }
        self._echo = echo
        
        self.engine: Optional[Engine] = None
        self.async_engine: Optional[AsyncEngine] = None
        self.SessionLocal: Optional[sessionmaker] = None
        self.AsyncSessionLocal: Optional[async_sessionmaker] = None
        
        logger.info("Database connection manager initialized")
    
    @staticmethod
    def _to_async_uri(sync_uri: str) -> str:
        """Convert synchronous PostgreSQL URI to async format."""
        if sync_uri.startswith("postgresql://"):
            return sync_uri.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif sync_uri.startswith("postgresql+psycopg2://"):
            return sync_uri.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        # TODO: Validate/normalize other sync drivers so connection strings are deterministic.
        return sync_uri
    
    def connect(self) -> None:
        """
        Create database engines and session factories.
        
        Creates both synchronous and asynchronous engines with
        configured connection pooling.
        """
        max_attempts = 3
        base_backoff = 0.25
        last_error: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                if self.engine is not None:
                    self.engine.dispose()
                self.engine = create_engine(
                    self.connection_string,
                    echo=self._echo,
                    **self._pool_config,
                )

                if self.async_engine is not None:
                    # Sync path cannot await async dispose; drop reference and replace.
                    self.async_engine = None
                self.async_engine = create_async_engine(
                    self.async_connection_string,
                    echo=self._echo,
                    **self._pool_config,
                )

                self.SessionLocal = sessionmaker(
                    autocommit=False,
                    autoflush=False,
                    bind=self.engine,
                )
                self.AsyncSessionLocal = async_sessionmaker(
                    autocommit=False,
                    autoflush=False,
                    bind=self.async_engine,
                    class_=AsyncSession,
                )

                if self.engine is not None:
                    event.listen(self.engine, "connect", self._on_connect)

                logger.info("Database engines and session factories created")
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Database connect attempt %d/%d failed: %s",
                    attempt,
                    max_attempts,
                    exc,
                )
                if attempt < max_attempts:
                    sleep_s = base_backoff * (2 ** (attempt - 1)) + random.uniform(0.0, 0.2)
                    time.sleep(sleep_s)

        raise RuntimeError(f"Failed to initialize database engines after retries: {last_error}")
    
    @staticmethod
    def _on_connect(dbapi_conn: Any, connection_record: Any) -> None:
        """Configure connection on creation."""
        # Set timezone to UTC
        cursor = dbapi_conn.cursor()
        cursor.execute("SET timezone TO 'UTC';")
        cursor.close()
        # TODO: Set role/search path and lock timeout defaults per request profile if needed.
    
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        Get synchronous database session as context manager.
        
        Yields:
            SQLAlchemy Session object
            
        Example:
            >>> with db.get_session() as session:
            ...     buildings = session.query(Building).all()
            ...     session.commit()
        """
        if self.SessionLocal is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Session rollback due to error: {e}")
            raise
        finally:
            session.close()
            # TODO: Track rollback/close metrics for connection pool pressure diagnostics.
    
    @asynccontextmanager
    async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get asynchronous database session as context manager.
        
        Yields:
            SQLAlchemy AsyncSession object
            
        Example:
            >>> async with db.get_async_session() as session:
            ...     result = await session.execute(select(Building))
            ...     await session.commit()
        """
        if self.AsyncSessionLocal is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        
        session = self.AsyncSessionLocal()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Async session rollback due to error: {e}")
            raise
        finally:
            await session.close()
    
    def create_tables(self) -> None:
        """
        Create all database tables from models.
        
        Creates tables defined in models.py including PostGIS
        geometry columns.
        """
        if self.engine is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=self.engine)
        logger.info("Database tables created successfully")
    
    async def create_tables_async(self) -> None:
        """
        Create all database tables asynchronously.
        
        Async version of create_tables().
        """
        if self.async_engine is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        
        logger.info("Creating database tables (async)...")
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully (async)")
    
    def create_indexes(self) -> None:
        """
        Create spatial and performance indexes.
        
        Creates GiST spatial indexes on geometry columns and
        additional performance indexes for common queries.
        """
        if self.engine is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        
        logger.info("Creating spatial and performance indexes...")
        
        index_statements = [
            # Spatial indexes using GiST
            """
            CREATE INDEX IF NOT EXISTS idx_buildings_geometry_gist
            ON buildings USING GIST (geometry);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_terrain_tiles_bbox_gist
            ON terrain_tiles USING GIST (bbox);
            """,
            
            # Additional performance indexes
            """
            CREATE INDEX IF NOT EXISTS idx_buildings_height_range
            ON buildings (height) WHERE height > 0;
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_cache_geohash_prefix
            ON analysis_cache (geohash varchar_pattern_ops);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_cache_active
            ON analysis_cache (geohash)
            WHERE expires_at IS NULL OR expires_at > NOW();
            """,
        ]
        
        with self.engine.connect() as conn:
            # TODO: Run DDL in an explicit transaction and report partial-failure details.
            for statement in index_statements:
                conn.execute(text(statement))
            conn.commit()
        
        logger.info("Spatial and performance indexes created successfully")
    
    async def create_indexes_async(self) -> None:
        """
        Create spatial and performance indexes asynchronously.
        
        Async version of create_indexes().
        """
        if self.async_engine is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        
        logger.info("Creating spatial and performance indexes (async)...")
        
        index_statements = [
            """
            CREATE INDEX IF NOT EXISTS idx_buildings_geometry_gist
            ON buildings USING GIST (geometry);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_terrain_tiles_bbox_gist
            ON terrain_tiles USING GIST (bbox);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_buildings_height_range
            ON buildings (height) WHERE height > 0;
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_cache_geohash_prefix
            ON analysis_cache (geohash varchar_pattern_ops);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_cache_active
            ON analysis_cache (geohash)
            WHERE expires_at IS NULL OR expires_at > NOW();
            """,
        ]
        
        async with self.async_engine.connect() as conn:
            # TODO: Consider `CREATE CONCURRENTLY` or lock-timeout settings for zero-downtime environments.
            for statement in index_statements:
                await conn.execute(text(statement))
            await conn.commit()
        
        logger.info("Spatial and performance indexes created successfully (async)")
    
    def enable_postgis(self) -> None:
        """
        Enable PostGIS extension.
        
        Must be run before creating spatial tables.
        """
        if self.engine is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        
        with self.engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis_topology;"))
            conn.commit()
        
        logger.info("PostGIS extension enabled")
    
    async def enable_postgis_async(self) -> None:
        """Enable PostGIS extension asynchronously."""
        if self.async_engine is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        
        async with self.async_engine.connect() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis_topology;"))
            await conn.commit()
        
        logger.info("PostGIS extension enabled (async)")
    
    def drop_tables(self) -> None:
        """
        Drop all database tables.
        
        WARNING: This will delete all data!
        """
        if self.engine is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        
        logger.warning("Dropping all database tables...")
        Base.metadata.drop_all(bind=self.engine)
        logger.info("Database tables dropped")
    
    async def drop_tables_async(self) -> None:
        """Drop all database tables asynchronously."""
        if self.async_engine is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        
        logger.warning("Dropping all database tables (async)...")
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        logger.info("Database tables dropped (async)")
    
    def close(self) -> None:
        """
        Close database connections and cleanup resources.
        
        Should be called on application shutdown.
        """
        logger.info("Closing database connections...")
        
        if self.engine:
            self.engine.dispose()
            self.engine = None
        
        if self.async_engine:
            # Async engine disposal must be done in async context
            self.async_engine = None
        
        self.SessionLocal = None
        self.AsyncSessionLocal = None
        
        logger.info("Database connections closed")
        # TODO: Add logging around connection close duration to catch slow shutdowns under load.
    
    async def close_async(self) -> None:
        """Close database connections asynchronously."""
        logger.info("Closing database connections (async)...")

        if self.async_engine:
            await self.async_engine.dispose()
            self.async_engine = None
        
        if self.engine:
            self.engine.dispose()
            self.engine = None
        
        self.SessionLocal = None
        self.AsyncSessionLocal = None
        
        logger.info("Database connections closed (async)")
    
    def health_check(self) -> bool:
        """
        Check database connectivity.
        
        Returns:
            True if database is accessible, False otherwise
        """
        if self.engine is None:
            return False
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT 1;"))
                return result.scalar() == 1
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            # TODO: Return a richer diagnostic object instead of bool for caller retries/fallbacks.
            return False
    
    async def health_check_async(self) -> bool:
        """Check database connectivity asynchronously."""
        if self.async_engine is None:
            return False
        
        try:
            async with self.async_engine.connect() as conn:
                result = await conn.execute(text("SELECT 1;"))
                return result.scalar() == 1
        except Exception as e:
            logger.error(f"Database health check failed (async): {e}")
            # TODO: Capture and surface async driver errors separately from SQL execution failures.
            return False


# Convenience function for quick database setup
def create_database(
    connection_string: str,
    create_tables: bool = True,
    create_indexes: bool = True,
    enable_postgis: bool = True,
) -> Database:
    """
    Create and configure database connection.
    
    Args:
        connection_string: PostgreSQL connection URI
        create_tables: Create tables on connect
        create_indexes: Create indexes on connect
        enable_postgis: Enable PostGIS extension
        
    Returns:
        Configured Database instance
    """
    db = Database(connection_string)
    db.connect()
    
    if enable_postgis:
        db.enable_postgis()
    
    if create_tables:
        db.create_tables()
    
    if create_indexes:
        db.create_indexes()
    
    return db


__all__ = [
    "Database",
    "create_database",
]
