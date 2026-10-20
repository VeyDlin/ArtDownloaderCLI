from dataclasses import dataclass
from enum import Enum
from ArtDownloader.Api.Filters import ANONYMOUS_OPERATOR_LIMIT, Sort


class Site(Enum):
    CHAN = 'chan'
    IDOL = 'idol'
    RULE34 = 'rule34'


class AuthKind(Enum):
    PASSWORD = 'password'
    API_KEY = 'api-key'


@dataclass(frozen=True)
class FilterSupport:
    sorts: tuple[Sort, ...]
    dates: bool = False
    stars: bool = False
    resolution: bool = False
    file_type: bool = False
    duration: bool = False
    score: bool = False
    dimensions: bool = False
    user_fields: tuple[str, ...] = ()
    user_suggestions: bool = False
    my_likes: bool = False
    anonymous_limit: int | None = None


@dataclass(frozen=True)
class SiteDefinition:
    title: str
    auth_kind: AuthKind
    filters: FilterSupport
    requires_auth: bool = False
    account_url: str = ''
    login_url: str = ''


SANKAKU_FILTERS: FilterSupport = FilterSupport(
    sorts=(
        Sort.NEWEST, Sort.POPULARITY, Sort.QUALITY, Sort.RANDOM,
        Sort.RECENTLY_FAVORITED, Sort.RECENTLY_VOTED
    ),
    dates=True,
    stars=True,
    resolution=True,
    file_type=True,
    duration=True,
    user_fields=('liked-by', 'uploaded-by', 'voted-by'),
    user_suggestions=True,
    my_likes=True,
    anonymous_limit=ANONYMOUS_OPERATOR_LIMIT
)
RULE34_FILTERS: FilterSupport = FilterSupport(
    sorts=(Sort.NEWEST, Sort.OLDEST, Sort.POPULARITY, Sort.UPDATED, Sort.RANDOM),
    score=True,
    dimensions=True,
    user_fields=('uploaded-by',)
)
SITE_DEFINITIONS: dict[Site, SiteDefinition] = {
    Site.CHAN: SiteDefinition('Chan', AuthKind.PASSWORD, SANKAKU_FILTERS),
    Site.IDOL: SiteDefinition('Idol', AuthKind.PASSWORD, SANKAKU_FILTERS),
    Site.RULE34: SiteDefinition(
        'Rule34',
        AuthKind.API_KEY,
        RULE34_FILTERS,
        requires_auth=True,
        account_url='https://rule34.xxx/index.php?page=account&s=options',
        login_url='https://rule34.xxx/index.php?code=00&page=account&s=login'
    )
}


def definition_for(site: Site) -> SiteDefinition:
    return SITE_DEFINITIONS[site]
