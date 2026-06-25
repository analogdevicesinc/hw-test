from dataclasses import dataclass
from pathlib import Path
from hw_tests.github import GitHub


ssh_config_path = Path.cwd() / "_ssh_config"


@dataclass
class SSHConfig:
    path: Path = ssh_config_path

    def _read_lines(self):
        if not self.path.exists():
            return ["Include ~/.ssh/config", ""]
        return self.path.read_text(encoding="utf-8").splitlines()

    def _write_lines(self, lines):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        self.path.chmod(0o600)

    def _host_block(self, host, lines):
        start = None
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.lower().startswith("host "):
                continue
            if start is not None:
                return start, index
            patterns = stripped.split()[1:]
            if host in patterns:
                start = index
        if start is None:
            return None
        return start, len(lines)

    def set_host_options(self, hosts, options):
        host_list = list(hosts)
        lines = self._read_lines()
        block = next(
            (
                block
                for host in host_list
                if (block := self._host_block(host, lines)) is not None
            ),
            None,
        )

        normalized = {key.lower(): (key, value) for key, value in options.items()}
        if block is None:
            if lines:
                lines.append("")
            lines.append(f"Host {' '.join(host_list)}")
            lines.extend(f"  {key} {value}" for key, value in options.items())
            self._write_lines(lines)
            return

        start, end = block
        lines[start] = f"Host {' '.join(host_list)}"
        seen = set()
        new_block = [lines[start]]

        for line in lines[start + 1 : end]:
            stripped = line.strip()
            key = stripped.split(None, 1)[0].lower() if stripped else ""
            if key in normalized:
                original_key, value = normalized[key]
                if key not in seen:
                    new_block.append(f"  {original_key} {value}")
                    seen.add(key)
                continue
            new_block.append(line)

        for key, (original_key, value) in normalized.items():
            if key not in seen:
                new_block.append(f"  {original_key} {value}")

        lines[start:end] = new_block
        self._write_lines(lines)

    def configure_host(self, host):
        if GitHub.in_actions():
            options = {
                "User": "ci",
                "IdentityFile": "~/.ssh/id_ecdsa",
                "CertificateFile": "~/.ssh/id_ecdsa-cert.pub",
                "IdentitiesOnly": "yes",
                "StrictHostKeyChecking": "accept-new",
            }
        else:
            options = {
                "User": "ci",
                "StrictHostKeyChecking": "accept-new",
            }
        self.set_host_options([host], options)

