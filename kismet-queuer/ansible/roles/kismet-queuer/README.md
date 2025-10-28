# Ansible Role: kismet-queuer

This Ansible role deploys and configures the kismet-queuer service, which streams Kismet wireless monitoring data to RabbitMQ message queues.

## Requirements

- Target system: Debian/Ubuntu Linux with systemd
- Python 3.x installed on target system
- RabbitMQ server must be already installed and accessible (either locally or remotely)
- Kismet server must be already installed and running

## Role Variables

### Installation Settings

```yaml
kismet_queuer_install_dir: /opt/kismet-queuer  # Installation directory
kismet_queuer_user: kismet-queuer              # System user to run the service
kismet_queuer_group: kismet-queuer             # System group
```

### Kismet Connection Settings

```yaml
kismet_queuer_kismet_host: localhost           # Kismet server hostname
kismet_queuer_kismet_port: 2501               # Kismet WebSocket port
kismet_queuer_kismet_username: ""             # Kismet username (if using basic auth)
kismet_queuer_kismet_password: ""             # Kismet password (if using basic auth)
kismet_queuer_kismet_api_key: ""              # Kismet API key (preferred over basic auth)
```

### RabbitMQ Connection Settings

```yaml
kismet_queuer_rabbitmq_host: localhost         # RabbitMQ server hostname
kismet_queuer_rabbitmq_port: 5672             # RabbitMQ port
kismet_queuer_rabbitmq_username: guest        # RabbitMQ username
kismet_queuer_rabbitmq_password: guest        # RabbitMQ password (use Ansible Vault!)
kismet_queuer_rabbitmq_virtual_host: /        # RabbitMQ virtual host
kismet_queuer_rabbitmq_exchange: kismet_events # Exchange name
kismet_queuer_rabbitmq_exchange_type: topic   # Exchange type
```

### Application Settings

```yaml
kismet_queuer_log_level: INFO                  # Logging level (DEBUG, INFO, WARNING, ERROR)
kismet_queuer_log_format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
kismet_queuer_reconnect_delay: 5               # Seconds to wait before reconnecting
kismet_queuer_max_reconnect_attempts: 10       # Max reconnection attempts
```

### Service Settings

```yaml
kismet_queuer_service_enabled: true            # Enable service on boot
kismet_queuer_service_state: started           # Service state (started/stopped)
```

## Dependencies

None. This role assumes RabbitMQ and Kismet are already installed and configured.

## Example Playbook

### Basic Example

```yaml
- hosts: monitoring_servers
  become: yes
  roles:
    - kismet-queuer
  vars:
    kismet_queuer_kismet_api_key: "your-kismet-api-key"
    kismet_queuer_rabbitmq_username: "kismet_user"
    kismet_queuer_rabbitmq_password: "secure_password"
```

### Example with Ansible Vault for Credentials

Create a vault file for sensitive variables:

```bash
ansible-vault create vars/kismet_credentials.yml
```

Add your credentials:

```yaml
---
kismet_queuer_kismet_api_key: "your-secret-api-key"
kismet_queuer_rabbitmq_username: "kismet_user"
kismet_queuer_rabbitmq_password: "very-secure-password"
```

Use in playbook:

```yaml
- hosts: monitoring_servers
  become: yes
  vars_files:
    - vars/kismet_credentials.yml
  roles:
    - kismet-queuer
  vars:
    kismet_queuer_rabbitmq_host: rabbitmq.example.com
    kismet_queuer_kismet_host: localhost
```

Run with:

```bash
ansible-playbook -i inventory playbook.yml --ask-vault-pass
```

### Advanced Example with Custom Configuration

```yaml
- hosts: monitoring_servers
  become: yes
  roles:
    - kismet-queuer
  vars:
    # Custom installation location
    kismet_queuer_install_dir: /usr/local/kismet-queuer

    # Remote RabbitMQ server
    kismet_queuer_rabbitmq_host: rabbitmq.example.com
    kismet_queuer_rabbitmq_virtual_host: /monitoring
    kismet_queuer_rabbitmq_exchange: wireless_events

    # Enhanced logging
    kismet_queuer_log_level: DEBUG

    # Increased resilience
    kismet_queuer_max_reconnect_attempts: 20
    kismet_queuer_reconnect_delay: 10
```

## Security Considerations

1. **Credentials**: Always use Ansible Vault to encrypt sensitive variables like passwords and API keys
2. **File Permissions**: The role automatically sets config.ini to mode 600 (owner read/write only)
3. **System User**: Service runs as a dedicated non-privileged user with no login shell
4. **Systemd Security**: Service includes security hardening (NoNewPrivileges, PrivateTmp, ProtectSystem, ProtectHome)

## Directory Structure

After deployment, the installation directory will contain:

```
/opt/kismet-queuer/
├── kismet_to_queue.py   # Main application
├── requirements.txt     # Python dependencies
└── config.ini          # Configuration file (mode 600)
```

## Service Management

After installation, manage the service using systemctl:

```bash
# Check status
sudo systemctl status kismet_to_queue

# View logs
sudo journalctl -u kismet_to_queue -f

# Restart service
sudo systemctl restart kismet_to_queue

# Stop service
sudo systemctl stop kismet_to_queue
```

## Troubleshooting

### Service fails to start

1. Check logs: `sudo journalctl -u kismet_to_queue -n 50`
2. Verify config.ini has correct credentials
3. Ensure RabbitMQ is accessible from the target host
4. Verify Kismet is running and WebSocket port is accessible

### Connection issues

- RabbitMQ: Check firewall rules, verify credentials, ensure exchange exists
- Kismet: Verify API key/credentials, check Kismet is running on specified port

### Permission errors

- Ensure kismet-queuer user has read access to config.ini
- Check ownership: `ls -la /opt/kismet-queuer/`

## License

MIT

## Author Information

This role was created for deploying the kismet-queuer service.
