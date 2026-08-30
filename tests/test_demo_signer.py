"""External demo signer keeps private material out of server/repository output."""

from __future__ import annotations

import json
import stat

from scripts.pactra_demo_signer import main


def test_generate_writes_external_key_0600_without_printing_private_material(tmp_path, capsys):
    key_path = tmp_path / "demo-approver.pem"
    code = main(
        [
            "generate",
            "--private-key-path",
            str(key_path),
            "--signing-key-id",
            "pytest-external-demo-key",
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    parsed = json.loads(output)
    assert parsed["signing_key_id"] == "pytest-external-demo-key"
    assert len(parsed["demo_approver_public_key_hex"]) == 64
    assert "PRIVATE KEY" not in output
    assert "BEGIN" not in output
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_generate_refuses_a_private_key_inside_the_repository(capsys):
    code = main(
        [
            "generate",
            "--private-key-path",
            "data/forbidden-demo-private.pem",
            "--signing-key-id",
            "pytest-external-demo-key",
        ]
    )
    assert code == 2
    assert "outside the PACTRA repository" in capsys.readouterr().err
