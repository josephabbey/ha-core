"""Websocket tests for Wyoming integration."""

from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from tests.common import MockUser
from tests.typing import WebSocketGenerator


async def test_info(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    init_components,
    init_wyoming_stt: ConfigEntry,
    init_wyoming_tts: ConfigEntry,
    init_wyoming_wake_word: ConfigEntry,
    init_wyoming_intent: ConfigEntry,
    init_wyoming_handle: ConfigEntry,
) -> None:
    """Test info websocket command."""
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "wyoming/info"})

    # result
    msg = await client.receive_json()
    assert msg["success"]

    info = msg.get("result", {}).get("info", {})

    # stt (speech-to-text) = asr (automated speech recognition)
    assert init_wyoming_stt.entry_id in info
    asr_info = info[init_wyoming_stt.entry_id].get("asr", [])
    assert len(asr_info) == 1
    assert asr_info[0].get("name") == "Test ASR"

    # tts (text-to-speech)
    assert init_wyoming_tts.entry_id in info
    tts_info = info[init_wyoming_tts.entry_id].get("tts", [])
    assert len(tts_info) == 1
    assert tts_info[0].get("name") == "Test TTS"

    # wake word detection
    assert init_wyoming_wake_word.entry_id in info
    wake_info = info[init_wyoming_wake_word.entry_id].get("wake", [])
    assert len(wake_info) == 1
    assert wake_info[0].get("name") == "Test Wake Word"

    # intent recognition
    assert init_wyoming_intent.entry_id in info
    intent_info = info[init_wyoming_intent.entry_id].get("intent", [])
    assert len(intent_info) == 1
    assert intent_info[0].get("name") == "Test Intent"

    # intent handling
    assert init_wyoming_handle.entry_id in info
    handle_info = info[init_wyoming_handle.entry_id].get("handle", [])
    assert len(handle_info) == 1
    assert handle_info[0].get("name") == "Test Handle"


async def test_identity_mapping_crud(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    init_components,
    init_wyoming_intent: ConfigEntry,
    hass_admin_user: MockUser,
) -> None:
    """Test Wyoming identity mapping websocket commands."""
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "wyoming/identity_mapping/set",
            "entry_id": init_wyoming_intent.entry_id,
            "identity_name": "Alice",
            "user_id": hass_admin_user.id,
        }
    )
    msg = await client.receive_json()
    assert msg["success"]

    await client.send_json_auto_id(
        {
            "type": "wyoming/identity_mapping/list",
            "entry_id": init_wyoming_intent.entry_id,
        }
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] == {
        "mappings": [
            {
                "identity_name": "Alice",
                "user_id": hass_admin_user.id,
                "user_name": hass_admin_user.name,
            }
        ]
    }

    await client.send_json_auto_id(
        {
            "type": "wyoming/identity_mapping/delete",
            "entry_id": init_wyoming_intent.entry_id,
            "identity_name": "Alice",
        }
    )
    msg = await client.receive_json()
    assert msg["success"]

    await client.send_json_auto_id(
        {
            "type": "wyoming/identity_mapping/list",
            "entry_id": init_wyoming_intent.entry_id,
        }
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] == {"mappings": []}


async def test_identity_list(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    init_components,
    init_wyoming_intent: ConfigEntry,
) -> None:
    """Test listing Wyoming identities from service info."""
    item = hass.data["wyoming"][init_wyoming_intent.entry_id]
    item.service.info.identity = [
        SimpleNamespace(
            models=[
                SimpleNamespace(
                    identities=[
                        SimpleNamespace(name="Alice"),
                        SimpleNamespace(name="Bob"),
                    ]
                )
            ]
        )
    ]

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "wyoming/identity/list",
            "entry_id": init_wyoming_intent.entry_id,
        }
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] == {"identities": ["Alice", "Bob"]}
