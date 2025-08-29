# API-Based Prometheus Configuration Management

## The Problem Solved ✅

**Original Issue**: Node exporter deployments don't coordinate with Prometheus configuration, leading to static configs and manual management.

**Solution**: Use Prometheus API to **read existing configuration** and **intelligently add/remove targets** without stepping on existing configs.

## How It Works

### 1. **Read Current Config via API**
```bash
GET http://containers.example.com:9191/api/v1/status/config
```
- Returns current Prometheus configuration as JSON
- Includes all existing scrape jobs and targets
- No guessing what's currently configured

### 2. **Extract Current Targets from API**
- Parse API response to get current node exporter targets
- Merge with new targets (add/remove as requested)
- Create clean target list for template

### 3. **Rebuild Config from Template**
- Use existing `prometheus.yaml.j2` template
- Pass merged targets as `prometheus_node_targets` variable
- Template generates clean, proper YAML structure

### 4. **Validate and Apply**
- Validate new configuration with `promtool`
- Apply via template regeneration + API reload
- Verify targets are active

## ✅ Key Benefits

- **No Config Stepping**: Reads existing config instead of replacing
- **Template-Based**: Uses simple template instead of complex YAML manipulation  
- **Smart Merging**: Adds new targets to existing ones
- **Clean Structure**: Template generates proper Prometheus defaults
- **Docker Compose Smart**: Auto-detects Docker Compose and adapts validation strategy
- **Validation**: Ensures config is valid before applying (with Docker Compose compatibility)
- **Rollback**: Automatic backup and restore on failure
- **API-First**: Uses Prometheus API for discovery and reloading

## Usage Examples

### Deploy Node Exporters + Auto-Register
```bash
# Semaphore Template: "Deploy Node Exporters with Registration" 
# Playbook: prometheus_exporter/deploy_and_register_exporter.yaml
# Variables:
auto_register_with_prometheus: true
node_exporter_version: "1.8.1"
node_exporter_port: 9100
```

### Manual Target Management  
```bash
# Add specific hosts
ansible-playbook prometheus_exporter/update_prometheus_targets.yaml \
  -e "hosts_to_add=['web1.example.com','web2.example.com']"

# Remove specific hosts  
ansible-playbook prometheus_exporter/update_prometheus_targets.yaml \
  -e "hosts_to_remove=['old-server.example.com']"

# Add and remove in one operation
ansible-playbook prometheus_exporter/update_prometheus_targets.yaml \
  -e "hosts_to_add=['new-server.com']" \
  -e "hosts_to_remove=['old-server.com']"
```

### Semaphore Templates

#### Template 1: "Deploy Node Exporters with Registration"
- **Playbook**: `prometheus_exporter/deploy_and_register_exporter.yaml`
- **Description**: Deploy node exporters and automatically register with Prometheus
- **Variables**:
```yaml
auto_register_with_prometheus: true
node_exporter_version: "1.8.1" 
node_exporter_port: 9100
prometheus_host: prometheus_servers
```

#### Template 2: "Update Prometheus Targets"
- **Playbook**: `prometheus_exporter/update_prometheus_targets.yaml`
- **Description**: Add/remove specific targets from Prometheus monitoring  
- **Variables**:
```yaml
hosts_to_add: []      # List of hosts to add
hosts_to_remove: []   # List of hosts to remove
node_exporter_port: 9100
backup_prometheus_config: true
validate_prometheus_config: true
```

#### Template 3: "Deploy Prometheus Server" 
- **Playbook**: `prometheus_server/install_prometheus_server.yaml`
- **Description**: Initial Prometheus server deployment (uses simple template)
- **Note**: This creates the initial server - target management happens later via node exporter deployments

## API Endpoints Used

| Endpoint | Purpose | Method |
|----------|---------|--------|
| `/-/healthy` | Check if Prometheus is running | GET |
| `/api/v1/status/config` | Get current configuration | GET |
| `/-/reload` | Reload configuration | POST |
| `/-/ready` | Check if ready after reload | GET |
| `/api/v1/targets` | Verify targets are active | GET |

## Example API Response

The `/api/v1/status/config` endpoint returns:
```json
{
  "status": "success",
  "data": {
    "yaml": "global:\n  scrape_interval: 15s\nscrape_configs:\n- job_name: nodes\n  static_configs:\n  - targets:\n    - web1:9100\n    - web2:9100"
  }
}
```

This YAML is parsed to understand existing configuration and build upon it.

## Configuration Flow

```
1. Check Prometheus Health
   ↓
2. GET /api/v1/status/config  
   ↓
3. Extract current node exporter targets
   ↓
4. Merge with new targets (add/remove)
   ↓  
5. Rebuild config from prometheus.yaml.j2 template
   ↓
6. Validate with promtool
   ↓
7. POST /-/reload
   ↓
8. Verify targets active
```

## Error Handling

- **Prometheus not running**: Fails gracefully with clear error
- **API errors**: Provides specific error messages  
- **Config validation fails**: Automatically restores backup
- **Reload fails**: Container restart as fallback
- **Network issues**: Proper timeout and retry logic

## No More Config Conflicts!

**Before**: 
```yaml
# Static template would replace existing config
targets:
  - web1:9100
  - web2:9100
# Lost: Any manually added targets, custom jobs, etc.
```

**After**:
```yaml
# API approach reads current targets and rebuilds template
# 1. GET /api/v1/status/config → Extract: [web1:9100, web2:9100, manual-server:9100]
# 2. Merge with new: web3:9100
# 3. Rebuild template with: [web1:9100, web2:9100, manual-server:9100, web3:9100]
# 4. Result: Clean config with all targets preserved + new ones added
```

### Template Structure

The `prometheus.yaml.j2` template now supports both approaches:

```yaml
-   job_name: nodes
    static_configs:
    -   targets:
        {% if prometheus_node_targets is defined %}
        # API-driven approach: use extracted + merged targets
        {% for target in prometheus_node_targets %}
        - {{ target }}
        {% endfor %}
        {% else %}
        # Fallback: traditional inventory approach  
        {% for host in groups['all'] %}
        - {{ host }}:9100
        {% endfor %}
        {% endif %}
```

## Architecture: Server vs Exporter Separation

### **Prometheus Server Deployment** (`prometheus_server/`)
- **Purpose**: Initial server setup
- **Method**: Uses simple `prometheus.yaml.j2` template with inventory-based targets
- **When**: First-time deployment or server recreation
- **Result**: Clean server with basic monitoring setup

### **Node Exporter Management** (`prometheus_exporter/`)  
- **Purpose**: Add/remove monitoring targets from existing server
- **Method**: Uses API-based approach to read current config + rebuild template
- **When**: Adding exporters to hosts, removing decommissioned servers
- **Result**: Existing server updated without stepping on configuration

This architectural separation ensures:
- ✅ **Server initialization** works without needing existing API
- ✅ **Exporter management** uses API for intelligent updates  
- ✅ **Clean separation** of concerns and responsibilities

Your insight was brilliant - this API-based approach completely eliminates the stepping-on-configs problem! 🎯
