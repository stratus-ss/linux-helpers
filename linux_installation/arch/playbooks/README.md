## Notes

These playbooks are used to setup ZFS on root on Arch Linux using the ZFSBootMenu. 

For some computers, you may need to expand the cowspace so that ansible has enough space to run

```
mount -o remount,size=2G /run/archiso/cowspace
```

You also need to install ansible. If you have a networked pacman cache you can mount it

```
mount -t nfs 192.168.1.1:/storage/backups/pacman_cache /var/cache/pacman/pkg
pacman -Sy ansible
```


**IMPORTANT:**

At the time of creation the `zfs-linux-lts` has a dependency on an LTS kernel that was only available in `[core-testing]` so these playbooks enable it for the ZFS installation and then disable it afterwards


### Usage

There are several playbooks that are in use due to the way arch-chroot works. 

__01_initiation_wrapper.sh__: This kicks off the stage1 playbook, expanding the cowspace, mounting the nas and installing ansible

__stage1.yaml__: this playbook is to be run at the prompt when you first boot arch ISO. This playbook installs the ZFS modules and partitions the disk according to the [recommended](https://wiki.archlinux.org/title/Install_Arch_Linux_on_ZFS#Partition_scheme) parition scheme on the arch wiki. YOU NEED TO SET THE DEVICE NAME. efi_partition and zfs_partition are populated later in the playbook based off the partition scheme and device name. This playbook is using the `linux-lts` kernel.

**IMPORTANT:** After this playbook runs you need to issue the `arch-chroot /mnt` command and then cd into `/mnt` where the next stage is run from.

__02_install_wrapper.sh__: This is a wrapper that installs the aur ansible module and then kicks off the playbook. Without this, the playbook would install the module, but then bail as ansible cannot install and then use the new module in the same playbook

__stage2.yaml__: This is a wrapper that establishes the variables for the rest of the playbooks. It calls `system-setup.yaml`. 

**IMPORTANT:** YOU NEED TO EDIT THIS FILE

__system-setup.yaml__: This sets up the base OS install including:
* removes everthing except for the `/boot/EFI` parition from `/etc/fstab`
* creates your user and puts it in the sudoers file **NOTE:** initially the user has no password on sudo to prevent prompting for sudo password. This change is reverted at the end of the playbook so sudo requires a password again
* Sets the locale to US.UTF-8
* mounts a network pacman cache
* updates makepkg.conf with some 'optimized' compiler flags
* installs `yay`
* edits mkinitcpio.conf for ZFS
* it calls the `desktop.yaml` if set to true in the vars

__install-zfs.yaml__:
* enables systemd services
* configures ZFSBootMenu
* installs and configures sanoid for auto-snapshotting
* sets packages to ignored in pacman.conf
* runs mkinitcpio

* adds the endeavourOS mirrors... because I like their theming
 and adds it with `efibootmgr`
* optionally installs flatpaks and various nvidia drivers
* optionally installs a desktop

__desktop.yaml__: Installs generic packages for use with all desktops (firefox, flameshot etc).
* Installs nvidia driver if applicable
* sets a new firefox icon
* gets the `.mozilla` file from a remote webserver and puts it inplace
* sets some custom fstab entries
* pulls down ssh and gpg keys from a remote source and puts them in place
* grabs vpn settings for NetworkManager from a remote source
* optionally triggers a specific desktop install

__cinnamon.yaml__: Installs some applications and the cinnamon desktop and then enables lightdm
* set's the EndeavourOS repo and pulls down cinnamon themes
* adds lightdm delay and override. Sometimes lightdm starts to fast causing breakage on boot and on resume
* adds autostart entries

__final_stage.yaml__: This umounts the drive and exports the zpool before rebooting
* adds efi boot entry
* unmounts the drives from `/mnt`
* reboots the host
