"""S1 gate: every CADBackend method exists on Com/Fake with compatible signatures."""
import inspect

A_STAGE_EXEMPT = set()


def test_all_protocol_methods_implemented():
    from cadmcp.backend.fake.backend import FakeBackend
    from cadmcp.backend.protocol.protocol import CADBackend
    from cadmcp.backend.solidworks.backend import ComBackend

    for name, _ in inspect.getmembers(CADBackend, inspect.isfunction):
        if name.startswith("_"):
            continue
        if name in A_STAGE_EXEMPT:
            continue
        assert hasattr(ComBackend, name), f"ComBackend missing {name}"
        assert hasattr(FakeBackend, name), f"FakeBackend missing {name}"


def test_signatures_compatible():
    from cadmcp.backend.fake.backend import FakeBackend
    from cadmcp.backend.protocol.protocol import CADBackend
    from cadmcp.backend.solidworks.backend import ComBackend

    for name, proto_method in inspect.getmembers(CADBackend, inspect.isfunction):
        if name.startswith("_"):
            continue
        if name in A_STAGE_EXEMPT:
            continue
        proto_sig = inspect.signature(proto_method)
        com_sig = inspect.signature(getattr(ComBackend, name))
        fake_sig = inspect.signature(getattr(FakeBackend, name))

        proto_params = list(proto_sig.parameters)
        com_params = list(com_sig.parameters)
        fake_params = list(fake_sig.parameters)

        assert com_params == proto_params, (
            f"Com {name} param mismatch: proto={proto_params}, com={com_params}"
        )
        assert fake_params == proto_params, (
            f"Fake {name} param mismatch: proto={proto_params}, fake={fake_params}"
        )
