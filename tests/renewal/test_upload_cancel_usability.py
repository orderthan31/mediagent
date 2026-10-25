from app.renewal import create_app
from fastapi.testclient import TestClient
from test_execution import admin as _admin
from test_execution import db as _db
from video_service.content_store import ContentStore

admin, db = _admin, _db


def test_upload_cancel_preserves_session_and_parts_and_refuses_resume(
    db, admin, tmp_path
):
    app = create_app(
        db,
        allowed_origins=["https://testserver"],
        secure_cookies=False,
        content_store=ContentStore(tmp_path),
    )
    with TestClient(app, base_url="https://testserver") as c:
        login = c.post(
            "/api/auth/login",
            headers={"Origin": "https://testserver"},
            json={"username": admin[0]["username"], "password": admin[1]},
        )
        assert login.status_code == 200
        headers = {
            "Origin": "https://testserver",
            "X-CSRF-Token": login.json()["csrf_token"],
            "Content-Type": "application/json",
        }
        u = c.post(
            "/api/video-uploads",
            headers=headers,
            json={
                "filename": "owned-cancel-test.mov",
                "size": 8,
                "request_id": "cancel-proof",
            },
        ).json()
        base = "/api/video-uploads/" + u["upload_id"]
        assert (
            c.put(
                base + "/chunks?offset=0",
                headers={**headers, "Content-Type": "application/octet-stream"},
                content=b"abcd",
            ).status_code
            == 200
        )
        deleted = c.delete(base, headers=headers)
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "CANCELLED"
        assert c.get(base).json()["uploaded_bytes"] == 4
        assert c.delete(base, headers=headers).status_code == 200
        assert (
            c.put(
                base + "/chunks?offset=4",
                headers={**headers, "Content-Type": "application/octet-stream"},
                content=b"efgh",
            ).status_code
            == 409
        )
        with db.connection() as conn:
            assert (
                conn.execute(
                    "SELECT count(*)AS n FROM source_upload_parts WHERE upload_id=%s",
                    (u["upload_id"],),
                ).fetchone()["n"]
                == 1
            )
