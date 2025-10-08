# Bastion Bridge Creation Role

This Ansible role creates and configures a Linux bridge from an existing network interface that has an IP address attached to it. It's designed to replicate Cockpit's bridge functionality in an enterprise environment.

## Features

- ✅ Automatic network interface detection
- ✅ SSH-safe bridge transitions 
- ✅ Enterprise-grade validation
- ✅ NetworkManager integration
- ✅ Comprehensive error handling
- ✅ No hardcoded network assumptions

## Requirements

- Ansible 2.9+
- NetworkManager installed and running
- `community.general` collection
- `ansible.utils` collection

## Variables

### Required Variables
None - all network parameters are auto-detected.

### Optional Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `NETWORK_BRIDGE` | Name of the bridge to create | `br0` |
| `BRIDGE_STP` | Enable Spanning Tree Protocol | `false` |
| `BRIDGE_PRIORITY` | Bridge priority (lower = higher priority) | `32768` |
| `BRIDGE_MTU` | Maximum Transmission Unit | `1500` |
| `NETWORK_PREFIX` | Override network prefix | `22` |

## Usage

Include this role in your playbook:

```yaml
- name: Setup Network Bridge
  ansible.builtin.include_role:
    name: bastion_bridge_creation
```

## How It Works

1. **Auto-Detection**: Finds the primary network interface with IP configuration
2. **Validation**: Ensures all required network parameters are available
3. **Bridge Creation**: Creates bridge connection via NetworkManager
4. **Port Configuration**: Adds physical interface as bridge port
5. **SSH-Safe Activation**: Activates bridge without dropping SSH connection
6. **Validation**: Confirms bridge is operational with correct network prefix

## Network Prefix Detection

The role uses multiple fallback methods to determine the correct network prefix:

1. **User Override**: `NETWORK_PREFIX` variable (highest priority)
2. **Netmask Calculation**: From interface netmask via `ansible.utils.ipaddr`
3. **Ansible Facts**: From `ansible_default_ipv4.prefix`
4. **Fail-Safe**: Clear error if all methods fail (no hardcoded fallbacks)

## Enterprise Features

- **Pre-flight Validation**: Comprehensive parameter checking
- **SSH-Safe Operations**: Background activation prevents connection loss
- **Atomic Operations**: All-or-nothing configuration changes  
- **Error Recovery**: Detailed error messages with resolution steps
- **Zero Hardcoding**: No assumptions about network configuration

## Error Handling

If network prefix detection fails:

```
Unable to determine network prefix. All detection methods failed.
Resolution: Set NETWORK_PREFIX variable (e.g., -e NETWORK_PREFIX=22) or verify interface network configuration.
```

## Dependencies

This role has no dependencies and can be used independently or with other roles.

## License

MIT

## Author

Enterprise System Administrator
