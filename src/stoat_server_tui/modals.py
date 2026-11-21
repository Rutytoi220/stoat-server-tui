"""Modal dialogs for Stoat Server TUI (ss-tui)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

MODAL_CSS = """
ModalScreen {
    align: center middle;
    background: rgba(10, 12, 18, 0.72);
}
.modal-box {
    width: 64;
    max-width: 90%;
    height: auto;
    padding: 1 2;
    border: round #5e81ac;
    background: #161922;
    color: #eef0f7;
}
.modal-title {
    text-style: bold;
    color: #88c0d0;
    margin-bottom: 1;
}
.modal-body {
    margin-bottom: 1;
    color: #d8dee9;
}
.modal-buttons {
    height: auto;
    align: right middle;
    margin-top: 1;
}
.modal-buttons Button {
    margin-left: 1;
}
Input {
    margin-bottom: 1;
}
"""


class ConfirmModal(ModalScreen[bool]):
    DEFAULT_CSS = MODAL_CSS
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("n", "cancel", "No"),
        Binding("y", "confirm", "Yes"),
    ]

    def __init__(self, title: str, message: str, confirm_label: str = "Confirm") -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label(self._title, classes="modal-title")
            yield Static(self._message, classes="modal-body")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel [Esc]", id="cancel")
                yield Button(self._confirm_label, variant="error", id="confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")


class InputModal(ModalScreen[str | None]):
    DEFAULT_CSS = MODAL_CSS
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        title: str,
        prompt: str,
        default: str = "",
        placeholder: str = "",
        password: bool = False,
    ) -> None:
        super().__init__()
        self._title = title
        self._prompt = prompt
        self._default = default
        self._placeholder = placeholder
        self._password = password

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label(self._title, classes="modal-title")
            yield Static(self._prompt, classes="modal-body")
            yield Input(
                value=self._default,
                placeholder=self._placeholder,
                password=self._password,
                id="modal-input",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel [Esc]", id="cancel")
                yield Button("Apply [Enter]", variant="primary", id="submit")

    def on_mount(self) -> None:
        self.query_one("#modal-input", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.dismiss(self.query_one("#modal-input", Input).value)
        else:
            self.dismiss(None)


class HelpModal(ModalScreen[None]):
    DEFAULT_CSS = MODAL_CSS + """
    .modal-box {
        width: 74;
    }
    """
    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("?", "close", "Close"),
    ]

    HELP_TEXT = """[bold #88c0d0]Global Navigation[/]
  1-6             Jump directly to tab
  h / l           Focus sidebar / main pane
  j / k / ↑ / ↓   Move selection up / down
  r               Refresh current view
  ?               Show / hide this help
  q / Ctrl+C      Quit ss-tui

[bold #88c0d0]Services Tab (2)[/]
  Enter           Open container logs
  s / x           Start / Stop selected service
  R               Restart selected service
  F               Force-recreate selected service

[bold #88c0d0]Users Tab (3)[/]
  p               Reset password (enter custom or leave blank to auto-generate)
  u               Unlock account / clear login timeout
  K               Revoke all active sessions
  d               Disable / Enable account
  D               Delete account permanently
  m               Auto-mesh all users as mutual friends

[bold #88c0d0]Limits & Config Tab (4)[/]
  Enter / e       Edit selected limit (supports e.g. 10GB, 50MB, or raw bytes)
  i               Re-run inject.js & restart Caddy

[bold #88c0d0]Logs Tab (6)[/]
  [ / ]           Previous / Next container
  o               Toggle OpenTelemetry log noise filter
  r               Reload latest logs"""

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label("Stoat Server TUI (ss-tui) — Keybindings", classes="modal-title")
            yield Static(self.HELP_TEXT, classes="modal-body")
            with Horizontal(classes="modal-buttons"):
                yield Button("Close [Esc]", variant="primary", id="close")

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)
