"""swarmbox_voice: the library of the `voice` tool, an INPUT of the box (stdlib only, Python 3.9+): it hears and publishes goals on the bus.
Stable API (other parts of the tool import only these names):

    stt.transcribe / stt.SttError / stt.check_wav          the ONE recognizer function (whisper.cpp)
    busclient.publish                                      a message on the topic of voice.topic, source `voice`
    server.Service / server.make_server                    the loopback HTTP service (health, audio)
    front.run                                              the web terminal port: page, health and audio next to ttyd
    models.fetch / models.MODELS                           pinned multilingual Whisper models
    config.load / config.Config / config.ConfigError

Nothing here plans or executes: what is done with a goal is the business of whoever subscribes to it (whoever listens on the topic).
Nothing here uses the network, a model or a microphone by itself.
"""

__all__ = ["busclient", "config", "front", "models", "server", "stt"]
