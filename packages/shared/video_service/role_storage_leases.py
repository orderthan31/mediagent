"""Trusted task-bound S3 leases; workers never receive the application's parent key."""

import json
from datetime import UTC, datetime

from .content_store import reference_origin
from .cpu_agents import digest


class RoleStorageLeases:
    def __init__(self, roles, role, *, issuer=None):
        if role not in {"transcription", "translation", "vocalization"}:
            raise ValueError("invalid_storage_role")
        self.roles, self.role, self.issuer = roles, role, issuer

    def grant(self, packet):
        if (
            type(packet) is not dict
            or set(packet) != {"task_id", "request_sha256", "kind"}
            or packet["kind"] not in {"result", "cancel_ack"}
        ):
            raise ValueError("invalid_storage_grant_request")
        runtime = self.roles.runtime
        with runtime.database.connection() as c:
            row = c.execute(
                "SELECT * FROM model_role_tasks WHERE task_id=%s", (packet["task_id"],)
            ).fetchone()
            if (
                not row
                or row["envelope"]["role"] != self.role
                or digest(row["envelope"]) != packet["request_sha256"]
            ):
                raise ValueError("storage_task_scope_mismatch")
            envelope = row["envelope"]
            if packet["kind"] == "result":
                if row["phase"] not in {"sending", "sent", "adopting"}:
                    raise ValueError("storage_task_not_active")
                command = c.execute(
                    "SELECT request FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                    (row["owner_id"], row["job_id"], row["attempt_id"]),
                ).fetchone()["request"]
                self.roles._current(c, row["owner_id"], command)
        source = runtime.store
        output = self.roles.result_stores.get(self.role, self.roles.results)
        if source.client.meta.endpoint_url != output.client.meta.endpoint_url:
            raise ValueError("storage_issuer_endpoint_mismatch")
        owner, ref = reference_origin(
            envelope["source"]["owner"], envelope["source"]["reference"]
        )
        statements = []
        if packet["kind"] == "result":
            statements.append(
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetObject"],
                    "Resource": [
                        "arn:aws:s3:::"
                        + source.bucket
                        + "/"
                        + source._key(owner, ref["storage_key"])
                    ],
                }
            )
        statements.append(
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject"],
                "Resource": [
                    "arn:aws:s3:::"
                    + output.bucket
                    + "/"
                    + output._key(envelope["output_owner"], "*")
                ],
            }
        )
        policy = {"Version": "2012-10-17", "Statement": statements}
        if self.issuer:
            credentials = self.issuer(policy)
        else:
            client = source.sts_client_factory()
            try:
                credentials = client.assume_role(
                    RoleArn="arn:aws:iam::000000000000:role/independent-" + self.role,
                    RoleSessionName="task-storage-" + packet["task_id"][:20],
                    DurationSeconds=900,
                    Policy=json.dumps(policy),
                )["Credentials"]
            finally:
                client.close()
        expiration = credentials["Expiration"]
        if (
            not isinstance(expiration, datetime)
            or expiration.tzinfo is None
            or (expiration - datetime.now(UTC)).total_seconds() < 60
        ):
            raise ValueError("storage_lease_not_fresh")
        return {
            "version": 1,
            "task_id": packet["task_id"],
            "request_sha256": packet["request_sha256"],
            "expires_at": expiration.isoformat(),
            "credentials": {
                "access_key_id": credentials["AccessKeyId"],
                "secret_access_key": credentials["SecretAccessKey"],
                "session_token": credentials["SessionToken"],
            },
        }
