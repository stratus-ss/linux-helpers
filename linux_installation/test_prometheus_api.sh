#!/bin/bash
# Test script to examine Prometheus API endpoints and understand JSON structure

set -euo pipefail

# Configuration
PROMETHEUS_URL="${PROMETHEUS_URL:-http://containers.x86experts.com:9191}"

echo "Testing Prometheus API at: $PROMETHEUS_URL"
echo "========================================"

# Test 1: Health check
echo "1. Testing health endpoint..."
if curl -s -f "$PROMETHEUS_URL/-/healthy" > /dev/null; then
    echo "   ✅ Prometheus is healthy"
else
    echo "   ❌ Prometheus health check failed"
    exit 1
fi

# Test 2: Get current configuration
echo "2. Getting current configuration..."
CONFIG_RESPONSE=$(curl -s "$PROMETHEUS_URL/api/v1/status/config")
echo "   Raw API response:"
echo "$CONFIG_RESPONSE" | jq '.'

# Extract and display the YAML config
echo "   Current Prometheus YAML configuration:"
echo "$CONFIG_RESPONSE" | jq -r '.data.yaml'

# Test 3: Parse scrape configs using jq (more reliable than yq)
echo "3. Analyzing scrape configurations..."
CONFIG_YAML=$(echo "$CONFIG_RESPONSE" | jq -r '.data.yaml')

# Parse YAML to JSON for easier manipulation
CONFIG_JSON=$(echo "$CONFIG_YAML" | python3 -c "import sys, yaml, json; print(json.dumps(yaml.safe_load(sys.stdin)))")

echo "   Scrape jobs found:"
echo "$CONFIG_JSON" | jq -r '.scrape_configs[].job_name'

# Test 4: Find node exporter jobs
echo "4. Looking for node exporter jobs..."
NODE_JOB=$(echo "$CONFIG_JSON" | jq '.scrape_configs[] | select(.job_name | test(".*nodes.*"))')
if [ "$NODE_JOB" != "null" ] && [ -n "$NODE_JOB" ]; then
    echo "   ✅ Found node exporter job"
    
    JOB_NAME=$(echo "$NODE_JOB" | jq -r '.job_name')
    echo "   Job name: $JOB_NAME"
    
    echo "   Current node exporter targets:"
    TARGETS=$(echo "$NODE_JOB" | jq -r '.static_configs[0].targets[]' 2>/dev/null)
    TARGET_COUNT=$(echo "$NODE_JOB" | jq '.static_configs[0].targets | length' 2>/dev/null)
    echo "   Total targets: $TARGET_COUNT"
    
    echo "   First 10 targets:"
    echo "$NODE_JOB" | jq -r '.static_configs[0].targets[0:10][]' 2>/dev/null
else
    echo "   ❌ No node exporter jobs found"
fi

# Test 5: Get current targets status
echo "5. Getting current targets status..."
TARGETS_RESPONSE=$(curl -s "$PROMETHEUS_URL/api/v1/targets")
echo "   Active targets summary:"
echo "$TARGETS_RESPONSE" | jq -r '.data.activeTargets[] | "\(.labels.job): \(.scrapeUrl) - \(.health)"' | sort

# Test 6: Test reload endpoint (dry run)
echo "6. Testing reload endpoint (this will reload Prometheus config!)..."
read -p "   Do you want to test config reload? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if curl -s -f -X POST "$PROMETHEUS_URL/-/reload"; then
        echo "   ✅ Config reload successful"
    else
        echo "   ❌ Config reload failed"
    fi
else
    echo "   Skipping reload test"
fi

# Test 7: Ready check
echo "7. Checking if Prometheus is ready..."
if curl -s -f "$PROMETHEUS_URL/-/ready" > /dev/null; then
    echo "   ✅ Prometheus is ready"
else
    echo "   ❌ Prometheus is not ready"
fi

echo ""
echo "🎉 API testing complete!"
echo ""
echo "Useful API endpoints:"
echo "- Health: $PROMETHEUS_URL/-/healthy"
echo "- Config: $PROMETHEUS_URL/api/v1/status/config"
echo "- Targets: $PROMETHEUS_URL/api/v1/targets"
echo "- Reload: $PROMETHEUS_URL/-/reload (POST)"
echo "- Ready: $PROMETHEUS_URL/-/ready"
echo ""
echo "To use with different Prometheus server:"
echo "PROMETHEUS_URL=http://your-prometheus:9090 $0"
echo ""
echo "Current default: containers.x86experts.com:9191"
