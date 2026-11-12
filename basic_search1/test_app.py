"""Tests for the simple LangGraph app."""

from app import build_graph, greet, shout


def test_greet_formats_message():
    result = greet({"name": "world", "message": ""})
    assert result == {"message": "Hello, world!"}


def test_shout_uppercases_message():
    result = shout({"name": "world", "message": "hello, world!"})
    assert result == {"message": "HELLO, WORLD!"}


def test_graph_runs_end_to_end():
    app = build_graph()
    result = app.invoke({"name": "world", "message": ""})
    assert result["message"] == "HELLO, WORLD!"


def test_graph_with_different_name():
    app = build_graph()
    result = app.invoke({"name": "Ada", "message": ""})
    assert result["message"] == "HELLO, ADA!"
