"""Explicit S3-compatible CAS. No bucket creation, listing, deletion or URL grants.

A private local cache is disposable process workspace, never shared authority.
Every read verifies remote bytes; ETag is deliberately not treated as SHA-256.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
from urllib.parse import urlsplit

from .content_store import (
    HEX,
    ID,
    MAX_CONTENT,
    ContentStore,
    reference_origin,
    valid_content_key,
)


class ObjectStoreError(ValueError):
    pass


class AttemptUnknown(ObjectStoreError):
    pass


def validate_reference(reference):
    if not isinstance(reference, dict) or set(reference) != {
        "storage_key",
        "sha256",
        "bytes",
        "type",
    }:
        raise ObjectStoreError("Invalid artifact reference")
    if not isinstance(reference["sha256"], str) or not HEX.fullmatch(
        reference["sha256"]
    ):
        raise ObjectStoreError("Invalid artifact digest")
    if not valid_content_key(reference["storage_key"], reference["sha256"]):
        raise ObjectStoreError("Invalid artifact key")
    if type(reference["bytes"]) is not int or not 0 < reference["bytes"] <= MAX_CONTENT:
        raise ObjectStoreError("Invalid artifact size")
    if not isinstance(reference["type"], str) or not re.fullmatch(
        "[a-z_]{1,50}", reference["type"]
    ):
        raise ObjectStoreError("Invalid artifact type")


class S3ContentStore(ContentStore):
    storage_kind = "s3"

    def __init__(self, client, bucket, cache_root, *, prefix):
        super().__init__(cache_root)
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise ObjectStoreError("Explicit bucket required")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", prefix):
            raise ObjectStoreError("Explicit isolated prefix required")
        self.client, self.bucket, self.prefix = client, bucket, prefix

    def _key(self, owner, relative):
        if not isinstance(owner, str) or not ID.fullmatch(owner):
            raise ObjectStoreError("Invalid owner")
        return self.prefix + "/" + owner + "/" + relative

    def _create(self, key, body, sha, size):
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentLength=size,
                ContentType="application/octet-stream",
                IfNoneMatch="*",
                ChecksumSHA256=base64.b64encode(bytes.fromhex(sha)).decode(),
                Metadata={"sha256": sha, "bytes": str(size)},
            )
            return True
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 412:
                return False
            raise ObjectStoreError(
                "Object write failed; outcome may be unknown"
            ) from None
        except BotoCoreError:
            raise ObjectStoreError(
                "Object write failed; outcome may be unknown"
            ) from None

    def _download(self, key, limit, destination):
        from botocore.exceptions import BotoCoreError, ClientError

        body = None
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            if not 0 < response["ContentLength"] <= limit:
                raise ObjectStoreError("Remote size exceeded")
            digest, size = hashlib.sha256(), 0
            while block := body.read(1024 * 1024):
                size += len(block)
                if size > limit:
                    raise ObjectStoreError("Remote size exceeded")
                digest.update(block)
                destination.write(block)
            if size != response["ContentLength"]:
                raise ObjectStoreError("Remote object truncated")
            return digest.hexdigest(), size
        except (BotoCoreError, ClientError, OSError):
            raise ObjectStoreError("Object unavailable or transfer failed") from None
        finally:
            if body is not None:
                body.close()

    def path(self, owner, reference):
        try:
            owner, reference = reference_origin(owner, reference)
        except ValueError as exc:
            raise ObjectStoreError("Invalid input origin/reference") from exc
        validate_reference(reference)
        key = self._key(owner, reference["storage_key"])
        with tempfile.TemporaryFile(dir=self.owner_root(owner)) as stream:
            sha, size = self._download(key, reference["bytes"], stream)
            if sha != reference["sha256"] or size != reference["bytes"]:
                raise ObjectStoreError("Remote content integrity mismatch")
            stream.seek(0)
            stored = ContentStore.put(
                self,
                owner,
                iter(lambda: stream.read(1024 * 1024), b""),
                reference["type"],
            )
        # ContentStore.put validates its local path without calling this override.
        if any(stored[k] != reference[k] for k in ("sha256", "bytes", "type")):
            raise ObjectStoreError("Remote content reference mismatch")
        return ContentStore.path(self, owner, stored)

    def bind_ticket(self, owner, key, reference):
        if (not isinstance(reference, dict) or not valid_content_key(key, reference.get("sha256"))
                or not key.startswith("tickets/")):
            raise ObjectStoreError("Invalid ticket content key")
        source = self.path(owner, reference)
        with source.open("rb") as body:
            self._create(self._key(owner, key), body, reference["sha256"], reference["bytes"])
        value = {k: reference[k] for k in ("sha256", "bytes", "type")}
        value["storage_key"] = key
        self.path(owner, value)
        return value

    def put(self, owner, blocks, kind):
        reference = ContentStore.put(self, owner, blocks, kind)
        validate_reference(reference)
        path = ContentStore.path(self, owner, reference)
        with path.open("rb") as body:
            self._create(
                self._key(owner, reference["storage_key"]),
                body,
                reference["sha256"],
                reference["bytes"],
            )
        self.path(owner, reference)
        return reference

    def claim_attempt(self, owner, command):
        from .cpu_agents import canonical, digest

        attempt = command.get("attempt_id")
        if not isinstance(attempt, str) or not ID.fullmatch(attempt):
            raise ObjectStoreError("Invalid attempt identity")
        raw = canonical({"request_sha256": digest(command)})
        key = self._key(owner, "attempts/" + attempt + "/claim.json")
        if self._create(key, raw, hashlib.sha256(raw).hexdigest(), len(raw)):
            return None
        previous = self._attempt_json(owner, attempt, "claim.json")
        if previous != {"request_sha256": digest(command)}:
            raise ObjectStoreError("Attempt identity collision")
        try:
            result = self._attempt_json(owner, attempt, "result.json")
        except ObjectStoreError:
            raise AttemptUnknown(
                "Attempt reserved without confirmed result; automatic replay denied"
            ) from None
        if result.get("request_sha256") != digest(command):
            raise ObjectStoreError("Attempt receipt differs")
        return result

    def _attempt_json(self, owner, attempt, name):
        import io

        stream = io.BytesIO()
        self._download(
            self._key(owner, "attempts/" + attempt + "/" + name), 65536, stream
        )
        try:
            result = json.loads(stream.getvalue())
        except ValueError:
            raise ObjectStoreError("Invalid attempt receipt") from None
        if not isinstance(result, dict):
            raise ObjectStoreError("Invalid attempt receipt")
        return result

    def finish_attempt(self, owner, command, result):
        from .cpu_agents import canonical

        raw = canonical(result)
        if len(raw) > 65536:
            raise ObjectStoreError("Attempt receipt too large")
        key = self._key(owner, "attempts/" + command["attempt_id"] + "/result.json")
        self._create(key, raw, hashlib.sha256(raw).hexdigest(), len(raw))
        if self._attempt_json(owner, command["attempt_id"], "result.json") != result:
            raise ObjectStoreError("Attempt receipt collision")


def from_config(config, *, environ=None):
    """Credentials come only from explicitly named process environment variables."""
    import boto3
    from botocore.config import Config

    environ = os.environ if environ is None else environ
    fields = {
        "endpoint",
        "bucket",
        "region",
        "prefix",
        "cache_root",
        "access_key_env",
        "secret_key_env",
    }
    if (
        not isinstance(config, dict)
        or not fields <= set(config)
        or set(config) - fields - {"ca_file"}
        or not all(isinstance(v, str) and v for v in config.values())
    ):
        raise ObjectStoreError("Invalid object store config")
    endpoint = urlsplit(config["endpoint"])
    if (
        endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
        or endpoint.path not in ("", "/")
    ):
        raise ObjectStoreError("Explicit plain endpoint required")
    if endpoint.scheme != "https" and not (
        endpoint.scheme == "http" and endpoint.hostname in ("127.0.0.1", "localhost")
    ):
        raise ObjectStoreError("TLS required outside loopback")
    if not endpoint.hostname:
        raise ObjectStoreError("Explicit endpoint required")
    keys = [environ.get(config[k]) for k in ("access_key_env", "secret_key_env")]
    if not all(keys):
        raise ObjectStoreError("Explicit credential environment missing")
    client = boto3.client(
        "s3",
        endpoint_url=config["endpoint"],
        verify=config.get("ca_file", True),
        region_name=config["region"],
        aws_access_key_id=keys[0],
        aws_secret_access_key=keys[1],
        config=Config(
            signature_version="s3v4",
            retries={"total_max_attempts": 1},
            connect_timeout=5,
            read_timeout=15,
            proxies={},
            s3={"addressing_style": "path"},
        ),
    )
    return S3ContentStore(
        client, config["bucket"], config["cache_root"], prefix=config["prefix"]
    )
