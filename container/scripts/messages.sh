#!/bin/bash
# Swarmbox messaging utilities
# Simple, sober design to complement the banner

# Minimal color palette - two grays of the box, in 256-colour numbers (the 16 colours of the terminal change with its scheme)
GRAY='\033[38;5;243m'
WHITE='\033[38;5;252m'
RESET='\033[0m'
# no colour codes when the output is not a terminal (swarmbox pubkey > file)
if [ ! -t 1 ]; then GRAY=''; WHITE=''; RESET=''; fi

# Simple message functions - no fancy icons
msg() {
    echo -e "${WHITE}${1}${RESET}"
}

msg_detail() {
    echo -e "${GRAY}  ${1}${RESET}"
}

msg_blank() {
    echo ""
}
