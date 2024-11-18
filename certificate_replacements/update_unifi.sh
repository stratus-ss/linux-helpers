#!/bin/bash
scp example.com/cert.pem example.com/fullchain.pem root@unifi.example.com:/etc/ssl/certs/
scp example.com/privkey.pem root@unifi.example.com:/etc/ssl/private
ssh root@unifi.example.com "/usr/local/bin/unifi_ssl_import.sh"
