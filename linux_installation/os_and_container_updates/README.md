# OS and Container Updates Playbook

A comprehensive Ansible playbook for performing operating system updates across different Linux distributions, with intelligent VM detection and Docker Compose management.

## Features

- **Multi-Distribution Support**: Works with Arch Linux, RHEL/CentOS/Fedora, Ubuntu/Debian, and SUSE
- **VM Detection**: Automatically detects virtual machines and handles post-update shutdown
- **Arch Linux AUR Support**: Uses `yay` package manager for AUR packages on Arch Linux
- **Docker Compose Management**: Automatically discovers and updates Docker Compose projects
- **Intelligent Post-Update Actions**: Different behavior for VMs vs physical machines
- **Comprehensive Logging**: Detailed logs and status reporting
- **Safety Features**: Backup options, timeouts, and error handling

## Quick Start

### Basic Usage

```bash
# Update all hosts in inventory
ansible-playbook os_and_container_updates.yaml

# Update specific host group
ansible-playbook os_and_container_updates.yaml -e "target_hosts=webservers"

# Update specific host
ansible-playbook os_and_container_updates.yaml -e "target_hosts=myserver.example.com"
```

### Common Use Cases

```bash
# Skip individual roles (new method)
ansible-playbook os_and_container_updates.yaml -e "skip_os_updates=true"
ansible-playbook os_and_container_updates.yaml -e "skip_docker_updates=true"  
ansible-playbook os_and_container_updates.yaml -e "skip_post_actions=true"
ansible-playbook os_and_container_updates.yaml -e "skip_system_detection=true"  # Not recommended

# Skip multiple roles at once
ansible-playbook os_and_container_updates.yaml -e "skip_docker_updates=true skip_post_actions=true"

# Legacy methods (still supported for backward compatibility)
ansible-playbook os_and_container_updates.yaml -e "perform_docker_updates=false"
ansible-playbook os_and_container_updates.yaml -e "perform_os_updates=false"

# Configuration options
ansible-playbook os_and_container_updates.yaml -e "auto_shutdown_vms=false"    # Keep VMs running
ansible-playbook os_and_container_updates.yaml -e "backup_before_update=true"
# Note: reboot_after_updates=true is IGNORED (physical machines never auto-reboot)

# Dry run to see what would be updated
ansible-playbook os_and_container_updates.yaml -e "dry_run_mode=true" --check

# Skip everything except system detection (for testing)
ansible-playbook os_and_container_updates.yaml -e "skip_os_updates=true skip_docker_updates=true skip_post_actions=true"
```

## Roles Overview

### system_detection
- Detects if the system is a virtual machine or physical hardware
- Identifies OS distribution and version
- Checks for Docker installation and running status
- Verifies yay availability on Arch Linux systems

### os_updates
- Handles package updates for different Linux distributions
- Uses appropriate package managers (pacman/yay, dnf/yum, apt, zypper)
- Special handling for Arch Linux AUR packages with yay
- Checks for required reboots after updates

### docker_compose_updates
- Discovers running Docker Compose projects using container labels
- Extracts project working directories from container metadata
- Performs `docker compose down && docker compose pull && docker compose up -d`
- Verifies services are running after updates

### post_update_actions
- Handles VM shutdown logic (VMs shutdown, physical machines don't)
- Manages system reboots when required
- Comprehensive logging and status reporting
- Safety delays and confirmation prompts

## Role Skip Control

Each role in the playbook can be individually skipped using skip variables:

### Skip Variables

| Variable | Default | Description | Recommendation |
|----------|---------|-------------|----------------|
| `skip_system_detection` | `false` | Skip VM/OS detection | ⚠️ Not recommended - other roles depend on this |
| `skip_os_updates` | `false` | Skip operating system updates | Safe to skip |
| `skip_docker_updates` | `false` | Skip Docker Compose updates | Safe to skip |
| `skip_post_actions` | `false` | Skip post-update actions (shutdown/reboot) | Safe to skip |

### Examples by Use Case

```bash
# Development: Only check system info, no updates
ansible-playbook os_and_container_updates.yaml -e "skip_os_updates=true skip_docker_updates=true skip_post_actions=true"

# Production: Update OS only, no VM shutdown  
ansible-playbook os_and_container_updates.yaml -e "skip_docker_updates=true skip_post_actions=true"

# Docker-only updates
ansible-playbook os_and_container_updates.yaml -e "skip_os_updates=true skip_post_actions=true"

# Maintenance mode: No shutdowns but update everything
ansible-playbook os_and_container_updates.yaml -e "skip_post_actions=true"

# Testing: Skip detection for speed (not recommended for production)
ansible-playbook os_and_container_updates.yaml -e "skip_system_detection=true"
```

### Backward Compatibility

The following legacy variables are still supported:

| Legacy Variable | Equivalent Skip Variable | Status |
|-----------------|--------------------------|---------|
| `perform_os_updates=false` | `skip_os_updates=true` | ✅ Supported |
| `perform_docker_updates=false` | `skip_docker_updates=true` | ✅ Supported |

## Configuration

### Variables File (`vars.yaml`)

Key configuration options:

```yaml
# Basic behavior
perform_os_updates: true
perform_docker_updates: true
auto_shutdown_vms: true

# Safety and backup
backup_before_update: false
update_timeout: 3600

# Arch Linux specific
use_yay_for_aur: true
yay_update_args: "--noconfirm --noprogressbar"
```

### Inventory Requirements

Your inventory should include the target hosts:

```ini
[webservers]
web01.example.com
web02.example.com

[databases]
db01.example.com

[arch_systems]
arch01.example.com
arch02.example.com
```

## Supported Operating Systems

| OS Family | Package Manager | AUR Support | Notes |
|-----------|-----------------|-------------|--------|
| Arch Linux | pacman + yay | ✅ | Full AUR support with yay |
| RHEL/CentOS/Fedora | dnf/yum | ❌ | Enterprise Linux support |
| Ubuntu/Debian | apt | ❌ | Debian-based distributions |
| SUSE | zypper | ❌ | openSUSE/SLES support |

## Docker Compose Discovery

The playbook automatically discovers Docker Compose projects by:

1. Finding running containers with `com.docker.compose.project` labels
2. Extracting working directories using `docker inspect`
3. Looking for compose files in the standard locations:
   - `docker-compose.yml`
   - `docker-compose.yaml`  
   - `compose.yml`
   - `compose.yaml`

This approach is more reliable than the bash alias method and integrates well with Ansible.

## VM Detection Logic

The playbook uses two reliable methods to detect virtual machines:

1. **systemd-detect-virt** (primary method)
2. **DMI information** (product name and vendor)

Supported virtualization platforms:
- VMware (ESXi, Workstation, Player)
- KVM/QEMU
- Xen
- VirtualBox
- Hyper-V
- Docker containers

## Post-Update Behavior

| System Type | Default Action | Override Options | Policy |
|-------------|----------------|------------------|---------|
| Virtual Machine | Shutdown after successful updates | `auto_shutdown_vms=false` | ✅ **SHUTDOWN ONLY** (never reboot) |
| Physical Machine | Continue running + manual reboot warning | None | 🚫 **NEVER AUTO-REBOOT** (manual only) |

### **Important Policy Changes:**

- **Physical Machines**: NEVER automatically reboot, regardless of settings
- **Virtual Machines**: Only shutdown (never reboot), even if reboot is required  
- **Manual Intervention**: Physical machines get clear warnings about required manual reboots

## Error Handling

The playbook includes comprehensive error handling:

- **Package Update Failures**: Continue with other roles, log errors
- **Docker Compose Failures**: Attempt recovery, continue with other projects
- **Network Issues**: Timeout protection, retry logic
- **Permission Issues**: Clear error messages and suggestions

## Logging

All activities are logged to `/var/log/ansible-updates.log`:

```
2024-01-15 10:30:00: Update process completed on webserver01
  - System Type: VM
  - OS Updates: Success
  - Docker Updates: Success
  - Action Taken: Shutdown
```

## Security Considerations

- **Privilege Escalation**: Uses `become: true` for system updates
- **User Context**: yay runs as regular user (not root) for AUR safety
- **Timeouts**: All operations have configurable timeouts
- **Validation**: Verifies services after Docker updates

## Troubleshooting

### Common Issues

1. **yay not found on Arch Linux**
   ```bash
   # Install yay manually first
   sudo pacman -S yay
   ```

2. **Docker Compose projects not detected**
   - Ensure containers have proper compose labels
   - Check that Docker daemon is running
   - Verify compose files exist in detected directories

3. **VM not shutting down**
   - Check `auto_shutdown_vms` setting
   - Verify VM detection worked correctly
   - Review error logs

### Debug Mode

Run with increased verbosity:

```bash
ansible-playbook os_and_container_updates.yaml -vvv
```

### Dry Run

Preview changes without making them:

```bash
ansible-playbook os_and_container_updates.yaml --check --diff
```

## Examples

### Update Only VMs
```bash
ansible-playbook os_and_container_updates.yaml --limit "$(ansible-inventory --list | jq -r '.all.children | keys[]' | xargs -I {} ansible -m setup {} --tree /tmp/facts | grep -l 'ansible_virtualization_type.*vm')"
```

### Skip Arch Linux Hosts
```bash
ansible-playbook os_and_container_updates.yaml --limit '!arch_systems'
```

### Update with Full Logging
```bash
ansible-playbook os_and_container_updates.yaml -e "detailed_logging=true" -v
```

## Contributing

When modifying this playbook:

1. Test on different distributions
2. Verify VM detection logic
3. Test Docker Compose discovery
4. Update documentation

## License

This playbook is part of the linux-helpers project. See the main repository LICENSE file for details.
