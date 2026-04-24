#
# Copyright 2021 HiveMQ GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import time
import ssl
import paho.mqtt.client as paho
import paho.mqtt.publish as pub
import foxglove

from foxglove.websocket import (Capability, ServerListener)
mqttClient = paho.Client(client_id="", userdata=None, protocol=paho.MQTTv5)

######### FOXGLOVE
class ExampleListener(ServerListener):
    def on_message_data(
        self,
        client: Client,
        client_channel_id: int,
        data: bytes,
    ) -> None:
        print(f"Message from client {client.id} on channel {client_channel_id}")
        print(f"Data: {data!r}")
        d = eval(str(data)[2:-1])
        print(d["linear"]["x"])
        mqttClient.publish("/test", d["linear"]["x"])

listener = ExampleListener()

server = foxglove.start_server(
  capabilities=[Capability.ClientPublish],
  supported_encodings=["json"],
  server_listener=listener,
)

# custom_message_channel = Channel("/custom", message_encoding="json")
# custom_message_channel.log({"hello": "world"})

# esp_button_channel = foxglove.Channel("/button0", message_encoding="json")
# romi_button_channel = foxglove.Channel("/button", message_encoding="json")
# romi_timer_channel = foxglove.Channel("/timer", message_encoding="json")
# button_channel.log({"pressed": True, "timestamp": time.time()})

######### MQTT

# setting callbacks for different events to see if it works, print the message etc.
def on_connect(client, userdata, flags, rc, properties=None):
    print("CONNACK received with code %s." % rc)

# with this callback you can see if your publish was successful
def on_publish(client, userdata, mid, properties=None):
    print("mid: " + str(mid))

# print which topic was subscribed to
def on_subscribe(client, userdata, mid, granted_qos, properties=None):
    print("Subscribed: " + str(mid) + " " + str(granted_qos))

# print message, useful for checking if it was successful
def on_message(client, userdata, msg):
    print(msg.topic + " " + str(msg.qos) + " " + str(msg.payload))
    # if msg.topic == "button0":
    #     esp_button_channel.log({"pressed": True, "timestamp": time.time()})
    #     print("button0 pressed, logged to Foxglove @ " + str(time.time()))
    # if msg.topic == "button":
    #     romi_button_channel.log({"pressed": True, "timestamp": time.time()})
    #     print("romi button pressed, logged to Foxglove @ " + str(time.time()))
    # if msg.topic == "timer":
    #     romi_timer_channel.log({"timestamp": time.time()})
    #     print("romi timer elapsed, logged to Foxglove @ " + str(time.time()))
    foxglove.log(msg.topic, {"payload": str(msg.payload), "qos": msg.qos, "timestamp": time.time()})
# using MQTT version 5 here, for 3.1.1: MQTTv311, 3.1: MQTTv31
# userdata is user defined data of any type, updated by user_data_set()
# client_id is the given name of the client

mqttClient.on_connect = on_connect

# enable TLS for secure connection
mqttClient.tls_set(tls_version=ssl.PROTOCOL_TLS) # mqtt.client.ssl.PROTOCOL_TLS
# set username and password
mqttClient.username_pw_set("RBE2002macbook", "RBE2002macbook")
# connect to HiveMQ Cloud on port 8883 (default for MQTT)
mqttClient.connect("19e34349420d4b38911b39f4bda2e3ff.s1.eu.hivemq.cloud", 8883)

# setting callbacks, use separate functions like above for better visibility
mqttClient.on_subscribe = on_subscribe
mqttClient.on_message = on_message
mqttClient.on_publish = on_publish

# subscribe to all topics of encyclopedia by using the wildcard "#"
# client.subscribe("encyclopedia/#", qos=1)
# client.subscribe("button0/#", qos=1)
mqttClient.subscribe("#", qos=1)

# a single publish, this can also be done in loops, etc.
# client.publish("encyclopedia/temperature", payload="hot", qos=1)

# loop_forever for simplicity, here you need to stop the loop manually
# you can also use loop_start and loop_stop
mqttClient.loop_forever()
