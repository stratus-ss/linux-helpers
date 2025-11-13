# Arch Linux with ZFS on Root - Ansible Playbooks

These playbooks are used to set up ZFS on root on Arch Linux using ZFSBootMenu.

## Quick Start

This guide assumes you have booted into the Arch Linux ISO and have a network connection.

**⚠️ IMPORTANT:** The install is split into stages because you will need to `chroot` into your `pac-strap` environment (mounted at `/mnt`). Once in the `chroot` you will find the playbooks copied to `/mnt` where you can then launch the `02_install_wrapper.sh`

## Before You Begin

- Know your target disk device (e.g., `/dev/sda`, `/dev/nvme0n1`)
  
- Have your desired username and password ready
  
- (Optional) Have NFS pacman cache available
  

## Perform Installation

1. **Clone the Repository:**
  Clone this repository to your home directory.
  
  ```bash
  git clone <repository_url> ~/linux-helpers
  cd ~/linux-helpers/linux_installation/arch/playbooks
  ```
  
2. **Configure Variables:**
  Open `vars.yaml` and configure the variables to match your system and preferences. At a minimum, you **must** set the following:
  
  - `device_name`: Target disk device (e.g., `/dev/sda`, `/dev/nvme0n1`)
  - `username`: Your desired username
  - `user_password`: Your user password
  - `luks_passphrase`: LUKS encryption passphrase (if using LUKS)
  - `luks_volume_name`: LUKS volume name (default: `cryptroot`)
  
  Optional variables control features like:
  
  - `desktop`: Enable desktop installation
  - `desktop_name`: Desktop environment (`cinnamon` or `deepin`)
  - `libvirt`: Install virtualization support
  - `nvidia_lts`: Install NVIDIA LTS drivers
  - `use_luks`: Enable LUKS encryption
  - `network_pacman_cache`: Use network pacman cache
  - `remote_server`: IP address of remote server for keys/configs
  - `enable_endeavour`: I like the endeavour Cinnamon customizations, so you can enable them.

3. **Run Stage 1 (from Arch ISO):**
  Execute the first wrapper script. This will partition your disk, set up ZFS, and install the base system.
  
  ```bash
  ./01_initiation_wrapper.sh
  ```
  
4. **Enter the New System:**
  After Stage 1 completes, `chroot` into the newly installed system.
  
  ```bash
  arch-chroot /mnt
  cd /mnt 
  ```
  
5. **Run Stage 2 (from `arch-chroot`):**
  Execute the second wrapper script from within the `chroot`. This will configure the operating system, install packages, and set up your user.
  
  ```bash
  ./02_install_wrapper.sh
  ```
  
6. **Finalize and Reboot:**
  The `final_stage.yaml` playbook should run automatically at the end of Stage 2 to unmount everything and reboot. If it doesn't, you may need to run it manually.
  
  ```bash
  ansible-playbook tasks/final_stage.yaml
  ```
  
7. **Post-Installation (Optional):**
  After rebooting and logging into your new system, you can run the `post-install.yaml` playbook to restore application settings and install Flatpaks.
  
  ```bash
  ansible-playbook post-install.yaml
  ```
  

## How This Works Under The Hood

### Prerequisites

The below steps are taken care of by the `01_initiation_wrapper.sh`. The below is an explanation of how Ansible is achieving the system setup.

### Expand Cowspace

For some computers, you may need to expand the `cowspace` so that Ansible has enough space to run.

```bash
mount -o remount,size=2G /run/archiso/cowspace
```

### Install Ansible

You also need to install Ansible. If you have a networked `pacman` cache, you can mount it first.

```bash
mount -t nfs 192.168.1.1:/storage/backups/pacman_cache /var/cache/pacman/pkg
pacman -Sy ansible
```

> **IMPORTANT:**
> At the time of creation, the `zfs-linux-lts` package had a dependency on an LTS kernel that was only available in `[core-testing]`. These playbooks enable this repository for the ZFS installation and then disable it afterward.

## Playbook Workflow

The installation is split into multiple stages due to the `arch-chroot` process. The playbooks are designed to be run in order. Configuration is handled by editing `vars.yaml`.

### 1. `01_initiation_wrapper.sh`

This script kicks off the `tasks/stage1.yaml` playbook from the live Arch ISO environment.

- Expands the `cowspace`.
- Mounts the network `pacman` cache (if available).
- Installs Ansible.
- Calls `tasks/stage1.yaml`.

### 2. `tasks/stage1.yaml`

This playbook handles the initial disk setup.

- Partitions the target disk and optionally sets up LUKS encryption.
- Creates the ZFS pool and datasets.
- Installs the base Arch Linux system into `/mnt`.
- Copies the playbook directory to `/mnt/mnt` so it's available inside the `chroot`.

> **IMPORTANT:** After this playbook runs, you must `arch-chroot /mnt` and `cd /mnt` to run the next stage.

### 3. `02_install_wrapper.sh`

This wrapper script is run from inside the `chroot` environment.

- Installs the `kewlfft.aur` Ansible collection, which is needed to manage AUR packages.
- Calls `tasks/stage2.yaml`.

### 4. `tasks/stage2.yaml`

This is a simple wrapper playbook that loads variables from `vars.yaml` and calls `tasks/system-setup.yaml`. It is not meant to be edited directly.

### 5. `tasks/system-setup.yaml`

This is the main configuration playbook for the new system.

- Creates a user and configures `sudo` access.
- Sets up system locale and timezone.
- Installs `yay` (an AUR helper).
- Calls `tasks/install-zfs.yaml` to configure ZFS within the new system.
- Optionally installs `libvirt` for virtualization.
- Calls `tasks/desktop.yaml` if `desktop: true` is set in `vars.yaml`.

### 6. `tasks/install-zfs.yaml`

This playbook configures ZFS, ZFSBootMenu, and related services.

- Installs `zfs-linux-lts` and `efibootmgr`.
- Configures `mkinitcpio.conf` and generates the initramfs.
- Installs and configures `sanoid` for automated snapshots.
- Creates an EFI boot entry using `efibootmgr`.

### 7. `tasks/desktop.yaml`

Installs and configures a desktop environment and common applications.

- Installs generic packages like Firefox, Steam, and Flameshot.
- Pulls user-specific configurations (SSH keys, GPG keys, VPN settings) from a remote server.
- Calls a desktop-specific playbook (`cinnamon.yaml` or `deepin.yaml`) based on the `desktop_name` variable in `vars.yaml`.

### 8. `tasks/cinnamon.yaml`

- Installs the Cinnamon desktop environment and related applications.
- Enables the `lightdm` display manager.
- Configures themes and autostart applications.

### 9. `tasks/deepin.yaml`

- Installs the Deepin desktop environment.
- **Status:** Currently broken in testing.

### 10. `tasks/final_stage.yaml`

This is the final playbook that cleans up the installation environment.

- Unmounts all partitions from `/mnt`.
- Exports the `zpool`.
- Reboots the system into the new Arch Linux installation.

## Post-Installation and Utility Playbooks

### `post-install.yaml`

This playbook is designed to be run after you have successfully booted into and logged into your new system. It restores application settings and installs a list of common Flatpak applications.

### `tasks/backup_configs.yaml`

This is a utility playbook for backing up user configuration files (`dconf` settings, Flatpak data, `.gnupg` directory, etc.) to a remote server. It is not used during the OS installation.