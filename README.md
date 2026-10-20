# ArtDownloaderCLI

A terminal app for searching and downloading art from **Sankaku Chan**, **Sankaku Idol**, **Rule34** and **Danbooru**. Save images together with their tags to build datasets for training AI models.

## Features

- **Four sources** — Search and download from several sites at the same time
- **Search filters** — Find posts by content rating, date, size, file type, score and more, depending on the site
- **Favorites** — Download your favorites from Sankaku and Danbooru
- **Tag saving** — Save tags beside each file as `.txt` captions or `.json` metadata
- **Resume** — Skip files you already have when continuing an interrupted download
- **Parallel downloads** — Download up to four files at once

## Preview

<img src=".github/downloads.png" alt="Download list" />
<img src=".github/search.png" alt="Search and filters" />
<img src=".github/sign-in.png" alt="Sign-in form" />
<img src=".github/settings.png" alt="Download settings" />

## Download

Get the latest build from [Releases](https://github.com/VeyDlin/SankakuParser/releases/latest) — no Python needed.

- **Windows** — Download `ArtDownloaderCLI-<version>-windows.exe` and run it.
- **Linux** — Unpack `ArtDownloaderCLI-<version>-linux.tar.gz` and run `./ArtDownloaderCLI`.
- **macOS** — Unpack `ArtDownloaderCLI-<version>-macos-arm64.zip` for Apple Silicon or `-macos-x64.zip` for Intel, then open `ArtDownloaderCLI`. If macOS blocks the unsigned app, allow it in **System Settings → Privacy & Security → Open Anyway**, or run `xattr -d com.apple.quarantine ArtDownloaderCLI`.

Downloads and settings are kept next to the executable. When updating from SankakuParser, keep your existing `.config/` and `data/` folders beside the new app.

## Getting started

1. Choose **Chan**, **Idol**, **Rule34** or **Danbooru**.
2. Sign in if needed using the instructions in the app.
3. Enter search tags, adjust **filters** if needed, and press **▶ start**.

Each search is saved in its own folder under `data/`, grouped by site. Set **limit** to cap the number of new files, or leave it empty to download all available results.

Use **my likes** in the filters to download your favorites from Sankaku or Danbooru after signing in.

## Accounts and limits

| Site | Sign-in |
| --- | --- |
| Sankaku Chan / Idol | Optional; use your username and password |
| Rule34 | Required; the app guides you through copying your access key |
| Danbooru | Optional; use your username and access key |

An access key lets the app connect to your account without your website password. The sign-in forms include links and step-by-step instructions.

Some posts require an account or a paid subscription. Signing in gives the app the access your account already has; it does not remove site restrictions.

- **Sankaku:** Searches stop after 50 pages unless your account has a paid subscription. Anonymous searches also have a limit on advanced filters, shown in the app.
- **Danbooru:** Search limits depend on your account. If the website asks you to verify your account, complete that step there.

## Controls

- **Downloads** — Start, pause, resume or stop from the selected site's tab.
- **Keyboard** — Use `Tab` or arrow keys to navigate, `Enter` or `Space` to select, `Esc` to close a dialog and `Ctrl+Q` to quit.
- **Suggestions** — Use `↑` / `↓` to choose a tag, `Tab` or `Enter` to accept it and `Esc` to dismiss the list.

## Running from source

Requires Python 3.10+.

Run `start.bat` on Windows, or `./start.bat` on Linux and macOS. The first run sets up the environment and installs dependencies.
