#!/bin/bash
scp pfsense-import-cert.php example.com/cert.pem example.com/privkey.pem  example.com/fullchain.pem admin@pfsense.example.com:/root/
ssh admin@pfsense.example.com "php /root/pfsense-import-cert.php /root/cert.pem /root/privkey.pem"
