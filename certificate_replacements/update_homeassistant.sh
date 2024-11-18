#!/bin/bash
mount -t cifs //<home assistent>/ssl /mnt -o user=<username>,password=<password>
cp example.com/fullchain.pem example.com/privkey.pem /mnt
umount -l /mnt

echo "Don't forget to restart Home Assistant so the new certs take affect!"
