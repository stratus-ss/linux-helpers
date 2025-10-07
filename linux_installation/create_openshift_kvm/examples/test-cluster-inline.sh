#!/bin/bash
# Example: Creating a test cluster with inline extra-vars
# This shows how to override variables directly on the command line

ansible-playbook semaphore_create_kvm_openshift.yaml \
  --extra-vars "CLUSTER_NAME=test" \
  --extra-vars "BASE_DOMAIN=test.example.com" \
  --extra-vars "MACHINE_IP_BASE=172.16.50" \
  --extra-vars "MACHINE_IP_START=50" \
  --extra-vars "API_VIP=172.16.50.40" \
  --extra-vars "APPS_VIP=172.16.50.41" \
  --extra-vars "NETWORK_GATEWAY=172.16.50.1" \
  --extra-vars "DNS_NAMESERVER=172.16.50.1" \
  --extra-vars "MACHINE_NETWORK=172.16.50.0/24" \
  --extra-vars "NETWORK_CIDR=24" \
  --extra-vars '{"CONTROL_PLANE_NAMES": ["test-master1", "test-master2", "test-master3"]}' \
  --extra-vars '{"WORKER_NAMES": ["test-worker1", "test-worker2"]}' \
  --extra-vars "NUMBER_OF_WORKER_VMS=2" \
  --extra-vars "VM_RAM_MB=12288" \
  --extra-vars "VM_vCPUS=4" \
  --extra-vars "OPENSHIFT_VERSION=4.17.11"

# This will create:
# test-master1.test.test.example.com: 172.16.50.50
# test-master2.test.test.example.com: 172.16.50.51  
# test-master3.test.test.example.com: 172.16.50.52
# test-worker1.test.test.example.com: 172.16.50.53
# test-worker2.test.test.example.com: 172.16.50.54
