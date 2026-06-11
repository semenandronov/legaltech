"""Unit tests for agent run event bus helpers."""
from app.services.agent_runs.event_channels import control_notify_channel, run_notify_channel


def test_run_notify_channel_sanitized():
    run_id = "8de78023-f32d-4005-b81e-0d787d10f54e"
    channel = run_notify_channel(run_id)
    assert channel.startswith("ar_")
    assert len(channel) <= 63
    assert "-" not in channel


def test_control_channel_name():
    assert control_notify_channel() == "agent_control"
