import paho.mqtt.client as mqtt
import time

client = mqtt.Client()

client.connect("localhost", 1883, 60)

for i in range(5):
    message = f"GridSense test message {i}"
    client.publish("station/test", message)
    print("Published:", message)
    time.sleep(2)

client.disconnect()

