"""Broker isolation proof: no retained message
survives into the next test.

Two tests that only make sense together: the first leaves retained messages on the broker, the
second asserts that a fresh subscriber to `#` gets none. With one broker per test (the `broker`
fixture) the second test must pass in any order. The proof run puts them in one process and
alternates them, so every a→b and b→a transition is exercised:

    pytest ... tests/ha/test_broker_isolation.py -n 0 --count=20 --repeat-scope=module

Under xdist they may land on different workers; they still pass, they just prove less.
"""

from __future__ import annotations

import threading
import uuid

import paho.mqtt.client as paho

from conftest import Broker

# Topics like the devices publish them retained (Shelly status, Victron Venus values).
_RETAINED = [f"pytest/isolation/{i}/state" for i in range(5)]


def _retained_on_broker(broker: Broker) -> list[str]:
    """Topics with a retained message: subscribe `#` with a fresh client, then a sentinel.

    The broker sends retained messages in reply to the subscribe, before any later publish to
    this client, so once the (non-retained) sentinel arrives every retained message has too.
    """
    sentinel = f"pytest/sentinel/{uuid.uuid4().hex}"
    retained: list[str] = []
    done = threading.Event()

    def on_message(_c: paho.Client, _u: object, msg: paho.MQTTMessage) -> None:
        if msg.topic == sentinel:
            done.set()
        elif msg.retain and msg.payload:
            retained.append(msg.topic)

    client = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=f"probe-{sentinel[-8:]}")
    client.on_message = on_message
    client.connect("127.0.0.1", broker.port)
    client.loop_start()
    try:
        client.subscribe("#", qos=1)
        client.publish(sentinel, "x", qos=1).wait_for_publish(5)
        assert done.wait(5), "sentinel not received"
    finally:
        client.disconnect()  # before loop_stop: wakes the network thread at once
        client.loop_stop()
    return retained


def test_a_leaves_retained_messages(broker: Broker) -> None:
    """Publish retained messages and leave them on the broker (the would-be leak)."""
    for topic in _RETAINED:
        broker.publish(topic, {"leak": True}, retain=True)
    # Self-check: the probe really sees retained messages, so test_b's empty result is real.
    assert sorted(_retained_on_broker(broker)) == sorted(_RETAINED)


def test_b_sees_no_retained_messages(broker: Broker) -> None:
    """A test never sees a retained message from an earlier test."""
    assert _retained_on_broker(broker) == []
