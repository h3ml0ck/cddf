# Kismet-Queuer Ansible Deployment

This directory contains an Ansible role and example playbooks for deploying the kismet-queuer service.

## Quick Start

### 1. Set up your inventory

```bash
cp inventory.example inventory
# Edit inventory with your server details
nano inventory
```

### 2. Configure credentials (Recommended: Use Ansible Vault)

```bash
# Create vars directory if it doesn't exist
mkdir -p vars

# Copy the example credentials file
cp vars/credentials.yml.example vars/credentials.yml

# Edit with your actual credentials
nano vars/credentials.yml

# Encrypt the file
ansible-vault encrypt vars/credentials.yml
```

### 3. Update playbook to use credentials

Edit `playbook.yml` and add the vars_files section:

```yaml
- name: Deploy kismet-queuer service
  hosts: kismet_servers
  become: yes
  vars_files:
    - vars/credentials.yml
  roles:
    - kismet-queuer
```

### 4. Run the playbook

```bash
# With vault encryption
ansible-playbook -i inventory playbook.yml --ask-vault-pass

# Without vault (not recommended for production)
ansible-playbook -i inventory playbook.yml
```

## Directory Structure

```
ansible/
├── README.md                          # This file
├── playbook.yml                       # Example playbook
├── inventory.example                  # Example inventory file
├── vars/
│   └── credentials.yml.example        # Example vault file for credentials
└── roles/
    └── kismet-queuer/                 # Ansible role
        ├── README.md                  # Role documentation
        ├── defaults/main.yml          # Default variables
        ├── tasks/main.yml             # Deployment tasks
        ├── templates/                 # Jinja2 templates
        │   ├── config.ini.j2
        │   └── kismet_to_queue.service.j2
        ├── handlers/main.yml          # Service handlers
        └── meta/main.yml              # Role metadata
```

## Configuration

### Required Variables

You must set these variables either in the playbook, inventory, or vars file:

- `kismet_queuer_kismet_api_key` (or username/password for Kismet)
- `kismet_queuer_rabbitmq_username`
- `kismet_queuer_rabbitmq_password`

### Optional Variables

See `roles/kismet-queuer/defaults/main.yml` for all available variables.

Common overrides:

```yaml
# Use remote RabbitMQ server
kismet_queuer_rabbitmq_host: rabbitmq.example.com

# Change installation directory
kismet_queuer_install_dir: /usr/local/kismet-queuer

# Increase logging verbosity
kismet_queuer_log_level: DEBUG

# Adjust reconnection behavior
kismet_queuer_reconnect_delay: 10
kismet_queuer_max_reconnect_attempts: 20
```

## Examples

### Deploy to single server

```bash
ansible-playbook -i inventory playbook.yml --limit monitoring-01
```

### Deploy to all servers

```bash
ansible-playbook -i inventory playbook.yml
```

### Check mode (dry run)

```bash
ansible-playbook -i inventory playbook.yml --check
```

### Verbose output for debugging

```bash
ansible-playbook -i inventory playbook.yml -vvv
```

## Testing

After deployment, verify the service is running:

```bash
# Check service status
ansible kismet_servers -i inventory -m shell -a "systemctl status kismet_to_queue" -b

# View service logs
ansible kismet_servers -i inventory -m shell -a "journalctl -u kismet_to_queue -n 20" -b
```

## Troubleshooting

### Connection errors

```bash
# Test connectivity
ansible kismet_servers -i inventory -m ping

# Check Python version
ansible kismet_servers -i inventory -m shell -a "python3 --version"
```

### Service not starting

```bash
# View detailed logs
ansible kismet_servers -i inventory -m shell -a "journalctl -u kismet_to_queue -n 50 --no-pager" -b

# Check config file
ansible kismet_servers -i inventory -m shell -a "cat /opt/kismet-queuer/config.ini" -b
```

### Update service after code changes

```bash
# Re-run the playbook (will restart service if files changed)
ansible-playbook -i inventory playbook.yml
```

## Security Best Practices

1. **Always use Ansible Vault** for credentials in production
2. **Restrict inventory file permissions**: `chmod 600 inventory`
3. **Use SSH keys** instead of password authentication
4. **Keep vault password secure** - don't commit it to version control
5. **Use different credentials** for each environment (dev/staging/prod)

## Support

For role-specific documentation, see `roles/kismet-queuer/README.md`
