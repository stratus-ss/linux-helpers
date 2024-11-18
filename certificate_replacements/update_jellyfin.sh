#!/bin/bash
scp example.com/* root@kids-tv.example.com:/etc/letsencrypt/live/kids-tv.example.com
ssh root@kids-tv.example.com "systemctl restart nginx"

scp example.com/* root@adult-tv:/etc/letsencrypt/live/adult-tv.example.com
ssh root@adult-tv "systemctl restart nginx"
