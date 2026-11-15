"""swarmbox_voice: the host library of the `voice` tool (stdlib only, Python 3.9+).

The planner turns an utterance plus the tmux state into a plan; the HOST validates, rates and executes it. This
package is that host side. Stable API (other parts of the tool import only these names):

    contract.build_input / contract.parse_output / contract.validate_plan / contract.ContractError
    risk.plan_risk / risk.action_risk / risk.classify_command
    context.snapshot / context.limit_context / context.build_input / context.redact
    planners.discover / planners.find / planners.run_planner / planners.PlannerResult
    executor.execute / executor.ExecutorError
    stt.transcribe / stt.SttError / stt.check_wav          the ONE recognizer function (whisper.cpp)
    store.PlanStore / store.PlanError                      pending plans: random id, TTL, one shot
    server.Service / server.make_server                    the loopback HTTP service
    models.fetch / models.MODELS                           pinned multilingual Whisper models
    tmuxrun.Tmux
    config.load / config.Config / config.ConfigError

Nothing here uses the network, a model or a microphone.
"""

__all__ = ["config", "context", "contract", "executor", "models", "planners", "risk", "server", "store", "stt", "tmuxrun"]
