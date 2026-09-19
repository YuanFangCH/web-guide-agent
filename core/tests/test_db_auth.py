from app import db
from app.db import hash_password, verify_password


def test_password_hash_round_trip() -> None:
    password_hash, salt = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", password_hash, salt)
    assert not verify_password("wrong password", password_hash, salt)


def test_website_write_session_expiry_and_revocation(tmp_path, monkeypatch) -> None:
    class Settings:
        db_path = str(tmp_path / "write-sessions.db")

    monkeypatch.setattr(db, "settings", Settings())
    db.init_db()
    db.save_website_write_session(
        session_id="active",
        token="secret",
        scopes=["posts:write"],
        mode="draft-only",
        purpose="test",
        created_by="admin",
        created_at="2026-09-10T00:00:00+00:00",
        expires_at="2999-01-01T00:00:00+00:00",
    )
    assert db.get_active_website_write_session()["token"] == "secret"
    assert db.get_active_website_write_session("admin")["token"] == "secret"
    assert db.get_active_website_write_session("other") is None

    db.mark_website_write_session_revoked("active")
    assert db.get_active_website_write_session() is None
    assert db.list_website_write_sessions()[0]["token"] == ""


def test_account_sync_roles_and_last_owner_protection(tmp_path, monkeypatch) -> None:
    class Settings:
        db_path = str(tmp_path / "accounts.db")
        admin_username = "admin"
        admin_password = "owner-password"

    monkeypatch.setattr(db, "settings", Settings())
    db.init_db()
    db.ensure_admin()

    owner = db.get_user_account("admin")
    assert owner["role"] == "owner"

    member = db.sync_user_account(
        username="member01",
        display_name="Member 01",
        role="member",
        password="member-password",
    )
    assert member["role"] == "member"
    authenticated = db.authenticate("member01", "member-password")
    assert authenticated["role"] == "member"

    try:
        db.delete_user_account("admin")
    except ValueError as exc:
        assert str(exc) == "last_owner_required"
    else:
        raise AssertionError("last owner deletion should fail")

    try:
        db.sync_user_account(
            username="admin",
            display_name="Administrator",
            role="member",
        )
    except ValueError as exc:
        assert str(exc) == "last_owner_required"
    else:
        raise AssertionError("last owner demotion should fail")

    db.sync_user_account(
        username="member01",
        display_name="团队成员 01",
        role="owner",
    )
    assert db.get_user_account("member01")["role"] == "owner"

    db.save_website_write_session(
        session_id="expired",
        token="expired-secret",
        scopes=["posts:write"],
        mode="draft-only",
        purpose="expired",
        created_by="admin",
        created_at="2020-01-01T00:00:00+00:00",
        expires_at="2020-01-01T00:01:00+00:00",
    )
    assert db.get_active_website_write_session() is None
    assert db.list_website_write_sessions()[0]["token"] == ""
