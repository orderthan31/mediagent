"""Normal broker chaining must advance staged application controls without another event."""

from types import SimpleNamespace

from video_service.rabbitmq_controller import BrokerController


def test_staged_normal_controls_advance_until_the_next_real_agent():
    class Runtime:
        store = SimpleNamespace(storage_kind="s3")
        fleet = None

        def __init__(self):
            self.step = 0

        def get(self, *_):
            runs = [{"id": str(i), "status": "completed"} for i in range(self.step)]
            if self.step == 3:
                runs.append({"id": "encode", "status": "running"})
            return {
                "status": "waiting" if self.step < 3 else "running",
                "snapshot": {"definition": {"nodes": [1, 2, 3, 4]}},
                "runs": runs,
            }

        def claim_next(self, *_):
            self.step += 1

    runtime = Runtime()
    controller = BrokerController(runtime, lambda: None)
    published = []
    controller.publish_exact = lambda owner, job, attempt: published.append(attempt)
    controller.dispatch("owner", "this-job")
    assert runtime.step == 3 and published == ["encode"]
