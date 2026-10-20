from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
import json
import os
import threading


@dataclass
class Tokens:
    access: str
    refresh: str
    username: str


@dataclass(frozen=True)
class ApiCredentials:
    user_id: str
    api_key: str


@dataclass(frozen=True)
class UserApiCredentials:
    username: str
    api_key: str
    user_id: int = 0


class CredentialStore:
    """Persists the session between runs: tokens plus the user name.

    Passwords are never stored. Signing out drops the tokens but remembers the
    name, so the next sign-in form can be prefilled.
    """

    def __init__(self, path: Path) -> None:
        self.path: Path = path
        # Each site tab reads and rewrites the same file from its own thread.
        self.lock: threading.Lock = threading.Lock()


    def load(self, site: str) -> Tokens | None:
        entry = self.read_all().get(site)
        if not isinstance(entry, dict):
            return None

        access = entry.get('access')
        if not isinstance(access, str) or not access:
            return None

        refresh = entry.get('refresh')
        username = entry.get('username')

        return Tokens(
            access=access,
            refresh=refresh if isinstance(refresh, str) else '',
            username=username if isinstance(username, str) else ''
        )


    def save(self, site: str, tokens: Tokens) -> None:
        with self.lock:
            data = self.read_all()
            data[site] = asdict(tokens)
            self.write_all(data)


    def load_key(self, site: str) -> ApiCredentials | None:
        entry: Any = self.read_all().get(site)
        if not isinstance(entry, dict):
            return None
        user_id: Any = entry.get('user_id')
        api_key: Any = entry.get('api_key')
        if not isinstance(user_id, str) or not user_id.isascii() or not user_id.isdigit():
            return None
        if not isinstance(api_key, str) or not api_key:
            return None
        return ApiCredentials(user_id, api_key)


    def save_key(self, site: str, credentials: ApiCredentials) -> None:
        with self.lock:
            data: dict[str, Any] = self.read_all()
            data[site] = asdict(credentials)
            self.write_all(data)


    def load_user_key(self, site: str) -> UserApiCredentials | None:
        entry: Any = self.read_all().get(site)
        if not isinstance(entry, dict):
            return None
        username: Any = entry.get('username')
        api_key: Any = entry.get('api_key')
        user_id: Any = entry.get('user_id')
        if not isinstance(username, str) or not username or not isinstance(api_key, str) or not api_key:
            return None
        return UserApiCredentials(
            username, api_key,
            user_id if isinstance(user_id, int) and not isinstance(user_id, bool) and user_id > 0 else 0
        )


    def save_user_key(self, site: str, credentials: UserApiCredentials) -> None:
        with self.lock:
            data: dict[str, Any] = self.read_all()
            data[site] = asdict(credentials)
            self.write_all(data)


    def clear(self, site: str) -> None:
        """Drops the site's tokens, keeping the remembered user name."""
        with self.lock:
            data = self.read_all()
            entry = data.get(site)
            if entry is None:
                return

            field: str = (
                'user_id' if isinstance(entry, dict) and 'user_id' in entry and 'username' not in entry else 'username'
            )
            username = entry.get(field) if isinstance(entry, dict) else None
            if isinstance(username, str) and username:
                data[site] = {field: username}
            else:
                del data[site]

            self.write_all(data)


    def remembered_identifier(self, site: str) -> str:
        entry = self.read_all().get(site)
        username = (entry.get('username') or entry.get('user_id')) if isinstance(entry, dict) else None

        return username if isinstance(username, str) else ''


    def read_all(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}

        try:
            with self.path.open('r', encoding='utf-8') as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return {}

        if not isinstance(data, dict):
            return {}

        return data


    def write_all(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=self.path.parent,
                prefix='.session-', suffix='.tmp', delete=False
            ) as file:
                temporary = Path(file.name)
                json.dump(data, file, indent=4)
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
