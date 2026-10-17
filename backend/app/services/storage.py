"""Artifact storage management service for generated MCP servers."""

import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any, Optional
import uuid
import zipfile

# Default base directory for storing generated packages and zip archives
DEFAULT_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "storage" / "artifacts"


class ArtifactStorageService:
    """Manages storage isolation, metadata persistence, ZIP archiving, and expiration for generated servers."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self.storage_dir = Path(
            os.environ.get("GENERATOR_STORAGE_DIR", str(storage_dir or DEFAULT_STORAGE_DIR))
        ).resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def validate_generation_id(self, generation_id: str) -> str:
        """Validate generation ID format to strictly prevent path traversal attacks."""
        if not generation_id or not re.match(r"^[0-9a-fA-F-]{36}$", generation_id):
            raise ValueError(
                f"Invalid generation_id '{generation_id}': must be a valid 36-character UUID string."
            )
        return generation_id

    def create_generation_dir(self, package_name: str) -> tuple[str, Path]:
        """Create a dedicated, isolated directory for a new generation request."""
        generation_id = str(uuid.uuid4())
        gen_dir = self.storage_dir / generation_id
        package_dir = gen_dir / package_name
        package_dir.mkdir(parents=True, exist_ok=True)
        return generation_id, package_dir

    def get_generation_dir(self, generation_id: str) -> Optional[Path]:
        """Resolve and verify directory for a validated generation ID."""
        validated_id = self.validate_generation_id(generation_id)
        gen_dir = (self.storage_dir / validated_id).resolve()
        if not gen_dir.exists() or not gen_dir.is_dir():
            return None
        # Safety check: must remain inside storage root
        if not gen_dir.is_relative_to(self.storage_dir):
            return None
        return gen_dir

    def save_metadata(self, generation_id: str, metadata: dict[str, Any]) -> None:
        """Persist generation metadata JSON safely inside generation folder."""
        gen_dir = self.get_generation_dir(generation_id)
        if not gen_dir:
            raise FileNotFoundError(f"Generation directory not found: {generation_id}")
        meta_file = gen_dir / "metadata.json"
        meta_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def get_metadata(self, generation_id: str) -> Optional[dict[str, Any]]:
        """Retrieve stored metadata for a generation ID."""
        gen_dir = self.get_generation_dir(generation_id)
        if not gen_dir:
            return None
        meta_file = gen_dir / "metadata.json"
        if not meta_file.exists():
            return None
        try:
            return json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def create_zip_archive(self, generation_id: str, package_name: str) -> Path:
        """Package generated server folder into a secure ZIP archive."""
        gen_dir = self.get_generation_dir(generation_id)
        if not gen_dir:
            raise FileNotFoundError(f"Generation directory not found: {generation_id}")

        package_dir = (gen_dir / package_name).resolve()
        if not package_dir.exists() or not package_dir.is_dir():
            raise FileNotFoundError(f"Package directory not found: {package_dir}")

        zip_path = (gen_dir / f"{package_name}.zip").resolve()

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(package_dir):
                root_path = Path(root)
                for file_name in files:
                    file_path = (root_path / file_name).resolve()
                    # Ensure each file is inside package_dir
                    if not file_path.is_relative_to(package_dir):
                        continue
                    arcname = file_path.relative_to(package_dir)
                    zf.write(file_path, arcname)

        return zip_path

    def get_zip_path(self, generation_id: str) -> Optional[tuple[Path, str]]:
        """Return (zip_path, download_filename) if archive exists and is valid."""
        meta = self.get_metadata(generation_id)
        if not meta:
            return None
        package_name = meta.get("package_name")
        if not package_name:
            return None

        gen_dir = self.get_generation_dir(generation_id)
        if not gen_dir:
            return None

        zip_path = (gen_dir / f"{package_name}.zip").resolve()
        if not zip_path.exists() or not zip_path.is_file():
            return None

        # Verify path containment
        if not zip_path.is_relative_to(self.storage_dir):
            return None

        return zip_path, f"{package_name}.zip"

    def cleanup_expired(self, max_age_seconds: int = 3600) -> int:
        """Remove artifact directories older than max_age_seconds. Returns count cleaned."""
        now = time.time()
        deleted_count = 0
        if not self.storage_dir.exists():
            return 0

        for item in self.storage_dir.iterdir():
            if item.is_dir():
                try:
                    mtime = item.stat().st_mtime
                    if now - mtime > max_age_seconds:
                        shutil.rmtree(item, ignore_errors=True)
                        deleted_count += 1
                except Exception:
                    pass

        return deleted_count


# Global singleton storage service
storage_service = ArtifactStorageService()
