HISTSIZE=10000
HISTFILESIZE=20000
alias snap-show='sudo zfs list -t snapshot'
alias mp3youtube='yt-dlp -x --audio-format mp3'
alias grep='grep --color'
alias best-youtube='yt-dlp -r 4M --yes-playlist -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]" -S vcodec:h264'
alias mpv='mpv --player-operation-mode=pseudo-gui'
alias nano='nano -wET 4'
alias ls='ls --color=auto'
PS1="\[\e[01;32m\]\u@\h \[\e[01;34m\]\w  \[\e[01;34m\]$\[\e[00m\] "
export EDITOR=nano
export AURDEST=/var/cache/pacman/pkg
