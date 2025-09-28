# Grafana Alloy Logging Deployment

This Ansible playbook deploys [Grafana Alloy](https://grafana.com/docs/alloy/) for log collection and forwards logs to [Grafana Loki](https://grafana.com/docs/loki/).

It is using the pre-built binary to provide a unified deployment across various distros including EndlessOS which is immutable. As such, the binary is placed in the `/root` because this directory is writable and persistent across all tested Linux OSes tested.

## Prerequisites

- Ansible installed on control node
- SSH access to target hosts with sudo privileges
- Target systems running Linux with systemd
- A running Loki instance to receive logs

## Quick Start

### 1. Configure Variables

Edit `vars.yaml` to match your environment:

```yaml
# ====== LOKI CONNECTION ======
loki_host: "your-loki-server.example.com"  # CHANGE THIS
loki_host_port: 3100

# ====== LABELS FOR LOGS ======
external_labels:
  environment: "production"  # Change as needed (dev, staging, prod)
```

### 2. Update Inventory

Modify `inventory` to include your target hosts:

```ini
[alloy_hosts]
192.168.1.10 ansible_user=root
server2.example.com ansible_user=root
```

### 3. Run the Playbook

```bash
ansible-playbook -i inventory deploy_alloy.yaml
```

For AWX/Semaphore, use the JSON format:
```bash
ansible-playbook -i inventory -e @vars.json deploy_alloy.yaml
```

## Configuration Options

All settings are in `vars.yaml` (or `vars.json`):

- **Installation paths**: Where Alloy is installed (`/root/` by default)
- **Log collection**: Enable/disable specific log types (auth, kernel, syslog, etc.)
- **DNS logging**: Configure NetworkManager to use dnsmasq for DNS query logging
- **Performance tuning**: Batch sizes, timeouts, retention settings
- **Labels**: Custom labels attached to all logs

## Verification

Check that Alloy is running:

```bash
# Service status
sudo systemctl status alloy

# Health check
curl http://localhost:12345/ready

# View logs
sudo journalctl -u alloy -f
```

## DNS Logging (Optional)

To enable DNS query logging via NetworkManager's dnsmasq plugin:

1. **Enable in configuration**:
   ```yaml
   log_dns: true
   ```

2. **Define target hosts** in inventory:
   ```ini
   [log_dns]
   server1.example.com ansible_user=root
   server2.example.com ansible_user=root
   ```

**What this does:**
- Configures NetworkManager to use dnsmasq (`dns=dnsmasq`)
- Enables DNS query logging (`log-queries` in `/etc/NetworkManager/dnsmasq.d/log`)
- Creates proper dnsmasq configuration directory structure
- DNS queries are logged to syslog and captured by Alloy alongside other system logs

**Requirements:** Target systems must use NetworkManager for network management (most modern Linux distributions).

## Available Tags

- `download` - Only download/install Alloy binary
- `configure` - Only update configuration files
- `dns` - Only configure NetworkManager DNS logging
- `networkmanager` - NetworkManager-related tasks

Example:
```bash
ansible-playbook -i inventory deploy_alloy.yaml --tags configure
```

## Smart Binary Management

The playbook intelligently manages Alloy versions:
- ✅ Checks if correct version is already installed
- ✅ Skips download when version matches
- ✅ Only downloads when version update is needed

## Documentation

- **Grafana Alloy**: https://grafana.com/docs/alloy/
- **Grafana Loki**: https://grafana.com/docs/loki/

## Files

- `deploy_alloy.yaml` - Main playbook
- `vars.yaml` / `vars.json` - Configuration variables  
- `inventory` - Target hosts
- `templates/` - Alloy configuration templates
- `roles/` - Download and configuration roles