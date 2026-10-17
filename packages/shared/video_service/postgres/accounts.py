"""Renewal accounts/sessions. No legacy account import and no automatic bootstrap."""
import hashlib
import hmac
import re
import secrets
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from ..auth import password_hash, verify_password, dummy_hash, LoginThrottled
from . import Conflict


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def csrf_for(token):
    return digest('renewal-csrf-v1:' + token)


def public(row):
    return {k: row[k] for k in ('id', 'username', 'role', 'active', 'created_at')}


class Accounts:
    def __init__(self, database):
        self.database = database

    def setup_required(self):
        with self.database.connection() as db:
            return not db.execute('SELECT 1 FROM accounts LIMIT 1').fetchone()

    def create(self, username, password, *, first=False, actor_id=None):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{2,63}', username):
            raise ValueError('아이디는 영문·숫자·._- 3~64자로 입력하세요.')
        # Derive outside the DB lock; competing bootstrap requests serialize below.
        encoded = password_hash(password)
        with self.database.connection() as db:
            db.execute('SELECT pg_advisory_xact_lock(764931003)')
            if first and db.execute('SELECT 1 FROM accounts LIMIT 1').fetchone():
                raise Conflict('관리자 계정이 이미 생성됐습니다.')
            if not first:
                actor = db.execute('SELECT role,active FROM accounts WHERE id=%s FOR SHARE', (actor_id,)).fetchone()
                if not actor or not actor['active'] or actor['role'] != 'admin':
                    raise PermissionError('관리자만 계정을 발급할 수 있습니다.')
            if db.execute('SELECT 1 FROM accounts WHERE lower(username)=lower(%s)', (username,)).fetchone():
                raise Conflict('이미 등록된 아이디입니다.')
            row = db.execute('INSERT INTO accounts(id,username,password_hash,role) VALUES (%s,%s,%s,%s) RETURNING *',
                             (uuid4().hex, username, encoded, 'admin' if first else 'user')).fetchone()
            return public(row)

    def throttle(self, address):
        bucket = digest(address)
        now = datetime.now(timezone.utc)
        retry = 0
        with self.database.connection() as db:
            db.execute('SELECT pg_advisory_xact_lock(764931004)')
            db.execute('DELETE FROM login_limits WHERE expires_at <= now()')
            row = db.execute('SELECT * FROM login_limits WHERE bucket=%s FOR UPDATE', (bucket,)).fetchone()
            if row and row['attempts'] >= 20:
                retry = max(1, int((row['expires_at'] - now).total_seconds()) + 1)
            elif row:
                db.execute('UPDATE login_limits SET attempts=attempts+1 WHERE bucket=%s', (bucket,))
            else:
                db.execute('INSERT INTO login_limits VALUES (%s,1,%s)', (bucket, now + timedelta(minutes=15)))
        if retry:
            raise LoginThrottled(retry)

    def login(self, username, password, address):
        self.throttle(address)
        with self.database.connection() as db:
            row = db.execute('SELECT * FROM accounts WHERE lower(username)=lower(%s) AND active', (username,)).fetchone()
        encoded = row['password_hash'] if row else dummy_hash()
        valid = verify_password(password, encoded)
        if not valid or row is None:
            return None
        token = secrets.token_urlsafe(32)
        csrf = csrf_for(token)
        expires = datetime.now(timezone.utc) + timedelta(hours=8)
        with self.database.connection() as db:
            current = db.execute('SELECT * FROM accounts WHERE id=%s AND active FOR UPDATE', (row['id'],)).fetchone()
            if not current or current['password_hash'] != encoded:
                return None
            db.execute('DELETE FROM sessions WHERE expires_at <= now()')
            db.execute('INSERT INTO sessions(token_hash,account_id,csrf_hash,expires_at) VALUES (%s,%s,%s,%s)',
                       (digest(token), row['id'], digest(csrf), expires))
            db.execute('DELETE FROM sessions WHERE token_hash IN (SELECT token_hash FROM sessions WHERE account_id=%s ORDER BY expires_at DESC OFFSET 20)', (row['id'],))
        return {'token': token, 'user': public(row), 'csrf_token': csrf, 'expires_at': expires}

    def session(self, token):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return None
        with self.database.connection() as db:
            row = db.execute('SELECT a.*,s.csrf_hash FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE s.token_hash=%s AND s.expires_at>now() AND a.active', (digest(token),)).fetchone()
        if not row or not hmac.compare_digest(row['csrf_hash'], digest(csrf_for(token))):
            return None
        return {'user': public(row), 'csrf_token': csrf_for(token)}

    def logout(self, token):
        with self.database.connection() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=%s', (digest(token),))

    def list(self):
        with self.database.connection() as db:
            return [public(row) for row in db.execute('SELECT * FROM accounts ORDER BY created_at,id')]
