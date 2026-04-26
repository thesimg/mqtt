# ----- Imports -------------------------
import json
import signal
import ssl
import sys
import time
from typing import Any
from pathlib import Path
import logging
import queue

import foxglove
import paho.mqtt.client as paho
from foxglove import Channel, Schema
from foxglove.websocket import Capability, Client, ServerListener

from parser import parse_loged_fields

# ----- Logger -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

mqtt_log = logging.getLogger("mqtt")
fox_log = logging.getLogger("foxglove")
bridge_log = logging.getLogger("bridge")

# ----- Config -------------------------
MQTT_HOST = "19e34349420d4b38911b39f4bda2e3ff.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "RBE2002macbook"
MQTT_PASS = "RBE2002macbook"
MQTT_SUB_TOPIC = "#"

ROMI_CMD_TOPIC = "/cmd"

ROMI_HEADER_PATH = Path(__file__).parent / "../examples/atmega32u4-client/include/logger.h"
ROMI_FIELDS = parse_loged_fields(ROMI_HEADER_PATH)

ROMI_FIELD_IDS: dict[str, int] = {v: k for k, v in ROMI_FIELDS.items()}

bridge_log.info(f"Logged Fields {ROMI_FIELDS}")

messageQueue: queue.Queue = queue.Queue()

# ----- Romi message parsing -------------------------
def parse_romi_message(field: int, payload: str) -> dict[str, Any] | None:
    parts = payload.split(":")
    if len(parts) != 2:
        bridge_log.error(f"Payload is wrong length (got {len(parts)} parts): raw={payload!r} parts={parts}")
        return None

    value_str, millis_str = parts
    try:
        device_millis = int(millis_str)
    except ValueError:
        bridge_log.error("Mills is not int")
        return None

    try:
        value: int | float = int(value_str)
    except ValueError:
        try:
            value = float(value_str)
        except ValueError:
            bridge_log.error("value not int or float")
            return None

    return {
        "field_id": field,
        "field_name": ROMI_FIELDS.get(field, f"field_{field}"),
        "value": value,
        "device_millis": device_millis,
    }

def decode_payload(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.hex()

# ----- Schemas -------------------------
ROMI_TELEMETRY_SCHEMA = Schema(
    name="RomiTelemetry",
    encoding="jsonschema",
    data=json.dumps({
        "type": "object",
        "properties": {
            "timestamp": {
                "type": "object",
                "title": "time",
                "properties": {
                    "sec": {"type": "integer"},
                    "nsec": {"type": "integer"},
                },
            },
            "value": {"type": "number"},
            "device_millis": {"type": "integer"},
        },
    }).encode("utf-8"),
)

RAW_PAYLOAD_SCHEMA = Schema(
    name="RawMqttMessage",
    encoding="jsonschema",
    data=json.dumps({
        "type": "object",
        "properties": {
            "timestamp": {
                "type": "object",
                "title": "time",
                "properties": {
                    "sec": {"type": "integer"},
                    "nsec": {"type": "integer"},
                },
            },
            "payload": {"type": "string"},
            "qos": {"type": "integer"},
        },
    }).encode("utf-8"),
)

ROMI_FIELD_INPUT_SCHEMA = Schema(
    name="RomiFieldInput",
    encoding="jsonschema",
    data=json.dumps({
        "type": "object",
        "properties": {
            "field_id": {"type": "integer"},
            "value": {"type": "number"},
        },
        "required": ["field_id", "value"],
    }).encode("utf-8"),
)

ROMI_JOYSTICK_SCHEMA = Schema(
    name="RomiJoystick",
    encoding="jsonschema",
    data=json.dumps({
        "type": "object",
        "properties": {
            "linear":  {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}}},
            "angular": {"type": "object", "properties": {"z": {"type": "number"}}},
        },
    }).encode("utf-8"),
)

# ----- Timestamp tracking -------------------------
RESTART_THRESHOLD_MS = 2_000

_millis_epoch_ns: int | None = None
_last_device_millis: int = 0

def _reset_romi_session() -> None:
    global _millis_epoch_ns, _last_device_millis
    bridge_log.info("Romi session reset: clearing Foxglove channels")
    _channels.clear()
    _millis_epoch_ns = None
    _last_device_millis = 0

def device_time_ns(device_millis: int) -> int:
    global _millis_epoch_ns, _last_device_millis

    if _millis_epoch_ns is not None and device_millis < _last_device_millis - RESTART_THRESHOLD_MS:
        bridge_log.info(
            f"Romi restart detected (millis {_last_device_millis} -> {device_millis})"
        )
        _reset_romi_session()

    if _millis_epoch_ns is None:
        _millis_epoch_ns = time.time_ns() - device_millis * 1_000_000

    _last_device_millis = device_millis
    return _millis_epoch_ns + device_millis * 1_000_000

def ns_to_timestamp(ns: int) -> dict[str, int]:
    return {"sec": ns // 1_000_000_000, "nsec": ns % 1_000_000_000}

def now_timestamp() -> dict[str, int]:
    return ns_to_timestamp(time.time_ns())

# ----- Channel registry -------------------------
_channels: dict[str, Channel] = {}

def channel_for(topic: str, schema: Schema) -> Channel:
    if topic not in _channels:
        _channels[topic] = Channel(topic, message_encoding="json", schema=schema)
    return _channels[topic]

# ----- Foxglove → MQTT listener -------------------------
class RomiInputListener(ServerListener):
    def __init__(self) -> None:
        self._advertised: dict[tuple[int, int], str] = {}
        self.lastTime = 0

    def on_client_advertise(self, client: Client, channel: Any) -> None:
        self._advertised[(client.id, channel.id)] = channel.topic
        fox_log.info(f"client {client.id} advertised channel '{channel.topic}' (id={channel.id})")

    def on_client_unadvertise(self, client: Client, channel_id: int) -> None:
        self._advertised.pop((client.id, channel_id), None)

    def on_message_data(self, client: Client, client_channel_id: int, data: bytes) -> None:
        topic = self._advertised.get((client.id, client_channel_id), "")

        if (time.time_ns() - self.lastTime) > (1000000 * 100):
            self.lastTime = time.time_ns()
            try:
                msg = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                fox_log.warning(f"could not parse client message on '{topic}': {e}")
                return
            # fox_log.info(msg)
            # Generic per-field slider: {"field_id": int, "value": number}
            if topic.startswith("/foxglove/input"):
                field_id = msg.get("field_id")
                value = msg.get("value")
                if field_id is None or value is None:
                    fox_log.warning(f"RomiFieldInput missing field_id or value: {msg!r}")
                    return
                payload = f"{field_id}:{value}"
                # if messageQueue.full():
                #     messageQueue.get_nowait()
                mqtt_client.publish(ROMI_CMD_TOPIC, payload)
                mqtt_log.info(ROMI_CMD_TOPIC, payload)

            # Joystick / teleop: {"linear": {"x": float, "y": float}, "angular": {"z": float}}
            elif topic == "/foxglove/joystick":
                # print("here")
                # print(msg["axes"])
                try:
                    lx = float(msg["axes"][1])
                    ly = float(msg["axes"][0])
                except (KeyError, TypeError, ValueError) as e:
                    fox_log.warning(f"bad joystick message: {e} | {msg!r}")
                    return
                # Publish each axis separately so the Romi can handle them individually.
                # Format: field_name:value  (Romi maps these by name or you can switch to IDs)
                for name, val in [("x", lx), ("y", ly)]:
                    # if messageQueue.full():
                    #     messageQueue.get_nowait()
                    #     messageQueue.get_nowait()
                    mqtt_client.publish(ROMI_CMD_TOPIC, f"{name}:{val:.4f}")
                    mqtt_log.info(f"{ROMI_CMD_TOPIC} {name}:{val:.4f}")
                    # print((ROMI_CMD_TOPIC, f"{name}:{val:.4f}"))

            else:
                fox_log.debug(f"unhandled client topic '{topic}': {msg!r}")


# ----- MQTT callbacks -------------------------
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        mqtt_log.info("connected")
        client.subscribe(MQTT_SUB_TOPIC, qos=1)
    else:
        mqtt_log.warning(f"connect failed, rc={rc}")

def on_disconnect(client, userdata, rc, properties=None):
    if rc == 0:
        mqtt_log.info("disconnected")
    else:
        mqtt_log.warning(f"unexpected disconnect (rc={rc}), reconnecting...")

def on_subscribe(client, userdata, mid, granted_qos, properties=None):
    mqtt_log.debug(f"subscribed mid={mid} qos={granted_qos}")

def on_publish(client, userdata, mid, properties=None):
    mqtt_log.debug(f"published mid={mid}")

def on_message(client, userdata, msg):
    if msg.topic == ROMI_CMD_TOPIC:
        return

    payload_str = decode_payload(msg.payload)
    
    parsed = parse_romi_message(msg.topic, payload_str)
    if parsed is not None:
        log_ns = device_time_ns(parsed["device_millis"])
        ts = ns_to_timestamp(log_ns)
        field_topic = f"/romi/{parsed['field_name']}"
        channel_for(field_topic, ROMI_TELEMETRY_SCHEMA).log(
            {
                "timestamp": ts,
                "value": parsed["value"],
                "device_millis": parsed["device_millis"],
            },
            log_time=log_ns,
        )
        return

    # Fallback: raw payload on a channel matching the MQTT topic
    channel_for(msg.topic, RAW_PAYLOAD_SCHEMA).log(
        {
            "timestamp": now_timestamp(),
            "payload": payload_str,
            "qos": msg.qos,
        }
    )

# ----- Shutdown -------------------------
def shutdown(signum=None, frame=None):
    bridge_log.info("shutting down...")
    try:
        mqtt_client.disconnect()
        mqtt_client.loop_stop()
    except Exception as e:
        bridge_log.warning(f"mqtt shutdown error: {e}")
    try:
        server.stop()
    except Exception as e:
        bridge_log.warning(f"foxglove shutdown error: {e}")
    sys.exit(0)

# ----- Setup -------------------------
mqtt_client = paho.Client(client_id="romi-mqtt-bridge", userdata=None, protocol=paho.MQTTv5)

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_subscribe = on_subscribe
mqtt_client.on_publish = on_publish
mqtt_client.on_message = on_message

mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)
mqtt_client.tls_set(tls_version=ssl.PROTOCOL_TLS)
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)

server = foxglove.start_server(
    capabilities=[Capability.ClientPublish],
    supported_encodings=["json"],
    server_listener=RomiInputListener(),
)

# ----- Signal handling -------------------------
signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

# ----- Run -------------------------
mqtt_client.connect_async(MQTT_HOST, MQTT_PORT)
mqtt_client.loop_forever(retry_first_connection=True)
# mqtt_client.loop_start()

# lastTime = 0
# while True:
#     if (time.time_ns() - lastTime) > (1000000 * 100):
#         lastTime = time.time_ns()
#         if not messageQueue.empty():
#             if (data := messageQueue.get_nowait()):
#                 mqtt_client.publish(*data)
#                 mqtt_log.info(f"Loged {data}")
#         if messageQueue.full():
#             print("QUEUE FULL")
            

