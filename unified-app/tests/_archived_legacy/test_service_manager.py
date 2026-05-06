from orchestrator.service_manager import ServiceManager


class _FakeBridge:
    def __init__(self):
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self):
        self.initialized = True

    async def get_capabilities(self):
        return {
            "desktop": {"target_server": "desktop_mcp"},
            "cli": {"target_server": "cli_mcp"},
            "web": {"target_server": "browser_mcp"},
        }

    async def shutdown(self):
        self.shutdown_called = True


def test_health_check_all_reflects_core_capabilities(monkeypatch):
    fake_bridge = _FakeBridge()
    monkeypatch.setattr("orchestrator.service_manager.TrinityBridge", lambda: fake_bridge)

    manager = ServiceManager()
    health = manager.health_check_all()

    assert health["desktop"]["status"] == "ok"
    assert health["cli"]["status"] == "ok"
    assert health["browser"]["status"] == "ok"
    assert fake_bridge.initialized is True


def test_start_all_is_core_readiness_check(monkeypatch):
    fake_bridge = _FakeBridge()
    monkeypatch.setattr("orchestrator.service_manager.TrinityBridge", lambda: fake_bridge)

    manager = ServiceManager()

    assert manager.start_all() is True


def test_stop_all_shuts_down_bridge(monkeypatch):
    fake_bridge = _FakeBridge()
    monkeypatch.setattr("orchestrator.service_manager.TrinityBridge", lambda: fake_bridge)

    manager = ServiceManager()
    manager.start_all()
    manager.stop_all()

    assert fake_bridge.shutdown_called is True
