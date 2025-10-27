#!/usr/bin/env python
"""
Database migration script for TwinOps.

This script initializes the Neo4j graph database schema with all required
constraints, indexes, and initial data structures.

Usage:
    python scripts/migrate.py [migrate|rollback|check]
"""

from __future__ import annotations

import asyncio
import logging
import sys

from backend.core.config import settings
from backend.core.database import database_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# Neo4j Graph Schema Migrations
# ============================================================================

NEO4J_CONSTRAINTS = [
    # Unique constraints for node IDs
    "CREATE CONSTRAINT role_id IF NOT EXISTS FOR (r:Role) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT project_id IF NOT EXISTS FOR (pr:Project) REQUIRE pr.id IS UNIQUE",
    "CREATE CONSTRAINT system_id IF NOT EXISTS FOR (s:System) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT workflow_id IF NOT EXISTS FOR (w:Workflow) REQUIRE w.id IS UNIQUE",
    "CREATE CONSTRAINT skill_id IF NOT EXISTS FOR (sk:Skill) REQUIRE sk.id IS UNIQUE",
]

NEO4J_INDEXES = [
    # Performance indexes for common queries
    "CREATE INDEX role_name IF NOT EXISTS FOR (r:Role) ON (r.name)",
    "CREATE INDEX role_department IF NOT EXISTS FOR (r:Role) ON (r.department)",
    "CREATE INDEX role_level IF NOT EXISTS FOR (r:Role) ON (r.level)",
    "CREATE INDEX person_email IF NOT EXISTS FOR (p:Person) ON (p.email)",
    "CREATE INDEX person_slack_id IF NOT EXISTS FOR (p:Person) ON (p.slack_id)",
    "CREATE INDEX person_availability IF NOT EXISTS FOR (p:Person) ON (p.availability_status)",
    "CREATE INDEX document_source IF NOT EXISTS FOR (d:Document) ON (d.source)",
    "CREATE INDEX document_classification IF NOT EXISTS FOR (d:Document) ON (d.classification)",
    "CREATE INDEX document_modified IF NOT EXISTS FOR (d:Document) ON (d.last_modified)",
    "CREATE INDEX project_name IF NOT EXISTS FOR (pr:Project) ON (pr.name)",
    "CREATE INDEX project_status IF NOT EXISTS FOR (pr:Project) ON (pr.status)",
    "CREATE INDEX workflow_status IF NOT EXISTS FOR (w:Workflow) ON (w.status)",
    "CREATE INDEX workflow_type IF NOT EXISTS FOR (w:Workflow) ON (w.workflow_type)",
]

NEO4J_FULLTEXT_INDEXES = [
    # Full-text search indexes
    """
    CREATE FULLTEXT INDEX document_content IF NOT EXISTS
    FOR (d:Document)
    ON EACH [d.title, d.content]
    """,
    """
    CREATE FULLTEXT INDEX role_search IF NOT EXISTS
    FOR (r:Role)
    ON EACH [r.name, r.description, r.responsibilities]
    """,
    """
    CREATE FULLTEXT INDEX person_search IF NOT EXISTS
    FOR (p:Person)
    ON EACH [p.name, p.email, p.skills]
    """,
]


async def run_migrations() -> None:
    """Execute all database migrations."""
    logger.info("Starting TwinOps database migrations...")

    await database_manager.initialize()
    driver = database_manager.neo4j

    if driver is None:
        logger.error("Neo4j driver unavailable")
        return

    try:
        async with driver.session() as session:
            # Create constraints
            logger.info("Creating constraints...")
            for constraint in NEO4J_CONSTRAINTS:
                try:
                    await session.run(constraint)
                    logger.info(f"✓ {constraint[:50]}...")
                except Exception as e:
                    logger.warning(f"Constraint already exists or failed: {e}")

            # Create indexes
            logger.info("Creating indexes...")
            for index in NEO4J_INDEXES:
                try:
                    await session.run(index)
                    logger.info(f"✓ {index[:50]}...")
                except Exception as e:
                    logger.warning(f"Index already exists or failed: {e}")

            # Create full-text indexes
            logger.info("Creating full-text indexes...")
            for ft_index in NEO4J_FULLTEXT_INDEXES:
                try:
                    await session.run(ft_index.strip())
                    logger.info("✓ Full-text index created")
                except Exception as e:
                    logger.warning(f"Full-text index already exists or failed: {e}")

            # Verify schema
            logger.info("Verifying schema...")
            result = await session.run("SHOW CONSTRAINTS")
            constraints = await result.data()
            logger.info(f"Total constraints: {len(constraints)}")

            result = await session.run("SHOW INDEXES")
            indexes = await result.data()
            logger.info(f"Total indexes: {len(indexes)}")

        logger.info("✓ Database migrations completed successfully!")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        await database_manager.close()


async def rollback_migrations() -> None:
    """Rollback all migrations (use with caution!)."""
    logger.warning("Rolling back migrations - this will drop all constraints and indexes!")

    response = input("Are you sure? This cannot be undone! (yes/no): ")
    if response.lower() != "yes":
        logger.info("Rollback cancelled.")
        return

    await database_manager.initialize()
    driver = database_manager.neo4j

    if driver is None:
        logger.error("Neo4j driver unavailable")
        return

    try:
        async with driver.session() as session:
            # Drop all constraints
            result = await session.run("SHOW CONSTRAINTS")
            constraints = await result.data()

            for constraint in constraints:
                constraint_name = constraint.get("name")
                if constraint_name:
                    await session.run(f"DROP CONSTRAINT {constraint_name}")
                    logger.info(f"Dropped constraint: {constraint_name}")

            # Drop all indexes
            result = await session.run("SHOW INDEXES")
            indexes = await result.data()

            for index in indexes:
                index_name = index.get("name")
                if index_name and not index_name.startswith("__"):  # Skip system indexes
                    await session.run(f"DROP INDEX {index_name}")
                    logger.info(f"Dropped index: {index_name}")

        logger.info("✓ Rollback completed.")

    finally:
        await database_manager.close()


async def check_schema() -> None:
    """Check current database schema."""
    logger.info("Checking database schema...")

    await database_manager.initialize()
    driver = database_manager.neo4j

    if driver is None:
        logger.error("Neo4j driver unavailable")
        return

    try:
        async with driver.session() as session:
            # Show constraints
            logger.info("\n=== CONSTRAINTS ===")
            result = await session.run("SHOW CONSTRAINTS")
            constraints = await result.data()
            for constraint in constraints:
                logger.info(f"  {constraint.get('name')}: {constraint.get('type')}")

            # Show indexes
            logger.info("\n=== INDEXES ===")
            result = await session.run("SHOW INDEXES")
            indexes = await result.data()
            for index in indexes:
                logger.info(f"  {index.get('name')}: {index.get('type')}")

            # Show node counts
            logger.info("\n=== NODE COUNTS ===")
            labels = ["Role", "Person", "Document", "Project", "System", "Workflow", "Skill"]
            for label in labels:
                result = await session.run(f"MATCH (n:{label}) RETURN count(n) as count")
                data = await result.single()
                logger.info(f"  {label}: {data['count']}")

    finally:
        await database_manager.close()


def main() -> None:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="TwinOps Database Migration Tool")
    parser.add_argument(
        "command",
        nargs="?",
        default="migrate",
        choices=["migrate", "rollback", "check"],
        help="Command to execute (default: migrate)"
    )

    args = parser.parse_args()

    try:
        if args.command == "migrate":
            asyncio.run(run_migrations())
        elif args.command == "rollback":
            asyncio.run(rollback_migrations())
        elif args.command == "check":
            asyncio.run(check_schema())
    except KeyboardInterrupt:
        logger.info("\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Operation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
