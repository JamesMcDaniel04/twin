"""Container artifact data models."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ContainerVulnerability(BaseModel):
    """Container vulnerability information."""

    cve_id: str = Field(..., description="CVE identifier")
    severity: str = Field(..., description="Severity level (LOW, MEDIUM, HIGH, CRITICAL)")
    package: str = Field(..., description="Affected package")
    version: str = Field(..., description="Affected version")
    fixed_version: Optional[str] = Field(None, description="Fixed version (if available)")
    description: Optional[str] = Field(None, description="Vulnerability description")


class ContainerImage(BaseModel):
    """Container image metadata."""

    image_id: str = Field(..., description="Container image SHA digest")
    tag: str = Field(..., description="Image tag")
    repository: str = Field(..., description="Container repository")
    artifact_uri: str = Field(..., description="URI to container artifact")
    version: str = Field(..., description="Semantic version or build number")
    ingested_at: datetime = Field(default_factory=datetime.utcnow, description="Ingestion timestamp")

    # Optional fields
    base_image: Optional[str] = Field(None, description="Base image")
    runtime: Optional[str] = Field(None, description="Runtime environment")
    owner_team: Optional[str] = Field(None, description="Owning team")
    labels: Optional[Dict[str, str]] = Field(default_factory=dict, description="Container labels")
    build_info: Optional[Dict[str, object]] = Field(default_factory=dict, description="Build metadata")

    # SBOM reference
    sbom_uri: Optional[str] = Field(None, description="URI to SBOM artifact")

    # Vulnerabilities
    vulnerabilities: Optional[List[ContainerVulnerability]] = Field(
        default_factory=list,
        description="Known vulnerabilities",
    )


class SBOM(BaseModel):
    """Software Bill of Materials metadata."""

    sbom_id: str = Field(..., description="SBOM identifier")
    uri: str = Field(..., description="URI to SBOM artifact in object storage")
    format: str = Field(..., description="SBOM format (e.g., SPDX, CycloneDX)")
    version: str = Field(..., description="SBOM format version")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="SBOM creation timestamp")

    # Related image
    image_id: Optional[str] = Field(None, description="Related container image ID")

    # Package information
    packages: Optional[List[Dict[str, object]]] = Field(
        default_factory=list,
        description="Package inventory",
    )


class ContainerService(BaseModel):
    """Service that uses a container image."""

    service_name: str = Field(..., description="Service name")
    namespace: str = Field(..., description="Kubernetes namespace or deployment environment")
    cluster: Optional[str] = Field(None, description="Cluster name")

    # Image reference
    image_id: Optional[str] = Field(None, description="Currently deployed image ID")
    image_tag: Optional[str] = Field(None, description="Currently deployed image tag")

    # Team ownership
    team: Optional[str] = Field(None, description="Owning team")
