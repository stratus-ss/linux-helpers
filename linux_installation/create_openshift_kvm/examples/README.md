# Dynamic Cluster Configuration Examples

## 🎯 How the Dynamic Generation Works

The refactored playbook now dynamically generates the `OPENSHIFT_CLUSTER_PROVISION_PARAMS` based on your node lists and IP configuration. This means you can easily create different clusters by overriding key variables.

### Key Variables for Override

| Variable | Purpose | Example |
|----------|---------|---------|
| `CLUSTER_NAME` | Cluster identifier | `"production"` |
| `BASE_DOMAIN` | DNS domain | `"prod.example.com"` |
| `MACHINE_IP_BASE` | IP network base | `"10.50.100"` |
| `MACHINE_IP_START` | Starting IP offset | `10` |
| `CONTROL_PLANE_NAMES` | Master node names | `["prod-cp1", "prod-cp2", "prod-cp3"]` |
| `WORKER_NAMES` | Worker node names | `["prod-worker1", "prod-worker2"]` |
| `API_VIP` | API load balancer IP | `"10.50.100.5"` |
| `APPS_VIP` | Apps load balancer IP | `"10.50.100.6"` |
| `LIBVIRT_POOL_NAME` | Control plane storage pool | `"nvme-pool"` |
| `LIBVIRT_DISK_PATH` | Control plane storage path | `"/var/lib/libvirt_nvme"` |
| `LIBVIRT_DISK_SIZE` | Control plane disk size (GB) | `200` |
| `WORKER_LIBVIRT_POOL_NAME` | Worker storage pool (optional) | `"ssd-pool"` |
| `WORKER_LIBVIRT_DISK_PATH` | Worker storage path (optional) | `"/mnt/ssd-storage/libvirt_ssd"` |
| `WORKER_LIBVIRT_DISK_SIZE` | Worker disk size in GB (optional) | `300` |

### IP Address Calculation

The playbook automatically calculates IP addresses:
- **Control Plane**: `{{ MACHINE_IP_BASE }}.{{ MACHINE_IP_START + index }}`
- **Workers**: `{{ MACHINE_IP_BASE }}.{{ MACHINE_IP_START + NUMBER_OF_MASTER_VMS + index }}`

## 🚀 Usage Examples

### 1. Using External Variable Files

```bash
# Production cluster
ansible-playbook semaphore_create_kvm_openshift.yaml \
  --extra-vars @examples/production-cluster-override.yaml

# Development cluster  
ansible-playbook semaphore_create_kvm_openshift.yaml \
  --extra-vars @examples/development-cluster-override.yaml
```

### 2. Using Inline Variables

```bash
# Quick test cluster
./examples/test-cluster-inline.sh
```

### 3. Mixed Approach (File + Inline Overrides)

```bash
# Use production base config but override cluster name and IPs
ansible-playbook semaphore_create_kvm_openshift.yaml \
  --extra-vars @examples/production-cluster-override.yaml \
  --extra-vars "CLUSTER_NAME=prod-backup" \
  --extra-vars "MACHINE_IP_BASE=10.60.100"
```

## 📊 Generated Configuration Examples

### Production Cluster (from production-cluster-override.yaml)
```yaml
# Generated OPENSHIFT_CLUSTER_PROVISION_PARAMS will contain:
- openshift_node_fqdn: "prod-master-01.production.prod.mycompany.com"
  openshift_node_machine_ip_address: "10.50.100.10"
  
- openshift_node_fqdn: "prod-master-02.production.prod.mycompany.com"  
  openshift_node_machine_ip_address: "10.50.100.11"
  
- openshift_node_fqdn: "prod-master-03.production.prod.mycompany.com"
  openshift_node_machine_ip_address: "10.50.100.12"
  
- openshift_node_fqdn: "prod-worker-01.production.prod.mycompany.com"
  openshift_node_machine_ip_address: "10.50.100.13"
  # ... and so on
```

### Development Cluster (from development-cluster-override.yaml)
```yaml
# Generated OPENSHIFT_CLUSTER_PROVISION_PARAMS will contain:
- openshift_node_fqdn: "dev-cp1.dev.dev.lab.local"
  openshift_node_machine_ip_address: "192.168.200.20"
  
- openshift_node_fqdn: "dev-cp2.dev.dev.lab.local"
  openshift_node_machine_ip_address: "192.168.200.21"
  
- openshift_node_fqdn: "dev-cp3.dev.dev.lab.local"  
  openshift_node_machine_ip_address: "192.168.200.22"
  # No workers (NUMBER_OF_WORKER_VMS: 0)
```

## 🔧 Benefits of This Approach

1. **Single Playbook**: One playbook works for all cluster types
2. **Automatic Scaling**: Add/remove nodes by just updating the name lists
3. **IP Management**: Automatic IP assignment prevents conflicts
4. **Consistent Configuration**: All clusters follow the same pattern
5. **Easy Maintenance**: Changes in one place affect all clusters

## 🎨 Customization Tips

### Different Network Ranges
```bash
# For different subnets, just change the base
--extra-vars "MACHINE_IP_BASE=172.20.50"
```

### Different Cluster Sizes  
```bash
# Smaller cluster
--extra-vars '{"CONTROL_PLANE_NAMES": ["cp1", "cp2", "cp3"]}'
--extra-vars "NUMBER_OF_WORKER_VMS=0"

# Larger cluster
--extra-vars '{"WORKER_NAMES": ["w1", "w2", "w3", "w4", "w5", "w6"]}'
--extra-vars "NUMBER_OF_WORKER_VMS=6"
```

### Different Resource Profiles
```bash
# High-performance cluster
--extra-vars "VM_RAM_MB=65536"
--extra-vars "VM_vCPUS=16"

# Development cluster  
--extra-vars "VM_RAM_MB=8192"
--extra-vars "VM_vCPUS=2"
```

### Different Storage Configurations
```bash
# Using separate storage pools for control plane vs workers
ansible-playbook semaphore_create_kvm_openshift.yaml \
  --extra-vars @examples/storage-override-example.yaml

# Control plane on NVMe, workers on SSD
--extra-vars "LIBVIRT_POOL_NAME=nvme-pool"
--extra-vars "LIBVIRT_DISK_PATH=/var/lib/libvirt_nvme"
--extra-vars "LIBVIRT_DISK_SIZE=200"
--extra-vars "WORKER_LIBVIRT_POOL_NAME=ssd-pool"
--extra-vars "WORKER_LIBVIRT_DISK_PATH=/mnt/ssd-storage/libvirt_ssd"
--extra-vars "WORKER_LIBVIRT_DISK_SIZE=300"

# Same pool, different sizes for control vs worker nodes
--extra-vars "LIBVIRT_POOL_NAME=vm-pool"
--extra-vars "LIBVIRT_DISK_SIZE=150"
--extra-vars "WORKER_LIBVIRT_DISK_SIZE=500"

# Workers inherit control plane storage (no worker variables specified)
--extra-vars "LIBVIRT_POOL_NAME=performance-pool"
--extra-vars "LIBVIRT_DISK_PATH=/var/lib/libvirt_performance"
--extra-vars "LIBVIRT_DISK_SIZE=250"
```

## ⚠️ Important Notes

- Ansible extra-vars have the highest precedence and will override defaults
- Make sure your IP ranges don't conflict with existing infrastructure
- The playbook will generate FQDNs as: `{node_name}.{CLUSTER_NAME}.{BASE_DOMAIN}`
- Worker nodes get IPs after control plane nodes automatically
