from enum import Enum
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Rule, Static, TextArea
from rich.markup import escape
from ArtDownloader.Api.Source import Source
from ArtDownloader.Api.Sites import AuthKind, SiteDefinition, definition_for
from ArtDownloader.Api.Errors import ApiError, WebsiteSignInRequired
from ArtDownloader.Tui.Navigation import ArrowNavigation
from ArtDownloader.Tui.Sites import site_title
from ArtDownloader.Tui.Widgets import Action


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
        with Vertical(id='dialog'):
            with Horizontal(classes='line'):
                yield Static(f'[b]{site_title(self.api.site)}[/] · sign in', classes='fill')
                yield Action('esc', id='close')

            yield Rule()

            if key_auth:
                yield Static(self.key_intro(), id='auth-hint')
                with Horizontal(classes='auth-step'):
                    yield Static('Otherwise,', id='site-login-lead', classes='auth-step-text')
                    yield Action('sign in', 'accent', id='open-site-login')
                    yield Static(f'on {site_title(self.api.site)}.', classes='auth-step-text')
                with Horizontal(id='auth-settings-step'):
                    yield Static('2. Open', classes='auth-step-text')
                    yield Action('account settings', 'accent', id='open-account-settings')
                yield Static(
                    '3. Find [$text-highlight]API Access Credentials[/]. '
                    'Copy the whole line starting with [$text-highlight]&api_key=[/] '
                    'and paste it below.',
                    id='auth-steps'
                )
                yield TextArea(
                    id='credentials',
                    placeholder='Paste the copied text here',
                    compact=True,
                    highlight_cursor_line=False
                )
            else:
                with Horizontal(classes='field'):
                    yield Label('login', classes='caption')
                    yield Input(
                        value=self.api.remembered_identifier(),
                        placeholder='username or e-mail', id='username', compact=True
                    )
                with Horizontal(classes='field'):
                    yield Label('password', classes='caption')
                    yield Input(placeholder='password', password=True, id='password', compact=True)
                    yield Action('show', id='reveal')
                yield Static(
                    'The password is only exchanged for a session token; it is never saved.',
                    id='auth-hint'
                )

            # The error lives in the action row, left of the buttons: that row
            # is always there, so an error appearing never shifts the layout.
            with Horizontal(classes='line actions'):
                yield Static('', id='auth-error', classes='fill message')
                if self.can_retry:
                    yield Action('↻ retry check', id='retry')
                yield Action('❯ continue' if key_auth else '❯ sign in', 'accent', id='sign-in')


    def on_mount(self) -> None:
        self.show_error(self.error)
        self.focus_credentials()


    def key_intro(self) -> str:
        return f'1. Already signed in to {site_title(self.api.site)}? Skip to step 2.'


    def focus_credentials(self) -> None:
        if self.definition.auth_kind is AuthKind.API_KEY:
            self.query_one('#credentials', TextArea).focus()
        else:
            focus_id: str = '#password' if self.api.remembered_identifier() else '#username'
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
            self.app.open_url(self.definition.account_url)
        elif action_id == 'open-site-login':
            self.app.open_url(self.definition.login_url)
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


    def toggle_reveal(self) -> None:
        password = self.query_one('#password', Input)
        password.password = not password.password
        self.query_one('#reveal', Action).label = 'show' if password.password else 'hide'
        password.focus()


    def submit(self) -> None:
        if self.busy:
            return

        key_auth: bool = self.definition.auth_kind is AuthKind.API_KEY
        username: str = '' if key_auth else self.query_one('#username', Input).value.strip()
        password: str = (
            self.query_one('#credentials', TextArea).text
            if key_auth else self.query_one('#password', Input).value
        )
        if not password or (not key_auth and not username):
            self.show_error(
                'Paste the complete text from API Access Credentials'
                if key_auth else 'Enter both login and password'
            )
            return

        self.show_error('')
        if key_auth:
            self.query_one('#auth-hint', Static).update(self.key_intro())
            self.query_one('#site-login-lead', Static).update('Otherwise,')
        self.set_busy(True)
        self.sign_in(username, password)


    @work(thread=True, exclusive=True, exit_on_error=False)
    def sign_in(self, username: str, password: str) -> None:
        try:
            name = self.api.login(username, password)
        except WebsiteSignInRequired as err:
            self.app.call_from_thread(self.sign_in_failed, str(err), True)
            return
        except ApiError as err:
            self.app.call_from_thread(self.sign_in_failed, str(err))
            return
        except Exception:
            self.app.call_from_thread(self.sign_in_failed, 'Could not connect; check your connection and local settings')
            return

        self.app.call_from_thread(self.sign_in_succeeded, name)


    def sign_in_succeeded(self, name: str) -> None:
        self.dismiss(AuthResult.SIGNED_IN)


    def sign_in_failed(self, message: str, website_sign_in: bool = False) -> None:
        self.set_busy(False)
        if website_sign_in:
            self.show_error('')
            self.query_one('#auth-hint', Static).update(f'[$error]{escape(message)}[/]')
            self.query_one('#site-login-lead', Static).update('First,')
            self.query_one('#open-site-login').focus()
        else:
            self.show_error(message)
            self.focus_credentials()


    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        sign_in = self.query_one('#sign-in', Action)
        sign_in.disabled = busy
        key_auth: bool = self.definition.auth_kind is AuthKind.API_KEY
        sign_in.label = 'signing in…' if busy else '❯ continue' if key_auth else '❯ sign in'
        self.query_one('#close').disabled = busy
        if key_auth:
            self.query_one('#credentials', TextArea).read_only = busy
        else:
            for selector in ('#username', '#password'):
                self.query_one(selector).disabled = busy


    def show_error(self, message: str) -> None:
        self.query_one('#auth-error', Static).update(f'[$error]{escape(message)}[/]' if message else '')
