from scripts.virtual_cursor import (
    install_virtual_cursor,
    move_virtual_cursor_to_bid,
    set_virtual_cursor_pressed,
)
from tracetotest.visualization import extract_visual_actions, visualize_action


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


def test_visual_actions_are_parsed_without_execution() -> None:
    actions = extract_visual_actions("fill(bid='16', value='user')\nclick(bid='20')")
    assert [(item.name, item.bid) for item in actions] == [("fill", "16"), ("click", "20")]
    assert extract_visual_actions("not valid python (") == []


def test_click_is_red_but_fill_is_not() -> None:
    page = FakePage()

    visualize_action(page, "fill(bid='16', value='user')", move_duration_ms=10)
    assert "pressed" not in [argument for _, argument in page.evaluations]

    visualize_action(page, "click(bid='20')", move_duration_ms=10, click_display_ms=25)
    assert [argument for _, argument in page.evaluations[-3:]] == [
        "idle",
        "pressed",
        "idle",
    ]
    assert page.waits == [110, 110, 25]
