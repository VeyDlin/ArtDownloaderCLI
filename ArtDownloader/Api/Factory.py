from ArtDownloader.Api.Client import SankakuApi
from ArtDownloader.Api.Rule34 import Rule34Api
from ArtDownloader.Api.Danbooru import DanbooruApi
from ArtDownloader.Api.Sites import Site
from ArtDownloader.Api.Source import Source
from ArtDownloader.Auth.CredentialStore import CredentialStore


def create_source(site: Site, store: CredentialStore) -> Source:
    if site is Site.RULE34:
        return Rule34Api(store)
    if site is Site.DANBOORU:
        return DanbooruApi(store)
    return SankakuApi(site, token_store=store)
