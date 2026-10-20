from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any
from urllib.parse import parse_qs, urlparse
from ArtDownloader.Api.Errors import ApiError, AuthError, WebsiteSignInRequired
from ArtDownloader.Api.Http import MAX_RETRY_DELAY, RateLimiter, SessionPool, retry_delay
from ArtDownloader.Api.Models import MediaItem, SessionCheck, SessionStatus, TagSuggestion, TypedTag, text_of
from ArtDownloader.Api.Sites import Site
from ArtDownloader.Api.Transfer import download_media
from ArtDownloader.Auth.CredentialStore import ApiCredentials, CredentialStore
import requests


API_URL: str = 'https://api.rule34.xxx/index.php'
AUTOCOMPLETE_URL: str = 'https://api.rule34.xxx/autocomplete.php'
# Application pacing, not a guarantee about the server's current quota.
REQUEST_INTERVAL: float = 1.1
REQUEST_TIMEOUT: int = 30
MAX_RETRIES: int = 3
TAG_CATEGORIES: dict[int, str] = {
    0: 'general', 1: 'artist', 3: 'copyright', 4: 'character', 5: 'meta'
}
AUTH_FAILURES: tuple[str, ...] = (
    'missing authentication', 'invalid api key', 'invalid api_key', 'invalid authentication'
)


class Rule34Api:
    """Rule34's key-authenticated API, independent of Sankaku's protocol."""

    def __init__(
        self,
        credential_store: CredentialStore | None = None,
        page_size: int = 100,
        request_interval: float = REQUEST_INTERVAL
    ) -> None:
        self.site: Site = Site.RULE34
        self.credential_store: CredentialStore | None = credential_store
        self.credentials: ApiCredentials | None = None
        self.page_size: int = min(max(page_size, 1), 1000)
        self.page: int = 0
        self.query: str = ''
        self.exhausted: bool = False
        self.sessions: SessionPool = SessionPool()
        self.limiter: RateLimiter = RateLimiter(request_interval)
        self.cancelled: Event = Event()
        self.closed: Event = Event()


    @property
    def is_authorized(self) -> bool:
        return self.credentials is not None


    @property
    def account_name(self) -> str:
        return self.credentials.user_id if self.credentials is not None else ''


    def remembered_identifier(self) -> str:
        if self.credential_store is None:
            return ''
        return self.credential_store.remembered_identifier(self.site.value)


    def login(self, identifier: str, secret: str) -> str:
        credentials: ApiCredentials = credentials_from_input(identifier, secret)
        self.verify_credentials(credentials)
        if self.credential_store is not None:
            try:
                self.credential_store.save_key(self.site.value, credentials)
            except OSError:
                raise ApiError('Could not save the key locally; check folder permissions') from None
        self.credentials = credentials
        return credentials.user_id


    def logout(self) -> None:
        if self.credential_store is not None:
            self.credential_store.clear(self.site.value)
        self.credentials = None


    def validate_login(self, identifier: str, secret: str) -> None:
        credentials_from_input(identifier, secret)


    def restore_session(self) -> SessionCheck:
        if self.credential_store is None:
            return SessionCheck(SessionStatus.NONE)
        self.credentials = self.credential_store.load_key(self.site.value)
        if self.credentials is None:
            return SessionCheck(SessionStatus.NONE)
        try:
            self.verify_credentials(self.credentials)
        except AuthError as error:
            try:
                self.logout()
            except OSError:
                self.credentials = None
            return SessionCheck(SessionStatus.INVALID, error=str(error))
        except ApiError as error:
            return SessionCheck(SessionStatus.UNREACHABLE, error=str(error))
        return SessionCheck(SessionStatus.VALID, username=self.account_name)


    def verify_credentials(self, credentials: ApiCredentials) -> None:
        data: Any = self.request_json(
            API_URL,
            {'page': 'dapi', 's': 'post', 'q': 'index', 'json': '1', 'limit': '1', 'tags': 'rating:safe'},
            credentials=credentials
        )
        if not isinstance(data, list):
            raise ApiError('Rule34 returned an unexpected response while checking the key')


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
        self.page = 0
        self.exhausted = False
        return self.load_page()


    def next_page(self) -> list[MediaItem]:
        if self.exhausted:
            return []
        return self.load_page()


    def load_page(self) -> list[MediaItem]:
        data: Any = self.request_json(
            API_URL,
            {
                'page': 'dapi', 's': 'post', 'q': 'index', 'json': '1',
                'pid': str(self.page), 'limit': str(self.page_size),
                'tags': self.query, 'fields': 'tag_info'
            },
            cancelled=self.cancelled
        )
        if not isinstance(data, list):
            raise ApiError('Rule34 returned an unexpected search response')
        items: list[MediaItem] = []
        for row in data:
            if not isinstance(row, dict):
                raise ApiError('Rule34 returned an invalid post')
            items.append(media_from_post(row))
        self.exhausted = len(data) < self.page_size
        self.page += 1
        return items


    def autocomplete(self, term: str, cancelled: Event | None = None) -> list[TagSuggestion]:
        if not term.strip() or not self.is_authorized:
            return []
        try:
            data: Any = self.request_json(AUTOCOMPLETE_URL, {'q': term.strip()}, cancelled=cancelled)
        except ApiError:
            return []
        if not isinstance(data, list):
            return []
        suggestions: list[TagSuggestion] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            name: Any = row.get('value') or row.get('name')
            if isinstance(name, str) and name:
                suggestions.append(TagSuggestion(name))
        return suggestions


    def autocomplete_users(self, term: str) -> list[str]:
        return []


    def post_tags(self, post_id: str) -> list[TypedTag]:
        # Search carries tag_info when available; never issue a second request
        # per file merely to fill missing categories.
        return []


    def resolve_file_url(self, item: MediaItem) -> str:
        if item.file_url:
            return item.file_url
        raise ApiError(f'Rule34 post {item.id} has no downloadable file')


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
        url: str,
        params: dict[str, str],
        credentials: ApiCredentials | None = None,
        cancelled: Event | None = None
    ) -> Any:
        key: ApiCredentials | None = credentials if credentials is not None else self.credentials
        if key is None:
            raise AuthError('Connect Rule34 with your User ID and API key first')
        if url not in (API_URL, AUTOCOMPLETE_URL):
            raise ValueError('Credentials may only be sent to the Rule34 API')
        query: dict[str, str] = {**params, 'user_id': key.user_id, 'api_key': key.api_key}
        for attempt in range(MAX_RETRIES + 1):
            self.limiter.wait(cancelled if cancelled is not None else self.closed)
            try:
                response: requests.Response = self.sessions.current().get(
                    url, params=query, timeout=REQUEST_TIMEOUT, allow_redirects=False
                )
            except requests.RequestException:
                raise ApiError('Cannot reach Rule34; check your connection and retry') from None
            with response:
                if response.headers.get('cf-mitigated') == 'challenge':
                    raise ApiError('Cloudflare blocked the API request; try again later')
                if response.status_code == 429:
                    delay: float = retry_delay(response.headers.get('Retry-After'), attempt)
                    if attempt == MAX_RETRIES or delay > MAX_RETRY_DELAY:
                        raise ApiError('Rule34 is rate limiting requests; wait before trying again')
                    self.limiter.defer(delay)
                    continue
                if response.status_code in (401, 403):
                    # An HTML block is not evidence that the key is invalid.
                    if 'text/html' in response.headers.get('Content-Type', '').lower():
                        raise ApiError('Rule34 blocked this request; your saved key has been kept')
                    raise AuthError('Rule34 rejected the User ID or API key; check both in account settings')
                if response.status_code != 200:
                    raise ApiError(f'Rule34 returned HTTP {response.status_code}; try again later')
                # Zero-result JSON post searches return an empty body instead of [].
                if (
                    not response.content
                    and response.headers.get('Content-Type', '').split(';')[0].strip().lower() == 'application/json'
                    and url == API_URL
                    and params.get('page') == 'dapi'
                    and params.get('s') == 'post'
                    and params.get('q') == 'index'
                    and params.get('json') == '1'
                ):
                    return []
                try:
                    data: Any = response.json()
                except ValueError:
                    text: str = response.text.lower()
                    if any(message in text for message in AUTH_FAILURES):
                        raise AuthError('Rule34 rejected the User ID or API key') from None
                    if not response.content:
                        raise ApiError('Rule34 returned an empty response; try again later') from None
                    raise ApiError('Rule34 returned unreadable data; try again later') from None
                if isinstance(data, str) and any(message in data.lower() for message in AUTH_FAILURES):
                    raise AuthError('Rule34 rejected the User ID or API key')
                if isinstance(data, dict) and data.get('success') is False:
                    raise ApiError('Rule34 could not complete this request; check the search and retry')
                return data
        raise ApiError('Rule34 is temporarily unavailable')


def credentials_from_input(identifier: str, secret: str) -> ApiCredentials:
    user_id: str = identifier.strip()
    api_key: str = secret.strip()
    if api_key.startswith(('&', 'api_key=', 'user_id=')):
        api_key = ''.join(api_key.split())
        try:
            fields: dict[str, list[str]] = parse_qs(
                api_key.lstrip('&'), keep_blank_values=True, strict_parsing=True, max_num_fields=2
            )
        except ValueError:
            raise AuthError('Paste the complete API credentials containing api_key and user_id') from None
        if set(fields) != {'api_key', 'user_id'} or any(len(values) != 1 for values in fields.values()):
            raise AuthError('Paste the complete API credentials containing api_key and user_id')
        user_id = fields['user_id'][0]
        api_key = fields['api_key'][0]
        if not api_key and user_id == '2':
            raise WebsiteSignInRequired(
                'It looks like you are not signed in on Rule34. '
                'Sign in on the website, then open account settings again.'
            )
        if not api_key:
            raise AuthError(
                'The copied line contains no API key. In account settings, '
                'choose Generate New Key? and Save, then copy the line again.'
            )
    if not user_id.isascii() or not user_id.isdigit() or int(user_id) <= 0:
        raise AuthError('Copy the complete line from API Access Credentials, including user_id')
    if not api_key or any(character.isspace() for character in api_key):
        raise AuthError('Paste the API key from API Access Credentials')
    return ApiCredentials(user_id, api_key)


def integer_of(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return 0


def media_from_post(post: dict[str, Any]) -> MediaItem:
    post_id: int = integer_of(post.get('id'))
    url: Any = post.get('file_url')
    if isinstance(url, str) and url.startswith('//'):
        url = f'https:{url}'
    if not post_id or not isinstance(url, str):
        raise ApiError('Rule34 returned a post without an ID or file URL')
    parsed = urlparse(url)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise ApiError('Rule34 returned an invalid media URL')
    extension: str = Path(parsed.path).suffix.lstrip('.').lower()
    if not extension.isascii() or not extension.isalnum() or len(extension) > 8:
        extension = 'bin'
    raw_tags: Any = post.get('tags')
    tags: list[str] = raw_tags.split() if isinstance(raw_tags, str) else []
    typed: list[TypedTag] = []
    info: Any = post.get('tag_info')
    if isinstance(info, dict):
        for name, metadata in info.items():
            kind: Any = metadata.get('type') if isinstance(metadata, dict) else metadata
            if isinstance(name, str) and isinstance(kind, (int, str)) and str(kind).isdigit():
                typed.append(TypedTag(name.replace('_', ' '), TAG_CATEGORIES.get(int(kind), 'other')))
    return MediaItem(
        id=str(post_id),
        file_url=url,
        file_format=extension,
        tags=[tag.replace('_', ' ') for tag in tags],
        file_size=integer_of(post.get('file_size')),
        rating=text_of(post.get('rating')),
        width=integer_of(post.get('width')),
        height=integer_of(post.get('height')),
        md5=text_of(post.get('hash')),
        source=text_of(post.get('source')),
        typed_tags=typed
    )
