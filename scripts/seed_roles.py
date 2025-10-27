#!/usr/bin/env python
"""
Seed Neo4j with role, person, and delegation relationships for TwinOps.

Usage:
    poetry run python scripts/seed_roles.py
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from backend.core.database import database_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("twinops.seed_roles")

ROLES = [
    {
        "id": "incident_commander",
        "name": "Incident Commander",
        "department": "operations",
        "level": "senior",
        "responsibilities": ["incident_triage", "stakeholder_updates", "swarm_management"],
        "required_skills": ["incident_response", "communication", "decision_making"],
        "delegation_chain": ["ops_lead", "sre_oncall"],
        "knowledge_domains": ["infrastructure", "observability"],
        "manager_id": "platform_manager",
    },
    {
        "id": "ops_lead",
        "name": "Operations Lead",
        "department": "operations",
        "level": "lead",
        "responsibilities": ["backlog_prioritization", "release_management"],
        "required_skills": ["operations", "project_management"],
        "delegation_chain": ["sre_oncall"],
        "knowledge_domains": ["operations", "delivery"],
        "manager_id": "platform_manager",
    },
    {
        "id": "sre_oncall",
        "name": "SRE On-call",
        "department": "platform",
        "level": "mid",
        "responsibilities": ["infrastructure_scaling", "alert_response"],
        "required_skills": ["infrastructure", "kubernetes", "observability"],
        "delegation_chain": ["sre_backup"],
        "knowledge_domains": ["infrastructure", "platform"],
        "manager_id": "platform_manager",
    },
    {
        "id": "sre_backup",
        "name": "SRE Backup",
        "department": "platform",
        "level": "mid",
        "responsibilities": ["alert_response"],
        "required_skills": ["infrastructure", "incident_response"],
        "delegation_chain": [],
        "knowledge_domains": ["infrastructure"],
        "manager_id": "platform_manager",
    },
    {
        "id": "platform_manager",
        "name": "Platform Engineering Manager",
        "department": "platform",
        "level": "manager",
        "responsibilities": ["team_leadership", "strategy"],
        "required_skills": ["leadership", "stakeholder_management"],
        "delegation_chain": ["incident_commander"],
        "knowledge_domains": ["platform", "operations"],
        "manager_id": "vp_engineering",
    },
    {
        "id": "vp_engineering",
        "name": "VP Engineering",
        "department": "executive",
        "level": "executive",
        "responsibilities": ["strategy", "org_alignment"],
        "required_skills": ["leadership", "strategy"],
        "delegation_chain": [],
        "knowledge_domains": ["strategy"],
    },
]

PEOPLE = [
    {
        "id": "person-alex",
        "name": "Alex Rivera",
        "email": "alex.rivera@twinops.local",
        "slack_id": "U01ALEX",
        "current_role_id": "incident_commander",
        "skills": ["incident_response", "communication", "observability"],
        "availability_status": "available",
        "timezone": "UTC",
    },
    {
        "id": "person-blair",
        "name": "Blair Chen",
        "email": "blair.chen@twinops.local",
        "slack_id": "U02BLAIR",
        "current_role_id": "ops_lead",
        "skills": ["operations", "project_management"],
        "availability_status": "online",
        "timezone": "America/Los_Angeles",
    },
    {
        "id": "person-cam",
        "name": "Cam Singh",
        "email": "cam.singh@twinops.local",
        "slack_id": "U03CAM",
        "current_role_id": "sre_oncall",
        "skills": ["kubernetes", "observability"],
        "availability_status": "busy",
        "timezone": "America/New_York",
    },
    {
        "id": "person-devon",
        "name": "Devon Patel",
        "email": "devon.patel@twinops.local",
        "slack_id": "U04DEVON",
        "current_role_id": "sre_backup",
        "skills": ["incident_response", "infrastructure"],
        "availability_status": "available",
        "timezone": "UTC",
    },
    {
        "id": "person-erin",
        "name": "Erin Okafor",
        "email": "erin.okafor@twinops.local",
        "slack_id": "U05ERIN",
        "current_role_id": "platform_manager",
        "skills": ["leadership", "coaching"],
        "availability_status": "offline",
        "timezone": "Europe/London",
    },
]


RESPONSIBILITIES = [
    {"name": "incident_triage", "description": "Coordinate intake and triage of active incidents."},
    {"name": "stakeholder_updates", "description": "Communicate incident status to stakeholders."},
    {"name": "swarm_management", "description": "Organize responders during incidents."},
    {"name": "backlog_prioritization", "description": "Prioritize operations backlog."},
    {"name": "release_management", "description": "Coordinate releases and change windows."},
    {"name": "infrastructure_scaling", "description": "Ensure infrastructure scales appropriately."},
    {"name": "alert_response", "description": "Respond to production alerts."},
]


async def seed() -> None:
    await database_manager.initialize()
    driver = database_manager.neo4j
    if driver is None:
        raise RuntimeError("Neo4j driver unavailable. Check configuration.")

    async with driver.session() as session:
        logger.info("Seeding roles...")
        await session.run(
            """
            UNWIND $roles AS role
            MERGE (r:Role {id: role.id})
            SET r += {
                name: role.name,
                department: role.department,
                level: role.level,
                responsibilities: role.responsibilities,
                required_skills: role.required_skills,
                delegation_chain: role.delegation_chain,
                knowledge_domains: role.knowledge_domains,
                is_active: true,
                created_at: coalesce(r.created_at, datetime()),
                updated_at: datetime()
            }
            WITH r, role
            FOREACH (manager_id IN CASE WHEN role.manager_id IS NOT NULL THEN [role.manager_id] ELSE [] END |
                MERGE (m:Role {id: manager_id})
                MERGE (r)-[:REPORTS_TO]->(m)
            )
            """,
            {"roles": ROLES},
        )

        logger.info("Seeding responsibilities...")
        await session.run(
            """
            UNWIND $responsibilities AS resp
            MERGE (r:Responsibility {name: resp.name})
            SET r.description = resp.description
            """,
            {"responsibilities": RESPONSIBILITIES},
        )

        logger.info("Linking role responsibilities...")
        await session.run(
            """
            UNWIND $roles AS role
            MATCH (r:Role {id: role.id})
            UNWIND role.responsibilities AS resp_name
            MATCH (resp:Responsibility {name: resp_name})
            MERGE (r)-[:RESPONSIBLE_FOR]->(resp)
            """,
            {"roles": ROLES},
        )

        logger.info("Creating delegation edges...")
        await session.run(
            """
            UNWIND $roles AS role
            MATCH (r:Role {id: role.id})
            UNWIND role.delegation_chain AS delegate_id
            MATCH (delegate:Role {id: delegate_id})
            MERGE (r)-[:DELEGATES_TO]->(delegate)
            """,
            {"roles": ROLES},
        )

        logger.info("Seeding people and availability...")
        await session.run(
            """
            UNWIND $people AS person
            MERGE (p:Person {id: person.id})
            SET p += {
                name: person.name,
                email: person.email,
                slack_id: person.slack_id,
                skills: person.skills,
                availability_status: person.availability_status,
                timezone: person.timezone,
                created_at: coalesce(p.created_at, datetime()),
                updated_at: datetime()
            }
            WITH p, person
            MATCH (role:Role {id: person.current_role_id})
            MERGE (p)-[:HOLDS_ROLE]->(role)
            """,
            {"people": PEOPLE},
        )

    await database_manager.close()
    logger.info("Seeding completed at %s", datetime.utcnow().isoformat())


if __name__ == "__main__":
    asyncio.run(seed())

