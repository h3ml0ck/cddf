# CDDF Ansible Playbooks

This directory contains Ansible resources for provisioning CDDF edge nodes that run the Watchtower stack.

## Contents

- `edge-node-watchtower-playbook.yml` – Provisions a Raspberry Pi OS (Debian-based) edge node with the CDDF toolchain, SDR dependencies, and Kismet services.
- `inventory.ini.example` – Template static inventory. Copy to `inventory.ini` (gitignored) and point the hosts at your own Watchtower nodes.

## Prerequisites

1. Install Ansible (version 2.14+ recommended).
2. Copy `inventory.ini.example` to `inventory.ini` and edit it to match your environment.
3. Ensure passwordless SSH or SSH key-based access to the target hosts. The default username in the inventory is `pi`.
4. Optional: export `ANSIBLE_CONFIG`, `ANSIBLE_HOST_KEY_CHECKING=False`, or other Ansible environment variables that fit your workflow.

## Example Commands

Show the hosts from the provided inventory:

```bash
ansible-inventory -i inventory.ini --list
```

Ping all Watchtower hosts to verify connectivity:

```bash
ansible all -i inventory.ini -m ping
```

Run the playbook against every host in the inventory, prompting for the privilege escalation password:

```bash
ansible-playbook edge-node-watchtower-playbook.yml \
  -i inventory.ini \
  --ask-become-pass
```

Limit execution to a single host from the inventory:

```bash
ansible-playbook edge-node-watchtower-playbook.yml \
  -i inventory.ini \
  --limit cddf-watchtower-a.local \
  --ask-become-pass
```

Run the playbook against an ad-hoc host without editing the inventory:

```bash
ansible-playbook edge-node-watchtower-playbook.yml \
  -i "watchtower-a.local," \
  -u pi \
  --become \
  --ask-become-pass
```

Check which tasks would run without making changes:

```bash
ansible-playbook edge-node-watchtower-playbook.yml \
  -i inventory.ini \
  --check \
  --diff
```

## Additional Tips

- Many tasks require elevated privileges; use `--become` and provide the sudo password when prompted.
- Review and customize `inventory.ini` (from `inventory.ini.example`) to match your environment (hostnames, users, Python interpreter path).
- To speed up repeated runs, consider enabling Ansible fact caching (`ansible.cfg`) or setting up SSH control master options.

