from __future__ import annotations

from chatglance.glance_config import remove_home_widget_types


def test_remove_home_widget_types_removes_unavailable_hacker_news_only_from_home_page() -> None:
    config = {
        "pages": [
            {
                "name": "ChatArch",
                "columns": [
                    {"size": "small", "widgets": [{"type": "calendar"}, {"type": "hacker-news"}]},
                    {"size": "full", "widgets": [{"type": "group", "widgets": [{"type": "lobsters"}, {"type": "hacker-news"}]}]},
                ],
            },
            {
                "name": "其他",
                "columns": [{"size": "full", "widgets": [{"type": "hacker-news"}]}],
            },
        ]
    }

    updated = remove_home_widget_types(config, {"hacker-news"})

    home_widgets: list[str] = []
    other_widgets: list[str] = []

    def collect(value, output):
        if isinstance(value, dict):
            if "type" in value:
                output.append(value["type"])
            for key in ("widgets", "columns"):
                for item in value.get(key, []) if isinstance(value.get(key), list) else []:
                    collect(item, output)

    collect(updated["pages"][0], home_widgets)
    collect(updated["pages"][1], other_widgets)

    assert "hacker-news" not in home_widgets
    assert "calendar" in home_widgets
    assert "lobsters" in home_widgets
    assert "hacker-news" in other_widgets
    assert config["pages"][0]["columns"][0]["widgets"][1]["type"] == "hacker-news"
