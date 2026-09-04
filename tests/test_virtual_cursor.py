from scripts.virtual_cursor import (
    install_virtual_cursor,
    move_virtual_cursor_to_bid,
    set_virtual_cursor_pressed,
)


class FakePage:
    def __init__(self) -> None:
        self.evaluations = []
        self.waits = []

    def evaluate(self, script, argument=None):
        self.evaluations.append((script, argument))
        if isinstance(argument, dict) and "bid" in argument:
            return {"x": 120, "y": 80}
        return None

    def wait_for_timeout(self, duration):
        self.waits.append(duration)


def test_virtual_cursor_lifecycle() -> None:
    page = FakePage()

    install_virtual_cursor(page)
    position = move_virtual_cursor_to_bid(page, "13", duration_ms=700)
    set_virtual_cursor_pressed(page, True)
    set_virtual_cursor_pressed(page, False)

    assert position == {"x": 120, "y": 80}
    assert page.waits == [800]
    assert [argument for _, argument in page.evaluations[-3:]] == [
        "idle",
        "pressed",
        "idle",
    ]
