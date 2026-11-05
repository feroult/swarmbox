# Sourced from /etc/bash.bashrc (the last thing it does): turns the Starship prompt on in interactive bash.
#
#  - SwarmBox ships its own prompt config (/etc/swarmbox/starship.toml, a palette unlike a typical personal one).
#    Your own ~/.config/starship.toml, if it exists, is used instead; so is an STARSHIP_CONFIG you already set.
#  - Opt out with SWARMBOX_STARSHIP=0 (plain bash prompt).

case $- in *i*) ;; *) return 0 ;; esac
[ "${SWARMBOX_STARSHIP:-1}" = "0" ] && return 0
command -v starship >/dev/null 2>&1 || return 0

if [ -z "${STARSHIP_CONFIG:-}" ] && [ ! -f "$HOME/.config/starship.toml" ]; then
    export STARSHIP_CONFIG=/etc/swarmbox/starship.toml
fi
eval "$(starship init bash)"
