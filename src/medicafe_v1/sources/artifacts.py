import hashlib
import os
import tempfile
from pathlib import Path

from django.conf import settings

from .domain import CommandError


class LocalArtifactStore:
    def __init__(self, root=None):
        self.root = Path(root or settings.ARTIFACT_ROOT).resolve()

    @staticmethod
    def storage_key(organization_id, digest):
        return f"{organization_id}/{digest[:2]}/{digest}"

    def put(self, organization_id, content):
        digest = hashlib.sha256(content).hexdigest()
        key = self.storage_key(organization_id, digest)
        destination = self.root / Path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            self._verify_path(destination, digest, len(content))
            return digest, key
        staging = self.root / ".staging"
        staging.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="admit-", dir=staging)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.replace(temporary, destination)
            except FileExistsError:
                Path(temporary).unlink(missing_ok=True)
            self._verify_path(destination, digest, len(content))
        finally:
            Path(temporary).unlink(missing_ok=True)
        return digest, key

    def read_verified(self, artifact):
        path = self.root / Path(artifact.storage_key)
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise CommandError("artifact_unavailable") from exc
        if hashlib.sha256(content).hexdigest() != artifact.sha256 or len(content) != artifact.byte_length:
            raise CommandError("artifact_unavailable")
        return content

    @staticmethod
    def _verify_path(path, digest, byte_length):
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise CommandError("artifact_promotion_failed") from exc
        if hashlib.sha256(content).hexdigest() != digest or len(content) != byte_length:
            raise CommandError("artifact_digest_conflict")

