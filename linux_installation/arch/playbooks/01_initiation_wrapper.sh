mount -o remount,size=2G /run/archiso/cowspace
mount -t nfs -o vers=3 192.168.1.1:/storage/backups/pacman_cache /var/cache/pacman/pkg
pacman -Sy ansible --noconfirm
time ansible-playbook -v tasks/stage1.yaml
