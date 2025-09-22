# OpenShift KVM Prerequisites
## 🏗️ Infrastructure Architecture Overview

This automation assumes a **three-tier architecture**:

```
┌─────────────┐    ┌─────────────┐    ┌─────────────────┐
│   Ansible   │────│  KVM Host   │────│  OpenShift VMs  │
│     Host    │    │             │    │   (Created)     │
│             │    │ (Hypervisor)│    └─────────────────┘
└─────────────┘    └─────────────┘
       │
┌─────────────┐    ┌─────────────┐
│   Bastion   │    │    DNS      │
│    Host     │    │   Server    │
│ (Installer) │    │ (pfSense)   │
└─────────────┘    └─────────────┘
       │
┌─────────────┐
│   Vault     │
│   Server    │
│ (Optional)  │
└─────────────┘
```

## 🎯 Core Infrastructure Requirements

### 1. Ansible Host (Ansible Controller)
**Purpose**: Runs Ansible playbooks and coordinates deployment

**Requirements:**
- RHEL/CentOS 8+ or compatible Linux distribution  
- Ansible 2.9+ installed
- Python 3.6+ with required modules:
  - `hvac` (for Vault integration)
  - `libvirt-python` (for KVM management)
- SSH access to all target hosts
- Network connectivity to all infrastructure components

**Required Ansible Collections:**
```bash
ansible-galaxy collection install -r requirements.yml
```
- `community.libvirt`
- `community.hashi_vault`
- `ansible.posix` 
- `pfsensible.core` (if using pfSense DNS)

### 2. KVM Host (Hypervisor)
**Purpose**: Runs the OpenShift cluster virtual machines

#### Hardware Requirements
- **CPU**: AMD/Intel with virtualization extensions (VT-x/AMD-V)
- **Nested Virtualization**: Must be enabled/supported
- **RAM**: Minimum 50GB (16GB per control plane node × 3 + overhead)
- **Storage**: 400GB+ fast storage (NVMe preferred)
- **Network**: Minimum 2 network interfaces recommended

#### Software Requirements
- **OS**: RHEL 8/9, CentOS Stream, AlmaLinux, or Rocky Linux
- **Services**: `libvirtd` will be enabled and started by automation
- **User Groups**: Deploy user will be added to `libvirt` group by automation

#### Network Configuration
- **Bridge Networks**: Pre-configured bridge interfaces
  - Default: `br0` (assumes this exists)
- **IP Ranges**: Non-conflicting IP address ranges for VM assignments

#### VLAN Support (Optional)
If using VLANs (`VLANS.enabled: true`):
- Network interface bonding capability
- VLAN tagging support on switches
- Proper VLAN configuration on hypervisor

### 3. Bastion Host (OpenShift Installer)
**Purpose**: Runs OpenShift installation process and provides cluster access

> ⚠️ **CRITICAL**: The bastion host is assumed. You might be able to use the KVM host for this purpose but this has not been tested!

#### Requirements
- **OS**: RHEL 8/9 or compatible (same as KVM host)
- **Network**: Access to OpenShift VMs and external registries
- **Storage**: 50GB+ for OpenShift binaries and cluster files
- **User Account**: Dedicated user (default: `ocp`) with sudo access

#### Network Access Required
- **OpenShift Registries**: 
  - `mirror.openshift.com`
  - `quay.io`
  - `registry.redhat.io`
- **KVM Host**: Libvirt connection capability
- **DNS Server**: For name resolution
- **Vault Server**: If using Vault integration

### 4. DNS Server
**Purpose**: Provides name resolution for OpenShift cluster

#### Current Implementation: pfSense Only
> ⚠️ **LIMITATION**: Automation currently **only supports pfSense**

**pfSense Requirements:**
- pfSense 2.4+ appliance or VM
- `pfsensible.core` Ansible collection
- SSH
- DNS Resolver service enabled
- Administrative access for DNS record creation

**DNS Records Created:**
- Bootstrap node: `bootstrap.{cluster}.{domain}`
- Control plane nodes: `{node}.{cluster}.{domain}`
- Worker nodes: `{node}.{cluster}.{domain}`  
- API endpoint: `api.{cluster}.{domain}` → API VIP
- Apps wildcard: `apps.{cluster}.{domain}` → Apps VIP

#### Alternative DNS Providers
> 📝 **TODO**: Add support for other DNS providers (BIND, Pihole, etc.)

Current workaround: Manually configure DNS entries or modify the `dns_settings_pfsense` role.

## 🔒 Security & Authentication

### 1. SSH Key Management
**Requirements:**
- SSH key pair for cluster node access
- Public key accessible to automation (via Vault or local file)

**Current Assumptions:**
- SSH keys stored in Vault at `credentials/data/OCP_SSHKEY`
- Key format: Standard SSH public key format
- No passphrase protection on private key

### 2. HashiCorp Vault (Recommended, Optional)
**Purpose**: Secure storage of secrets and credentials

#### Vault Server Requirements
- **Version**: Vault OSS or Enterprise
- **Authentication**: AppRole method configured
- **Network**: HTTPS access from all hosts
- **Policies**: Read/write access to required paths

#### Required Vault Paths and Secrets

| Path | Content | Purpose |
|------|---------|---------|
| `credentials/data/OpenShift_Pull` | `pull_secret` | Registry authentication |
| `credentials/data/OCP_SSHKEY` | `public_key` | SSH access to nodes |
| `certificates/data/mirror-registry-cert` | `certificate` | Additional trust bundle |
| `configs/data/{cluster}.{domain}` | `install_config` | OpenShift configuration |

#### Vault Configuration Example
```bash
# Enable AppRole authentication
vault auth enable approle

# Create policy for OpenShift automation
vault policy write openshift-automation - <<EOF
path "credentials/data/*" {
  capabilities = ["read"]
}
path "certificates/data/*" {
  capabilities = ["read"]
}
path "configs/data/*" {
  capabilities = ["create", "read", "update"]
}
EOF

# Create role
vault write auth/approle/role/openshift-automation \
    token_policies="openshift-automation" \
    token_ttl=1h \
    token_max_ttl=4h
```

#### Non-Vault Deployment
> 📝 **TODO**: Add support for local secret files

Current workaround: Manually set variables in playbook or vars file.

### 3. OpenShift Pull Secret
**Requirements:**
- Valid Red Hat Customer Portal account
- OpenShift pull secret downloaded from [cloud.redhat.com](https://cloud.redhat.com/openshift/install/pull-secret)
- Pull secret with access to required registries

**Registry Access Required:**
- `registry.redhat.io` - Red Hat container images
- `quay.io` - OpenShift and operator images  
- `registry.connect.redhat.com` - Certified partner images

## 🌐 Network Requirements

### 1. IP Address Planning
**Requirements:**
- (Optional) subnet for OpenShift cluster
- Static IP addresses for all components
- No IP conflicts with existing infrastructure

#### Required IP Assignments
```
Example for 3+2 cluster (MACHINE_IP_BASE: "10.50.100", MACHINE_IP_START: 10):

10.50.100.5     - API VIP (load balancer)
10.50.100.6     - Apps VIP (ingress)
10.50.100.10    - Control plane node 1
10.50.100.11    - Control plane node 2  
10.50.100.12    - Control plane node 3
10.50.100.13    - Worker node 1
10.50.100.14    - Worker node 2
10.50.100.95    - Bootstrap node (temporary)
```

### 2. Proxy Configuration (Optional but Assumed)

#### When Proxy is Required
- Corporate environments with restricted internet access
- Air-gapped deployments with proxy for registry access
- Environments with web filtering/monitoring

#### Proxy Server Requirements
- HTTP/HTTPS proxy supporting CONNECT method
- Access to OpenShift registries and external resources
- Proper exclusions for cluster internal traffic

#### Proxy Variables
```yaml
HTTPS_PROXY: "http://proxy.company.com:8080"
HTTP_PROXY: "http://proxy.company.com:8080"  
NO_PROXY: "localhost,127.0.0.1,api.openshift.com,example.com,.cluster.domain"
```

#### No-Proxy Environment
Set proxy variables to empty strings:
```yaml
HTTPS_PROXY: ""
HTTP_PROXY: ""
NO_PROXY: "localhost,127.0.0.1"
```

### 3. Sushy Tools (RedFish Emulation)
**Purpose**: Provides BMC emulation for baremetal OpenShift installer

> ℹ️ **Note**: Sushy-tools installation, service configuration, and firewall setup are handled automatically by the automation.

## 💾 Storage Requirements

### 1. Separate Worker Storage (Optional)
Variables support separate storage for worker nodes:
- `WORKER_LIBVIRT_POOL_NAME`
- `WORKER_LIBVIRT_DISK_PATH`
- `WORKER_LIBVIRT_DISK_SIZE`

### 2. Storage Calculations
**Minimum Storage Requirements:**
```
Control Plane: 3 × 120GB = 360GB
Workers: N × 120GB = N×120GB  
Bootstrap: 1 × 120GB = 120GB (temporary)
Overhead: ~50GB

Total: 530GB + (N×120GB) where N = number of workers
```

## 📋 Pre-Flight Checklist

Before running the automation, verify:

- [ ] **Ansible Host**
  - [ ] Ansible 2.9+ installed
  - [ ] Required collections installed
  - [ ] SSH access to all hosts
  - [ ] Python dependencies installed

- [ ] **KVM Host**  
  - [ ] Virtualization support enabled
  - [ ] Bridge networks configured
  - [ ] Storage pools defined
  - [ ] Sufficient resources available

- [ ] **Bastion Host**
  - [ ] OS compatible with OpenShift requirements
  - [ ] Network access to registries
  - [ ] SSH access configured

- [ ] **DNS Server**
  - [ ] pfSense accessible and configured
  - [ ] DNS resolver service enabled
  - [ ] Administrative credentials available

- [ ] **Network**
  - [ ] IP address ranges planned
  - [ ] No IP conflicts exist
  - [ ] Firewall rules configured
  - [ ] Proxy settings validated (if applicable)

- [ ] **Storage**
  - [ ] Sufficient disk space available
  - [ ] Storage pools created and accessible
  - [ ] Proper permissions configured

- [ ] **Security**
  - [ ] SSH keys generated and accessible
  - [ ] OpenShift pull secret obtained
  - [ ] Vault server configured (if used)
  - [ ] All required secrets stored

- [ ] **Validation Tests**
  - [ ] Network connectivity verified
  - [ ] DNS resolution working
  - [ ] Registry access confirmed
  - [ ] Vault authentication tested (if used)

> 📝 **Note**: This prerequisites document addresses currently undocumented assumptions in the automation. Many of these requirements are enforced by the code but not explained in existing documentation.
