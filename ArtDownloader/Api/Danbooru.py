from base64 import b64encode
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Any
from urllib.parse import urlsplit
from ArtDownloader.Api.Errors import ApiError, AuthError
from ArtDownloader.Api.Http import MAX_RETRY_DELAY, RateLimiter, SessionPool, retry_delay
from ArtDownloader.Api.Models import (
    MediaItem, SessionCheck, SessionStatus, TagSuggestion, TypedTag, positive_int, seconds_of, text_of
)
from ArtDownloader.Api.Sites import Site
from ArtDownloader.Api.Transfer import download_media
from ArtDownloader.Auth.CredentialStore import CredentialStore, UserApiCredentials
import requests


BASE_URL: str = 'https://danbooru.donmai.us'
REQUEST_INTERVAL: float = 1.1
MAX_RETRIES: int = 3
TAG_CATEGORIES: tuple[str, ...] = ('general', 'artist', 'copyright', 'character', 'meta')


class DanbooruApi:
    """Danbooru JSON API with optional username/key authentication."""

    def __init__(
        self,
        credential_store: CredentialStore | None = None,
        page_size: int = 100,
        request_interval: float = REQUEST_INTERVAL
    ) -> None:
        self.site: Site = Site.DANBOORU
        self.credential_store: CredentialStore | None = credential_store
        self.credentials: UserApiCredentials | None = None
        self.page_size: int = min(max(page_size, 1), 200)
        self.page: int = 1
        self.cursor: str = ''
        self.cursor_order: str = 'descending'
        self.query: str = ''
        self.exhausted: bool = False
        self.previous_ids: tuple[str, ...] = ()
        self.sessions: SessionPool = SessionPool()
        self.limiter: RateLimiter = RateLimiter(request_interval)
        self.cancelled: Event = Event()
        self.closed: Event = Event()


    @property
    def is_authorized(self) -> bool:
        return self.credentials is not None


    @property
    def account_name(self) -> str:
        return self.credentials.username if self.credentials is not None else ''


    def remembered_identifier(self) -> str:
        if self.credential_store is None:
            return ''
        return self.credential_store.remembered_identifier(self.site.value)


    def validate_login(self, identifier: str, secret: str) -> None:
        if not identifier.strip() or any(character.isspace() or character == ':' for character in identifier.strip()):
            raise AuthError('Enter your Danbooru username, as shown on your profile')
        if not secret.strip() or not secret.strip().isascii() or any(character.isspace() for character in secret.strip()):
            raise AuthError('Copy the API key from your Danbooru profile')


    def login(self, identifier: str, secret: str) -> str:
        self.validate_login(identifier, secret)
        credentials: UserApiCredentials = self.verify_credentials(
            UserApiCredentials(identifier.strip(), secret.strip())
        )
        if self.credential_store is not None:
            try:
                self.credential_store.save_user_key(self.site.value, credentials)
            except OSError:
                raise ApiError('Could not save the key locally; check folder permissions') from None
        self.credentials = credentials
        return credentials.username


    def verify_credentials(self, credentials: UserApiCredentials) -> UserApiCredentials:
        data: Any = self.request_json('/profile.json', {}, credentials=credentials)
        if not isinstance(data, dict):
            raise ApiError('Danbooru returned an invalid account profile')
        user_id: int = positive_int(data.get('id'))
        username: str = text_of(data.get('name'))
        if not user_id or not username:
            raise ApiError('Danbooru returned an invalid account profile')
        return UserApiCredentials(username, credentials.api_key, user_id)


    def logout(self) -> None:
        if self.credential_store is not None:
            self.credential_store.clear(self.site.value)
        self.credentials = None


    def restore_session(self) -> SessionCheck:
        if self.credential_store is None:
            return SessionCheck(SessionStatus.NONE)
        self.credentials = self.credential_store.load_user_key(self.site.value)
        if self.credentials is None:
            return SessionCheck(SessionStatus.NONE)
        try:
            self.credentials = self.verify_credentials(self.credentials)
        except AuthError as error:
            try:
                self.logout()
            except OSError:
                self.credentials = None
            return SessionCheck(SessionStatus.INVALID, error=str(error))
        except ApiError as error:
            return SessionCheck(SessionStatus.UNREACHABLE, error=str(error))
        return SessionCheck(SessionStatus.VALID, username=self.account_name)


    def prepare_download(self) -> None:
        self.cancelled.clear()


    def cancel_pending(self) -> None:
        self.cancelled.set()


    def close(self) -> None:
        self.closed.set()
        self.cancel_pending()
        self.sessions.close()


    def search(self, tags: str) -> list[MediaItem]:
        self.query = tags
        self.page = 1
        self.cursor = ''
        self.previous_ids = ()
        self.exhausted = False
        orders: list[str] = [tag.lower() for tag in tags.split() if tag.lower().startswith('ord')]
        if not orders or orders == ['order:id_desc']:
            self.cursor_order = 'descending'
        elif orders in (['order:id'], ['order:id_asc']):
            self.cursor_order = 'ascending'
        else:
            self.cursor_order = ''
        return self.load_page()


    def next_page(self) -> list[MediaItem]:
        return [] if self.exhausted else self.load_page()


    def load_page(self) -> list[MediaItem]:
        data: Any = self.request_json('/posts.json', {
            'tags': self.query, 'limit': str(self.page_size), 'page': self.cursor or str(self.page)
        }, cancelled=self.cancelled)
        if not isinstance(data, list):
            raise ApiError('Danbooru returned an unexpected search response')
        items: list[MediaItem] = []
        for row in data:
            if not isinstance(row, dict):
                raise ApiError('Danbooru returned an invalid post')
            items.append(media_from_post(row))
        ids: tuple[str, ...] = tuple(item.id for item in items)
        if ids and ids == self.previous_ids:
            raise ApiError('Danbooru repeated the previous page; narrow the search and try again')
        self.previous_ids = ids
        self.exhausted = len(data) < self.page_size
        if ids and self.cursor_order:
            numbers: list[int] = [int(value) for value in ids]
            self.cursor = f'b{min(numbers)}' if self.cursor_order == 'descending' else f'a{max(numbers)}'
        self.page += 1
        return items


    def autocomplete(self, term: str, cancelled: Event | None = None) -> list[TagSuggestion]:
        if not term.strip():
            return []
        try:
            data: Any = self.request_json('/tags.json', {
                'search[name_matches]': f'{term.strip()}*', 'search[order]': 'count', 'limit': '10'
            }, cancelled=cancelled)
        except ApiError:
            return []
        if not isinstance(data, list):
            return []
        suggestions: list[TagSuggestion] = []
        for row in data:
            if isinstance(row, dict):
                suggestion: TagSuggestion | None = TagSuggestion.from_row(row)
                if suggestion is not None:
                    suggestions.append(suggestion)
        return suggestions


    def autocomplete_users(self, term: str) -> list[str]:
        if not term.strip():
            return []
        try:
            data: Any = self.request_json('/users.json', {
                'search[name_matches]': f'{term.strip()}*', 'search[order]': 'name', 'limit': '10'
            })
        except ApiError:
            return []
        if not isinstance(data, list):
            return []
        return [row['name'] for row in data if isinstance(row, dict) and isinstance(row.get('name'), str)]


    def post_tags(self, post_id: str) -> list[TypedTag]:
        # Search responses include every tag category.
        return []


    def resolve_file_url(self, item: MediaItem) -> str:
        if item.file_url:
            return item.file_url
        raise ApiError(f'Danbooru does not make post {item.id} downloadable for this account')


    def download_file(
        self,
        url: str,
        destination: Path,
        should_abort: Callable[[], bool] | None = None,
        on_progress: Callable[[int, int | None], None] | None = None
    ) -> bool:
        return download_media(self.sessions.current(), url, destination, should_abort, on_progress)


    def request_json(
        self,
        path: str,
        params: dict[str, str],
        credentials: UserApiCredentials | None = None,
        cancelled: Event | None = None
    ) -> Any:
        if path not in ('/profile.json', '/posts.json', '/tags.json', '/users.json'):
            raise ValueError('Credentials may only be sent to supported Danbooru API endpoints')
        key: UserApiCredentials | None = credentials if credentials is not None else self.credentials
        headers: dict[str, str] = {'Accept': 'application/json', 'User-Agent': 'ArtDownloaderCLI/1.0'}
        if key is not None:
            token: str = b64encode(f'{key.username}:{key.api_key}'.encode('utf-8')).decode('ascii')
            headers['Authorization'] = f'Basic {token}'
            identity: str = f'user #{key.user_id}' if key.user_id else f'user {key.username}'
            headers['User-Agent'] += f' ({identity})'
        for attempt in range(MAX_RETRIES + 1):
            self.limiter.wait(cancelled if cancelled is not None else self.closed)
            try:
                response: requests.Response = self.sessions.current().get(
                    f'{BASE_URL}{path}', params=params, headers=headers, timeout=30, allow_redirects=False
                )
            except requests.RequestException:
                raise ApiError('Cannot reach Danbooru; check your connection and retry') from None
            with response:
                if (
                    response.headers.get('cf-mitigated') == 'challenge'
                    or 'text/html' in response.headers.get('Content-Type', '').lower()
                ):
                    raise ApiError('Danbooru returned a web page or browser challenge; try again later')
                if response.status_code == 429:
                    delay: float = retry_delay(response.headers.get('Retry-After'), attempt)
                    if attempt == MAX_RETRIES or delay > MAX_RETRY_DELAY:
                        raise ApiError('Danbooru is rate limiting requests; wait before trying again')
                    self.limiter.defer(delay)
                    continue
                if response.status_code == 401:
                    raise AuthError('Danbooru rejected the username or API key; check both on your profile')
                if response.status_code == 403:
                    raise ApiError(
                        'Danbooru denied access. Check the website for an account verification request, '
                        'and check your API key permissions.'
                    )
                if response.status_code == 410:
                    raise ApiError('Danbooru reached its page limit; use newest sorting or narrow the search')
                if response.status_code in (400, 422):
                    raise ApiError('Danbooru rejected the search; check the tags and your account search limits')
                if response.status_code != 200:
                    raise ApiError(f'Danbooru returned HTTP {response.status_code}; try again later')
                try:
                    data: Any = response.json()
                except ValueError:
                    raise ApiError('Danbooru returned unreadable data; try again later') from None
                if isinstance(data, dict) and data.get('success') is False:
                    raise ApiError('Danbooru could not complete the request; check your search and key permissions')
                return data
        raise ApiError('Danbooru is temporarily unavailable')


def media_from_post(post: dict[str, Any]) -> MediaItem:
    post_id: int = positive_int(post.get('id'))
    if not post_id:
        raise ApiError('Danbooru returned a post without a valid ID')
    url: str = text_of(post.get('file_url'))
    if url:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ApiError('Danbooru returned an invalid media URL')
    extension: str = text_of(post.get('file_ext')).lower()
    if not extension.isascii() or not extension.isalnum() or len(extension) > 8:
        extension = 'bin'
    typed: list[TypedTag] = [
        TypedTag(name.replace('_', ' '), category)
        for category in TAG_CATEGORIES for name in text_of(post.get(f'tag_string_{category}')).split()
    ]
    created_at: int = 0
    try:
        created_at = int(datetime.fromisoformat(text_of(post.get('created_at')).replace('Z', '+00:00')).timestamp())
    except (ValueError, OverflowError, OSError):
        pass
    asset: Any = post.get('media_asset')
    duration: float = seconds_of(asset.get('duration')) if isinstance(asset, dict) else 0.0
    return MediaItem(
        id=str(post_id),
        file_url=url or None,
        file_format=extension,
        tags=[tag.replace('_', ' ') for tag in text_of(post.get('tag_string')).split()],
        file_size=positive_int(post.get('file_size')),
        rating=text_of(post.get('rating')),
        width=positive_int(post.get('image_width')),
        height=positive_int(post.get('image_height')),
        created_at=created_at,
        md5=text_of(post.get('md5')),
        source=text_of(post.get('source')),
        duration=duration,
        typed_tags=typed
    )
