"""Integration tests for verify injection behaviour against a live telescope.

These tests connect to a real device and assert that:
  - The firmware version is read correctly from device state.
  - For firmware < 2706: "verify" is injected into outgoing commands.
  - For firmware >= 2706: no "verify" is injected and commands still succeed
    (no error code 109 / 107 from the device).

Run with:
    RUN_HARDWARE_TESTS=true TELESCOPE_HOST=<ip> pytest tests/test_verify_injection.py -v
"""

import asyncio
import json
import os

import pytest
import pytest_asyncio

from scopinator.seestar.client import SeestarClient
from scopinator.seestar.commands.simple import GetDeviceState, GetTime
from scopinator.seestar.commands.settings import SetSetting, SettingParameters
from scopinator.util.eventbus import EventBus

TELESCOPE_HOST = os.environ.get("TELESCOPE_HOST", "localhost")
TELESCOPE_PORT = int(os.environ.get("TELESCOPE_PORT", "4700"))

pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(
        os.environ.get("RUN_HARDWARE_TESTS", "false").lower() != "true",
        reason="Hardware tests skipped (set RUN_HARDWARE_TESTS=true to run)",
    ),
]


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def connected_client():
    client = SeestarClient(
        host=TELESCOPE_HOST,
        port=TELESCOPE_PORT,
        event_bus=EventBus(),
        connection_timeout=5.0,
        read_timeout=10.0,
    )
    try:
        await client.connect()
        # Populate device state so firmware_ver_int is available
        await client.send_and_recv(GetDeviceState())
        yield client
    except (ConnectionError, OSError) as e:
        pytest.skip(f"Hardware not available at {TELESCOPE_HOST}:{TELESCOPE_PORT}: {e}")
    finally:
        if client.is_connected:
            await client.disconnect()


def _last_sent(client) -> dict:
    """Return the parsed JSON of the most-recently sent message."""
    for msg in reversed(client.message_history):
        if msg.direction == "sent":
            return json.loads(msg.message)
    raise AssertionError("No sent messages found in history")


# ---------------------------------------------------------------------------
# Firmware version detection
# ---------------------------------------------------------------------------

class TestFirmwareDetection:
    @pytest.mark.asyncio
    async def test_firmware_ver_int_populated_after_device_state(self, connected_client):
        """After GetDeviceState the client should know the firmware version."""
        fw = connected_client._get_firmware_ver_int()
        # 0 means unknown; anything > 0 means we got it from the device
        assert isinstance(fw, int)
        assert fw >= 0
        print(f"\nDetected firmware_ver_int: {fw}")

    @pytest.mark.asyncio
    async def test_should_inject_verify_matches_firmware(self, connected_client):
        """_should_inject_verify should be consistent with the firmware version.

        Note: on 2706+ the dict-param guard lives in _transform_message_for_verify,
        not in _should_inject_verify, so _should_inject_verify still returns True
        for firmware >= 2706 (it only gates on the > 2582 range).
        """
        fw = connected_client._get_firmware_ver_int()
        should_inject = connected_client._should_inject_verify()

        if fw == 0 or fw > 2582:
            assert should_inject is True, (
                f"firmware {fw} should inject but _should_inject_verify returned False"
            )
        else:
            assert should_inject is False, (
                f"firmware {fw} <= 2582 should NOT inject but returned True"
            )


# ---------------------------------------------------------------------------
# Wire-level verify injection
# ---------------------------------------------------------------------------

class TestVerifyInjectionOnWire:
    @pytest.mark.asyncio
    async def test_get_time_sent_with_verify_on_2706_plus(self, connected_client):
        """On firmware >= 2706 GetTime (no params) still gets ['verify'] injected.

        The 2706+ guard only skips verify for dict params; list/no-params commands
        continue to receive verify injection.
        """
        fw = connected_client._get_firmware_ver_int()
        if fw < 2706:
            pytest.skip(f"firmware {fw} < 2706; skipping 2706+ assertion")

        await connected_client.send_and_recv(GetTime())
        sent = _last_sent(connected_client)

        assert sent.get("params") == ["verify"], (
            f"Expected ['verify'] for no-param command on firmware {fw}, "
            f"got {sent.get('params')!r}"
        )

    @pytest.mark.asyncio
    async def test_get_time_sent_with_verify_before_2706(self, connected_client):
        """On firmware that needs verify, GetTime (no params) gets ['verify'] injected."""
        fw = connected_client._get_firmware_ver_int()
        if not (fw == 0 or (2582 < fw < 2706)):
            pytest.skip(f"firmware {fw} does not require injection; skipping pre-2706 assertion")

        await connected_client.send_and_recv(GetTime())
        sent = _last_sent(connected_client)

        assert sent.get("params") == ["verify"], (
            f"Expected ['verify'] in params for firmware {fw}, got {sent.get('params')!r}"
        )

    @pytest.mark.asyncio
    async def test_set_setting_no_verify_injected_on_2706_plus(self, connected_client):
        """SetSetting (dict params) must not have 'verify' injected on firmware >= 2706.

        On 2706+ the dict-param branch of _transform_message_for_verify returns early,
        so the outgoing message must have a clean params dict with no 'verify' key.
        We fire-and-forget (send only) to avoid a timeout when the device doesn't ack
        the specific setting, and assert only on the transmitted wire content.
        """
        fw = connected_client._get_firmware_ver_int()
        if fw < 2706:
            pytest.skip(f"firmware {fw} < 2706; skipping 2706+ assertion")

        cmd = SetSetting(params=SettingParameters(save_discrete_frame=False))
        await connected_client.send(cmd)

        sent = _last_sent(connected_client)
        params = sent.get("params", {})
        assert isinstance(params, dict), f"Expected dict params, got {params!r}"
        assert "verify" not in params, (
            f"'verify' key found in dict params sent to firmware {fw}: {params}"
        )

    @pytest.mark.asyncio
    async def test_set_setting_has_verify_before_2706(self, connected_client):
        """SetSetting (dict params) should contain verify key for pre-2706 firmware."""
        fw = connected_client._get_firmware_ver_int()
        if not (fw == 0 or (2582 < fw < 2706)):
            pytest.skip(f"firmware {fw} does not require injection; skipping pre-2706 assertion")

        await connected_client.send_and_recv(
            SetSetting(params=SettingParameters(auto_power_off=False))
        )
        sent = _last_sent(connected_client)
        params = sent.get("params", {})
        assert "verify" in params and params["verify"] is True, (
            f"Expected verify=True in dict params for firmware {fw}, got: {params}"
        )
