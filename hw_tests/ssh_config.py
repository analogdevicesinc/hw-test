from dataclasses import dataclass
from pathlib import Path


def host_aliases(host):
    aliases = [host]
    if "." not in host:
        aliases.append(f"{host}.local")
    elif host.endswith(".local"):
        aliases.append(host.removesuffix(".local"))
    return aliases


def parse_hosts(value):
    hosts = []
    for raw_line in (value or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        if "=" in line:
            host, address = line.split("=", 1)
        else:
            parts = line.split()
            if len(parts) < 2:
                raise ValueError(f"Invalid ssh-hosts entry: {line}")
            host, address = parts[:2]

        host = host.strip()
        address = address.strip()
        if not host or not address:
            raise ValueError(f"Invalid ssh-hosts entry: {line}")
        hosts.append((host, address))
    return hosts


@dataclass
class SSHConfig:
    path: Path = Path.home() / ".ssh" / "config"

    def _read_lines(self):
        if not self.path.exists():
            return []
        return self.path.read_text(encoding="utf-8").splitlines()

    def _write_lines(self, lines):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
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

    def set_strict_host(self, host, value):
        self.set_host_options([host], {"StrictHostKeyChecking": value})

    def configure_host(self, host, address):
        self.set_host_options(
            host_aliases(host),
            {
                "HostName": address,
                "User": "ci",
                "IdentityFile": "~/.ssh/id_ecdsa",
                "CertificateFile": "~/.ssh/id_ecdsa-cert.pub",
                "IdentitiesOnly": "yes",
                "HostKeyAlias": address,
                "StrictHostKeyChecking": "accept-new",
            },
        )

    def configure_hosts(self, ssh_hosts=None, host=None):
        if ssh_hosts:
            for h, address in parse_hosts(ssh_hosts):
                self.configure_host(h, address)
        elif host:
            self.set_strict_host(host, 'accept-new')

