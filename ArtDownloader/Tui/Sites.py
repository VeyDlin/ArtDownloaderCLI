from ArtDownloader.Api.Sites import Site, definition_for


def site_title(site: Site) -> str:
    return definition_for(site).title
