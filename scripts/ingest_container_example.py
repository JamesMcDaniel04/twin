#!/usr/bin/env python3
"""
Example script for ingesting container artifacts with vulnerability scans and SBOMs.

Usage:
    python scripts/ingest_container_example.py \
        --image myorg/backend-api:v1.0.0 \
        --registry gcr.io \
        --scan-results scan.json \
        --sbom sbom.json \
        --api-url http://localhost:8000
"""

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Dict, Optional

import requests


def load_json_file(file_path: str) -> Optional[Dict]:
    """Load JSON file."""
    try:
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {file_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {file_path}: {e}")
        return None


def parse_trivy_scan(scan_results: Dict) -> Dict[str, Dict]:
    """Parse Trivy scan results into vulnerability dictionary."""
    vulnerabilities = {}

    for result in scan_results.get("Results", []):
        for vuln in result.get("Vulnerabilities", []):
            cve_id = vuln.get("VulnerabilityID")
            if cve_id:
                vulnerabilities[cve_id] = {
                    "severity": vuln.get("Severity", "unknown").lower(),
                    "package": vuln.get("PkgName", ""),
                    "version": vuln.get("InstalledVersion", ""),
                    "fixed_version": vuln.get("FixedVersion"),
                    "description": vuln.get("Description", "")[:500],  # Truncate
                }

    return vulnerabilities


def upload_sbom_to_storage(sbom_data: Dict, image_name: str, storage_config: Dict) -> str:
    """
    Upload SBOM to object storage.

    Returns URI to the uploaded SBOM.
    """
    # This is a placeholder - implement actual S3/GCS upload
    sbom_filename = f"{image_name.replace('/', '-').replace(':', '-')}-sbom.json"

    # Example S3 upload (requires boto3)
    if storage_config.get("backend") == "s3":
        import boto3

        s3 = boto3.client("s3")
        bucket = storage_config["bucket"]
        key = f"sboms/{sbom_filename}"

        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(sbom_data),
            ContentType="application/json",
        )

        return f"s3://{bucket}/{key}"

    # Fallback: base64 encode for inline storage
    print("Warning: No storage backend configured; using inline SBOM encoding")
    return "inline"


def extract_image_metadata(image_name: str, registry: str) -> Dict:
    """
    Extract image metadata using Docker or container registry API.

    This is a simplified example - in production, use Docker SDK or registry API.
    """
    import subprocess

    try:
        # Get image inspect data
        result = subprocess.run(
            ["docker", "inspect", f"{registry}/{image_name}"],
            capture_output=True,
            text=True,
            check=True,
        )
        inspect_data = json.loads(result.stdout)[0]

        return {
            "created_at": inspect_data.get("Created"),
            "size_bytes": inspect_data.get("Size"),
            "architecture": inspect_data.get("Architecture"),
            "os": inspect_data.get("Os"),
            "layers": [layer["Digest"] for layer in inspect_data.get("RootFS", {}).get("Layers", [])],
            "labels": inspect_data.get("Config", {}).get("Labels", {}),
            "env_vars": {
                env.split("=", 1)[0]: env.split("=", 1)[1] if "=" in env else ""
                for env in inspect_data.get("Config", {}).get("Env", [])
            },
        }
    except subprocess.CalledProcessError:
        print("Warning: Failed to inspect image; using default metadata")
        return {}


def ingest_container(
    image_name: str,
    registry: str,
    scan_results: Optional[Dict],
    sbom_data: Optional[Dict],
    api_url: str,
    storage_config: Optional[Dict] = None,
    tags: Optional[list] = None,
) -> Dict:
    """
    Ingest container artifact to TwinOps.

    Args:
        image_name: Image name with tag (e.g., myorg/backend-api:v1.0.0)
        registry: Registry URL (e.g., gcr.io)
        scan_results: Trivy scan results
        sbom_data: SBOM document (SPDX or CycloneDX)
        api_url: TwinOps API URL
        storage_config: Storage configuration for SBOM upload
        tags: Additional tags

    Returns:
        API response
    """
    # Parse image name
    if ":" in image_name:
        repository, tag = image_name.rsplit(":", 1)
    else:
        repository = image_name
        tag = "latest"

    # Generate image ID (in production, get from registry)
    # This is a placeholder - use actual digest from registry
    image_id = f"sha256:{'0' * 64}"  # Replace with actual digest

    # Extract metadata
    metadata = extract_image_metadata(image_name, registry)

    # Parse vulnerabilities
    vulnerabilities = {}
    if scan_results:
        vulnerabilities = parse_trivy_scan(scan_results)
        print(f"Parsed {len(vulnerabilities)} vulnerabilities")

    # Upload SBOM
    sbom_uri = None
    sbom_format = None
    if sbom_data:
        storage_config = storage_config or {"backend": "s3", "bucket": "my-sbom-bucket"}
        sbom_uri = upload_sbom_to_storage(sbom_data, image_name, storage_config)

        # Detect SBOM format
        if "spdxVersion" in sbom_data:
            sbom_format = "spdx"
        elif "bomFormat" in sbom_data:
            sbom_format = "cyclonedx"

        print(f"Uploaded SBOM: {sbom_uri} (format: {sbom_format})")

    # Build request payload
    payload = {
        "source": "container",
        "tags": tags or ["container", "artifact"],
        "container_metadata": {
            "image_id": image_id,
            "image_tag": tag,
            "registry": registry,
            "repository": repository,
            "sbom_uri": sbom_uri,
            "sbom_format": sbom_format,
            **metadata,
        },
    }

    if vulnerabilities:
        payload["container_metadata"]["vulnerabilities"] = vulnerabilities

    # Send request
    print(f"Ingesting container: {registry}/{repository}:{tag}")
    response = requests.post(
        f"{api_url}/api/v1/ingest",
        json=payload,
        headers={"Content-Type": "application/json"},
    )

    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser(description="Ingest container artifact to TwinOps")
    parser.add_argument("--image", required=True, help="Image name with tag (e.g., myorg/api:v1.0.0)")
    parser.add_argument("--registry", required=True, help="Registry URL (e.g., gcr.io)")
    parser.add_argument("--scan-results", help="Path to Trivy scan results JSON")
    parser.add_argument("--sbom", help="Path to SBOM JSON (SPDX or CycloneDX)")
    parser.add_argument("--api-url", default="http://localhost:8000", help="TwinOps API URL")
    parser.add_argument("--tags", help="Comma-separated tags")
    parser.add_argument("--s3-bucket", help="S3 bucket for SBOM storage")

    args = parser.parse_args()

    # Load scan results
    scan_results = None
    if args.scan_results:
        scan_results = load_json_file(args.scan_results)
        if scan_results is None:
            sys.exit(1)

    # Load SBOM
    sbom_data = None
    if args.sbom:
        sbom_data = load_json_file(args.sbom)
        if sbom_data is None:
            sys.exit(1)

    # Parse tags
    tags = args.tags.split(",") if args.tags else None

    # Storage config
    storage_config = None
    if args.s3_bucket:
        storage_config = {"backend": "s3", "bucket": args.s3_bucket}

    # Ingest
    try:
        result = ingest_container(
            image_name=args.image,
            registry=args.registry,
            scan_results=scan_results,
            sbom_data=sbom_data,
            api_url=args.api_url,
            storage_config=storage_config,
            tags=tags,
        )

        print("\nIngestion successful!")
        print(f"Task ID: {result['task_id']}")
        print(f"Workflow ID: {result['workflow_id']}")
        print(f"Status: {result['status']}")

        # Poll for completion
        print("\nPolling for completion...")
        import time

        for i in range(30):
            time.sleep(2)
            status_response = requests.get(f"{args.api_url}/api/v1/ingest/{result['task_id']}")
            status_response.raise_for_status()
            status = status_response.json()

            print(f"Status: {status['status']}")

            if status["status"] == "completed":
                print(f"\nDocument ID: {status['document_id']}")
                break
            elif status["status"] == "failed":
                print(f"\nError: {status.get('error')}")
                sys.exit(1)

    except requests.exceptions.RequestException as e:
        print(f"Error: API request failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
