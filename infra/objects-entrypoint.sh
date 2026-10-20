#!/bin/sh
set -eu
IFS= read -r MINIO_ROOT_USER < /run/bootstrap/objects-user
IFS= read -r MINIO_ROOT_PASSWORD < /run/bootstrap/objects-password
export MINIO_ROOT_USER MINIO_ROOT_PASSWORD
exec /usr/local/bin/minio server --address :9000 --console-address 127.0.0.1:9001 --certs-dir /run/bootstrap /data
