#!/bin/bash
echo -e "\nUpdating server-vms\n"
scp example.com.com/cert.pem server-vms.example.com.com:/etc/cockpit/ws-certs.d/cert.cert
scp example.com.com/privkey.pem server-vms.example.com.com:/etc/cockpit/ws-certs.d/cert.key
ssh root@server-vms.example.com.com "systemctl restart cockpit"

echo -e "\nUpdating epyc-vms\n"
scp example.com.com/cert.pem epyc-vms.example.com.com:/etc/cockpit/ws-certs.d/cert.cert
scp example.com.com/privkey.pem epyc-vms.example.com.com:/etc/cockpit/ws-certs.d/cert.key
ssh root@epyc-vms.example.com.com "systemctl restart cockpit"
