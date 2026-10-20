from enum import Enum
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Rule, Static
from rich.markup import escape
from ArtDownloader.Api.Source import Source
from ArtDownloader.Api.Sites import AuthKind, SiteDefinition, definition_for
from ArtDownloader.Api.Errors import ApiError
from ArtDownloader.Tui.Navigation import ArrowNavigation
from ArtDownloader.Tui.Sites import site_title
from ArtDownloader.Tui.Widgets import Action
import webbrowser


class AuthResult(Enum):
    SIGNED_IN = 'signed-in'
    RETRY = 'retry'
    CLOSED = 'closed'


class AuthScreen(ModalScreen[AuthResult], ArrowNavigation):
    """Sign-in dialog. Closes by itself the moment sign-in succeeds.

    When opened because the stored session failed, it shows why; if the
    failure was the server being unreachable, it also offers a retry.
    """

    BINDINGS = [Binding('escape', 'close', 'Close')]


    def __init__(self, api: Source, error: str = '', can_retry: bool = False) -> None:
        super().__init__()
        self.api: Source = api
        self.definition: SiteDefinition = definition_for(api.site)
        self.error: str = error
        self.can_retry: bool = can_retry
        self.busy: bool = False


    def compose(self) -> ComposeResult:
        key_auth: bool = self.definition.auth_kind is AuthKind.API_KEY
        with Vertical(id='dialog', classes='key-dialog' if key_auth else ''):
            with Horizontal(classes='line'):
                action: str = 'connect' if key_auth else 'sign in'
                yield Static(f'[b]{site_title(self.api.site)}[/] · {action}', classes='fill')
                yield Action('esc', id='close')

            yield Rule()

            if key_auth:
                yield Static(
                    'An [b]API key[/] is a private access code for this app.\n\n'
                    '1. Open account settings below and sign in.\n'
                    '2. Under [b]API Access Credentials[/], select [b]Generate New Key?[/] '
                    'and [b]Save[/] if you do not have a key yet.\n'
                    '3. Paste your [b]User ID[/] and [b]API key[/] below.',
                    id='auth-guide'
                )
                with Horizontal(classes='field'):
                    yield Action('open account settings ↗', 'accent', id='open-account-settings')
                yield Static(self.definition.account_url, id='account-settings-url', markup=False)

            with Horizontal(classes='field'):
                yield Label('User ID' if key_auth else 'login', classes='caption')
                yield Input(
                    value=self.api.remembered_identifier(),
                    placeholder='number from account settings' if key_auth else 'username or e-mail',
                    id='username',
                    compact=True
                )
            with Horizontal(classes='field'):
                yield Label('API key' if key_auth else 'password', classes='caption')
                yield Input(
                    placeholder='paste your API key' if key_auth else 'password',
                    password=True, id='password', compact=True
                )
                yield Action('show', id='reveal')

            yield Static(
                'Your key is saved locally in .config/session.json. Keep it private. '
                'Request limits are handled automatically.'
                if key_auth else 'The password is only exchanged for a session token; it is never saved.',
                id='auth-hint'
            )

            # The error lives in the action row, left of the buttons: that row
            # is always there, so an error appearing never shifts the layout.
            with Horizontal(classes='line actions'):
                yield Static('', id='auth-error', classes='fill message')
                if self.can_retry:
                    yield Action('↻ retry check', id='retry')
                yield Action('❯ connect' if key_auth else '❯ sign in', 'accent', id='sign-in')


    def on_mount(self) -> None:
        self.show_error(self.error)
        focus_id = '#password' if self.api.remembered_identifier() else '#username'
        self.query_one(focus_id, Input).focus()


    def on_action_pressed(self, event: Action.Pressed) -> None:
        action_id = event.action.id
        if action_id == 'sign-in':
            self.submit()
        elif action_id == 'reveal':
            self.toggle_reveal()
        elif action_id == 'retry':
            self.dismiss(AuthResult.RETRY)
        elif action_id == 'open-account-settings':
            self.open_account_settings()
        elif action_id == 'close':
            self.action_close()


    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == 'username':
            self.query_one('#password', Input).focus()
            return

        self.submit()


    def action_close(self) -> None:
        if not self.busy:
            self.dismiss(AuthResult.CLOSED)


    @work(thread=True, exit_on_error=False)
    def open_account_settings(self) -> None:
        try:
            opened: bool = webbrowser.open(self.definition.account_url)
        except webbrowser.Error:
            opened = False
        if not opened:
            self.app.call_from_thread(self.show_account_url)


    def show_account_url(self) -> None:
        self.query_one('#account-settings-url').display = True
        self.show_error('Open the account settings URL above in your browser')


    def toggle_reveal(self) -> None:
        password = self.query_one('#password', Input)
        password.password = not password.password
        self.query_one('#reveal', Action).label = 'show' if password.password else 'hide'
        password.focus()


    def submit(self) -> None:
        if self.busy:
            return

        username = self.query_one('#username', Input).value.strip()
        password = self.query_one('#password', Input).value
        if not username or not password:
            self.show_error(
                'Enter both User ID and API key'
                if self.definition.auth_kind is AuthKind.API_KEY else 'Enter both login and password'
            )
            return

        self.show_error('')
        self.set_busy(True)
        self.sign_in(username, password)


    @work(thread=True, exclusive=True, exit_on_error=False)
    def sign_in(self, username: str, password: str) -> None:
        try:
            name = self.api.login(username, password)
        except ApiError as err:
            self.app.call_from_thread(self.sign_in_failed, str(err))
            return
        except Exception:
            self.app.call_from_thread(self.sign_in_failed, 'Could not connect; check your connection and local settings')
            return

        self.app.call_from_thread(self.sign_in_succeeded, name)


    def sign_in_succeeded(self, name: str) -> None:
        self.dismiss(AuthResult.SIGNED_IN)


    def sign_in_failed(self, message: str) -> None:
        # Keep what was typed: a typo is fixed faster than a password retyped.
        self.set_busy(False)
        self.show_error(message)
        self.query_one('#password', Input).focus()


    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        sign_in = self.query_one('#sign-in', Action)
        sign_in.disabled = busy
        key_auth: bool = self.definition.auth_kind is AuthKind.API_KEY
        sign_in.label = ('checking key…' if key_auth else 'signing in…') if busy else (
            '❯ connect' if key_auth else '❯ sign in'
        )
        for selector in ('#username', '#password', '#close'):
            self.query_one(selector).disabled = busy


    def show_error(self, message: str) -> None:
        self.query_one('#auth-error', Static).update(f'[$error]{escape(message)}[/]' if message else '')
