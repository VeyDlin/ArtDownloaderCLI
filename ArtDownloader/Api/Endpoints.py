from dataclasses import dataclass
from ArtDownloader.Api.Sites import Site


# The Sankaku media CDN (iv./v.sankakucomplex.com) answers 403 to a bare tool
# User-Agent, so every request presents a browser agent instead.
BROWSER_USER_AGENT: str = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
)

# Registrable domains the bearer token may be sent to. A file_url can point at a
# foreign host, and the session token must never leak there.
AUTH_HOSTS: tuple[str, ...] = ('sankakucomplex.com', 'sankakuapi.com')

REQUEST_TIMEOUT: int = 30
DEFAULT_PAGE_SIZE: int = 40


@dataclass(frozen=True)
class SiteEndpoints:
    api_base: str
    site_base: str
    search_extra: str


SITE_ENDPOINTS: dict[Site, SiteEndpoints] = {
    Site.CHAN: SiteEndpoints(
        api_base='https://sankakuapi.com',
        site_base='https://chan.sankakucomplex.com',
        search_extra='lang=en&hide_posts_in_books=in-larger-tags'
    ),
    Site.IDOL: SiteEndpoints(
        api_base='https://i.sankakuapi.com',
        site_base='https://idol.sankakucomplex.com',
        search_extra='lang=en'
    )
}


def endpoints_for(site: Site) -> SiteEndpoints:
    return SITE_ENDPOINTS[site]
